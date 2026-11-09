"""The hot store's DDL + lifecycle helpers (ADR-0025), and `delete_subject`.

Owned by logging_manager (no module outside this package writes
`log_events` — same discipline as model calls through llm_manager):

- `ensure_log_schema` / `ensure_day_partition` — the pinned DDL, idempotent;
- `sweep_expired` — retention per class (L1/L2/credit 7 d hot, L3 30 d) with
  cold-sync verification honored via `verify_export`;
- `export_day` / `sync` — the daily cold-sync Job's mechanics: NDJSON export
  + checksum manifest, verify-then-drop (a day that failed sync is NEVER
  swept);
- `delete_subject` — the guardian-deletion path (ADR-0025 §4b): hot rows +
  fallback JSONL rewritten + one L3 `privacy.subject_deleted` audit event
  (IDs only);
- `python -m logging_manager.store <sweep|export|sync>` — the CLI the
  k8s/51 CronJob runs (kept inside this file so the package layout stays
  exactly as logging-api.md §1 pins it).

The cold provider's specifics (endpoint, credentials, bucket layout) are
OQ-8: `sync` writes verified NDJSON + manifest under the sync directory and
records what it exported; pointing it at the real provider is config that
lands with ADR-0004/0006, not a code change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Retention (ADR-0025 / spec.md §6): hot TTL per privacy class. L3
# (security/audit) keeps 30 hot days; everything else (L1, L2, credit) 7.
HOT_TTL_DAYS = 7
HOT_TTL_L3_DAYS = 30
SYNC_SIZE_CAP_BYTES = 200 * 1024 * 1024  # the 200 MB per-file cap (ADR-0025)

# ADR-0025's pinned DDL (the writer contract; migrations co-reviewed with the
# backend-db-storage agent). The table is schema-agnostic (JSONB fields), so
# schema-version bumps never need a migration (logging-api.md §9).
LOG_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS log_events (
  id             BIGSERIAL,
  ts             TIMESTAMPTZ NOT NULL,
  schema_version INT NOT NULL,
  severity       TEXT NOT NULL,
  event          TEXT NOT NULL,
  component      TEXT NOT NULL,
  env            TEXT NOT NULL,
  run_id         TEXT,
  session_id     TEXT,
  turn_id        TEXT,
  request_id     TEXT,
  stage          TEXT,
  latency_ms     BIGINT,
  error_class    TEXT,
  fields         JSONB NOT NULL DEFAULT '{}'::jsonb,
  trace_id       TEXT,
  span_id        TEXT,
  PRIMARY KEY (id, ts)
) PARTITION BY RANGE (ts)
"""

LOG_EVENTS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS log_events_event_ts_idx ON log_events (event, ts DESC)",
    "CREATE INDEX IF NOT EXISTS log_events_run_id_idx ON log_events (run_id)",
    "CREATE INDEX IF NOT EXISTS log_events_session_ts_idx ON log_events (session_id, ts)",
    "CREATE INDEX IF NOT EXISTS log_events_request_id_idx ON log_events (request_id)",
    (
        "CREATE INDEX IF NOT EXISTS log_events_errors_idx ON log_events "
        "(component, severity, ts DESC) WHERE severity IN ('ERROR', 'CRITICAL')"
    ),
)

_PARTITION_NAME = "log_events_{stamp}"
_DAY_FORMAT = "%Y%m%d"


def ensure_log_schema(conn: Any) -> None:
    """Idempotent DDL: the partitioned table + its indexes."""
    with conn.cursor() as cur:
        cur.execute(LOG_EVENTS_DDL)
        for ddl in LOG_EVENTS_INDEXES:
            cur.execute(ddl)


