"""Unit tests for the llm_manager service node (the isolated model-call node).

The node is what "everybody else" talks to: an OpenAI-format
chat-completions endpoint over LLMManager, shipped as its own image and run
as a K8s Deployment + Service. These tests prove the HTTP contract:
aggregated + SSE responses, upstream error mapping (502 for exhausted
transport, 400 passthrough with the server's body), the health probe, and
that the node NEVER pulls in factory/ (standalone isolation).

Skipped automatically when fastapi is not installed (e.g. slim verification
images); CI installs it via requirements.txt.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from llm_manager import LLMConfig
from testing.content_factory.mocks.openai_mock import start_mock

if importlib.util.find_spec("fastapi") is not None:  # pragma: no branch - env-gated
    from fastapi.testclient import TestClient

    from llm_manager.service.app import create_app

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

MARKER = "[ZIVON STAGE: 02-generate] service"
MESSAGES = [{"role": "system", "content": MARKER}, {"role": "user", "content": "go"}]


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi not installed")
class TestServiceNode(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fixtures = self.tmp / "fixtures"
        self.fixtures.mkdir()

    def _fixture(self, name: str, payload) -> None:
        (self.fixtures / name).write_text(
            payload if isinstance(payload, str) else json.dumps(payload)
        )

    def _client(self, **config_over):
        self.server, self.url, self.state = start_mock(self.fixtures)
        self.addCleanup(self.server.shutdown)
        config = LLMConfig(
            base_url=self.url,
            model="mock-model",
            heartbeat_s=1000.0,
            backoff_base_s=0.1,
            **config_over,
        )
        app = create_app(config)
        return TestClient(app)

    def test_healthz_reports_config_without_calling_upstream(self):
        client = self._client()
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["model"], "mock-model")
        self.assertEqual(self.state.served, [], "a health probe never calls the model")

    def test_non_streaming_completion_returns_openai_shape(self):
        self._fixture("02-generate.json", {"topic": "x", "claims": []})
        client = self._client()
        response = client.post(
            "/v1/chat/completions",
            json={"messages": MESSAGES, "temperature": 0.3},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "mock-model")
        self.assertEqual(
            body["choices"][0]["message"],
            {"role": "assistant", "content": '{"topic": "x", "claims": []}'},
        )
        self.assertEqual(body["choices"][0]["finish_reason"], "stop")
        self.assertEqual(body["usage"]["prompt_tokens"], 10)
        self.assertEqual(body["usage"]["total_tokens"], 20)

    def test_streaming_completion_emits_sse_chunks(self):
        self._fixture("02-generate.json", {"topic": "x"})
        client = self._client()
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "messages": MESSAGES,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                response.headers["content-type"].startswith("text/event-stream")
            )
            raw = "".join(part.decode() for part in response.iter_raw())
        events = [
            json.loads(line[len("data: ") :])
            for line in raw.split("\n\n")
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        self.assertTrue(raw.rstrip().endswith("data: [DONE]"))
        chunks = [e for e in events if e.get("choices")]
        self.assertTrue(
            all(c["object"] == "chat.completion.chunk" for c in chunks),
            "every SSE payload is an OpenAI chunk",
        )
        deltas = "".join(
            c["choices"][0]["delta"].get("content", "")
            for c in chunks
            if c["choices"][0]["delta"].get("content")
        )
        self.assertEqual(deltas, '{"topic": "x"}')
        finishes = [
            c["choices"][0]["finish_reason"]
            for c in chunks
            if c["choices"][0]["finish_reason"]
        ]
        self.assertEqual(finishes, ["stop"])
        usage_events = [e for e in events if e.get("usage")]
        self.assertEqual(usage_events[0]["usage"]["total_tokens"], 20)

    def test_streaming_without_usage_request_has_no_usage_chunk(self):
        self._fixture("02-generate.json", {"topic": "x"})
        client = self._client()
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={"messages": MESSAGES, "stream": True},
        ) as response:
            raw = "".join(part.decode() for part in response.iter_raw())
        self.assertNotIn('"usage"', raw)
        self.assertTrue(raw.rstrip().endswith("data: [DONE]"))

    def test_upstream_transport_exhaustion_maps_to_502(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture("02-generate__fail500.json", {"error": "overloaded"})
        client = self._client(max_attempts=1)
        response = client.post("/v1/chat/completions", json={"messages": MESSAGES})
        self.assertEqual(response.status_code, 502)
        self.assertIn("HTTP 500", response.json()["error"]["message"])

    def test_upstream_400_passes_through_with_the_servers_body(self):
        self._fixture("02-generate.json", {"topic": "x"})
        self._fixture(
            "02-generate__fail400.json",
            {"error": {"message": "response_format json_object not supported"}},
        )
        client = self._client()
        response = client.post("/v1/chat/completions", json={"messages": MESSAGES})
        self.assertEqual(response.status_code, 400)
        message = response.json()["error"]["message"]
        self.assertIn("response_format json_object not supported", message)
        self.assertIn("set ZIVON_JSON_MODE=false", message)

    def test_service_module_never_imports_factory(self):
        # In-process sys.modules is polluted by sibling tests, so this is a
        # STATIC source check; the runtime guarantee is proven in a fresh
        # interpreter by test_llm_manager.TestPackageIsolation.
        pkg_dir = REPO_ROOT / "llm_manager"
        offenders: list[str] = []
        for path in sorted(pkg_dir.rglob("*.py")):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                if stripped.startswith(("import factory", "from factory")):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
        self.assertEqual(offenders, [], "llm_manager must be standalone")


if __name__ == "__main__":
    unittest.main()
