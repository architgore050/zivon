"""Contract-compliant shim for `logging_manager` (docs/specs/observability/logging-api.md).

If the `logging_manager` package (built by EX3-OBS) is present on PYTHONPATH,
this module re-exports its public symbols directly. Otherwise it provides a
contract-compatible implementation (contextvars correlation, key-denylist +
value-regex redaction, JSON line formatting, JSONL fallback + DB sink hook,
and `delete_subject` for guardian deletion).
"""

from __future__ import annotations

import contextlib
import contextvars
import datetime
import enum
import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

LOG_SCHEMA_VERSION: int = 1


class Severity(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorClass(str, enum.Enum):
    TRANSPORT_ERROR = "transport_error"
    VALIDATION_ERROR = "validation_error"
    GATE_FAIL = "gate_fail"
    REPAIR_EXHAUSTED = "repair_exhausted"
    INFRA_ERROR = "infra_error"
    QUOTA_ERROR = "quota_error"
    AUTH_ERROR = "auth_error"
    CLIENT_ERROR = "client_error"
    PRIVACY_VIOLATION = "privacy_violation"
    STORE_ERROR = "store_error"


_CTX_VAR: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "zivon_log_context", default=None
)

_DENYLIST_PREFIXES: tuple[str, ...] = (
    "transcript",
    "audio",
    "speech",
    "utterance",
)

_DENYLIST_EXACT: frozenset[str] = frozenset(
    {
        "text",
        "content",
        "prompt",
        "messages",
        "response",
        "completion",
        "answer",
        "page_html",
        "code",
        "patch",
        "wav",
        "pcm",
        "cookie",
        "token",
        "secret",
        "key",
        "authorization",
    }
)

_ALLOWED_REFERENCE_KEYS: frozenset[str] = frozenset(
    {
        "transcript_row_id",
        "artifact_path",
        "block_id",
        "topic",
        "chapter",
    }
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
_API_KEY_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|ZIVON_[A-Za-z0-9_]{8,})\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+\b", re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_B64_RE = re.compile(r"[A-Za-z0-9+/]{513,}={0,2}")

_DB_WRITER_HOOK: Callable[[dict[str, Any]], None] | None = None
_DB_DELETE_SUBJECT_HOOK: Callable[[str], int] | None = None
_EMITTED_EVENTS_BUFFER: list[dict[str, Any]] = []


def register_db_sink(
    writer: Callable[[dict[str, Any]], None] | None,
    delete_hook: Callable[[str], int] | None = None,
) -> None:
    """Register the database sink writer and subject-deletion hook."""
    global _DB_WRITER_HOOK, _DB_DELETE_SUBJECT_HOOK
    _DB_WRITER_HOOK = writer
    _DB_DELETE_SUBJECT_HOOK = delete_hook


def get_emitted_events() -> list[dict[str, Any]]:
    """Return a copy of in-memory emitted events (for tests)."""
    return list(_EMITTED_EVENTS_BUFFER)


def clear_emitted_events() -> None:
    """Clear the in-memory emitted events buffer (for tests)."""
    _EMITTED_EVENTS_BUFFER.clear()


def _is_denied_key(key: str) -> bool:
    low = key.lower()
    if low in _ALLOWED_REFERENCE_KEYS:
        return False
    if low in _DENYLIST_EXACT:
        return True
    return any(low.startswith(prefix) for prefix in _DENYLIST_PREFIXES)


def _scrub_string(value: str) -> str:
    if len(value) > 512 and _B64_RE.search(value):
        return "[REDACTED:base64]"
    scrubbed = _JWT_RE.sub("[REDACTED:jwt]", value)
    scrubbed = _BEARER_RE.sub("[REDACTED:bearer]", scrubbed)
    scrubbed = _API_KEY_RE.sub("[REDACTED:api_key]", scrubbed)
    scrubbed = _EMAIL_RE.sub("[REDACTED:email]", scrubbed)
    scrubbed = _PHONE_RE.sub("[REDACTED:phone]", scrubbed)
    return scrubbed


def redact_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    """Apply mechanical key-denylist and value-regex redaction per logging-api §6."""
    if not fields:
        return {}
    out: dict[str, Any] = {}
    for key, val in fields.items():
        if _is_denied_key(key):
            out[key] = "[REDACTED:key-denylist]"
            continue
        if isinstance(val, str):
            out[key] = _scrub_string(val)
        elif isinstance(val, list):
            out[key] = [
                _scrub_string(item) if isinstance(item, str) else item for item in val
            ]
        elif isinstance(val, dict):
            nested: dict[str, Any] = {}
            for k2, v2 in val.items():
                if _is_denied_key(k2):
                    nested[k2] = "[REDACTED:key-denylist]"
                elif isinstance(v2, str):
                    nested[k2] = _scrub_string(v2)
                else:
                    nested[k2] = v2
            out[key] = nested
        else:
            out[key] = val
    return out


