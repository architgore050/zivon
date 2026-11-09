"""Unit tests for 02-generate / 04-repair rule wiring and merge mechanics (graph v2).

Note: Prompt-substring and reviewer-calibration assertions were migrated to
`evals/checkers/prompt_contract_checks.py` (`EV-SYN-001`, `EV-SYN-002`, `EV-REV-001`)
per `docs/specs/evals/migration-map.csv` rows 12, 13, and 15.
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
        cfg = dataclasses.replace(load_config(tmp / "config.json"), root=REPO_ROOT)
        return cfg.with_class_level(9)
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
        self.assertEqual(validator(out), [])

    def test_violations_are_reported_to_the_model(self):
        stub = StubLLM()
        self._run_generate(stub)
        validator = stub.kwargs["extra_validator"]
        bad = load("02-generate.json")
        bad["blocks"]["blocks"][2]["spec"]["problem"] = (
            "A body gains a speed of 73 m/s in 5 s. What is its acceleration?"
        )
        bad["blocks"]["blocks"][0]["citations"] = []
        problems = validator(bad)
        self.assertTrue(any("73" in p for p in problems), problems)
        self.assertTrue(any("no citations" in p for p in problems), problems)


class TestRepairCatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = _cfg(self.tmp)
        self.run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "t-repair"
        )

    def test_repair_passes_round_tag_kwarg(self):
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
