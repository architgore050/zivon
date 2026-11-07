"""llm_manager: the shared, generalized OpenAI-format model-call module.

Standalone by contract: imports nothing from factory/, reusable by the
content factory (via the thin adapter in factory/llm.py), by the service node
(llm_manager/service/), and by any future consumer (translator; voice agent
out of scope - voice streaming is a different domain).

Exports the public surface: LLMManager (complete/stream/stream_events),
LLMConfig (+ from_env), ChatResult, StreamEvent, the error types, and the
validation-round machinery.
"""

from __future__ import annotations

from .client import ChatResult, LLMManager, LLMObserver, StreamEvent, build_wire_request
from .config import LLMConfig, LLMConfigError
from .errors import (
    BadServerResponseError,
    LLMManagerError,
    NonRetryableHTTPError,
    TransportError,
    ValidationExhaustedError,
)
from .validation import (
    format_jsonschema_error,
    parse_json_object,
    run_validation_rounds,
)

__all__ = [
    "BadServerResponseError",
    "ChatResult",
    "LLMConfig",
    "LLMConfigError",
    "LLMManager",
    "LLMManagerError",
    "LLMObserver",
    "NonRetryableHTTPError",
    "StreamEvent",
    "TransportError",
    "ValidationExhaustedError",
    "build_wire_request",
    "format_jsonschema_error",
    "parse_json_object",
    "run_validation_rounds",
]
