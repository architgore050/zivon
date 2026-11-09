"""Unit tests for 09-review (two-call split, 2026-11-08).

The Code Reviewer is now two bounded calls - facts (truth) and design (visual
usability) - each carrying only the context its checks need, each outputting
issues only; the verdict is computed by the harness from severities. These
tests pin: the context split, both bounded procedures (incl. the general
rendering sweep), the manifest decision (identity header, no manifest dump),
the harness verdict rule, the honest framing + 'unverified:' way-out, and the
issues_ledger entries every finding must land in.
"""

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import review
from factory.artifacts import RunContext
from factory.errors import ModelCallError
from factory.llm import LLMClient
from factory.render import run as render_run
from testing.content_factory.unit.test_render import make_cfg, minimal_inputs

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StubLLM:
    """Captures both review calls; returns configurable issues per call."""

    def __init__(
        self,
        facts_issues: list[dict[str, Any]] | None = None,
        design_issues: list[dict[str, Any]] | None = None,
    ):
        self.calls: list[dict[str, Any]] = []
        self.facts_issues = facts_issues if facts_issues is not None else []
        self.design_issues = design_issues if design_issues is not None else []

    def call(self, stage_id, messages, schema, schema_name, **kw):
        tag = str(kw.get("round_tag") or "")
        issues = self.design_issues if "design" in tag else self.facts_issues
        self.calls.append(
            {
                "stage_id": stage_id,
                "messages": messages,
                "schema": schema,
                "round_tag": tag,
                "schema_name": schema_name,
            }
        )
        return {"issues": list(issues)}

    def _msg(self, which: str, role: str) -> str:
        for c in self.calls:
            if which in c["round_tag"]:
                return next(m["content"] for m in c["messages"] if m["role"] == role)
        raise AssertionError(f"no {which} call was made")

    def user(self, which: str) -> str:
        return self._msg(which, "user")

    def system(self, which: str) -> str:
        return self._msg(which, "system")


class VisionRefusingLLM(StubLLM):
    """Raises a vision-style rejection exactly once on the design call, then
    answers normally (proves the design call retries text-only)."""

    def __init__(self, design_issues=None):
        super().__init__(design_issues=design_issues)
        self.design_attempts = 0

    def call(self, stage_id, messages, schema, schema_name, **kw):
        tag = str(kw.get("round_tag") or "")
        if "design" in tag and self.design_attempts < 1:
            self.design_attempts += 1
            self.calls.append(
                {
                    "stage_id": stage_id,
                    "messages": messages,
                    "schema": schema,
                    "round_tag": tag,
                    "schema_name": schema_name,
                    "vision_rejected": True,
                }
            )
            raise ModelCallError(
                stage_id, "400 - the model does not support vision input (images)"
            )
        return super().call(stage_id, messages, schema, schema_name, **kw)


