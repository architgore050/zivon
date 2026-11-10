"""LLMManager: the single, generalized model-call path.

Streaming by default (2026-11-07). Why streaming is not an optimization but a
correctness fix: on 2026-11-07 a factory run died because the inference server
kept generating tokens for 3,592 s per attempt (77,921 -> 131,445 -> 199,056
tokens across three transport tries) while the client sat silent and read-
timed-out at 3,600 s each time. A non-streaming response sends zero bytes
until generation ends, so `requests`' per-read-operation timeout cannot kill a
rambling generation - the read timeout only proves the socket was quiet, and
the server kept burning its single slot. Streaming changes the physics:

- bytes flow as tokens are generated, so "no chunk for timeout_s" is an
  HONEST dead-server signal (inactivity, not total duration);
- a wall-clock deadline (`call_deadline_s`) can close the connection
  mid-stream, which makes the server stop generating and frees its slot for
  the next try.

Retry policy (single source of truth - `max_retries=0` is mandatory on the
langchain client so this module owns retry semantics): connection errors,
timeouts, HTTP 429 and 500/502/503/504 are retried up to `max_attempts` with
exponential backoff (`backoff_base_s` doubling). Any other HTTP status fails
immediately as `NonRetryableHTTPError` with the server's body. The
validation-round loop (validation.py) has its OWN budget and never shares
this transport budget.

Observability: this module prints NOTHING. An optional `observer` receives
`on_call_start(request_summary)`, `on_progress(elapsed_s, chunks_received)`
every `heartbeat_s`, and `on_call_end(result)` - the factory prints its own
way and a plain consumer stays silent.

Token counting: never local. langchain/tiktoken counters are offline-hostile;
usage comes only from the server's reported usage, normalized to the OpenAI
keys prompt_tokens / completion_tokens / total_tokens.

This module is standalone: it imports nothing from factory/.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import openai
from langchain_openai import ChatOpenAI

from .config import LLMConfig
from .errors import (
    BadServerResponseError,
    NonRetryableHTTPError,
    TransportError,
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class ChatResult:
    """One finished model call. Usage uses OpenAI's key names (normalized
    back from langchain's usage_metadata); an empty dict means the server
    reported no usage. first_token_s is None when no content chunk ever
    arrived (a None is itself diagnostic: the server produced nothing)."""

    text: str
    usage: dict[str, int]
    finish_reason: str | None
    http_status: int
    latency_s: float
    first_token_s: float | None
    chunks_received: int
    model: str


@dataclass
class StreamEvent:
    """One typed event on the incremental stream. Exactly one field is set:
    `delta` (a content chunk), `finish_reason` (the terminal chunk), or
    `usage` (the final usage report when the server sends one)."""

    delta: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class LLMObserver:
    """Observer hooks: no-op defaults, override what you need.

    on_call_start fires once per complete()/stream_events() call; on_progress
    fires on the heartbeat cadence while the call is in flight; on_call_end
    fires once with the final ChatResult (complete() only).
    """

    def on_call_start(self, request_summary: dict[str, Any]) -> None:
        pass

    def on_progress(self, elapsed_s: float, chunks_received: int) -> None:
        pass

    def on_call_end(self, result: ChatResult) -> None:
        pass


class _CallState:
    """Shared per-call counters (heartbeat thread reads, consume loop writes;
    GIL-safe int reads/writes are good enough for progress reporting)."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.chunks = 0


@contextmanager
def _heartbeat(
    observer: LLMObserver, interval_s: float, state: _CallState
) -> Iterator[None]:
    """A tiny daemon thread that ticks the observer's on_progress while the
    main thread blocks on the next chunk. A thinking model can be silent for
    many minutes; the heartbeat proves the client is alive and shows real
    streaming progress (chunks received), not just elapsed time."""
    stop = threading.Event()

    def run() -> None:
        while not stop.wait(interval_s):
            observer.on_progress(time.monotonic() - state.t0, state.chunks)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def build_wire_request(
    config: LLMConfig,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
) -> dict[str, Any]:
    """The OpenAI-format request this config implies, as closely as langchain
    allows. Used both as the source of truth for the call and as the
    artifact/summary representation (the factory persists a redacted copy).
    `stream` / `stream_options` appear only when streaming."""
    request: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
    }
    if config.json_mode:
        request["response_format"] = {"type": "json_object"}
    if config.stream:
        request["stream"] = True
        if config.stream_usage:
            request["stream_options"] = {"include_usage": True}
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
    return request