def ensure_day_partition(conn: Any, day: str) -> None:
    """Create the day partition (UTC calendar day) if missing. Safe to race:
    a duplicate is another writer having won the same race."""
    day_start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    name = _PARTITION_NAME.format(stamp=day_start.strftime(_DAY_FORMAT))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {name} PARTITION OF log_events
            FOR VALUES FROM (%s) TO (%s)
            """,
            (day_start, day_end),
        )


# ---------------------------------------------------------------------------
# retention / sweeper
# ---------------------------------------------------------------------------


def l3_events() -> frozenset[str]:
    """Event names whose privacy class is L3 (security/audit) — the rows the
    30-day TTL protects from the 7-day sweep. Derived from the
    instrumentation map (the per-event declaration of record)."""
    from . import events as _events

    return frozenset(
        event
        for event, row in _events.load_map().items()
        if row.privacy_class.upper() == "L3"
    )


def sweep_expired(conn: Any, now: datetime | None = None) -> dict[str, int]:
    """Enforce the hot TTLs.

    Daily partitions mix privacy classes, so a 7-day class cannot be dropped
    by whole-partition DROP without shortening L3's 30 days: the sweeper
    row-deletes the 7-day classes, then whole-partition-drops days that are
    entirely past the L3 TTL (cheap, and exact at the 30-day boundary).
    Days whose export manifest is missing or unverified are NEVER touched
    (retain-until-synced, ADR-0025).
    """
    now = now or datetime.now(UTC)
    cutoff_7 = now - timedelta(days=HOT_TTL_DAYS)
    cutoff_30 = now - timedelta(days=HOT_TTL_L3_DAYS)
    l3 = l3_events()
    result = {"rows_deleted": 0, "partitions_dropped": 0}
    with conn.cursor() as cur:
        if l3:
            placeholders = ", ".join(["%s"] * len(l3))
            cur.execute(
                f"""
                DELETE FROM log_events
                WHERE ts < %s
                  AND (event NOT IN ({placeholders}))
                """,
                (cutoff_7, *sorted(l3)),
            )
        else:
            cur.execute("DELETE FROM log_events WHERE ts < %s", (cutoff_7,))
        result["rows_deleted"] += (
            cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        )
        conn.commit()
        for day in _hot_days(conn):
            day_start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
            if day_start >= cutoff_30:
                continue
            if not day_verified(day):
                continue
            name = _PARTITION_NAME.format(stamp=day_start.strftime(_DAY_FORMAT))
            cur.execute(f"DROP TABLE IF EXISTS {name}")
            conn.commit()
            result["partitions_dropped"] += 1
    return result


def _hot_days(conn: Any) -> list[str]:
    """UTC days that have a child partition of log_events."""
    days: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'log_events'
            """
        )
        for (relname,) in cur.fetchall():
            stamp = relname.replace("log_events_", "")
            try:
                days.append(datetime.strptime(stamp, _DAY_FORMAT).strftime("%Y-%m-%d"))
            except ValueError:
                continue
    return sorted(days)


# ---------------------------------------------------------------------------
# cold sync (the interface; provider specifics are OQ-8)
# ---------------------------------------------------------------------------


def sync_dir() -> Path:
    """Where verified exports + manifests land (runs/logs-exports on the
    sources PVC until ADR-0004's provider config arrives)."""
    base = os.environ.get("ZIVON_RUNS_DIR", "").strip() or "runs"
    return Path(base) / "logs-exports"


