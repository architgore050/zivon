"""Unit tests for 10-review: the Code Reviewer must see the cited ground truth
(the final code was rewritten by 09-fixloop AFTER 05-check reviewed the
draft), must be told to check the simulation's DRAWN behaviour, and must know
the verdict rule the code enforces."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory import review
from factory.artifacts import RunContext
from factory.llm import LLMClient
from factory.render import run as render_run
from testing.unit.test_render import make_cfg, minimal_inputs

FIXTURES = REPO_ROOT / "testing" / "mocks" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubLLM:
    """Captures what review hands to llm.call; returns a passing report."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.messages = messages
        return {"verdict": "pass", "issues": []}


class TestReviewPrompt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg, _ = make_cfg(self.tmp)
        self.run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "t-review"
        )
        source_pack, lesson, blocks, interactive = minimal_inputs()
        self.blocks = blocks
        self.render_out = render_run(
            self.cfg,
            self.run_ctx,
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )

    def _review(self, stub: StubLLM) -> dict[str, Any]:
        return review.run(
            self.cfg,
            self.run_ctx,
            cast(LLMClient, stub),
            self.blocks,
            self.render_out,
            load("02-synth.json"),
        )

    def test_review_prompt_carries_cited_facts(self):
        # 05 checked the DRAFT against sources; 10 must be able to check the
        # FINAL code against the same facts, so every claim + equation lands.
        stub = StubLLM()
        self._review(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        gt = load("02-synth.json")
        self.assertIn("CITED FACTS", user)
        for c in gt["claims"]:
            self.assertIn(c["statement"], user)
        for e in gt["equations"]:
            self.assertIn(e["expression"], user)

    def test_review_prompt_checks_drawn_behaviour_and_verdict_rule(self):
        stub = StubLLM()
        self._review(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("DRAWN behaviour", user)
        self.assertIn("physically wrong behaviour is a fatal issue", user)
        self.assertIn("verdict=fail only if you report at least one fatal", user)

    def test_clean_page_passes_and_report_is_saved(self):
        stub = StubLLM()
        report = self._review(stub)
        self.assertEqual(report["verdict"], "pass")
        self.assertTrue((self.run_ctx.stage_dir("10-review") / "output.json").exists())


if __name__ == "__main__":
    unittest.main()