class LLMManager:
    """Transport, streaming, retries, deadline. The only model-handling path:
    no other module may hand-roll HTTP calls to an inference server."""

    def __init__(self, config: LLMConfig, observer: LLMObserver | None = None):
        self.config = config
        self.observer: LLMObserver = observer or LLMObserver()

    # ------------------------------------------------------------- public API
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """One blocking model call with transport retries and deadline abort.

        When config.stream is True the stream is consumed internally and
        accumulated - the caller gets one ChatResult and the server's
        connection is held only as long as generation runs."""
        temperature = self.config.temperature if temperature is None else temperature
        wire = build_wire_request(self.config, messages, temperature, max_tokens)
        summary = dict(wire)
        summary["messages"] = f"{len(messages)} message(s)"
        summary["prompt_chars"] = sum(len(m.get("content", "")) for m in messages)
        self.observer.on_call_start(summary)

        state = _CallState()
        client = self._build_http_client()
        try:
            with _heartbeat(self.observer, self.config.heartbeat_s, state):
                return self._complete_with_retries(
                    messages, temperature, max_tokens, wire, state, client
                )
        finally:
            client.close()

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> Iterator[str]:
        """Content deltas only - the thin text view over stream_events(), for
        consumers that want incremental output (the future translator)."""
        for event in self.stream_events(messages, temperature=temperature):
            if event.delta is not None:
                yield event.delta

    def stream_events(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> Iterator[StreamEvent]:
        """Typed incremental stream: content deltas plus the terminal
        finish_reason and usage events when the server sends them.

        Retry semantics (honest, loud): transport retries happen until the
        FIRST event is yielded. Once a delta has reached the consumer, a
        transport failure propagates - silently restarting would duplicate
        text the consumer already saw. Deadline abort works exactly as in
        complete(): the stream is closed so the server stops generating."""
        temperature = self.config.temperature if temperature is None else temperature
        state = _CallState()
        client = self._build_http_client()
        try:
            emitted = False
            for attempt in range(1, self.config.max_attempts + 1):
                chat = self._build_chat(
                    temperature, None, streaming=True, http_client=client
                )
                try:
                    for event in self._iter_events(chat, messages, state):
                        emitted = True
                        yield event
                    return
                except (
                    openai.APITimeoutError,
                    openai.APIConnectionError,
                ) as exc:
                    if emitted:
                        raise self._partial_stream_failure(exc, state) from exc
                    if attempt == self.config.max_attempts:
                        raise self._unreachable(exc, attempt) from exc
                    self._sleep_backoff(attempt)
                except openai.APIStatusError as exc:
                    if emitted:
                        raise self._partial_stream_failure(exc, state) from exc
                    if exc.status_code in RETRYABLE_STATUS:
                        if attempt == self.config.max_attempts:
                            raise self._status_exhausted(exc, attempt) from exc
                        self._sleep_backoff(attempt)
                    else:
                        raise self._non_retryable(exc) from exc
                except openai.APIError as exc:
                    # A bare APIError (not a status/connection/timeout subclass)
                    # means the server itself reported failure inside the call:
                    # an OpenAI-format server may answer HTTP 200 and put the
                    # failure in an SSE error payload (llama.cpp does this for
                    # context overflow; our llm-manager node does it when its
                    # upstream budget is exhausted). The SDK raises it with the
                    # server's own message. Retrying cannot fix "the server
                    # says it failed" - terminal TransportError, message kept.
                    raise self._server_reported(exc) from exc
        finally:
            client.close()

    # ------------------------------------------------------------- internals
    def _complete_with_retries(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        wire: dict[str, Any],
        state: _CallState,
        client: httpx.Client,
    ) -> ChatResult:
        last_transport: Exception | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                if self.config.stream:
                    return self._complete_streaming(
                        messages, temperature, max_tokens, state, client
                    )
                return self._complete_invocation(
                    messages, temperature, max_tokens, state, client
                )
            except (openai.APITimeoutError, openai.APIConnectionError) as exc:
                last_transport = exc
                if attempt == self.config.max_attempts:
                    raise self._unreachable(exc, attempt) from exc
                self._sleep_backoff(attempt)
            except openai.APIStatusError as exc:
                if exc.status_code in RETRYABLE_STATUS:
                    last_transport = exc
                    if attempt == self.config.max_attempts:
                        raise self._status_exhausted(exc, attempt) from exc
                    self._sleep_backoff(attempt)
                else:
                    raise self._non_retryable(exc) from exc
            except openai.APIError as exc:
                # Server-reported failure inside the call (see stream_events):
                # terminal, with the server's own message preserved.
                raise self._server_reported(exc) from exc
            except (
                openai.APIResponseValidationError,
                KeyError,
                IndexError,
                AttributeError,
                TypeError,
                ValueError,
            ) as exc:
                raise self._bad_shape(exc, wire) from exc
        raise TransportError(
            f"retry loop exited after {self.config.max_attempts} attempts "
            f"(last error: {last_transport})"
        )  # pragma: no cover - the loop always returns or raises

    def _complete_streaming(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        state: _CallState,
        client: httpx.Client,
    ) -> ChatResult:
        chat = self._build_chat(
            temperature, max_tokens, streaming=True, http_client=client
        )
        text_parts: list[str] = []
        usage: dict[str, int] = {}
        finish_reason: str | None = None
        first_token_s: float | None = None
        chunks = 0
        deadline = (
            state.t0 + self.config.call_deadline_s
            if self.config.call_deadline_s > 0
            else None
        )
        stream = chat.stream(messages)  # a generator: close() aborts the HTTP body
        try:
            for chunk in stream:
                chunks += 1
                state.chunks = chunks
                if deadline is not None and time.monotonic() > deadline:
                    # Closing the stream closes the HTTP connection, which
                    # makes the server stop generating mid-run.
                    raise self._deadline_abort(chunks, state)
                if finish_reason is None:
                    finish_reason = chunk.response_metadata.get("finish_reason")
                chunk_usage = _normalize_usage(chunk.usage_metadata)
                if chunk_usage:
                    usage = chunk_usage
                piece = _chunk_text(chunk)
                if piece:
                    if first_token_s is None:
                        first_token_s = time.monotonic() - state.t0
                    text_parts.append(piece)
        finally:
            _close_stream(stream)
        if chunks == 0:
            raise BadServerResponseError(
                "stream produced no chunks at all - response does not match "
                "the OpenAI chat-completions shape (server may not support "
                "streaming or rejected the request silently)"
            )
        elapsed = time.monotonic() - state.t0
        return ChatResult(
            text="".join(text_parts),
            usage=usage,
            finish_reason=finish_reason,
            http_status=200,
            latency_s=round(elapsed, 2),
            first_token_s=round(first_token_s, 3)
            if first_token_s is not None
            else None,
            chunks_received=chunks,
            model=self.config.model,
        )

    def _complete_invocation(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        state: _CallState,
        client: httpx.Client,
    ) -> ChatResult:
        chat = self._build_chat(
            temperature, max_tokens, streaming=False, http_client=client
        )
        response = chat.invoke(messages)
        state.chunks = 1
        text = response.text if isinstance(response.text, str) else ""
        if text == "" and response.response_metadata.get("finish_reason") is None:
            raise BadServerResponseError(
                "response carries neither content nor finish_reason - does not "
                f"match the OpenAI chat-completions shape; got: {str(response)[:300]}"
            )
        usage = _normalize_usage(response.usage_metadata)
        if not usage:
            token_usage = response.response_metadata.get("token_usage") or {}
            usage = {
                key: token_usage[key]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if key in token_usage
            }
        elapsed = time.monotonic() - state.t0
        if self.config.call_deadline_s > 0 and elapsed > self.config.call_deadline_s:
            # A non-streaming response cannot be aborted mid-flight (zero
            # bytes flow until the end); the breach is reported the moment it
            # is observable. Streaming is the way to actually cap a runaway.
            raise self._deadline_abort(1, state)
        return ChatResult(
            text=text,
            usage=usage,
            finish_reason=response.response_metadata.get("finish_reason"),
            http_status=200,
            latency_s=round(elapsed, 2),
            first_token_s=None,
            chunks_received=0,
            model=self.config.model,
        )

    def _iter_events(
        self,
        chat: ChatOpenAI,
        messages: list[dict[str, Any]],
        state: _CallState,
    ) -> Iterator[StreamEvent]:
        deadline = (
            state.t0 + self.config.call_deadline_s
            if self.config.call_deadline_s > 0
            else None
        )
        stream = chat.stream(messages)  # a generator: close() aborts the HTTP body
        try:
            for chunk in stream:
                state.chunks += 1
                if deadline is not None and time.monotonic() > deadline:
                    raise self._deadline_abort(state.chunks, state)
                piece = _chunk_text(chunk)
                if piece:
                    yield StreamEvent(delta=piece)
                usage = _normalize_usage(chunk.usage_metadata)
                if usage:
                    yield StreamEvent(usage=usage)
                finish = chunk.response_metadata.get("finish_reason")
                if finish:
                    yield StreamEvent(finish_reason=finish)
        finally:
            _close_stream(stream)
        if state.chunks == 0:
            raise BadServerResponseError(
                "stream produced no chunks at all - response does not match "
                "the OpenAI chat-completions shape"
            )

    # ------------------------------------------------------------ plumbing
    def _build_http_client(self) -> httpx.Client:
        # read=timeout_s is the inactivity bound: with streaming, any gap
        # longer than this between chunks kills the call (dead server, not a
        # slow one - a generating server sends bytes).
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=self.config.connect_timeout_s,
                read=self.config.timeout_s,
                write=10.0,
                pool=10.0,
            ),
            headers=self._request_headers(),
        )

    def _request_headers(self) -> dict[str, str]:
        """Extra gateway headers + an identifying User-Agent (2026-11-10:
        OpenCode Go requires a stable x-opencode-session per conversation and
        asks clients to name themselves rather than spoof an SDK)."""
        headers = dict(self.config.extra_headers)
        if self.config.user_agent:
            headers["User-Agent"] = self.config.user_agent
        return headers

    def _build_chat(
        self,
        temperature: float,
        max_tokens: int | None,
        *,
        streaming: bool,
        http_client: httpx.Client,
    ) -> ChatOpenAI:
        # A fresh ChatOpenAI per call: temperature/max_tokens are per-call
        # knobs, and constructing is local-only (no network). max_retries=0
        # is MANDATORY: llm_manager owns retry semantics (single source of
        # truth); langchain must never add its own retry layer on top.
        # The timeout is passed BOTH as the http_client default AND as the
        # explicit request_timeout: the openai SDK sends its own timeout with
        # every request, which would silently override the client default.
        timeout = httpx.Timeout(
            connect=self.config.connect_timeout_s,
            read=self.config.timeout_s,
            write=10.0,
            pool=10.0,
        )
        kwargs: dict[str, Any] = {
            "base_url": self.config.base_url,
            "api_key": self.config.api_key or "unused",
            "model": self.config.model,
            "temperature": temperature,
            "streaming": streaming,
            "stream_usage": self.config.stream_usage,
            "max_retries": 0,
            "http_client": http_client,
            "timeout": timeout,
        }
        headers = self._request_headers()
        if headers:
            kwargs["default_headers"] = headers
        model_kwargs: dict[str, Any] = {}
        if self.config.json_mode:
            model_kwargs["response_format"] = {"type": "json_object"}
        if self.config.reasoning_effort:
            model_kwargs["reasoning_effort"] = self.config.reasoning_effort
        if model_kwargs:
            kwargs["model_kwargs"] = model_kwargs
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**kwargs)

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self.config.backoff_base_s * (2 ** (attempt - 1)))

    def _unreachable(self, exc: Exception, tries: int) -> TransportError:
        kind = (
            "timed out waiting for the server (inactivity between chunks)"
            if isinstance(exc, openai.APITimeoutError)
            else "connection failed"
        )
        return TransportError(
            f"could not reach inference server at {self.config.base_url} after "
            f"{tries} tries: {kind} ({exc}). Is the server running and is "
            "ZIVON_BASE_URL set correctly?"
        )

    def _status_exhausted(
        self, exc: openai.APIStatusError, tries: int
    ) -> TransportError:
        return TransportError(
            f"server returned HTTP {exc.status_code} on all {tries} tries. "
            f"Body: {_error_body(exc)[:500]}"
        )

    def _server_reported(self, exc: openai.APIError) -> TransportError:
        """A bare openai.APIError: the server reported failure INSIDE the call
        (HTTP 200 + an SSE error payload - llama.cpp context-overflow style, or
        our llm-manager node relaying an exhausted upstream). The SDK carries
        the server's own message; keep it verbatim - it already names the fix
        when there is one. Terminal: retrying cannot un-fail what the server
        says it failed."""
        detail = exc.message or str(exc.body or "no detail")[:500]
        return TransportError(
            f"the inference server reported an error mid-call: {detail}"
        )

    def _non_retryable(self, exc: openai.APIStatusError) -> NonRetryableHTTPError:
        body = _error_body(exc)
        message = f"server rejected the call with HTTP {exc.status_code}: {body[:500]}."
        if exc.status_code == 400 and "response_format" in body.lower():
            message += (
                " Your server appears not to support response_format json_object;"
                " set ZIVON_JSON_MODE=false in the environment and re-run."
            )
        if exc.status_code == 400 and "stream_options" in body.lower():
            message += (
                " Your server appears not to support stream_options;"
                " set ZIVON_STREAM_USAGE=false in the environment and re-run."
            )
        return NonRetryableHTTPError(message, exc.status_code)

    def _deadline_abort(self, chunks: int, state: _CallState) -> TransportError:
        elapsed = round(time.monotonic() - state.t0, 1)
        return TransportError(
            f"model call exceeded call_deadline_s={self.config.call_deadline_s:g}s "
            f"after {chunks} chunks ({elapsed}s elapsed) - aborted so the server "
            "stops generating"
        )

    def _partial_stream_failure(
        self, exc: Exception, state: _CallState
    ) -> TransportError:
        return TransportError(
            f"stream failed after {state.chunks} chunks had already been "
            "delivered (no silent restart - the consumer already saw those "
            f"deltas): {exc}"
        )

    def _bad_shape(
        self, exc: Exception, wire: dict[str, Any]
    ) -> BadServerResponseError:
        return BadServerResponseError(
            f"response did not match the OpenAI chat-completions shape ({exc}). "
            f"Requested model={wire.get('model')} stream={wire.get('stream')}."
        )