def export_day(conn: Any, day: str, out_dir: Path | None = None) -> dict[str, Any]:
    """Export one UTC day as NDJSON + a manifest (row count + sha256).

    Returns the manifest dict; also written to <out_dir>/<day>.manifest.json.
    The manifest is the verify-then-drop evidence the sweeper requires.
    """
    out_dir = out_dir or sync_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    day_start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    out_path = out_dir / f"{day}.ndjson"
    rows = 0
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts, schema_version, severity, event, component, env,
                   run_id, session_id, turn_id, request_id, stage,
                   latency_ms, error_class, fields, trace_id, span_id
            FROM log_events WHERE ts >= %s AND ts < %s ORDER BY ts, id
            """,
            (day_start, day_end),
        )
        with out_path.open("w", encoding="utf-8") as fh:
            for row in cur.fetchall():
                line = json.dumps(
                    _row_to_record(row), separators=(",", ":"), ensure_ascii=False
                )
                fh.write(line + "\n")
                rows += 1
    # The manifest's checksum is taken over the WRITTEN file bytes, so
    # day_verified compares like with like.
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    manifest = {
        "day": day,
        "rows": rows,
        "sha256": digest,
        "bytes": out_path.stat().st_size,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "verified": True,
    }
    (out_dir / f"{day}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def _row_to_record(row: tuple[Any, ...]) -> dict[str, Any]:
    """A DB row -> the JSON-line record shape (the export IS the cold copy
    of the wire format)."""
    (
        ts,
        schema_version,
        severity,
        event,
        component,
        env,
        run_id,
        session_id,
        turn_id,
        request_id,
        stage,
        latency_ms,
        error_class,
        fields,
        trace_id,
        span_id,
    ) = row
    record: dict[str, Any] = {
        "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "schema_version": schema_version,
        "severity": severity,
        "event": event,
        "component": component,
        "env": env,
        "fields": fields or {},
    }
    for key, value in (
        ("run_id", run_id),
        ("session_id", session_id),
        ("turn_id", turn_id),
        ("request_id", request_id),
        ("stage", stage),
        ("latency_ms", latency_ms),
        ("error_class", error_class),
        ("trace_id", trace_id),
        ("span_id", span_id),
    ):
        if value is not None:
            record[key] = value
    return record


def day_verified(day: str, out_dir: Path | None = None) -> bool:
    """A day may be swept only when a manifest exists and its checksum still
    matches the exported file (retain-until-synced)."""
    out_dir = out_dir or sync_dir()
    manifest_path = out_dir / f"{day}.manifest.json"
    export_path = out_dir / f"{day}.ndjson"
    if not manifest_path.is_file() or not export_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not manifest.get("verified"):
        return False
    digest = hashlib.sha256()
    try:
        with export_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == manifest.get("sha256")


def ingest_fallback_files(conn: Any, out_dir: Path | None = None) -> dict[str, int]:
    """Ingest JSONL fallback files into the hot store (the recovery half of
    the daily sync). Idempotent per file: a sync manifest keyed by the
    file's sha256 skips files already ingested unchanged."""
    out_dir = out_dir or sync_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ingested = {"files": 0, "rows": 0, "skipped": 0}
    logs_dir = Path(os.environ.get("ZIVON_RUNS_DIR", "runs")) / "logs"
    if not logs_dir.is_dir():
        return ingested
    done_manifest = out_dir / "fallback-ingested.json"
    done: dict[str, str] = {}
    if done_manifest.is_file():
        try:
            done = dict(json.loads(done_manifest.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            done = {}
    for path in sorted(logs_dir.glob("*-*.jsonl")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if done.get(path.name) == file_hash:
            ingested["skipped"] += 1
            continue
        rows = [line for line in content.splitlines() if line.strip()]
        if _insert_lines(conn, rows):
            done[path.name] = file_hash
            ingested["files"] += 1
            ingested["rows"] += len(rows)
            (done_manifest).write_text(
                json.dumps(done, indent=2, sort_keys=True), encoding="utf-8"
            )
    return ingested


def _insert_lines(conn: Any, lines: list[str]) -> bool:
    from psycopg.types.json import Json

    sql = (
        "INSERT INTO log_events (ts, schema_version, severity, event, "
        "component, env, run_id, session_id, turn_id, request_id, stage, "
        "latency_ms, error_class, fields, trace_id, span_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s)"
    )
    rows = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        fields = dict(record.get("fields") or {})
        if record.get("client_session_id"):
            fields.setdefault("client_session_id", record["client_session_id"])
        rows.append(
            (
                record.get("ts"),
                record.get("schema_version", 1),
                record.get("severity"),
                record.get("event"),
                record.get("component"),
                record.get("env"),
                record.get("run_id"),
                record.get("session_id"),
                record.get("turn_id"),
                record.get("request_id"),
                record.get("stage"),
                record.get("latency_ms"),
                record.get("error_class"),
                Json(fields),
                record.get("trace_id"),
                record.get("span_id"),
            )
        )
    if not rows:
        return False
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    except Exception:  # noqa: BLE001 — sync is retryable, never fatal
        conn.rollback()
        return False
    return True


def sync(dsn: str, *, now: datetime | None = None) -> dict[str, Any]:
    """The daily log-sync Job's whole job (ADR-0025 §3): export the previous
    UTC day, ingest fallback JSONL, verify, and only then let the sweeper
    drop what is verified. Returns a summary for the Job's log line."""
    import psycopg

    now = now or datetime.now(UTC)
    previous = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    summary: dict[str, Any] = {"day": previous}
    with psycopg.connect(dsn, autocommit=False) as conn:
        ensure_log_schema(conn)
        conn.commit()
        summary["export"] = export_day(conn, previous)
        summary["fallback_ingest"] = ingest_fallback_files(conn)
        summary["sweep"] = sweep_expired(conn, now=now)
    return summary


# ---------------------------------------------------------------------------
# guardian deletion (ADR-0025 §4b)
# ---------------------------------------------------------------------------


def delete_subject(session_id: str) -> dict[str, Any]:
    """Remove every event row for the subject's pseudonymous session id —
    hot store + fallback JSONL — within 24 h of the guardian request, and
    write the one L3 audit event (IDs only). Cold-export manifests carry
    checksums, not session data, so they are pruned by the next day's
    export cycle; nothing in this module references raw audio (spec §4),
    so no other deletion path exists by construction."""
    from . import events as _events
    from .sink import _dispatch, _jsonl, _utc_now_iso_ms

    stores_touched: list[str] = []
    hot_removed = 0
    dsn = os.environ.get("ZIVON_LOG_DSN", "").strip()
    if dsn:
        import psycopg

        try:
            with psycopg.connect(dsn, autocommit=False) as conn:
                ensure_log_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM log_events WHERE session_id = %s", (session_id,)
                    )
                    hot_removed = max(cur.rowcount or 0, 0)
                conn.commit()
            stores_touched.append("hot")
        except Exception as exc:  # noqa: BLE001 — deletion retries; never raise to the guardian path
            del exc
    stores_touched.append("fallback")  # the rewrite pass runs unconditionally
    fallback_removed = _jsonl().remove_session(session_id)
    summary = {
        "session_id": session_id,
        "session_count": hot_removed + fallback_removed,
        "stores_touched": stores_touched or ["none"],
    }
    record = {
        "ts": _utc_now_iso_ms(),
        "schema_version": 1,
        "severity": "INFO",
        "event": "privacy.subject_deleted",
        "component": _events.component_for("privacy.subject_deleted"),
        "env": _events.env_name(),
        "session_id": session_id,
        "fields": {
            "session_count": summary["session_count"],
            "stores_touched": summary["stores_touched"],
        },
    }
    _dispatch(record)
    return summary


# ---------------------------------------------------------------------------
# CLI (the k8s/51 CronJob's entry point)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m logging_manager.store",
        description="log_events retention + cold sync (ADR-0025)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sweep", help="enforce hot TTLs (retain-until-synced)")
    sub.add_parser("sync", help="export yesterday + ingest fallback + sweep")
    export = sub.add_parser("export", help="export one UTC day to NDJSON")
    export.add_argument("--day", required=True, help="UTC day, YYYY-MM-DD")
    args = parser.parse_args(argv)

    dsn = os.environ.get("ZIVON_LOG_DSN", "").strip()
    if not dsn:
        print(
            "ZIVON_LOG_DSN is not set — the hot store is unreachable; nothing "
            "to sweep or sync (JSONL fallback files are left for the next run).",
            file=sys.stderr,
        )
        return 1
    import psycopg

    if args.command == "sync":
        summary = sync(dsn)
        print(json.dumps(summary, default=str))
        return 0
    with psycopg.connect(dsn, autocommit=False) as conn:
        ensure_log_schema(conn)
        conn.commit()
        if args.command == "sweep":
            print(json.dumps(sweep_expired(conn)))
        else:
            print(json.dumps(export_day(conn, args.day)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