class TestReviewCalls(unittest.TestCase):
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

    # ------------------------------------------------------ the context split
    def test_two_calls_with_own_stage_tags_and_schema(self):
        stub = StubLLM()
        self._review(stub)
        self.assertEqual(len(stub.calls), 2)
        tags = {c["round_tag"] for c in stub.calls}
        self.assertEqual(tags, {"facts", "design"})
        for c in stub.calls:
            self.assertEqual(c["stage_id"], "09-review")
            self.assertEqual(c["schema_name"], "review_call")
        self.assertIn("[ZIVON STAGE: 09-review-facts]", stub.system("facts"))
        self.assertIn("[ZIVON STAGE: 09-review-design]", stub.system("design"))

    def test_facts_call_gets_specs_facts_files_not_doctrine(self):
        stub = StubLLM()
        self._review(stub)
        user = stub.user("facts")
        self.assertIn("BLOCK SPECS", user)
        self.assertIn("CITED FACTS", user)
        self.assertIn("FINAL PAGE FILES", user)
        for c in load("gt.json")["claims"]:
            self.assertIn(c["statement"], user)
        for e in load("gt.json")["equations"]:
            self.assertIn(e["expression"], user)
        # the truth call carries no visual-language context
        self.assertNotIn("DESIGN DOCTRINE", user)

    def test_design_call_gets_inventory_files_doctrine_not_specs_or_facts(self):
        stub = StubLLM()
        self._review(stub)
        user = stub.user("design")
        self.assertIn("BLOCK INVENTORY", user)
        self.assertIn("FINAL PAGE FILES", user)
        self.assertIn("DESIGN DOCTRINE", user)
        self.assertIn("=== design-doctrine-lesson-example.html ===", user)
        self.assertNotIn("=== design-doctrine-example.html ===", user)
        # the visual call re-reads neither the full specs nor the facts list
        self.assertNotIn("CITED FACTS", user)
        self.assertNotIn("BLOCK SPECS (what the page must implement)", user)
        # inventory is compact: one line per block with id + type
        for b in self.blocks["blocks"]:
            self.assertIn(f"- {b['id']} [{b['type']}]", user)

    def test_manifest_dump_replaced_by_identity_header(self):
        # The manifest is mechanical page metadata; its traceability is a
        # static check. Both calls get a 3-line identity header instead.
        stub = StubLLM()
        self._review(stub)
        for which in ("facts", "design"):
            self.assertIn("PAGE UNDER REVIEW", stub.user(which))
            self.assertNotIn("MANIFEST:", stub.user(which))

    # ------------------------------------------------- the bounded procedures
    def test_facts_call_is_a_bounded_truth_procedure(self):
        stub = StubLLM()
        self._review(stub)
        user = stub.user("facts")
        self.assertIn("EXACTLY ONCE", user)
        self.assertIn("Commit to this procedure", user)
        self.assertIn("one check per item", user)
        for step in range(1, 6):
            self.assertIn(f"STEP {step} -", user)
        self.assertIn("Answer keys", user)
        self.assertIn("Facts sweep", user)
        self.assertIn("DRAWN behaviour", user)
        self.assertIn("physically wrong behaviour is a fatal issue", user)
        # the b-31 pathology from the live plateau: HTML vs JS value drift
        self.assertIn("Consistency sweep", user)
        self.assertIn("49 s", user)
        self.assertNotIn("Hunt for REAL defects", user)

    def test_design_call_includes_the_general_rendering_sweep(self):
        # Founder requirement (2026-11-08): design correctness must not be
        # only doctrine-example comparison - the model must also identify
        # rendering errors on its own terms.
        stub = StubLLM()
        self._review(stub)
        user = stub.user("design")
        self.assertIn("EXACTLY ONCE", user)
        self.assertIn("Commit to this procedure", user)
        for step in range(1, 6):
            self.assertIn(f"STEP {step} -", user)
        self.assertIn("The page follows the DESIGN DOCTRINE", user)
        doctrine = (REPO_ROOT / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(doctrine[:400], user)  # the live document, verbatim
        self.assertIn("Rendering sweep", user)
        self.assertIn("as a learner would, not against the doctrine", user)
        self.assertIn("empty or broken canvases", user)
        self.assertIn("contradict their caption", user)

    def test_design_call_carries_screenshots_when_capture_produces_them(self):
        # The design reviewer sees the rendered page: screenshots captured
        # by factory/shots.py arrive below the text as vision parts.
        shot_file = self.tmp / "diagram-1-w1280.png"
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\ndata")
        fake_shots = [
            {
                "path": str(shot_file),
                "width": 1280,
                "label": "figure.zn-diagram#1 @ 1280px",
                "bytes": 16,
            }
        ]
        stub = StubLLM()
        with mock.patch("factory.review.shots.capture", return_value=fake_shots):
            self._review(stub)
        design = next(c for c in stub.calls if "design" in c["round_tag"])
        content = next(m["content"] for m in design["messages"] if m["role"] == "user")
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("Rendering sweep", content[0]["text"])
        image_parts = [p for p in content if p.get("type") == "image_url"]
        self.assertEqual(len(image_parts), 1)
        self.assertTrue(
            image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        )
        labels = [p.get("text", "") for p in content if p.get("type") == "text"]
        self.assertIn("[figure.zn-diagram#1 @ 1280px]", labels)

    def test_design_call_stays_text_only_when_capture_produces_nothing(self):
        # Capture failure (no chromium, render error) must not change the
        # call shape at all: the pre-shots text call is the default.
        stub = StubLLM()
        with mock.patch("factory.review.shots.capture", return_value=[]):
            self._review(stub)
        design = next(c for c in stub.calls if "design" in c["round_tag"])
        content = next(m["content"] for m in design["messages"] if m["role"] == "user")
        self.assertIsInstance(content, str)
        self.assertIn("Rendering sweep", content)

    def test_vision_rejection_retries_text_only(self):
        # A model endpoint without vision rejects the design call with a 400
        # naming vision/images; the stage must fall back to the pre-shots
        # text call instead of failing the run, and leave evidence.
        shot_file = self.tmp / "diagram-1-w360.png"
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\ndata")
        fake_shots = [
            {
                "path": str(shot_file),
                "width": 360,
                "label": "figure.zn-diagram#1 @ 360px",
                "bytes": 16,
            }
        ]
        stub = VisionRefusingLLM()
        with mock.patch("factory.review.shots.capture", return_value=fake_shots):
            self._review(stub)
        design_calls = [c for c in stub.calls if "design" in c["round_tag"]]
        self.assertEqual(len(design_calls), 2)
        first = next(
            m["content"] for m in design_calls[0]["messages"] if m["role"] == "user"
        )
        second = next(
            m["content"] for m in design_calls[1]["messages"] if m["role"] == "user"
        )
        self.assertIsInstance(first, list)  # vision attempt
        self.assertIsInstance(second, str)  # text-only fallback
        self.assertIn("Rendering sweep", second)
        evidence = self.run_ctx.stage_dir(review.STAGE_ID) / "vision-fallback.json"
        self.assertTrue(evidence.exists())

    def test_non_vision_model_errors_still_raise(self):
        # A generic 400 is not a vision problem: it must propagate, not
        # silently retry as text-only (which would double-charge a broken call).
        class _OtherErrorLLM(StubLLM):
            def call(self, stage_id, messages, schema, schema_name, **kw):
                if "design" in str(kw.get("round_tag") or ""):
                    raise ModelCallError(stage_id, "400 - bad schema upstream")
                return super().call(stage_id, messages, schema, schema_name, **kw)

        shot_file = self.tmp / "diagram-1-w768.png"
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\ndata")
        fake_shots = [
            {
                "path": str(shot_file),
                "width": 768,
                "label": "figure.zn-diagram#1 @ 768px",
                "bytes": 16,
            }
        ]
        with (
            mock.patch("factory.review.shots.capture", return_value=fake_shots),
            self.assertRaises(ModelCallError),
        ):
            self._review(_OtherErrorLLM())

    def test_verdict_rule_is_harness_code_not_prompt_prose(self):
        # The old prompt carried "verdict=fail only if..."; the calls now
        # output issues only and the harness computes the verdict. The task
        # text each call is given must not mention verdicts at all (the
        # doctrine document may use the word elsewhere - only the TASK we
        # write is pinned here).
        self.assertNotIn("verdict", review._FACTS_TASK)
        self.assertNotIn("verdict", review._DESIGN_TASK)
        stub = StubLLM()
        self._review(stub)
        for which in ("facts", "design"):
            self.assertTrue(
                stub.user(which).endswith(
                    review._DESIGN_TASK if which == "design" else review._FACTS_TASK
                )
            )
        # and the contract each call must return is issues-only
        for c in stub.calls:
            self.assertEqual(list(c["schema"]["required"]), ["issues"])

    # ------------------------------------------------------ honesty + way-out
    def test_reviewer_framing_is_honest_not_adversarial(self):
        # "Assume the page contains at least one defect" manufactured
        # trivia-failures (same lesson graph v2 learned for 03-check). Both
        # calls also keep the way out: unverifiable suspicions are
        # 'unverified:' minor.
        stub = StubLLM()
        self._review(stub)
        for which in ("facts", "design"):
            user = stub.user(which)
            self.assertNotIn("Assume the page contains at least one defect", user)
            self.assertIn("do not invent problems", user)
            self.assertIn("starting 'unverified:'", user)

    # ------------------------------------------------- harness verdict + save
    def test_clean_page_passes_and_report_is_saved(self):
        stub = StubLLM()
        report = self._review(stub)
        self.assertEqual(report["verdict"], "pass")
        self.assertTrue((self.run_ctx.stage_dir("09-review") / "output.json").exists())

    def test_majors_alone_do_not_fail_the_page(self):
        # Severity law (unchanged): majors are advisory; only fatal fails.
        stub = StubLLM(
            facts_issues=[
                {
                    "severity": "major",
                    "category": "answer_key",
                    "message": "answer key wording could mislead a careful reader",
                }
            ],
            design_issues=[
                {
                    "severity": "major",
                    "category": "accessibility",
                    "block_id": "b-05",
                    "message": "SVG diagram lacks an accessible name for its labels",
                }
            ],
        )
        report = self._review(stub)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(len(report["issues"]), 2)

    def test_fatal_in_either_call_fails_and_is_returned_not_raised(self):
        # Graph v2 contract: a fail verdict is the HANDOFF to 10-reviewfix.
        # review.run must return the report; the orchestrator routes it to the
        # catcher. Raising here would kill the run (the behaviour v1 had).
        for call_kwargs in (
            {
                "facts_issues": [
                    {
                        "severity": "fatal",
                        "category": "drawn_behaviour",
                        "block_id": "b-06",
                        "message": "the simulation draws an impossible curve",
                    }
                ]
            },
            {
                "design_issues": [
                    {
                        "severity": "fatal",
                        "category": "rendering",
                        "block_id": "b-09",
                        "message": "the velocity arrow points opposite to the caption",
                    }
                ]
            },
        ):
            stub = StubLLM(**call_kwargs)
            report = self._review(stub)
            self.assertEqual(report["verdict"], "fail")
            saved = json.loads(
                (self.run_ctx.stage_dir("09-review") / "output.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(saved["verdict"], "fail")
            self.assertTrue(any(i["severity"] == "fatal" for i in saved["issues"]))

    # ---------------------------------------------------------------- ledger
    def test_issues_ledger_records_every_finding_with_its_class(self):
        stub = StubLLM(
            facts_issues=[
                {
                    "severity": "fatal",
                    "category": "inconsistency",
                    "block_id": "b-31",
                    "message": "HTML states 49 s while page.js rewrites it to 37 s",
                }
            ],
            design_issues=[
                {
                    "severity": "minor",
                    "category": "frame",
                    "block_id": "b-14",
                    "message": "unverified: canvas has fixed width/height attributes",
                }
            ],
        )
        self._review(stub)
        ledger = self.run_ctx.dir / "issues_ledger.jsonl"
        self.assertTrue(ledger.exists())
        rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 2)
        by_call = {r["call"]: r for r in rows}
        self.assertEqual(by_call["facts"]["severity"], "fatal")
        self.assertEqual(by_call["facts"]["category"], "inconsistency")
        self.assertEqual(by_call["facts"]["block_id"], "b-31")
        self.assertFalse(by_call["facts"]["unverified"])
        self.assertEqual(by_call["design"]["category"], "frame")
        self.assertTrue(by_call["design"]["unverified"])
        self.assertTrue(all(r["stage"] == "09-review" for r in rows))

    def test_clean_page_writes_no_ledger_lines(self):
        stub = StubLLM()
        self._review(stub)
        self.assertFalse((self.run_ctx.dir / "issues_ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
