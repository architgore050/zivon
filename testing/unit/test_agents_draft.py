"""Unit tests for 04-draft wiring: code-side rule checks run AT DRAFT TIME.

The model must see its own rule violations (invented numbers, missing
citations) in the retry transcript instead of the run dying at 05-check.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory import agents
from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient
from testing.unit._server_env import install_server_env, release_server_env

FIXTURES = REPO_ROOT / "testing" / "mocks" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_pack() -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(FIXTURES / "pdfs" / "ch01.pdf")
    return {
        "ncert_text": "\n".join(p.extract_text() for p in reader.pages),
        "chapter": {"book_id": "ncert-fixture-ch01"},
        "supplements": [
            {"source_id": "alt-open-physics#c0001", "book_id": "alt-open-physics"}
        ],
    }


class StubLLM:
    """Captures what run_draft hands to llm.call and returns the fixture draft."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        self.messages: list[dict[str, str]] = []

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.kwargs = kw
        self.messages = messages
        return load("04-draft.json")


class TestDraftRuleWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        base["paths"]["runs"] = str(self.tmp / "runs")
        (self.tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
        saved = install_server_env()
        try:
            self.cfg = load_config(self.tmp / "config.json")
        finally:
            release_server_env(saved)
        self.run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-draft")

    def _run_draft(self, stub: StubLLM) -> dict[str, Any]:
        return agents.run_draft(
            self.cfg,
            self.run_ctx,
            cast(LLMClient, stub),
            load("03-explain.json"),
            load("02-synth.json"),
            make_pack(),
        )

    def test_validator_is_wired_into_the_call(self):
        stub = StubLLM()
        out = self._run_draft(stub)
        self.assertIn("extra_validator", stub.kwargs)
        validator = stub.kwargs["extra_validator"]
        # the clean fixture draft passes the rules - no feedback loop needed
        self.assertEqual(validator(out), [])

    def test_prompt_promises_verbatim_numbers(self):
        # The rule checks verbatim presence; the prompt must promise the same,
        # or correct-but-computed answers die at 05-check for no good reason.
        stub = StubLLM()
        self._run_draft(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("VERBATIM", user)
        self.assertIn("do not compute new figures", user)

    def test_violations_are_reported_to_the_model(self):
        stub = StubLLM()
        self._run_draft(stub)
        validator = stub.kwargs["extra_validator"]
        bad = load("04-draft.json")
        bad["blocks"][2]["spec"]["answer"] = "73 m/s2"  # invented figure
        bad["blocks"][0]["citations"] = []  # uncited text block
        problems = validator(bad)
        self.assertTrue(any("73" in p for p in problems), problems)
        self.assertTrue(any("no citations" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
