"""logging_manager: the single emission point for every Zivon event.

The contract other modules code against is
`docs/specs/observability/logging-api.md`; the system decisions behind it are
ADR-0024 (stdlib JSON logging over OpenTelemetry), ADR-0025 (hot store +
fallback) and ADR-0026 (dashboard auth). This package imports nothing from
`factory/`, `llm_manager/` or any other Zivon module, does no model calls, no
hand-rolled HTTP, and prints nothing outside the sanctioned stdout sink.

Public surface (frozen — other agents' shims resolve to exactly these names):

    from logging_manager import (
        log_event,
        bind_context,
        context_scope,
        current_context,
        delete_subject,
        LOG_SCHEMA_VERSION,
        Severity,
        ErrorClass,
    )

Instrumentation owners (the factory adapter, the llm-manager node, the
dashboard) additionally import the helper modules directly
(`logging_manager.context.correlation_headers`, ...) — that is not part of
the frozen surface and never will be for consumers.
"""

from __future__ import annotations

from .context import bind_context, context_scope, current_context
from .events import LOG_SCHEMA_VERSION, ErrorClass, Severity
from .sink import log_event
from .store import delete_subject

__all__ = [
    "LOG_SCHEMA_VERSION",
    "ErrorClass",
    "Severity",
    "bind_context",
    "context_scope",
    "current_context",
    "delete_subject",
    "log_event",
]
