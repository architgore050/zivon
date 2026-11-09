"""TEST-ONLY logging_manager shim — merge agent: replace with the real module.

`logging_manager/` (SP3-OBS, EX3-OBS) is not yet on this branch (wave E runs
in parallel; EX1 is last in the integration order). The mission brief
sanctions this shim: voice code is written against the contract in
``docs/specs/observability/logging-api.md`` and this module provides the same
public surface so the swap is a one-line change in ``voice/logging_surface.py``.

Deliberately NOT implemented here (the real module owns them):
- the Postgres sink / JSONL fallback / batch flush (§5) — this shim writes one
  JSON line to stdout through stdlib ``logging`` and nothing else;
- instrumentation-map.csv lint (§2) — CI's map-lint is the real module's job;
- the full redaction rule set (§6) — a minimal denylist + value-regex pass is
  kept here as defence-in-depth, but the guarantee voice relies on is at the
  call sites: **no transcripts, no audio, no tokens ever enter `fields`**.

Contract surface mirrored from logging-api.md §1–§8: signatures, JSON line
schema v1 (field order fixed, ``separators=(",", ":")``), closed Severity /
ErrorClass vocabularies, contextvars helpers, log_event never raises.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import Enum
from typing import Any

__all__ = [
    "LOG_SCHEMA_VERSION",
    "ErrorClass",
    "Severity",
    "bind_context",
    "context_scope",
    "current_context",
    "log_event",
]

LOG_SCHEMA_VERSION = 1

_ENV = os.environ.get("ZIVON_ENV", "dev")
_LEVEL = os.environ.get("ZIVON_LOG_LEVEL", "INFO").upper()

_LOGGER = logging.getLogger("zivon.voice.log")

_context: ContextVar[dict[str, str] | None] = ContextVar(
    "zivon_voice_log_context", default=None
)


class Severity(str, Enum):
    """logging-api.md §8 closed vocabulary (stdlib names)."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorClass(str, Enum):
    """logging-api.md §8 closed vocabulary — failure-shaped events only."""

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


# §6 key denylist (compact shim subset, case-insensitive, `*` = any suffix).
_DENYLIST = (
    "transcript",
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
    "audio",
    "wav",
    "pcm",
    "speech",
    "utterance",
    "cookie",
    "token",
    "secret",
    "key",
    "authorization",
)
_REDACTED = "[REDACTED:key-denylist]"

# §6 value regexes (shim subset): smuggle-prone shapes only.
_VALUE_RES = (
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE)),
    ("api_key", re.compile(r"\b(?:sk-|ZIVON_|GNANI_|AIza)[A-Za-z0-9_-]{8,}")),
    ("phone", re.compile(r"\+91[-\s]?\d{10}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    ("base64_blob", re.compile(r"\b[A-Za-z0-9+/=]{513,}\b")),
)

_known_unknown_events: set[str] = set()


def bind_context(**ids: str) -> None:
    """Set correlation ids at edges (logging-api.md §3 edge discipline)."""
    raw = _context.get()
    ctx = dict(raw) if raw else {}
    for name, value in ids.items():
        if value:
            ctx[name] = value
    _context.set(ctx)


def context_scope(**ids: str) -> Any:
    """Scoped, async-safe override of correlation ids (task-local)."""
    from types import TracebackType
    from typing import Self

    class _Scope:
        def __enter__(self) -> Self:
            self._token = _context.set(
                {**(_context.get() or {}), **{k: v for k, v in ids.items() if v}}
            )
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            _context.reset(self._token)

    return _Scope()


def current_context() -> dict[str, str]:
    """Read-only snapshot of the correlation context (tests, debugging)."""
    raw = _context.get()
    return dict(raw) if raw else {}


def log_event(
    event: str,
    fields: dict[str, Any] | None = None,
    *,
    severity: Severity | None = None,
    error_class: ErrorClass | None = None,
    latency_ms: int | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    turn_id: str | None = None,
    request_id: str | None = None,
    stage: str | None = None,
) -> None:
    """The single emission point (logging-api.md §2) — never raises."""
    try:
        _emit(
            event,
            fields,
            severity=severity,
            error_class=error_class,
            latency_ms=latency_ms,
            run_id=run_id,
            session_id=session_id,
            turn_id=turn_id,
            request_id=request_id,
            stage=stage,
        )
    except Exception:
        _LOGGER.exception("log_event failed for %s", event)


def _emit(
    event: str,
    fields: dict[str, Any] | None,
    *,
    severity: Severity | None,
    error_class: ErrorClass | None,
    latency_ms: int | None,
    run_id: str | None,
    session_id: str | None,
    turn_id: str | None,
    request_id: str | None,
    stage: str | None,
) -> None:
    if severity is None:
        severity = Severity.INFO
    if severity is Severity.DEBUG and _LEVEL == "INFO":
        return
    ctx_raw = _context.get()
    ctx = ctx_raw if ctx_raw is not None else {}
    record: dict[str, Any] = {
        "ts": datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "schema_version": LOG_SCHEMA_VERSION,
        "severity": severity.value,
        "event": event,
        "component": "voice",
        "env": _ENV,
    }
    for name, value in (
        ("run_id", run_id),
        ("session_id", session_id),
        ("turn_id", turn_id),
        ("request_id", request_id),
    ):
        resolved = value or ctx.get(name)
        if resolved:
            record[name] = resolved
    if stage:
        record["stage"] = stage
    if latency_ms is not None:
        record["latency_ms"] = max(0, int(latency_ms))
    if error_class is not None:
        record["error_class"] = ErrorClass(error_class).value
    record["fields"] = _redact(fields or {})
    if event not in _known_unknown_events and not event.startswith(("log.", "voice.")):
        # Real module: unknown map name → log.event_unknown WARNING + still
        # delivered (§2). Shim: dedup to first occurrence to avoid floods.
        _known_unknown_events.add(event)
        _emit(
            "log.event_unknown",
            {"offender": event},
            severity=Severity.WARNING,
            error_class=None,
            latency_ms=None,
            run_id=None,
            session_id=None,
            turn_id=None,
            request_id=None,
            stage=None,
        )
    _LOGGER.log(
        getattr(logging, severity.value),
        json.dumps(record, separators=(",", ":"), ensure_ascii=False),
    )


def _redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Minimal §6 pass — denylist keys + smuggle regexes (shim subset)."""
    out: dict[str, Any] = {}
    for raw_key, value in fields.items():
        key = raw_key.lower()
        if any(key.startswith(d) for d in _DENYLIST):
            out[raw_key] = _REDACTED
            continue
        if isinstance(value, str):
            for kind, rx in _VALUE_RES:
                if rx.search(value):
                    value = rx.sub(f"[REDACTED:{kind}]", value)
        out[raw_key] = value
    return out
