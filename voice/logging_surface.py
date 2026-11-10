"""Logging surface for ``voice/`` — the ONLY import point for log_event.

Codes against the ``logging_manager`` contract (docs/specs/observability/
logging-api.md) and resolves to the real ``logging_manager`` package (EX3-OBS,
landed on main). There is deliberately no local fallback: a single emission
point is the contract, and a second event vocabulary would drift.

Call-site law (logging-api.md §6 + spec.md §6): transcripts, audio and
secrets NEVER enter ``fields`` — logs carry ids, latencies, and counters only.
"""

from __future__ import annotations

from logging_manager import (
    LOG_SCHEMA_VERSION,
    ErrorClass,
    Severity,
    bind_context,
    context_scope,
    current_context,
    log_event,
)

__all__ = [
    "LOG_SCHEMA_VERSION",
    "ErrorClass",
    "Severity",
    "bind_context",
    "context_scope",
    "current_context",
    "log_event",
]
