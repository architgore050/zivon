"""A minimal OpenAI-format chat-completions mock for wiring tests.

This server exists ONLY under testing/. The pipeline never imports or touches
it. It serves pre-written fixture outputs (one per pipeline stage, keyed by the
[ZIVON STAGE: ...] marker in the system prompt) so the full pipeline can be
exercised without a real inference server.

A fixture may be "scripted": place <stage>__attempt1.json next to <stage>.json
and the mock returns the attempt-1 content on the first call for that stage
(within one server lifetime) and the canonical fixture afterwards - this tests
the validation-retry path.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_STAGE_RE = re.compile(r"\[ZIVON STAGE: ([0-9]{2}-[a-z]+)\]")


def _fixture_index(fixtures_dir: Path) -> dict[str, Path]:
    # Whitelisted fixture files, snapshotted when the server starts: request-
    # derived text is only ever used as a dict key, never as a path component
    # (CodeQL py/path-injection).
    return {p.name: p for p in sorted(fixtures_dir.iterdir()) if p.suffix == ".json"}


class MockState:
    def __init__(self) -> None:
        self.served: list[dict] = []
        self._attempt_counters: dict[str, int] = {}


class _Handler(BaseHTTPRequestHandler):
    state: MockState  # injected by start_mock() before the server thread starts
    fixture_index: dict[str, Path]  # injected by start_mock(): whitelisted files

    def log_message(self, fmt, *args):  # silence request logging
        pass

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
        self.state.served.append({"stage": stage, "messages": messages})

        fixture = self.fixture_index.get(f"{stage}.json")
        if fixture is None:
            self._json_response(500, {"error": f"no fixture for stage {stage}"})
            return
        # scripted retry: <stage>__attempt1.json served once before the canonical fixture
        scripted = self.fixture_index.get(f"{stage}__attempt1.json")
        content = None
        if scripted is not None:
            count = self.state._attempt_counters.get(stage, 0)
            self.state._attempt_counters[stage] = count + 1
            if count == 0:
                content = scripted.read_text(encoding="utf-8")
        if content is None:
            content = fixture.read_text(encoding="utf-8")

        self._json_response(
            200,
            {
                "id": "mock-completion",
                "object": "chat.completion",
                "model": body.get("model", "mock"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "user", "content": content},
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

    def _json_response(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


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