def _close_stream(stream: Any) -> None:
    """Close the SSE generator so the HTTP connection closes and the server
    stops generating (used by the deadline abort and every exit path)."""
    close = getattr(stream, "close", None)
    if close is not None:
        close()


def _chunk_text(chunk: Any) -> str:
    """The text a streamed chunk carries (str content, or the text parts of a
    content-block list). Reasoning-model extra fields are deliberately NOT
    collected: only real content reaches the result."""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _normalize_usage(usage_metadata: Any | None) -> dict[str, int]:
    """langchain's usage_metadata uses input_tokens/output_tokens; normalize
    back to the OpenAI names the factory's artifacts (and humans) expect."""
    if not usage_metadata:
        return {}
    usage: dict[str, int] = {}
    if "input_tokens" in usage_metadata:
        usage["prompt_tokens"] = usage_metadata["input_tokens"]
    if "output_tokens" in usage_metadata:
        usage["completion_tokens"] = usage_metadata["output_tokens"]
    if "total_tokens" in usage_metadata:
        usage["total_tokens"] = usage_metadata["total_tokens"]
    return usage


def _error_body(exc: openai.APIStatusError) -> str:
    body = getattr(exc, "body", None)
    if body is None:
        response = getattr(exc, "response", None)
        body = getattr(response, "text", "") if response is not None else ""
    return str(body)
