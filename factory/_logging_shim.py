"""Logging contract adapter and test-only shim for logging_manager (SP3-OBS).

When EX3-OBS's `logging_manager` package is present in the environment, this
module re-exports its public surface directly. When running on an isolated
branch before Wave-E merge, it provides a contract-faithful shim implementing
`docs/specs/observability/logging-api.md` (JSON line schema v1, contextvars
correlation, mechanical key/value redaction, and JSONL fallback sink).
"""

from __future__ import annotations

import contextvars
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from logging_manager import (  # type: ignore[import-not-found]
        LOG_SCHEMA_VERSION,
        ErrorClass,
        Severity,
        bind_context,
        context_scope,
        current_context,
        delete_subject,
        log_event,
    )

    USING_SHIM = False
except ImportError:
    USING_SHIM = True
    LOG_SCHEMA_VERSION = 1

    class Severity(str, Enum):  # type: ignore[no-redef]
        DEBUG = "DEBUG"
        INFO = "INFO"
        WARNING = "WARNING"
        ERROR = "ERROR"
        CRITICAL = "CRITICAL"

    class ErrorClass(str, Enum):  # type: ignore[no-redef]
        transport_error = "transport_error"
        validation_error = "validation_error"
        gate_fail = "gate_fail"
        repair_exhausted = "repair_exhausted"
        infra_error = "infra_error"
        quota_error = "quota_error"
        auth_error = "auth_error"
        client_error = "client_error"
        privacy_violation = "privacy_violation"
        store_error = "store_error"

    _CTX_VARS: dict[str, contextvars.ContextVar[str | None]] = {
        "run_id": contextvars.ContextVar("zivon_run_id", default=None),
        "session_id": contextvars.ContextVar("zivon_session_id", default=None),
        "turn_id": contextvars.ContextVar("zivon_turn_id", default=None),
        "request_id": contextvars.ContextVar("zivon_request_id", default=None),
    }

    _DENYLIST_EXACT = {
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
    _DENYLIST_PREFIXES = ("transcript", "audio", "speech", "utterance")

    _VALUE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (
            re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
            "email",
        ),
        (
            re.compile(r"(?:\+91[\-\s]?)?[6-9]\d{9}\b"),
            "phone",
        ),
        (
            re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ZIVON_[A-Za-z0-9_]{8,})\b"),
            "api_key",
        ),
        (
            re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]+\b", re.IGNORECASE),
            "bearer",
        ),
        (
            re.compile(
                r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"
            ),
            "jwt",
        ),
    ]

    _EMITTED_EVENTS: list[dict[str, Any]] = []

    def bind_context(
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if run_id is not None:
            _CTX_VARS["run_id"].set(run_id)
        if session_id is not None:
            _CTX_VARS["session_id"].set(session_id)
        if turn_id is not None:
            _CTX_VARS["turn_id"].set(turn_id)
        if request_id is not None:
            _CTX_VARS["request_id"].set(request_id)

    @contextmanager
    def context_scope(**overrides: str | None) -> Iterator[None]:
        tokens: list[tuple[contextvars.ContextVar[str | None], Any]] = []
        for k, v in overrides.items():
            if k in _CTX_VARS:
                tokens.append((_CTX_VARS[k], _CTX_VARS[k].set(v)))
        try:
            yield
        finally:
            for var, tok in reversed(tokens):
                var.reset(tok)

    def current_context() -> dict[str, str]:
        out: dict[str, str] = {}
        for k, var in _CTX_VARS.items():
            val = var.get()
            if val is not None:
                out[k] = val
        return out

    def _is_denied_key(key: str) -> bool:
        low = key.lower()
        if low in _DENYLIST_EXACT:
            return True
        return any(low.startswith(prefix) for prefix in _DENYLIST_PREFIXES)

    def _scrub_string(value: str) -> str:
        if len(value) > 512 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", value):
            return "[REDACTED:base64]"
        out = value
        for pattern, kind in _VALUE_PATTERNS:
            out = pattern.sub(f"[REDACTED:{kind}]", out)
        return out

    def _redact_payload(fields: dict[str, Any] | None) -> dict[str, Any]:
        if not fields:
            return {}
        clean: dict[str, Any] = {}
        for k, v in fields.items():
            if _is_denied_key(str(k)):
                clean[str(k)] = "[REDACTED:key-denylist]"
            elif isinstance(v, str):
                clean[str(k)] = _scrub_string(v)
            elif isinstance(v, list):
                clean[str(k)] = [
                    _scrub_string(item) if isinstance(item, str) else item for item in v
                ]
            elif isinstance(v, dict):
                clean[str(k)] = _redact_payload(v)
            else:
                clean[str(k)] = v
        return clean

    def log_event(
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
        try:
            ctx = current_context()
            comp_prefix = event.split(".", 1)[0] if "." in event else "translator"
            comp_map = {
                "factory": "factory",
                "node": "llm_node",
                "voice": "voice",
                "translator": "translator",
                "frontend": "frontend",
                "dashboard": "dashboard",
                "credit": "credit",
                "log": "log",
                "privacy": "log",
            }
            component = comp_map.get(comp_prefix, "translator")
            sev_str = (
                severity.value
                if isinstance(severity, Severity)
                else str(severity or "INFO")
            )
            err_str = (
                error_class.value
                if isinstance(error_class, ErrorClass)
                else (str(error_class) if error_class is not None else None)
            )
            now_dt = datetime.now(UTC)
            record: dict[str, Any] = {
                "ts": now_dt.strftime("%Y-%m-%dT%H:%M:%S.")
                + f"{now_dt.microsecond // 1000:03d}Z",
                "schema_version": LOG_SCHEMA_VERSION,
                "severity": sev_str,
                "event": event,
                "component": component,
                "env": os.environ.get("ZIVON_ENV", "dev"),
            }
            resolved_run = run_id or ctx.get("run_id")
            if resolved_run:
                record["run_id"] = resolved_run
            resolved_session = session_id or ctx.get("session_id")
            if resolved_session:
                record["session_id"] = resolved_session
            resolved_turn = turn_id or ctx.get("turn_id")
            if resolved_turn:
                record["turn_id"] = resolved_turn
            resolved_req = request_id or ctx.get("request_id")
            if resolved_req:
                record["request_id"] = resolved_req
            if stage:
                record["stage"] = stage
            if latency_ms is not None:
                record["latency_ms"] = max(0, int(latency_ms))
            if err_str is not None:
                record["error_class"] = err_str
            record["fields"] = _redact_payload(fields)

            _EMITTED_EVENTS.append(record)

            log_dir = os.environ.get("ZIVON_LOG_DIR")
            if log_dir:
                day_str = now_dt.strftime("%Y%m%d")
                target = Path(log_dir) / f"{day_str}-{component}.jsonl"
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(record, separators=(",", ":"), ensure_ascii=False)
                        + "\n"
                    )
        except Exception:  # noqa: BLE001 — logging_manager contract §2: log_event never raises
            return

    def delete_subject(session_id: str) -> dict[str, Any]:
        before = len(_EMITTED_EVENTS)
        _EMITTED_EVENTS[:] = [
            e for e in _EMITTED_EVENTS if e.get("session_id") != session_id
        ]
        removed = before - len(_EMITTED_EVENTS)
        log_event(
            "privacy.subject_deleted",
            {"session_count": removed, "stores_touched": ["memory_shim"]},
            severity=Severity.INFO,
            session_id=session_id,
        )
        return {"session_id": session_id, "deleted": removed}


def get_recorded_events() -> list[dict[str, Any]]:
    """Return in-memory emitted events (used by unit tests verifying telemetry)."""
    if USING_SHIM:
        return list(_EMITTED_EVENTS)
    return []


def clear_recorded_events() -> None:
    """Clear in-memory emitted events (used by unit tests)."""
    if USING_SHIM:
        _EMITTED_EVENTS.clear()


__all__ = [
    "LOG_SCHEMA_VERSION",
    "USING_SHIM",
    "ErrorClass",
    "Severity",
    "bind_context",
    "clear_recorded_events",
    "context_scope",
    "current_context",
    "delete_subject",
    "get_recorded_events",
    "log_event",
]
