"""Sinks + the single emission point (logging-api.md §2, §4, §5).

Every event becomes ONE JSON line (UTF-8, `separators=(",", ":")`,
`ensure_ascii=False`, fixed field order — §4) and is written:

- to stdout always (pod logs stay greppable; `scripts/logs-factory-run.sh`
  keeps working);
- to the Postgres `log_events` hot store when `ZIVON_LOG_DSN` is set —
  batched (flush every 1 s or 64 events, whichever first; a failed batch
  retries once, then the batch falls back to JSONL and a loud
  `log.store_fallback` is emitted; recovery emits `log.store_recovered`);
- otherwise (or while degraded) to the JSONL fallback
  `runs/logs/YYYYMMDD-<component>.jsonl` — byte-identical schema, a sync
  source for the daily `log-sync` Job (ADR-0025).

`log_event` NEVER raises on the delivery path — telemetry must not break the
caller. The only raises are the three programmer errors, and only in dev
mode (`ZIVON_LOG_LEVEL=DEBUG`): an unknown event name, an unknown
`error_class`, a negative `latency_ms`.

The DB insert path follows ADR-0025's pinned DDL exactly (which has no
`client_session_id` column): when a client_session_id is bound it is ALSO
merged into the JSONB `fields` so dashboard queries stay possible.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import events
from .context import snapshot_for
from .redact import redact_fields

# ---------------------------------------------------------------------------
# serialization (the wire format, §4)
# ---------------------------------------------------------------------------

_FIELD_ORDER = (
    "ts",
    "schema_version",
    "severity",
    "event",
    "component",
    "env",
    "run_id",
    "session_id",
    "turn_id",
    "request_id",
    "client_session_id",
    "stage",
    "latency_ms",
    "error_class",
    "fields",
    "trace_id",
    "span_id",
)

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _utc_now_iso_ms() -> str:
    now = datetime.now(UTC)
    return f"{now.strftime('%Y-%m-%dT%H:%M:%S')}.{now.microsecond // 1000:03d}Z"


def serialize(record: dict[str, Any]) -> str:
    """One event -> one JSON line, fixed field order, absent fields omitted."""
    line: dict[str, Any] = {}
    for key in _FIELD_ORDER:
        value = record.get(key)
        if value is None:
            continue
        line[key] = value
    if "fields" not in line:
        line["fields"] = {}
    return json.dumps(line, separators=(",", ":"), ensure_ascii=False)


def parse_line(line: str) -> dict[str, Any] | None:
    """The inverse (sync Job + tests): one JSON line -> record, or None."""
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _level_rank(level: str) -> int:
    try:
        return _LEVELS.index(level)
    except ValueError:
        return 1  # unknown level behaves like INFO


# ---------------------------------------------------------------------------
# sinks
# ---------------------------------------------------------------------------


class _JsonlSink:
    """The PVC fallback: runs/logs/YYYYMMDD-<component>.jsonl, byte-identical
    schema. The component decides the file so the daily sync can partition
    its ingestion work."""

    def __init__(self, runs_dir: str | None = None) -> None:
        override = os.environ.get("ZIVON_RUNS_DIR", "").strip()
        self.base = str(runs_dir if runs_dir is not None else (override or "runs"))
        self._lock = threading.Lock()

    def path_for(self, component: str, day: str) -> Path:
        return Path(self.base) / "logs" / f"{day}-{component}.jsonl"

    def write(self, record: dict[str, Any]) -> None:
        line = serialize(record)
        component = str(record.get("component", "log"))
        day = str(record.get("ts", ""))[:10] or _utc_now_iso_ms()[:10]
        path = self.path_for(component, day)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # last-resort sink failed: stdout already carries the line

    def remove_session(self, session_id: str) -> int:
        """Guardian deletion on the fallback store: rewrite every day-file
        without the subject's rows (ADR-0025 §4 — deletion wins over
        append-only purity). Returns the number of rows removed."""
        removed = 0
        logs_dir = Path(self.base) / "logs"
        if not logs_dir.is_dir():
            return 0
        for path in sorted(logs_dir.glob("*-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            kept: list[str] = []
            hit = False
            for line in lines:
                record = parse_line(line)
                if record is not None and record.get("session_id") == session_id:
                    hit = True
                    removed += 1
                    continue
                kept.append(line)
            if hit:
                try:
                    path.write_text(
                        "".join(f"{line}\n" for line in kept), encoding="utf-8"
                    )
                except OSError:
                    continue
        return removed


class _PostgresSink:
    """The hot store (ADR-0025): batched inserts, one background flusher.

    The psycopg driver is imported lazily — the JSON path is stdlib-only, and
    a deployment that never sets ZIVON_LOG_DSN never needs the driver.
    """

    FLUSH_INTERVAL_S = 1.0
    FLUSH_THRESHOLD = 64

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._buf: list[dict[str, Any]] = []
        self._condition = threading.Condition()
        self._closed = False
        self._conn: Any = None
        self._created_partitions: set[str] = set()
        self._thread = threading.Thread(
            target=self._flusher, name="logging-manager-pg-flusher", daemon=True
        )
        self._thread.start()

    def enqueue(self, record: dict[str, Any]) -> bool:
        """Buffer one record; returns False when the sink is shutting down."""
        with self._condition:
            if self._closed:
                return False
            self._buf.append(record)
            if len(self._buf) >= self.FLUSH_THRESHOLD:
                self._condition.notify_all()
            return True

    def flush(self) -> None:
        """Drain whatever is buffered right now (exit path, tests)."""
        with self._condition:
            batch = self._buf
            self._buf = []
        if batch:
            self._write_batch(batch)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=5)
        self._teardown_conn()

    # ------------------------------------------------------------ internals
    def _flusher(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                self._condition.wait(timeout=self.FLUSH_INTERVAL_S)
                batch = self._buf
                self._buf = []
            if batch:
                self._write_batch(batch)

    def _connect(self) -> Any:
        if self._conn is None or self._conn.closed:
            import psycopg

            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def _teardown_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as exc:  # noqa: BLE001 — a broken conn must not break exit
                del exc
            self._conn = None

    def _write_batch(self, batch: list[dict[str, Any]]) -> None:
        for attempt in (1, 2):  # one retry, then the batch falls back (§5)
            try:
                conn = self._connect()
                from .store import ensure_day_partition, ensure_log_schema

                ensure_log_schema(conn)
                for day in sorted({str(r.get("ts", ""))[:10] for r in batch}):
                    if day and day not in self._created_partitions:
                        ensure_day_partition(conn, day)
                        self._created_partitions.add(day)
                self._insert(conn, batch)
            except Exception:  # noqa: BLE001 — any DB failure degrades, loudly
                self._teardown_conn()
                if attempt == 2:
                    for record in batch:
                        _jsonl().write(record)
                    _mark_degraded(dsn_set=True)
                    return
            else:
                if _fallback_engaged:
                    _mark_recovered()
                return

    def _insert(self, conn: Any, batch: list[dict[str, Any]]) -> None:
        from psycopg.types.json import Json

        sql = (
            "INSERT INTO log_events (ts, schema_version, severity, event, "
            "component, env, run_id, session_id, turn_id, request_id, stage, "
            "latency_ms, error_class, fields, trace_id, span_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s)"
        )
        rows = []
        for record in batch:
            fields = dict(record.get("fields") or {})
            # ADR-0025's DDL has no client_session_id column; the JSONB
            # fields carry it so dashboard/frontend joins stay possible.
            if record.get("client_session_id"):
                fields.setdefault("client_session_id", record["client_session_id"])
            rows.append(
                (
                    record.get("ts"),
                    record.get("schema_version", events.LOG_SCHEMA_VERSION),
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
        with conn.cursor() as cur:
            cur.executemany(sql, rows)


# ---------------------------------------------------------------------------
# module state + dispatch
# ---------------------------------------------------------------------------

_stdout_lock = threading.Lock()
_dispatch_lock = threading.Lock()
_pg_sink: _PostgresSink | None = None
_pg_dsn_seen: str | None = None
_jsonl_sink: _JsonlSink | None = None
_fallback_engaged = False
_internal_depth = 0
_violation_counts: dict[tuple[str, str, str], int] = {}


def fallback_dir() -> str:
    """The runs/logs directory the JSONL fallback writes to (and the daily
    sync Job ingests)."""
    base = os.environ.get("ZIVON_RUNS_DIR", "").strip() or "runs"
    return str(Path(base) / "logs")


def _jsonl() -> _JsonlSink:
    global _jsonl_sink
    if _jsonl_sink is None:
        _jsonl_sink = _JsonlSink()
    return _jsonl_sink


def _write_stdout(line: str) -> None:
    try:
        with _stdout_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass  # stdout closed (pipe down): the other sinks still get the event


def _emit_fallback_switch(dsn_set: bool) -> None:
    _emit_store_event(
        "log.store_fallback",
        {"dsn_set": dsn_set, "target_path": fallback_dir()},
        severity=events.Severity.WARNING,
        error_class=events.ErrorClass.STORE_ERROR,
    )


def _mark_degraded(dsn_set: bool) -> None:
    """Enter degraded mode; the `log.store_fallback` switch is emitted ONCE
    per degradation (spec.md §6: loud, not noisy) — a DB that stays down
    must not flood the store with fallback events every flush tick."""
    global _fallback_engaged
    if _fallback_engaged:
        return
    _fallback_engaged = True
    _emit_fallback_switch(dsn_set)


def _mark_recovered() -> None:
    global _fallback_engaged
    if not _fallback_engaged:
        return
    _fallback_engaged = False
    _emit_store_event(
        "log.store_recovered",
        {"target_path": fallback_dir()},
        severity=events.Severity.INFO,
        error_class=None,
    )


def _dispatch(record: dict[str, Any], *, internal: bool = False) -> None:
    """Deliver one event to the sinks. stdout always; Postgres when the DSN
    is set; JSONL otherwise / while degraded."""
    _write_stdout(serialize(record))
    global _pg_sink, _pg_dsn_seen
    dsn = os.environ.get("ZIVON_LOG_DSN", "").strip()
    if not dsn:
        _mark_degraded(dsn_set=False)
        _jsonl().write(record)
        return
    delivered = False
    with _dispatch_lock:
        try:
            if _pg_sink is None or _pg_dsn_seen != dsn:
                if _pg_sink is not None:
                    _pg_sink.close()
                _pg_sink = _PostgresSink(dsn)
                _pg_dsn_seen = dsn
            delivered = _pg_sink.enqueue(record)
        except Exception:  # noqa: BLE001 — a broken sink must not break the caller
            delivered = False
    if not delivered:
        _jsonl().write(record)
        if not internal:
            _mark_degraded(dsn_set=True)


def _emit_store_event(
    event: str,
    fields: dict[str, Any],
    *,
    severity: events.Severity,
    error_class: events.ErrorClass | None,
) -> None:
    """Module-own events (store_fallback / store_recovered / event_unknown /
    redaction_violation): straight to the sinks, no recursion, no re-entrant
    violation emission."""
    global _internal_depth
    if _internal_depth > 0:
        return
    _internal_depth += 1
    try:
        record: dict[str, Any] = {
            "ts": _utc_now_iso_ms(),
            "schema_version": events.LOG_SCHEMA_VERSION,
            "severity": severity.value,
            "event": event,
            "component": events.component_for(event),
            "env": events.env_name(),
            "error_class": error_class.value if error_class else None,
            "fields": fields,
        }
        _dispatch(record, internal=True)
    except Exception as exc:  # noqa: BLE001 — the module's own events never raise
        del exc
    finally:
        _internal_depth -= 1


def flush_sinks() -> None:
    """Flush any pending Postgres batch (exit path + tests)."""
    with _dispatch_lock:
        sink = _pg_sink
    if sink is not None:
        sink.flush()


def _atexit_flush() -> None:
    with _dispatch_lock:
        sink = _pg_sink
    if sink is not None:
        try:
            sink.flush()
        except Exception as exc:  # noqa: BLE001 — exit must not hang on a dead DB
            del exc


atexit.register(_atexit_flush)


def reset_for_tests(*, runs_dir: str | None = None) -> None:
    """Test isolation: drop sinks, state and env overrides. A test helper by
    convention (kept underscore-free so tests can find it); never part of
    the frozen public surface."""
    global _pg_sink, _pg_dsn_seen, _jsonl_sink, _fallback_engaged
    global _violation_counts
    with _dispatch_lock:
        if _pg_sink is not None:
            _pg_sink.close()
        _pg_sink = None
        _pg_dsn_seen = None
        _jsonl_sink = None
        _fallback_engaged = False
        _violation_counts = {}
    for name in ("ZIVON_LOG_DSN", "ZIVON_LOG_LEVEL", "ZIVON_ENV", "ZIVON_RUNS_DIR"):
        os.environ.pop(name, None)
    if runs_dir is not None:
        os.environ["ZIVON_RUNS_DIR"] = runs_dir


# ---------------------------------------------------------------------------
# log_event — the single emission point (§2)
# ---------------------------------------------------------------------------


def log_event(
    event: str,
    fields: dict[str, Any] | None = None,
    *,
    severity: events.Severity | None = None,
    error_class: events.ErrorClass | None = None,
    latency_ms: int | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    request_id: str | None = None,
    stage: str | None = None,
) -> None:
    """Emit one event. See logging-api.md §2 for the full contract; the
    short version: never raises (outside dev-mode programmer errors),
    redaction is applied here, severity comes from the map unless the
    ERROR/CRITICAL boundary needs an explicit override."""
    frame = sys._getframe(1)  # noqa: SL001 — the call site IS the audit data
    emitter_module = str(frame.f_globals.get("__name__", "") or "")
    call_site = f"{frame.f_code.co_filename}:{frame.f_lineno}"
    dev = events.dev_mode()

    # --- validation (the only raises; dev mode only) -----------------------
    row = events.known_event(event)
    if row is None and dev:
        raise ValueError(
            f"log_event: unknown event name '{event}' — every event needs a "
            "row in docs/specs/observability/instrumentation-map.csv"
        )
    resolved_error_class = events.validate_error_class(error_class)
    if dev and error_class is not None and resolved_error_class is None:
        raise ValueError(
            f"log_event: error_class {error_class!r} is outside the closed "
            "taxonomy (logging-api.md §8)"
        )
    if latency_ms is not None:
        if isinstance(latency_ms, bool) or not isinstance(latency_ms, int):
            if dev:
                raise TypeError("log_event: latency_ms must be an int or None")
            latency_ms = None
        elif latency_ms < 0 and dev:
            raise ValueError("log_event: latency_ms must be >= 0")

    # --- build + deliver (never raises beyond this point) ------------------
    try:
        clean_fields: dict[str, Any] = {}
        violations: list[tuple[str, str]] = []
        if fields:
            try:
                clean_fields, violations = redact_fields(dict(fields))
            except Exception:  # noqa: BLE001 — a broken payload must not break the caller
                clean_fields, violations = {"redaction_error": True}, [("?", "shape")]
        ids = snapshot_for(
            {
                "run_id": run_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "request_id": request_id,
            }
        )
        if severity is not None:
            level = (
                severity.value
                if isinstance(severity, events.Severity)
                else str(severity).upper()
            )
        else:
            level = events.severity_for(event).value
        record: dict[str, Any] = {
            "ts": _utc_now_iso_ms(),
            "schema_version": events.LOG_SCHEMA_VERSION,
            "severity": level,
            "event": event,
            "component": events.component_for(event, emitter_module),
            "env": events.env_name(),
            "stage": stage,
            "latency_ms": latency_ms,
            "error_class": (
                resolved_error_class.value
                if resolved_error_class is not None
                else error_class
            ),
            "fields": clean_fields,
        }
        for key in (
            "run_id",
            "session_id",
            "turn_id",
            "request_id",
            "client_session_id",
        ):
            if ids.get(key):
                record[key] = ids[key]
        # Level filter at emit (§5): a dropped DEBUG event costs nothing.
        configured = os.environ.get("ZIVON_LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if _level_rank(str(record["severity"])) < _level_rank(configured):
            return
        _dispatch(record)
        for key, kind in violations:
            _note_violation(event, call_site, key, kind)
        if row is None:
            _emit_store_event(
                "log.event_unknown",
                {"offender_event": event},
                severity=events.Severity.WARNING,
                error_class=None,
            )
    except Exception as exc:  # noqa: BLE001 — telemetry must never break the caller
        del exc


def _note_violation(event: str, call_site: str, key: str, kind: str) -> None:
    """Dedup per call site (first + every 100th, spec.md §4.4) so a chatty
    bug cannot flood the store."""
    counter_key = (call_site, key, kind)
    with _dispatch_lock:
        count = _violation_counts.get(counter_key, 0) + 1
        _violation_counts[counter_key] = count
        report = count == 1 or count % 100 == 0
    if report:
        _emit_store_event(
            "log.redaction_violation",
            {"event_ref": event, "key": key, "kind": kind},
            severity=events.Severity.WARNING,
            error_class=events.ErrorClass.PRIVACY_VIOLATION,
        )
