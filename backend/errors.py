"""Problem-details error model per backend-spec §6.

Every API error returns `{code, message_key, trace_id, retryable}` (plus
optional `retry_after` for `E-RATE-LIMIT`) so the frontend renders localized
copy from `INF-068` rather than raw stack traces or model text.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ERROR_MESSAGE_KEYS: Final[dict[str, str]] = {
    "E-RATE-LIMIT": "error.rate_limit",
    "E-INTERNAL": "error.system_internal",
    "E-SESSION-EXPIRED": "error.session_expired",
    "E-CONSENT-REQUIRED": "error.consent_required",
    "E-CONSENT-STALE": "error.consent_stale",
    "E-EVT-SCHEMA": "error.event_schema",
    "E-CONFIRM-REQUIRED": "error.confirm_required",
    "E-VALIDATION": "error.validation_failed",
    "E-NOT-FOUND": "error.not_found",
    "E-UNAUTHORIZED": "error.unauthorized",
    "E-FORBIDDEN": "error.forbidden",
    "E-SERVICE-UNAVAILABLE": "error.service_unavailable",
}


class APIError(Exception):
    """Structured API error mapped to the backend-spec §6 problem-details shape."""

    def __init__(
        self,
        code: str,
        status_code: int = 400,
        *,
        message_key: str | None = None,
        retryable: bool = False,
        retry_after: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.message_key = message_key or ERROR_MESSAGE_KEYS.get(
            code, "error.system_internal"
        )
        self.retryable = retryable
        self.retry_after = retry_after
        self.extra = extra or {}

    def to_payload(self, trace_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message_key": self.message_key,
            "trace_id": trace_id,
            "retryable": self.retryable,
        }
        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after
        if self.extra:
            payload.update(self.extra)
        return payload


def get_request_trace_id(request: Request) -> str:
    """Return the trace_id / request_id bound to the request."""
    trace_id = getattr(request.state, "trace_id", None)
    if isinstance(trace_id, str) and trace_id:
        return trace_id
    return "00000000-0000-0000-0000-000000000000"


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Render an APIError into a JSONResponse with X-Request-Id and Retry-After."""
    trace_id = get_request_trace_id(request)
    headers: dict[str, str] = {"X-Request-Id": trace_id}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_payload(trace_id),
        headers=headers,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Render FastAPI request validation errors in the standard error envelope."""
    trace_id = get_request_trace_id(request)
    return JSONResponse(
        status_code=422,
        content={
            "code": "E-VALIDATION",
            "message_key": ERROR_MESSAGE_KEYS["E-VALIDATION"],
            "trace_id": trace_id,
            "retryable": False,
        },
        headers={"X-Request-Id": trace_id},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render unexpected exceptions as E-INTERNAL without leaking internal details."""
    del exc
    trace_id = get_request_trace_id(request)
    return JSONResponse(
        status_code=500,
        content={
            "code": "E-INTERNAL",
            "message_key": ERROR_MESSAGE_KEYS["E-INTERNAL"],
            "trace_id": trace_id,
            "retryable": True,
        },
        headers={"X-Request-Id": trace_id},
    )