def bind_context(
    *,
    run_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """Bind correlation IDs into the current async/thread context."""
    updated = dict(_CTX_VAR.get() or {})
    if run_id is not None:
        updated["run_id"] = run_id
    if session_id is not None:
        updated["session_id"] = session_id
    if turn_id is not None:
        updated["turn_id"] = turn_id
    if request_id is not None:
        updated["request_id"] = request_id
    _CTX_VAR.set(updated)


@contextlib.contextmanager
def context_scope(
    *,
    run_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    request_id: str | None = None,
) -> Iterator[None]:
    """Scoped correlation ID override (async-safe and task-local)."""
    updated = dict(_CTX_VAR.get() or {})
    if run_id is not None:
        updated["run_id"] = run_id
    if session_id is not None:
        updated["session_id"] = session_id
    if turn_id is not None:
        updated["turn_id"] = turn_id
    if request_id is not None:
        updated["request_id"] = request_id
    token = _CTX_VAR.set(updated)
    try:
        yield
    finally:
        _CTX_VAR.reset(token)


def current_context() -> dict[str, str]:
    """Return a read-only snapshot of current correlation IDs."""
    return dict(_CTX_VAR.get() or {})


def _infer_component(event: str) -> str:
    prefix = event.split(".", 1)[0] if "." in event else "voice"
    mapping = {
        "factory": "factory",
        "node": "llm_node",
        "llm": "llm",
        "voice": "voice",
        "translator": "translator",
        "frontend": "frontend",
        "credit": "credit",
        "dashboard": "dashboard",
        "log": "log",
        "privacy": "voice",
    }
    return mapping.get(prefix, "voice")


def _fallback_log_file(component: str, day_str: str) -> Path:
    runs_dir = Path(os.environ.get("ZIVON_RUNS_DIR", "/tmp/zivon-runs"))
    log_dir = runs_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{day_str}-{component}.jsonl"


def _shim_log_event(
    event: str,
    fields: dict[str, Any] | None = None,
    *,
    severity: Severity | str | None = None,
    error_class: ErrorClass | str | None = None,
    latency_ms: int | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    request_id: str | None = None,
    stage: str | None = None,
) -> None:
    """Emit a structured JSON log line per logging-api §2 and §4."""
    if latency_ms is not None and latency_ms < 0:
        if os.environ.get("ZIVON_LOG_LEVEL", "INFO").upper() == "DEBUG":
            raise ValueError("latency_ms must be >= 0")
        latency_ms = 0

    sev_val = (
        severity.value
        if isinstance(severity, Severity)
        else (str(severity) if severity else Severity.INFO.value)
    )
    if (
        sev_val == Severity.DEBUG.value
        and os.environ.get("ZIVON_LOG_LEVEL", "INFO").upper() != "DEBUG"
    ):
        return

    now = datetime.datetime.now(datetime.UTC)
    ts_str = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    ctx = _CTX_VAR.get() or {}
    eff_run_id = run_id if run_id is not None else ctx.get("run_id")
    eff_session_id = session_id if session_id is not None else ctx.get("session_id")
    eff_turn_id = turn_id if turn_id is not None else ctx.get("turn_id")
    eff_request_id = request_id if request_id is not None else ctx.get("request_id")

    component = _infer_component(event)
    env = os.environ.get("ZIVON_ENV", "dev").strip() or "dev"
    redacted = redact_fields(fields)

    record: dict[str, Any] = {
        "ts": ts_str,
        "schema_version": LOG_SCHEMA_VERSION,
        "severity": sev_val,
        "event": event,
        "component": component,
        "env": env,
    }
    if eff_run_id:
        record["run_id"] = eff_run_id
    if eff_session_id:
        record["session_id"] = eff_session_id
    if eff_turn_id:
        record["turn_id"] = eff_turn_id
    if eff_request_id:
        record["request_id"] = eff_request_id
    if stage:
        record["stage"] = stage
    if latency_ms is not None:
        record["latency_ms"] = int(latency_ms)
    if error_class is not None:
        record["error_class"] = (
            error_class.value
            if isinstance(error_class, ErrorClass)
            else str(error_class)
        )
    record["fields"] = redacted

    _EMITTED_EVENTS_BUFFER.append(record)
    if len(_EMITTED_EVENTS_BUFFER) > 2000:
        del _EMITTED_EVENTS_BUFFER[:500]

    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
    try:
        if os.environ.get("ZIVON_LOG_STDOUT", "false").lower() == "true":
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001, S110
        pass

    wrote_db = False
    if _DB_WRITER_HOOK is not None:
        try:
            _DB_WRITER_HOOK(record)
            wrote_db = True
        except Exception:  # noqa: BLE001
            wrote_db = False

    if not wrote_db:
        try:
            day_str = now.strftime("%Y%m%d")
            path = _fallback_log_file(component, day_str)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001, S110
            pass


def _shim_delete_subject(session_id: str) -> int:
    """Purge log events for a pseudonymous session_id across DB and JSONL fallback.

    Deleting a subject must FAIL LOUD: a DB-hook error is re-raised (never
    swallowed), so the caller can stamp the tombstone `failed`. Unreadable
    JSONL fallback files are logged at WARNING with their path; they are NOT
    silently dropped — they are counted in the `privacy.subject_deleted`
    event fields (`unreadable_files`) and exposed via the module-level
    `LAST_SCRUB_UNREADABLE` list.
    """
    deleted = 0
    unreadable: list[str] = []
    if _DB_DELETE_SUBJECT_HOOK is not None:
        # Propagate DB-hook failures — deletion must never quietly half-complete.
        deleted += _DB_DELETE_SUBJECT_HOOK(session_id)

    # Scrub in-memory buffer
    before = len(_EMITTED_EVENTS_BUFFER)
    _EMITTED_EVENTS_BUFFER[:] = [
        ev for ev in _EMITTED_EVENTS_BUFFER if ev.get("session_id") != session_id
    ]
    deleted += before - len(_EMITTED_EVENTS_BUFFER)

    # Scrub fallback JSONL files if present
    runs_dir = Path(os.environ.get("ZIVON_RUNS_DIR", "/tmp/zivon-runs"))
    log_dir = runs_dir / "logs"
    if log_dir.is_dir():
        for path in log_dir.glob("*.jsonl"):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                kept: list[str] = []
                for raw in lines:
                    if not raw.strip():
                        continue
                    try:
                        parsed = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        # Unparseable lines may still contain subject-bearing
                        # records: keep them and count the file as
                        # scrub-incomplete (once per file).
                        if str(path) not in unreadable:
                            unreadable.append(str(path))
                        kept.append(raw)
                        continue
                    if parsed.get("session_id") == session_id:
                        deleted += 1
                    else:
                        kept.append(raw)
                path.write_text(
                    "\n".join(kept) + ("\n" if kept else ""), encoding="utf-8"
                )
            except Exception as exc:  # noqa: BLE001
                unreadable.append(str(path))
                log_event(
                    "privacy.log_scrub_failed",
                    {"artifact_path": str(path), "reason_code": "unreadable"},
                    severity=Severity.WARNING,
                    error_class=ErrorClass.STORE_ERROR,
                    session_id=session_id,
                )
                if os.environ.get("ZIVON_LOG_LEVEL", "INFO").upper() == "DEBUG":
                    print(
                        f"[logging_shim] jsonl scrub failed {path}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                continue

    globals()["LAST_SCRUB_UNREADABLE"] = unreadable
    _shim_log_event(
        "privacy.subject_deleted",
        {
            "session_count": 1,
            "stores_touched": 2,
            "unreadable_files": len(unreadable),
        },
        severity=Severity.INFO,
        session_id=session_id,
    )
    return deleted


# Populated by _shim_delete_subject after each scrub (inspectable for wipe result)
LAST_SCRUB_UNREADABLE: list[str] = []


try:
    # Prefer the real EX3-OBS logging_manager package when merged on PYTHONPATH
    from logging_manager import (  # type: ignore[import-not-found]
        LOG_SCHEMA_VERSION as _REAL_SCHEMA_VERSION,
    )
    from logging_manager import (
        ErrorClass as _RealErrorClass,
    )
    from logging_manager import (
        Severity as _RealSeverity,
    )
    from logging_manager import (
        bind_context as _real_bind_context,
    )
    from logging_manager import (
        context_scope as _real_context_scope,
    )
    from logging_manager import (
        current_context as _real_current_context,
    )
    from logging_manager import (
        delete_subject as _real_delete_subject,
    )
    from logging_manager import (
        log_event as _real_log_event,
    )

    LOG_SCHEMA_VERSION = _REAL_SCHEMA_VERSION
    Severity = _RealSeverity  # type: ignore[misc,assignment]
    ErrorClass = _RealErrorClass  # type: ignore[misc,assignment]
    bind_context = _real_bind_context
    context_scope = _real_context_scope
    current_context = _real_current_context

    def log_event(
        event: str,
        fields: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        _real_log_event(event, fields, **kwargs)
        if _DB_WRITER_HOOK is not None:
            try:
                _shim_log_event(event, fields, **kwargs)
            except Exception:  # noqa: BLE001, S110
                pass

    def delete_subject(session_id: str) -> int:
        _real_delete_subject(session_id)
        return _shim_delete_subject(session_id)

except ImportError:
    log_event = _shim_log_event
    delete_subject = _shim_delete_subject
