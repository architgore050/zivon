"""Unit tests for 02-generate / 03-check / 04-repair wiring (graph v2).

The generation call must carry the code-side rule checks AT GENERATION TIME
(the model sees its own violations in the retry transcript), the fact
reviewer prompt must carry the calibrated severity ladder, and the repair
catcher must merge replacements correctly.
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

from factory import agents
from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient
from factory.schemas import GENERATED, REPAIR
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_pack() -> dict[str, Any]:
    import pdfplumber

    with pdfplumber.open(FIXTURES / "pdfs" / "ch01.pdf") as pdf:
        ncert = "\n".join((p.extract_text(use_text_flow=True) or "") for p in pdf.pages)
    return {
        "ncert_text": ncert,
        "chapter": {
            "book_id": "ncert-fixture-ch01",
            "title": "Motion",
            "book_title": "Fixture Science Class 9",
            "class": 9,
            "pages": [97, 112],
        },
        "supplements": [
            {
                "source_id": "alt-open-physics#c0001",
                "book_id": "alt-open-physics",
                "book_title": "Alternative Open Physics",
                "page_from": 4,
                "page_to": 6,
                "text": "Speed is distance divided by time.",
            }
        ],
    }


class StubLLM:
    """Captures what the agent runner hands to llm.call and returns a fixture."""

    def __init__(self, fixture: str = "02-generate.json") -> None:
        self.fixture = fixture
        self.kwargs: dict[str, Any] = {}
        self.messages: list[dict[str, str]] = []
        self.stage_id: str = ""

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.stage_id = stage_id
        self.kwargs = kw
        self.messages = messages
        return load(self.fixture)


def _cfg(tmp: Path):
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    (tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
    saved = install_server_env()
    try:
        # root must be the real repo: the agents inject the shipped doctrine
        # and stylesheet.
        return dataclasses.replace(load_config(tmp / "config.json"), root=REPO_ROOT)
    finally:
        release_server_env(saved)


class TestGenerateRuleWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = _cfg(self.tmp)
        self.run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-gen")

    def _run_generate(self, stub: StubLLM) -> dict[str, Any]:
        return agents.run_generate(
            self.cfg, self.run_ctx, cast(LLMClient, stub), make_pack()
        )

    def test_combined_output_validates_against_generated_schema(self):
        import jsonschema

        generated = load("02-generate.json")
        jsonschema.validate(instance=generated, schema=GENERATED)
        self.assertEqual(self._run_generate(StubLLM()), generated)

    def test_validator_is_wired_into_the_call(self):
        stub = StubLLM()
        out = self._run_generate(stub)
        self.assertIn("extra_validator", stub.kwargs)
        validator = stub.kwargs["extra_validator"]
        # the clean fixture page passes the rules - no feedback loop needed
        self.assertEqual(validator(out), [])

    def test_prompt_promises_verbatim_problem_data_and_computed_answers(self):
        # The harness checks PROBLEM data verbatim; answers are computed from
        # the source's own equations and recomputed by 03-check. (2026-11-04:
        # the old verbatim-answers rule made every NCERT numerical impossible,
        # which is why the Motion page skipped all of them.)
        stub = StubLLM()
        self._run_generate(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("VERBATIM", user)
        self.assertIn("COMPUTED from those numbers", user)
        self.assertIn("do not convert units or compute new values", user)

    def test_prompt_carries_the_coverage_contract(self):
        # 2026-11-04 (founder): the Motion run taught only the basics and
        # skipped momentum, conservation ideas, exercises and practice problems.
        # The chapter is the unit of teaching - the prompt must say so in
        # harness-verifiable words.
        stub = StubLLM()
        self._run_generate(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("COVERAGE CONTRACT", user)
        self.assertIn("end-of-chapter exercises", user)
        self.assertIn("every titled section of the chapter", user)
        self.assertIn("every item of your chapter inventory must appear", user)

    def test_prompt_carries_the_grounding_law(self):
        # The founder calibration: model priors must not smuggle in concepts the
        # chapter never teaches (the 2026-11-02 05-check failure class).
        stub = StubLLM()
        self._run_generate(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        system = next(m["content"] for m in stub.messages if m["role"] == "system")
        self.assertIn("standard Physics", user)  # in the page-level grounding law
        self.assertIn("does NOT count", system)  # in the global rules
        self.assertIn("whole universe of this page", system)

    def test_violations_are_reported_to_the_model(self):
        stub = StubLLM()
        self._run_generate(stub)
        validator = stub.kwargs["extra_validator"]
        bad = load("02-generate.json")
        bad["blocks"]["blocks"][2]["spec"]["problem"] = (
            "A body gains a speed of 73 m/s in 5 s. What is its acceleration?"  # 73 appears nowhere in the sources - invented problem data
        )
        bad["blocks"]["blocks"][0]["citations"] = []  # uncited text block
        problems = validator(bad)
        self.assertTrue(any("73" in p for p in problems), problems)
        self.assertTrue(any("no citations" in p for p in problems), problems)

    def test_generate_prompt_carries_live_doctrine_and_palette(self):
        # 02-generate specs the diagrams, so it must see the live doctrine (its
        # diagram rules) and the exact palette - not a held-over excerpt.
        stub = StubLLM()
        self._run_generate(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("DESIGN DOCTRINE", user)
        doctrine = (REPO_ROOT / "docs" / "frontend" / "design-doctrine.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(doctrine[:400], user)  # the live document, verbatim
        self.assertIn("#1F3A9E", user)  # palette parsed from zivon.css
        self.assertIn("PALETTE values for fill/stroke", user)
        # generate specs blocks, it does not build the shell: no example pages
        self.assertNotIn("=== design-doctrine-example.html ===", user)

    def test_generate_prompt_carries_persona_teaching_order_and_shape_example(self):
        stub = StubLLM()
        self._run_generate(stub)
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("patient tutor", user)
        self.assertIn("TEACHING ORDER", user)
        self.assertIn("keep numbers and units exactly", user)
        self.assertIn("Example of the required SHAPE", user)
        self.assertIn("never reuse", user)


class TestCheckPromptCalibration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = _cfg(self.tmp)
        self.run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-check")

    def _check_prompt(self) -> str:
        stub = StubLLM()
        agents.run_check(
            self.cfg,
            self.run_ctx,
            cast(LLMClient, stub),
            make_pack(),
            load("gt.json"),
            load("lesson.json"),
            load("blocks.json"),
        )
        return next(m["content"] for m in stub.messages if m["role"] == "user")

    def test_severity_ladder_is_exact(self):
        user = self._check_prompt()
        self.assertIn("Severity ladder (apply it exactly)", user)
        self.assertIn("smuggled-in concept", user)
        self.assertIn("advisory and must never fail the page", user)
        self.assertIn("verdict=fail if and only if you report at least one fatal", user)

    def test_reviewer_is_not_fed_adversarial_framing(self):
        # Graph v1 said "assume the draft contains at least one error" - that
        # framing manufactured trivia-failures. v2 demands honest review.
        user = self._check_prompt()
        self.assertNotIn("Assume the draft contains at least one error", user)
        self.assertIn("Do not invent problems", user)

    def test_reviewer_teaches_and_hedges(self):
        user = self._check_prompt()
        self.assertIn("teach the expected_understanding before", user)
        self.assertIn("starting 'unverified:'", user)
        self.assertIn("Example issue (SHAPE only", user)
        self.assertIn("never reuse", user)

    def test_reviewer_gates_coverage_and_arithmetic(self):
        # 2026-11-04 (founder): a faithful-but-thin page must FAIL the gate.
        # Coverage omissions are fatal, and every computed answer is recomputed
        # from the problem data - never trusted.
        user = self._check_prompt()
        self.assertIn("RECOMPUTE every worked_example", user)
        self.assertIn("COVERAGE", user)
        self.assertIn("end-of-chapter exercises", user)
        self.assertIn("omits a chapter section", user)

    def test_reviewer_sees_the_lesson_it_must_verify_against(self):
        # Checklist item 5 asks whether the page teaches an expected_understanding
        # BEFORE testing it - the reviewer cannot judge that without the lesson
        # prose in its context (context-completeness rule, prompting skill).
        user = self._check_prompt()
        self.assertIn("THE LESSON THE PAGE TEACHES", user)
        self.assertIn(load("lesson.json")["title"], user)


class TestRepairCatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = _cfg(self.tmp)
        self.run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "t-repair"
        )

    def test_repair_prompt_carries_findings_and_omission_rule(self):
        stub = StubLLM(fixture="repair_plan.json")
        issues = [
            {
                "block_id": "b-05",
                "severity": "major",
                "message": "block tests mass/force, a concept the chapter never defines",
            }
        ]
        agents.run_repair(
            self.cfg,
            self.run_ctx,
            cast(LLMClient, stub),
            make_pack(),
            load("gt.json"),
            load("lesson.json"),
            load("blocks.json"),
            issues,
            round_tag="round-01",
        )
        user = next(m["content"] for m in stub.messages if m["role"] == "user")
        self.assertIn("mass/force", user)  # the reviewer's verdict is the input
        self.assertIn("OMIT it", user)
        self.assertIn("Fix ONLY the flagged blocks", user)
        # coverage omissions are fixed by ADDING blocks, not re-running 02
        self.assertIn("coverage-omission fix", user)
        self.assertIn("LAST added block a check", user)
        self.assertIn("Example of the required SHAPE", user)
        self.assertIn("never reuse", user)
        self.assertEqual(stub.kwargs.get("round_tag"), "round-01")

    def test_repair_output_validates_against_repair_schema(self):
        import jsonschema

        plan = load("repair_plan.json")
        jsonschema.validate(instance=plan, schema=REPAIR)

    def test_repair_validator_checks_merged_blocks_not_just_replacements(self):
        stub = StubLLM(fixture="repair_plan.json")
        agents.run_repair(
            self.cfg,
            self.run_ctx,
            cast(LLMClient, stub),
            make_pack(),
            load("gt.json"),
            load("lesson.json"),
            load("blocks.json"),
            [{"block_id": "b-05", "severity": "major", "message": "x"}],
            round_tag="round-01",
        )
        validator = stub.kwargs["extra_validator"]
        # a replacement that invents problem data must be caught even though
        # the rest of the page is untouched
        bad_plan = load("repair_plan.json")
        bad_plan["blocks"][0]["spec"]["question"] = (
            "A runner covers 73 m in 20 s. What is her average speed (in m/s)?"
        )
        problems = validator(bad_plan)
        self.assertTrue(any("73" in p for p in problems), problems)


class TestMergeBlocks(unittest.TestCase):
    def _page(self, ids: list[str]) -> dict[str, Any]:
        return {
            "blocks": [
                {
                    "id": i,
                    "type": "text",
                    "spec": {"paragraphs": ["p"]},
                    "citations": [],
                }
                for i in ids
            ]
        }

    def test_replacement_keeps_position(self):
        current = self._page(["b-01", "b-02", "b-03"])
        replacement = {
            "id": "b-02",
            "type": "check",
            "spec": {"question": "q"},
            "citations": [{"claim_id": "claim-01"}],
        }
        merged = agents.merge_blocks(current, [replacement])
        self.assertEqual([b["id"] for b in merged["blocks"]], ["b-01", "b-02", "b-03"])
        self.assertEqual(merged["blocks"][1]["type"], "check")

    def test_new_ids_append(self):
        merged = agents.merge_blocks(
            self._page(["b-01"]),
            [
                {
                    "id": "b-02",
                    "type": "check",
                    "spec": {"question": "q"},
                    "citations": [],
                }
            ],
        )
        self.assertEqual([b["id"] for b in merged["blocks"]], ["b-01", "b-02"])

    def test_removal(self):
        merged = agents.remove_blocks(self._page(["b-01", "b-02"]), {"b-01"})
        self.assertEqual([b["id"] for b in merged["blocks"]], ["b-02"])


if __name__ == "__main__":
    unittest.main()
