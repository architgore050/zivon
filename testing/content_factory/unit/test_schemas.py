"""Unit tests for the stage handoff schemas (factory/schemas.py)."""

import json
import sys
import unittest
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.schemas import (
    BLOCKS,
    CHECK_REPORT,
    GENERATED,
    GROUND_TRUTH,
    LESSON,
    REPAIR,
)

FIXTURES = Path(REPO_ROOT) / "testing" / "content_factory" / "mocks" / "fixtures"


class TestSchemas(unittest.TestCase):
    def test_fixture_ground_truth_is_valid(self):
        gt = json.loads((FIXTURES / "gt.json").read_text())
        jsonschema.validate(gt, GROUND_TRUTH)

    def test_fixture_lesson_is_valid(self):
        lesson = json.loads((FIXTURES / "lesson.json").read_text())
        jsonschema.validate(lesson, LESSON)

    def test_fixture_blocks_are_valid(self):
        blocks = json.loads((FIXTURES / "blocks.json").read_text())
        jsonschema.validate(blocks, BLOCKS)

    def test_ground_truth_requires_citations(self):
        bad = {
            "topic": "T",
            "summary": "s" * 50,
            "claims": [{"id": "claim-01", "statement": "x" * 20, "citations": []}],
            "key_terms": [],
            "equations": [],
            "misconceptions": [],
            "uncertain": [],
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, GROUND_TRUTH)

    def test_blocks_reject_unknown_type(self):
        blocks = json.loads((FIXTURES / "blocks.json").read_text())
        blocks["blocks"][0]["type"] = "hologram"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(blocks, BLOCKS)

    def test_blocks_reject_bare_fields(self):
        """AGENTS.md format wins: payload lives under spec, not bare fields."""
        blocks = json.loads((FIXTURES / "blocks.json").read_text())
        del blocks["blocks"][0]["spec"]
        blocks["blocks"][0]["content"] = "bare"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(blocks, BLOCKS)

    def test_check_report_shape(self):
        jsonschema.validate({"verdict": "pass", "issues": []}, CHECK_REPORT)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"verdict": "maybe", "issues": []}, CHECK_REPORT)

    def test_block_id_pattern(self):
        blocks = json.loads((FIXTURES / "blocks.json").read_text())
        blocks["blocks"][0]["id"] = "block-1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(blocks, BLOCKS)

    # ---- graph v2: GENERATED (one giant call) + REPAIR (catcher) ------------
    def test_fixture_generated_is_valid(self):
        generated = json.loads((FIXTURES / "02-generate.json").read_text())
        jsonschema.validate(generated, GENERATED)

    def test_generated_requires_all_three_layers(self):
        generated = json.loads((FIXTURES / "02-generate.json").read_text())
        del generated["lesson"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(generated, GENERATED)

    def test_generated_rejects_extra_layers(self):
        generated = json.loads((FIXTURES / "02-generate.json").read_text())
        generated["page_html"] = "<html>..."
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(generated, GENERATED)

    def test_fixture_repair_plan_is_valid(self):
        plan = json.loads((FIXTURES / "repair_plan.json").read_text())
        jsonschema.validate(plan, REPAIR)

    def test_repair_must_replace_at_least_one_block(self):
        # A repair that replaces nothing is a whole-page re-run in disguise.
        plan = json.loads((FIXTURES / "repair_plan.json").read_text())
        plan["blocks"] = []
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(plan, REPAIR)


if __name__ == "__main__":
    unittest.main()
