"""Dashboard data layer: SQL over the ADR-0025 hot store + runs/ artifacts.

Every view's data comes from HERE (dashboard-spec.md §4 "the exact source"):
percentiles and counters are plain SQL over `log_events` (the store
logging_manager writes); run stage detail joins `runs/<run_id>/status.json`
from the read-only PVC mount. A store that cannot be reached is an honest
state (`store="unreachable"`), never a fake empty series — the views render
"no data" states per the spec.

Tests seed fixtures by injecting a stub connection (`LogStore(connection=...)`)
— the SQL stays the contract.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Gate C + burn-budget constants (spec.md §9) — the dashboard's budget lines.
GATE_C_P95_BUDGET_MS = 4000
CREDIT_BURN_BUDGET = 3000  # 40% demo reserve of the 10,000 total stays intact
HOP_FIELDS = ("stt_final_ms", "llm_first_token_ms", "tts_first_audio_ms")

# Run ids are factory slugify() output (factory/artifacts.py): lowercase
# alphanumerics and hyphens, 63 chars max. Enforced at EVERY path
# construction below so a route param can never carry path separators,
# "..", or "..%2f"-decoded slashes outside runs/ (CodeQL py/path-injection).
# The guard is spelled inline at each site as
# re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", run_id): CodeQL py/path-injection
# recognizes the re.fullmatch module call with a literal pattern as a
# sanitizer, but not a compiled-pattern .fullmatch() — keep the literal at
# each call site for that reason.


def runs_dir() -> Path:
    return Path(os.environ.get("ZIVON_RUNS_DIR", "runs"))


# Thread-local connections (FastAPI runs sync endpoints on a thread pool; a
# single shared psycopg handle must not cross threads — cursors and
# transaction state are not safe for concurrent use). Each worker thread
# keeps its own connection for the process lifetime (the dashboard is
# single-replica, read-mostly); a failed query drops the caller's own handle
# so the next request on that thread reconnects instead of poisoning every
# view with a dead handle. Connections are never shared between threads.
_CONNECTIONS = threading.local()


def _cached_connection() -> tuple[str | None, Any | None]:
    return (
        getattr(_CONNECTIONS, "dsn", None),
        getattr(_CONNECTIONS, "conn", None),
    )


def _drop_connection(conn: Any) -> None:
    cached_dsn, cached = _cached_connection()
    if cached is conn:
        _CONNECTIONS.dsn = None  # type: ignore[attr-defined]
        _CONNECTIONS.conn = None  # type: ignore[attr-defined]
        del cached_dsn
    try:
        conn.close()
    except Exception as exc:  # noqa: BLE001 — a broken handle must not break the view
        del exc


@dataclass
class LogStore:
    """A thin, honest query layer. `connection` is a psycopg connection (or
    None — the DSN is unset); every failure degrades to `unreachable`."""

    connection: Any = None
    error: str | None = None

    @classmethod
    def from_env(cls) -> LogStore:
        dsn = os.environ.get("ZIVON_LOG_DSN", "").strip()
        if not dsn:
            return cls(connection=None, error=None)  # fallback mode: honest
        cached_dsn, cached = _cached_connection()
        if cached is not None and cached_dsn == dsn:
            return cls(connection=cached)
        try:
            import psycopg

            conn = psycopg.connect(dsn, autocommit=True)
        except Exception as exc:  # noqa: BLE001 — degrade, say so on the page
            return cls(connection=None, error=str(exc)[:200])
        _CONNECTIONS.dsn = dsn  # type: ignore[attr-defined]
        _CONNECTIONS.conn = conn  # type: ignore[attr-defined]
        return cls(connection=conn)

    @property
    def reachable(self) -> bool:
        return self.connection is not None

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if self.connection is None:
            return []
        try:
            with self.connection.cursor() as cur:
                cur.execute(sql, params)
                description = cur.description if cur.description else []
                columns = [getattr(c, "name", c[0]) for c in description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001 — a view never crashes the page
            self.error = self.error or str(exc)[:200]
            _drop_connection(self.connection)
            return []

    # ------------------------------------------------------------- views
    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """V1 rows: the last factory.run.* events, folded into one row per
        run with its terminal state (running only when a cluster Job says
        so — cluster.py answers that, not this module)."""
        rows = self._fetchall(
            """
            SELECT run_id, event, severity, ts, error_class,
                   fields->>'chapter' AS chapter,
                   fields->>'class_level' AS class_level,
                   fields->>'reason_code' AS reason_code
            FROM log_events
            WHERE event LIKE 'factory.run.%' AND run_id IS NOT NULL
            ORDER BY ts DESC
            LIMIT %s
            """,
            (limit * 4,),
        )
        folded: dict[str, dict[str, Any]] = {}
        for row in rows:
            run_id = row["run_id"]
            state = folded.get(run_id)
            if state is None:
                state = folded.setdefault(
                    run_id,
                    {
                        "run_id": run_id,
                        "state": "running",
                        "chapter": row["chapter"],
                        "class_level": row["class_level"],
                        "last_event": row["event"],
                        "last_ts": row["ts"],
                        "reason_code": row["reason_code"],
                    },
                )
            if row["event"] == "factory.run.completed":
                state["state"] = "completed"
            elif row["event"] == "factory.run.failed":
                state["state"] = "failed"
                state["reason_code"] = row["reason_code"] or state["reason_code"]
            elif row["event"] == "factory.run.resumed":
                state["state"] = (
                    "resumed" if state["state"] == "running" else state["state"]
                )
        return list(folded.values())[:limit]

    def run_detail(self, run_id: str) -> dict[str, Any]:
        """One run: its stage/repair rows + the on-disk status.json (PVC)."""
        stages = self._fetchall(
            """
            SELECT stage, event, severity, ts, latency_ms, error_class,
                   fields->>'reason_code' AS reason_code,
                   fields->>'blocks' AS blocks,
                   fields->>'attempts' AS attempts
            FROM log_events
            WHERE run_id = %s AND event LIKE 'factory.stage.%'
            ORDER BY ts
            """,
            (run_id,),
        )
        repairs = self._fetchall(
            """
            SELECT stage, event, ts, fields->>'round' AS round,
                   fields->>'issues_count' AS issues_count,
                   fields->>'plateau' AS plateau, fields->>'cap_hit' AS cap_hit
            FROM log_events
            WHERE run_id = %s AND event LIKE 'factory.repair.%'
            ORDER BY ts
            """,
            (run_id,),
        )
        calls = self._fetchall(
            """
            SELECT event, ts, latency_ms, error_class,
                   fields->>'call_intent' AS call_intent,
                   fields->>'attempts' AS attempts
            FROM log_events
            WHERE run_id = %s AND event LIKE 'factory.call.%'
            ORDER BY ts DESC
            LIMIT 50
            """,
            (run_id,),
        )
        # Path guard (py/path-injection): early-return re.fullmatch guard
        # BEFORE any Path use kills run_id taint — construction below runs
        # only for slug-shaped ids. resolve() + is_relative_to is kept as
        # defense-in-depth (a symlinked runs/<id> cannot escape the PVC
        # mount). SQL above is parameterized and therefore safe; only the
        # file read needs this guard, and invalid ids degrade to status=None.
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", run_id):
            return {
                "run_id": run_id,
                "stages": stages,
                "repairs": repairs,
                "calls": calls,
                "status": None,
            }
        base_dir = runs_dir().resolve()
        # codeql[py/path-injection] — false positive: run_id is validated to
        # ^[a-z0-9][a-z0-9-]{0,62}$ by the early-return re.fullmatch guard
        # above (no separators, no traversal possible) plus defense-in-depth
        # resolve()/is_relative_to containment against symlink escape.
        run_dir = (base_dir / run_id).resolve()
        if not run_dir.is_relative_to(base_dir):
            return {
                "run_id": run_id,
                "stages": stages,
                "repairs": repairs,
                "calls": calls,
                "status": None,
            }
        status_path = run_dir / "status.json"
        status: dict[str, Any] | None = None
        # codeql[py/path-injection] — false positive (same validation as
        # above: run_id slug-gated by early-return re.fullmatch, plus
        # resolve()/is_relative_to containment).
        if status_path.is_file():
            try:
                # codeql[py/path-injection] — false positive (same bar as
                # above: slug-gated run_id + resolve()/is_relative_to).
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                status = None
        return {
            "run_id": run_id,
            "stages": stages,
            "repairs": repairs,
            "calls": calls,
            "status": status,
        }

    def voice_percentiles(self) -> dict[str, Any]:
        """V3: p50/p95/max for the trailing windows, split by hop, against
        the Gate C budget line (spec.md §9). Zero data → honest no-data."""
        windows = {"1h": 1, "24h": 24, "7d": 168}
        out: dict[str, Any] = {"windows": {}, "slowest_hop": None}
        for label, hours in windows.items():
            overall = self._fetchall(
                """
                SELECT
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
                  MAX(latency_ms) AS max_ms,
                  COUNT(*) AS n
                FROM log_events
                WHERE event = 'voice.turn.e2e_latency'
                  AND latency_ms IS NOT NULL
                  AND ts > now() - (%s * interval '1 hour')
                """,
                (hours,),
            )
            row = overall[0] if overall else {}
            hops: dict[str, Any] = {}
            for hop in HOP_FIELDS:
                hop_rows = self._fetchall(
                    f"""
                    SELECT
                      percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY (fields->>'{hop}')::numeric
                      ) AS p95,
                      AVG((fields->>'{hop}')::numeric) AS avg_ms
                    FROM log_events
                    WHERE event = 'voice.turn.e2e_latency'
                      AND fields ? %s
                      AND ts > now() - (%s * interval '1 hour')
                    """,
                    (hop, hours),
                )
                hops[hop] = hop_rows[0] if hop_rows else {}
            out["windows"][label] = {
                "p50_ms": row.get("p50"),
                "p95_ms": row.get("p95"),
                "max_ms": row.get("max_ms"),
                "count": row.get("n", 0),
                "hops": hops,
            }
        slow = self._fetchall(
            """
            SELECT fields->>'slowest_hop' AS hop, COUNT(*) AS n
            FROM log_events
            WHERE event = 'voice.turn.e2e_latency'
              AND ts > now() - interval '24 hours'
              AND fields ? 'slowest_hop'
            GROUP BY 1 ORDER BY n DESC LIMIT 1
            """
        )
        out["slowest_hop"] = slow[0]["hop"] if slow else None
        return out

    def credit_usage(self) -> dict[str, Any]:
        """V4: the latest cumulative counter per profile vs cap + the burn
        budget line; guard refusals listed underneath."""
        latest = self._fetchall(
            """
            SELECT DISTINCT ON (fields->>'profile')
                   fields->>'profile' AS profile,
                   (fields->>'used')::numeric AS used,
                   (fields->>'cap')::numeric AS cap,
                   ts
            FROM log_events
            WHERE event = 'credit.counter_update'
              AND fields ? 'profile'
            ORDER BY fields->>'profile', ts DESC
            """
        )
        blocked = self._fetchall(
            """
            SELECT ts, fields->>'profile' AS profile,
                   fields->>'requested' AS requested,
                   fields->>'remaining' AS remaining
            FROM log_events
            WHERE event = 'credit.guard_blocked'
            ORDER BY ts DESC LIMIT 20
            """
        )
        return {
            "latest": latest,
            "guard_blocked": blocked,
            "burn_budget": CREDIT_BURN_BUDGET,
        }

    def error_feed(self, limit: int = 100) -> dict[str, Any]:
        """V5: latest ERROR/CRITICAL rows grouped by the closed taxonomy, plus
        the pinned redaction-violation section (a nonempty section is a
        call-site bug to fix, never noise to clear)."""
        rows = self._fetchall(
            """
            SELECT ts, event, component, severity, error_class, run_id,
                   session_id, turn_id, request_id, fields
            FROM log_events
            WHERE severity IN ('ERROR', 'CRITICAL')
            ORDER BY ts DESC LIMIT %s
            """,
            (limit,),
        )
        by_class: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_class.setdefault(row["error_class"] or "(none)", []).append(row)
        violations = self._fetchall(
            """
            SELECT ts, event_ref, key, kind
            FROM (
              SELECT ts, fields->>'event_ref' AS event_ref,
                     fields->>'key' AS key, fields->>'kind' AS kind
              FROM log_events
              WHERE event = 'log.redaction_violation'
            ) v
            ORDER BY ts DESC LIMIT 50
            """
        )
        return {"rows": rows, "by_class": by_class, "redaction_violations": violations}

    def publish_status(self) -> dict[str, Any]:
        """V6: publish rows from the map's factory.publish.* events plus the
        latest completed run's block counts (runs/ artifacts). Until the
        publish script emits its rows, this renders its honest empty state."""
        events = self._fetchall(
            """
            SELECT run_id, event, ts, fields->>'target' AS target,
                   fields->>'reason_code' AS reason_code,
                   fields->>'asset_count' AS asset_count
            FROM log_events
            WHERE event LIKE 'factory.publish.%'
            ORDER BY ts DESC LIMIT 20
            """
        )
        completions = self._fetchall(
            """
            SELECT run_id, ts, fields->>'blocks_published' AS blocks_published
            FROM log_events
            WHERE event = 'factory.run.completed'
            ORDER BY ts DESC LIMIT 10
            """
        )
        return {"events": events, "completions": completions}

    # ------------------------------------------------------------- alerts
    def alerts(self) -> list[dict[str, Any]]:
        """The §9 alert minimum, computed from the store (the banner's open
        conditions, each with the query that proves it)."""
        alerts: list[dict[str, Any]] = []
        failed = self._fetchall(
            """
            SELECT run_id, ts FROM log_events
            WHERE event = 'factory.run.failed'
              AND ts > now() - interval '24 hours'
            ORDER BY ts DESC LIMIT 5
            """
        )
        if failed:
            alerts.append(
                {
                    "name": "alert.pipeline_run_failed",
                    "detail": f"{len(failed)} failed run(s) in the last 24 h",
                    "runs": [row["run_id"] for row in failed],
                    "query": "event = 'factory.run.failed' AND ts > now()-'24h'",
                }
            )
        voice = self.voice_percentiles()
        p95 = voice["windows"]["24h"].get("p95_ms")
        if p95 is not None and float(p95) > GATE_C_P95_BUDGET_MS:
            alerts.append(
                {
                    "name": "alert.voice_p95_breach",
                    "detail": (
                        f"24 h p95 {float(p95):.0f} ms > {GATE_C_P95_BUDGET_MS} ms "
                        f"(slowest hop: {voice.get('slowest_hop') or 'n/a'})"
                    ),
                    "runs": [],
                    "query": "percentile_cont(0.95) over voice.turn.e2e_latency, 24h",
                }
            )
        credits = self.credit_usage()
        for row in credits["latest"]:
            used = row.get("used")
            if used is not None and float(used) > CREDIT_BURN_BUDGET:
                alerts.append(
                    {
                        "name": "alert.credit_tranche_exhausted",
                        "detail": (
                            f"profile {row['profile']} used {float(used):.0f} > "
                            f"burn budget {CREDIT_BURN_BUDGET}"
                        ),
                        "runs": [],
                        "query": "latest credit.counter_update per profile > 3000",
                    }
                )
        return alerts


@dataclass
class RunsArtifacts:
    """Read-only look into runs/<run_id>/ (the PVC mount)."""

    base: Path = field(default_factory=runs_dir)

    def _run_dir(self, run_id: str) -> Path | None:
        """The run dir only when run_id is a strict slug AND the resolved
        path stays inside base (same two barriers as run_detail: allowlist +
        resolve()/is_relative_to, so a symlinked run dir cannot escape)."""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", run_id):
            return None
        base_dir = self.base.resolve()
        run_dir = (base_dir / run_id).resolve()
        if not run_dir.is_relative_to(base_dir):
            return None
        return run_dir

    def status(self, run_id: str) -> dict[str, Any] | None:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            return None
        path = run_dir / "status.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def report(self, run_id: str) -> dict[str, Any] | None:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            return None
        path = run_dir / "run_report.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def has_run(self, run_id: str) -> bool:
        run_dir = self._run_dir(run_id)
        return run_dir is not None and run_dir.is_dir()
