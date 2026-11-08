"""A minimal OpenAI-format chat-completions mock for wiring tests.

This server exists ONLY under testing/. The pipeline never imports or touches
it. It serves pre-written fixture outputs (one per pipeline stage, keyed by the
[ZIVON STAGE: ...] marker in the system prompt) so the full pipeline can be
exercised without a real inference server.

Streaming (2026-11-07): when the request carries "stream": true the mock
answers `text/event-stream` exactly like an OpenAI-compatible server - delta
chunks, a final finish_reason chunk, a usage chunk when
stream_options.include_usage was requested, then `data: [DONE]`. The e2e
pipeline path exercises this by default.

Scripted + failure-injection fixtures (all resolved through the whitelisted
fixture index snapshot - request-derived text is never a path component,
CodeQL py/path-injection):

- <stage>.json                     canonical output (also the retry target)
- <stage>__attempt1.json           served ONCE before the canonical fixture
                                   (validation-retry path)
- <stage>__fail500.json            first request for the stage -> HTTP 500
                                   (transport-retry path), then canonical
- <stage>__fail400.json            ALWAYS HTTP 400, body = fixture JSON
                                   (non-retryable path)
- <stage>__badshape.json          200 with a body that is NOT chat-completions
                                   shaped (BadServerResponseError path)
- <stage>__slow.json              streaming only: {"content", "chunks",
                                   "delay_s"} - many small chunks with a sleep
                                   between them (deadline-abort path)
- <stage>__stall.json             streaming only: {"content", "stall_s"} - no
                                   bytes until the stall elapses (inactivity
                                   timeout path)
- <stage>__midstream_close.json   streaming only: {"content"} - two chunks,
                                   then the socket is closed abruptly
                                   (mid-stream transport-retry path)
- <stage>__stream_error.json      streaming only: {"message"} - HTTP 200,
                                   role chunk, then an SSE error payload
                                   `{"error": {...}}`, then [DONE] (the
                                   server-reported-failure path: llama.cpp
                                   context-overflow style, and how the
                                   llm-manager node relays an exhausted
                                   upstream to its callers)

Disconnect accounting: when a streaming write fails (the client aborted -
e.g. a deadline abort closed the connection), the stage is appended to
MockState.disconnected so tests can assert the server observed the
disconnect (that is the whole point of the deadline abort: the server stops
generating).
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_STAGE_RE = re.compile(r"\[ZIVON STAGE: ([0-9]{2}-[a-z]+(?:-[a-z]+)?)\]")

# Exit codes for a write against a client that is gone.
_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


def _fixture_index(fixtures_dir: Path) -> dict[str, Path]:
    # Whitelisted fixture files, snapshotted when the server starts: request-
    # derived text is only ever used as a dict key, never as a path component
    # (CodeQL py/path-injection).
    return {p.name: p for p in sorted(fixtures_dir.iterdir()) if p.suffix == ".json"}


class MockState:
    def __init__(self) -> None:
        self.served: list[dict] = []
        self.disconnected: list[str] = []
        self._attempt_counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, stage: str, messages: list, body: dict) -> None:
        with self._lock:
            self.served.append(
                {
                    "stage": stage,
                    "messages": messages,
                    "stream": bool(body.get("stream")),
                    "stream_options": body.get("stream_options"),
                }
            )

    def next_attempt(self, stage: str) -> int:
        with self._lock:
            count = self._attempt_counters.get(stage, 0)
            self._attempt_counters[stage] = count + 1
            return count


class _Handler(BaseHTTPRequestHandler):
    state: MockState  # injected by start_mock() before the server thread starts
    fixture_index: dict[str, Path]  # injected by start_mock(): whitelisted files

    def log_message(self, fmt, *args):  # silence request logging
        pass

    # ------------------------------------------------------------- dispatch
    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self._json_response(404, {"error": f"unknown path {self.path}"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages", [])
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        match = _STAGE_RE.search(system)
        if not match:
            self._json_response(
                400, {"error": "no [ZIVON STAGE: ...] marker in system prompt"}
            )
            return
        stage = match.group(1)
        self.state.record(stage, messages, body)

        def fixture(name: str) -> Path | None:
            return self.fixture_index.get(name)  # whitelist lookup only

        # Failure injections are ONE-SHOT (first request for the stage only):
        # a retry then gets the canonical fixture, so tests can prove the
        # retry actually recovers. __fail400 stays always-on (non-retryable:
        # there is no retry to recover).

        # Always-400 injection (non-retryable path).
        fail400 = fixture(f"{stage}__fail400.json")
        if fail400 is not None:
            self._json_response(400, self._load_json(fail400))
            return

        # First-request-500 injection (transport-retry path).
        fail500 = fixture(f"{stage}__fail500.json")
        if fail500 is not None and self._first_request(f"{stage}__fail500"):
            self._json_response(500, self._load_json(fail500))
            return

        # Shapeless 200 injection (BadServerResponseError path).
        badshape = fixture(f"{stage}__badshape.json")
        if badshape is not None and self._first_request(f"{stage}__badshape"):
            self._json_response(200, self._load_json(badshape))
            return

        content = self._content_for(stage, fixture)
        if content is None:
            self._json_response(500, {"error": f"no fixture for stage {stage}"})
            return

        if body.get("stream"):
            self._stream_response(stage, body, content, fixture)
            return
        self._json_response(
            200,
            {
                "id": "mock-completion",
                "object": "chat.completion",
                "model": body.get("model", "mock"),
                "choices": [
                    {
                        "index": 0,
                        # role MUST be assistant (OpenAI contract): langchain
                        # parses the response message by its role - the old
                        # "user" here only worked because the previous client
                        # never looked at it.
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    # ------------------------------------------------------------- fixtures
    def _content_for(self, stage: str, fixture) -> str | None:
        """Canonical content, with the one-shot __attempt1 scripting kept from
        the original mock (first call for the stage serves the scripted
        output once, the canonical fixture afterwards)."""
        scripted = fixture(f"{stage}__attempt1.json")
        if scripted is not None and self._first_request(f"{stage}__scripted"):
            return scripted.read_text(encoding="utf-8")
        canonical = fixture(f"{stage}.json")
        if canonical is None:
            return None
        return canonical.read_text(encoding="utf-8")

    def _first_request(self, key: str) -> bool:
        return self.state.next_attempt(key) == 0

    @staticmethod
    def _load_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ streaming
    def _stream_response(self, stage: str, body: dict, content: str, fixture) -> None:
        """SSE answer: delta chunks -> finish_reason chunk -> optional usage
        chunk -> [DONE]. Injection fixtures may slow, stall, or truncate the
        stream; every write is guarded so a client disconnect (deadline
        abort!) is recorded instead of crashing the handler thread."""
        slow = fixture(f"{stage}__slow.json")
        stall = fixture(f"{stage}__stall.json")
        midclose = fixture(f"{stage}__midstream_close.json")
        stream_error = fixture(f"{stage}__stream_error.json")

        if stream_error is not None and self._first_request(f"{stage}__stream_error"):
            # HTTP 200 with the failure INSIDE the stream: the OpenAI SDK
            # raises a bare openai.APIError carrying the payload's message -
            # exactly the shape the llm-manager node emits when its upstream
            # transport dies (and llama.cpp's for context overflow).
            message = str(
                self._load_json(stream_error).get("message", "mock stream error")
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            role_chunk = {
                "id": "mock-stream",
                "object": "chat.completion.chunk",
                "model": body.get("model", "mock"),
                "choices": [
                    {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                ],
            }
            try:
                for payload in (role_chunk, {"error": {"message": message}}):
                    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except _DISCONNECT_ERRORS:
                with self.state._lock:
                    self.state.disconnected.append(stage)
            return

        pieces: list[str]
        inter_delay = 0.0
        pre_stall = 0.0
        close_early = False
        if slow is not None and self._first_request(f"{stage}__slow"):
            spec = self._load_json(slow)
            pieces = _split_chunks(spec["content"], int(spec.get("chunks", 12)))
            inter_delay = float(spec.get("delay_s", 0.05))
        elif stall is not None and self._first_request(f"{stage}__stall"):
            spec = self._load_json(stall)
            pre_stall = float(spec.get("stall_s", 3.0))
            pieces = _split_chunks(spec["content"], 4)
        else:
            if midclose is not None and self._first_request(
                f"{stage}__midstream_close"
            ):
                spec = self._load_json(midclose)
                content = str(spec.get("content", content))
                close_early = True
            pieces = _split_chunks(content, 4)

        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        try:
            # HTTP/1.0 (BaseHTTPRequestHandler default) with no
            # Content-Length: the body is close-delimited, which is exactly
            # how a minimal SSE endpoint behaves. No chunked framing: with
            # HTTP/1.0 it would be protocol noise the client must unpick.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def emit(payload: dict) -> bool:
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()
                return True

            if pre_stall:
                time.sleep(pre_stall)
            emit(
                {
                    "id": "mock-stream",
                    "object": "chat.completion.chunk",
                    "model": body.get("model", "mock"),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant"},
                            "finish_reason": None,
                        }
                    ],
                }
            )
            for piece in pieces:
                if inter_delay:
                    time.sleep(inter_delay)
                emit(
                    {
                        "id": "mock-stream",
                        "object": "chat.completion.chunk",
                        "model": body.get("model", "mock"),
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": piece},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            if close_early:
                # Abrupt mid-stream close: the client sees a truncated SSE
                # body (transport error -> retryable).
                self.connection.close()
                return
            emit(
                {
                    "id": "mock-stream",
                    "object": "chat.completion.chunk",
                    "model": body.get("model", "mock"),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            if include_usage:
                emit(
                    {
                        "id": "mock-stream",
                        "object": "chat.completion.chunk",
                        "model": body.get("model", "mock"),
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 10,
                            "total_tokens": 20,
                        },
                    }
                )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except _DISCONNECT_ERRORS:
            with self.state._lock:
                self.state.disconnected.append(stage)
        except (OSError, ValueError):
            # OSError: the client vanished mid-write; recorded the same way.
            with self.state._lock:
                self.state.disconnected.append(stage)

    # -------------------------------------------------------------- helpers
    def _json_response(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _split_chunks(content: str, n: int) -> list[str]:
    """Split content into n non-empty delta pieces."""
    n = max(1, min(n, max(1, len(content))))
    size = max(1, len(content) // n)
    pieces = [content[i : i + size] for i in range(0, len(content), size)]
    return [p for p in pieces if p]


def start_mock(
    fixtures_dir: Path | None = None,
) -> tuple[ThreadingHTTPServer, str, MockState]:
    if fixtures_dir is not None:
        global FIXTURES_DIR
        FIXTURES_DIR = fixtures_dir  # pragma: no cover
    state = MockState()
    handler = type(
        "BoundHandler",
        (_Handler,),
        {"state": state, "fixture_index": _fixture_index(FIXTURES_DIR)},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1", state
