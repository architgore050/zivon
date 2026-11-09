"""Typed errors for the shared model-call module.

Rule (mirrors factory/errors.py): no silent fallbacks, ever. Every failure is
one of these exceptions with a message that says what broke and how to fix
it. Callers (the content factory adapter, the service node, a future
translator) map these onto their own error types at their boundary.

This package is standalone: it imports nothing from factory/.
"""

from __future__ import annotations


class LLMManagerError(Exception):
    """Base class for every deliberate llm_manager failure."""


class TransportError(LLMManagerError):
    """The model call failed for a transport reason no retry could fix.

    Covers: connection errors, read/connect timeouts (inactivity between
    streamed chunks), retryable HTTP statuses (429/5xx) exhausted across all
    attempts, and the per-call wall-clock deadline abort. The message carries
    the URL, the number of tries and the underlying cause so the operator can
    act without opening a debugger.
    """


class NonRetryableHTTPError(LLMManagerError):
    """The server rejected the call with a non-retryable HTTP status.

    Carries the status code and the server's own body: a 400 about
    response_format means "set ZIVON_JSON_MODE=false", a 400 about
    stream_options means "set ZIVON_STREAM_USAGE=false". Retrying cannot fix
    these, so they surface immediately.
    """

    def __init__(self, message: str, status_code: int):
        self.status_code = status_code
        super().__init__(message)


class BadServerResponseError(LLMManagerError):
    """The response did not match the OpenAI chat-completions shape.

    The message includes everything observable about the offending response
    (first 300 chars where available) so a misbehaving server is diagnosable
    from the error alone.
    """


class ValidationExhaustedError(LLMManagerError):
    """Model output failed validation on every validation round.

    Raised by the validation-round loop after `validation_rounds` rounds of
    feeding the exact violation back to the model. The caller decides what
    this means for its domain (the factory maps it to SchemaError).
    """
