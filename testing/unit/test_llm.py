"""Unit tests for the LLM client against the mock OpenAI-format server."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory.artifacts import RunContext  # noqa: E402
from factory.config import load_config  # noqa: E402
from factory.errors import ModelCallError, SchemaError  # noqa: E402
from factory.llm import LLMClient, parse_json_object  # noqa: E402
from testing.mocks.openai_mock import start_mock  # noqa: E402

GOOD = {"topic": "x", "claims": []}
BAD = {"topic": 42}  # right key, wrong type -> schema failure

SIMPLE_SCHEMA = {"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}}}


def make_cfg(tmp: Path, base_url: str, attempts: int = 3):
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["server"]["model"] = "mock-model"
    base["server"]["base_url"] = base_url
    base["server"]["max_attempts"] = attempts
    base["paths"]["runs"] = str(tmp / "runs")
    path = tmp / "config.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return load_config(path)


class TestParseJsonObject(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_json_object("Here is your JSON: {\"a\": 1} hope that helps!")

    def test_non_object_rejected(self):
        with self.assertRaises(ValueError):
            parse_json_object("[1,2,3]")


class TestLLMClient(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fixtures = self.tmp / "fixtures"
        self.fixtures.mkdir()
        os.environ["ZIVON_API_KEY"] = "test-key"

    def tearDown(self):
        os.environ.pop("ZIVON_API_KEY", None)

    def _serve(self, canonical: dict, scripted_first=None):
        (self.fixtures / "02-synth.json").write_text(json.dumps(canonical))
        if scripted_first is not None:
            (self.fixtures / "02-synth__attempt1.json").write_text(
                scripted_first if isinstance(scripted_first, str) else json.dumps(scripted_first))
        return start_mock(self.fixtures)

    def _run(self, cfg):
        return RunContext(cfg.repo_path(cfg.paths["runs"]), "t-llm")

    def _call(self, client):
        return client.call("02-synth", [
            {"role": "system", "content": "[ZIVON STAGE: 02-synth] x"},
            {"role": "user", "content": "go"},
        ], SIMPLE_SCHEMA, "test")

    def test_happy_path_with_artifacts(self):
        server, url, state = self._serve(GOOD)
        try:
            cfg = make_cfg(self.tmp, url)
            run = self._run(cfg)
            client = LLMClient(cfg, run)
            out = self._call(client)
            self.assertEqual(out["topic"], "x")
            stage_dir = run.stage_dir("02-synth")
            self.assertTrue((stage_dir / "attempts" / "attempt-01" / "request.json").exists())
            self.assertTrue((stage_dir / "attempts" / "attempt-01" / "response.json").exists())
            meta = json.loads((stage_dir / "attempts" / "attempt-01" / "meta.json").read_text())
            self.assertEqual(meta["http_status"], 200)
            self.assertEqual(state.served[0]["stage"], "02-synth")
        finally:
            server.shutdown()

    def test_validation_retry_feeds_errors_back(self):
        server, url, _ = self._serve(GOOD, scripted_first={"topic": 42})
        try:
            cfg = make_cfg(self.tmp, url)
            run = self._run(cfg)
            client = LLMClient(cfg, run)
            out = self._call(client)
            self.assertEqual(out["topic"], "x")
            attempts = sorted(p.name for p in (run.stage_dir("02-synth") / "attempts").iterdir())
            self.assertEqual(attempts, ["attempt-01", "attempt-02"])
            req2 = json.loads((run.stage_dir("02-synth") / "attempts" / "attempt-02" / "request.json").read_text())
            roles = [m["role"] for m in req2["messages"]]
            self.assertIn("assistant", roles)
            self.assertIn("Schema validation failed", req2["messages"][-1]["content"])
        finally:
            server.shutdown()

    def test_invalid_json_retry_also_fed_back(self):
        server, url, _ = self._serve(GOOD, scripted_first="this is not json at all")
        try:
            cfg = make_cfg(self.tmp, url)
            out = self._call(LLMClient(cfg, self._run(cfg)))
            self.assertEqual(out["topic"], "x")
            req2 = json.loads((self._run(cfg).stage_dir("02-synth") / "attempts" / "attempt-02" / "request.json").read_text())
            self.assertIn("JSON parse failure", req2["messages"][-1]["content"])
        finally:
            server.shutdown()

    def test_persistent_failure_raises_model_call_error(self):
        # base_url points at a port with nothing listening
        cfg = make_cfg(self.tmp, "http://127.0.0.1:9/v1", attempts=1)
        client = LLMClient(cfg, self._run(cfg))
        with self.assertRaises(ModelCallError):
            self._call(client)

    def test_schema_failures_exhaust_to_schema_error(self):
        server, url, _ = self._serve(BAD)  # canonical is itself schema-invalid
        try:
            cfg = make_cfg(self.tmp, url, attempts=2)
            client = LLMClient(cfg, self._run(cfg))
            with self.assertRaises(SchemaError) as ctx:
                self._call(client)
            self.assertIn("all 2 attempts", str(ctx.exception))
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
