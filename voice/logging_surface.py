"""Logging surface for ``voice/`` — the ONLY import point for log_event.

Codes against the ``logging_manager`` contract (docs/specs/observability/
logging-api.md). When the real module lands (EX3-OBS), the merge agent
deletes the import-error fallback and everything else stays untouched:

    try:
        from logging_manager import ...   # real module (Postgres sink, map lint)
    except ImportError:
        from ._logging_shim import ...    # test-only shim (stdout JSON lines)

Call-site law (logging-api.md §6 + spec.md §6): transcripts, audio and
secrets NEVER enter ``fields`` — logs carry ids, latencies, and counters only.
"""

from __future__ import annotations

try:  # real module (EX3-OBS lands logging_manager/ on main)
    from logging_manager import (  # type: ignore[import-not-found]
        LOG_SCHEMA_VERSION,
        ErrorClass,
        Severity,
        bind_context,
        context_scope,
        current_context,
        log_event,
    )
except ImportError:  # test-only shim until the merge agent wires EX3's module
    from ._logging_shim import (
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
