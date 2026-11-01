"""Unit tests for the stage handoff schemas (factory/schemas.py)."""

import json
import sys
import unittest
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory.schemas import BLOCKS, CHECK_REPORT, GROUND_TRUTH, LESSON

FIXTURES = Path(REPO_ROOT) / "testing" / "mocks" / "fixtures"


class TestSchemas(unittest.TestCase):
    def test_fixture_ground_truth_is_valid(self):
        gt = json.loads((FIXTURES / "02-synth.json").read_text())
        jsonschema.validate(gt, GROUND_TRUTH)

    def test_fixture_lesson_is_valid(self):
        lesson = json.loads((FIXTURES / "03-explain.json").read_text())
        jsonschema.validate(lesson, LESSON)

    def test_fixture_blocks_are_valid(self):
        blocks = json.loads((FIXTURES / "04-draft.json").read_text())
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
        blocks = json.loads((FIXTURES / "04-draft.json").read_text())
        blocks["blocks"][0]["type"] = "hologram"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(blocks, BLOCKS)

    def test_blocks_reject_bare_fields(self):
        """AGENTS.md format wins: payload lives under spec, not bare fields."""
        blocks = json.loads((FIXTURES / "04-draft.json").read_text())
        del blocks["blocks"][0]["spec"]
        blocks["blocks"][0]["content"] = "bare"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(blocks, BLOCKS)

    def test_check_report_shape(self):
        jsonschema.validate({"verdict": "pass", "issues": []}, CHECK_REPORT)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"verdict": "maybe", "issues": []}, CHECK_REPORT)

    def test_block_id_pattern(self):
        blocks = json.loads((FIXTURES / "04-draft.json").read_text())
        blocks["blocks"][0]["id"] = "block-1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(blocks, BLOCKS)


if __name__ == "__main__":
    unittest.main()
