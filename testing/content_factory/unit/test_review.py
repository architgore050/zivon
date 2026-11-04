"""Unit tests for 09-review: the Code Reviewer must see the cited ground truth
(the final code was rewritten by 08-fixloop AFTER 03-check reviewed the
draft), must be told to check the simulation's DRAWN behaviour, must know the
verdict rule the code enforces, and must be handed the LIVE design doctrine to
police the page's visual language against.
"""

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import review
from factory.artifacts import RunContext
from factory.llm import LLMClient
from factory.render import run as render_run
from testing.content_factory.unit.test_render import make_cfg, minimal_inputs

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


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
        # doctrine/paths.frontend: frontend is configured absolute; doctrine is
        # repo-relative, so root must be the real repo for the injected block.
        self.cfg = dataclasses.replace(self.cfg, root=REPO_ROOT)
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
            load("gt.json"),
        )

    def test_review_prompt_carries_cited_facts(self):
        # 03 checks the DRAFT against sources; 09 must be able to check the
        # FINAL code against the same facts, so every claim + equation lands.
        stub = StubLLM()
        self._review(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        gt = load("gt.json")
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

    def test_reviewer_framing_is_honest_not_adversarial(self):
        # "Assume the page contains at least one defect" manufactured
        # trivia-failures (same lesson graph v2 learned for 03-check). The judge
        # also gets a way out: unverifiable suspicions are 'unverified:' minor.
        stub = StubLLM()
        self._review(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertNotIn("Assume the page contains at least one defect", user)
        self.assertIn("do not invent problems", user)
        self.assertIn("starting 'unverified:'", user)

    def test_review_prompt_carries_live_doctrine_and_checklist_item(self):
        # Style policing against a held-over excerpt drifts when the doctrine
        # changes; the reviewer must get the live document plus the checklist
        # item that makes violations reportable. 2026-11-04 (founder rule):
        # anybody who reviews, writes or edits page code also gets the lesson-
        # page example - the canonical reference the visual language is judged
        # against. The main (post/brand) example stays out of factory context.
        stub = StubLLM()
        self._review(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("DESIGN DOCTRINE", user)
        doctrine = (REPO_ROOT / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(doctrine[:400], user)  # the live document, verbatim
        self.assertIn("Visual language: the page follows the DESIGN DOCTRINE", user)
        self.assertIn("=== design-doctrine-lesson-example.html ===", user)
        self.assertNotIn("=== design-doctrine-example.html ===", user)

    def test_clean_page_passes_and_report_is_saved(self):
        stub = StubLLM()
        report = self._review(stub)
        self.assertEqual(report["verdict"], "pass")
        self.assertTrue((self.run_ctx.stage_dir("09-review") / "output.json").exists())

    def test_fail_verdict_is_returned_not_raised(self):
        # Graph v2 contract: a fail verdict is the HANDOFF to 10-reviewfix.
        # review.run must return the report; the orchestrator routes it to the
        # catcher. Raising here would kill the run (the behaviour v1 had).
        class FailingStub:
            def call(self, stage_id, messages, schema, schema_name, **kw):
                return {
                    "verdict": "fail",
                    "issues": [
                        {
                            "severity": "fatal",
                            "block_id": "b-06",
                            "message": "the simulation draws an impossible curve",
                        }
                    ],
                }

        report = self._review(cast(LLMClient, FailingStub()))
        self.assertEqual(report["verdict"], "fail")
        saved = json.loads(
            (self.run_ctx.stage_dir("09-review") / "output.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(saved["verdict"], "fail")
        self.assertTrue(any(i["severity"] == "fatal" for i in saved["issues"]))


if __name__ == "__main__":
    unittest.main()
