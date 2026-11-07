"""The llm_manager service node: OpenAI chat-completions over LLMManager.

Contract (kept deliberately thin):

- `POST /v1/chat/completions` - an OpenAI-format request. Non-streaming
  requests get one aggregated chat.completion object; `"stream": true`
  requests get an SSE chunk stream (delta chunks, a finish_reason chunk, a
  usage chunk when the caller asked `stream_options.include_usage`, then
  `data: [DONE]`). Under the hood the node ALWAYS streams from upstream when
  its own config says so, so the inactivity timeout and the call deadline
  bound every upstream leg, whatever the caller asked for.
- `GET /healthz` - process + config liveness for the K8s probes. It never
  calls the inference server (a proxy must stay healthy while its upstream
  is down).

Policy lives on the node, not in request bodies: JSON mode
(`ZIVON_JSON_MODE`), streaming to upstream, retry/deadline budgets and the
model are the node's configured behavior - that is the isolation bargain.
Consumers control per-call `temperature` and `max_tokens`; a body
`response_format` field is accepted for wire compatibility but IGNORED (the
node's own `ZIVON_JSON_MODE` decides - documented in config-reference.md); a
body `model` naming a DIFFERENT model is refused with 400 (a mismatch is a
misconfiguration, and silently answering with the node's model would hide it).

Errors surface honestly: an exhausted upstream transport maps to HTTP 502, a
non-retryable upstream 400 passes through as 400 with the server's body (so
the client-side hints - "set ZIVON_JSON_MODE=false" - still reach the
operator), a malformed upstream reply maps to 502.

NOTE for in-cluster wiring: the FACTORY leg keeps transport retries off
(ZIVON_MAX_ATTEMPTS=1 in the factory ConfigMap) because THIS node already
retries the upstream leg with its own budget. Without that split, one factory
attempt would fan out into node-attempts x factory-attempts upstream calls.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..client import LLMManager
from ..config import LLMConfig, LLMConfigError
from ..errors import (
    BadServerResponseError,
    LLMManagerError,
    NonRetryableHTTPError,
    TransportError,
)


class _Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None  # accepted; a mismatch with the node's model -> 400
    messages: list[_Message] = Field(min_length=1)
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None  # accepted, ignored (node policy)


def create_app(config: LLMConfig | None = None) -> FastAPI:
    """Build the service app. `config=None` defers env loading to first use so
    that importing the module never crashes on a machine without server env
    (tests inject a config explicitly; the container entry point loads env
    loudly and fails fast before uvicorn starts)."""
    app = FastAPI(title="zivon-llm-manager", docs_url=None, redoc_url=None)
    state = _State(config)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        try:
            cfg = state.config()
        except LLMConfigError as exc:
            return JSONResponse(
                status_code=503, content={"ok": False, "error": str(exc)}
            )
        return JSONResponse(
            content={"ok": True, "model": cfg.model, "stream": cfg.stream}
        )

    @app.post("/v1/chat/completions")
    def chat_completions(body: ChatCompletionRequest) -> Response:
        state.config()  # loud config tripwire on first use (LLMConfigError -> 500)
        manager = LLMManager(state.config())
        if body.model and body.model != manager.config.model:
            # A single-model node serves its configured model - but a request
            # naming a DIFFERENT model is a misconfiguration, and silently
            # answering with the node's model would hide it (no silent
            # fallbacks, ever). Refuse loudly with the fix in the message.
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": (
                            f"this node serves model '{manager.config.model}'; "
                            f"the request asked for '{body.model}'. Set your "
                            "ZIVON_MODEL to match the node's configured model."
                        ),
                        "type": "invalid_request_error",
                    }
                },
            )
        messages = [{"role": m.role, "content": m.content} for m in body.messages]
        if body.stream:
            include_usage = bool(
                (body.stream_options or {}).get("include_usage", False)
            )
            return StreamingResponse(
                _sse_stream(manager, messages, body, include_usage),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            result = manager.complete(
                messages,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            )
        except NonRetryableHTTPError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {"message": str(exc), "type": "invalid_request_error"}
                },
            )
        except (TransportError, BadServerResponseError) as exc:
            return JSONResponse(
                status_code=502,
                content={"error": {"message": str(exc), "type": "upstream_error"}},
            )
        usage: dict[str, int] | None = None
        if result.usage:
            usage = {
                "prompt_tokens": result.usage.get("prompt_tokens", 0),
                "completion_tokens": result.usage.get("completion_tokens", 0),
                "total_tokens": result.usage.get(
                    "total_tokens",
                    result.usage.get("prompt_tokens", 0)
                    + result.usage.get("completion_tokens", 0),
                ),
            }
        return JSONResponse(
            content={
                "id": f"chatcmpl-llmmgr-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": result.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": result.text},
                        "finish_reason": result.finish_reason or "stop",
                    }
                ],
                "usage": usage,
            }
        )

    return app


class _State:
    """Lazy, thread-safe config holder: env is read once, on first use."""

    def __init__(self, config: LLMConfig | None):
        self._config = config
        self._error: LLMConfigError | None = None
        self._loaded = config is not None
        self._lock = threading.Lock()

    def config(self) -> LLMConfig:
        with self._lock:
            if not self._loaded:
                try:
                    self._config = LLMConfig.from_env()
                except LLMConfigError as exc:
                    self._error = exc
            if self._error is not None:
                raise self._error
            assert self._config is not None  # narrowed by the two lines above
            return self._config


def _sse_stream(
    manager: LLMManager,
    messages: list[dict[str, str]],
    body: ChatCompletionRequest,
    include_usage: bool,
):
    """Re-emit the upstream typed stream as an OpenAI-format SSE chunk stream.

    Upstream transport errors BEFORE the first event surface as an SSE error
    event (the HTTP head is already sent once streaming starts); after the
    first event they surface the same way - no fake completion, ever.

    Keepalives (review fix 2026-11-07): a thinking model streams reasoning
    tokens for minutes, and llm_manager deliberately does NOT re-emit them as
    content deltas. Without bytes flowing downstream, the CALLER's inactivity
    timeout would kill a healthy call whose server is busy thinking - the
    exact failure class this whole streaming redesign exists to end. So while
    the upstream is silent this generator emits SSE comment keepalives
    (`: keepalive`): OpenAI-format parsers ignore comment lines per spec, but
    the bytes prove the connection is alive and reset the caller's read
    timeout. The upstream stream is consumed in a feeder thread bridging a
    bounded queue; a closed consumer sets `stop`, the feeder exits, and the
    upstream generator's finally closes the upstream connection (no orphan
    generation on the single-slot server).
    """
    completion_id = f"chatcmpl-llmmgr-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    model = manager.config.model

    def chunk(delta: dict[str, Any], finish: str | None = None) -> str:
        return _sse_line(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
        )

    events: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=64)
    stop = threading.Event()

    def feed() -> None:
        try:
            for event in manager.stream_events(messages, temperature=body.temperature):
                if stop.is_set():
                    return  # consumer gone: dropping this generator closes upstream
                while not stop.is_set():
                    try:
                        events.put(("event", event), timeout=1.0)
                        break
                    except queue.Full:
                        pass
        except LLMManagerError as exc:
            if not stop.is_set():
                try:
                    events.put(("error", exc), timeout=5.0)
                except queue.Full:
                    pass
        if not stop.is_set():
            try:
                events.put(("end", None), timeout=5.0)
            except queue.Full:
                pass

    threading.Thread(target=feed, daemon=True).start()

    yield chunk({"role": "assistant"})
    heartbeat_s = manager.config.heartbeat_s
    try:
        while True:
            try:
                kind, payload = events.get(timeout=heartbeat_s)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if kind == "end":
                break
            if kind == "error":
                yield _sse_line(
                    {
                        "error": {
                            "message": str(payload),
                            "type": type(payload).__name__,
                        }
                    }
                )
                break
            event = payload
            if event.delta is not None:
                yield chunk({"content": event.delta})
            elif event.finish_reason is not None:
                yield chunk({}, finish=event.finish_reason)
            elif event.usage is not None and include_usage:
                yield _sse_line(
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [],
                        "usage": {
                            "prompt_tokens": event.usage.get("prompt_tokens", 0),
                            "completion_tokens": event.usage.get(
                                "completion_tokens", 0
                            ),
                            "total_tokens": event.usage.get("total_tokens", 0),
                        },
                    }
                )
        yield "data: [DONE]\n\n"
    finally:
        stop.set()


def _sse_line(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"
