"""Unit tests for the rule-based checker (factory/checks.py)."""

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory import checks

FIXTURES = Path(REPO_ROOT) / "testing" / "mocks" / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class TestAnswerKeys(unittest.TestCase):
    def test_mcq_ok(self):
        blocks = load("04-draft.json")["blocks"]
        self.assertEqual(checks.rule_answer_keys(blocks), [])

    def test_mcq_index_out_of_range(self):
        blocks = load("04-draft.json")["blocks"]
        blocks[3]["spec"]["answer_index"] = 9
        issues = checks.rule_answer_keys(blocks)
        self.assertTrue(any(i["severity"] == "fatal" for i in issues))

    def test_mcq_answer_mismatch(self):
        blocks = load("04-draft.json")["blocks"]
        blocks[3]["spec"]["answer"] = "Speed"  # answer_index points at Acceleration
        issues = checks.rule_answer_keys(blocks)
        self.assertTrue(any("mismatch" in i["message"] for i in issues))

    def test_numeric_answer_not_a_number(self):
        blocks = load("04-draft.json")["blocks"]
        blocks[6]["spec"]["answer"] = "fast"
        issues = checks.rule_answer_keys(blocks)
        self.assertTrue(any("not a number" in i["message"] for i in issues))


class TestCitations(unittest.TestCase):
    def test_known_claims_pass(self):
        blocks = load("04-draft.json")["blocks"]
        gt = load("02-synth.json")
        self.assertEqual(checks.rule_citations(blocks, gt), [])

    def test_unknown_claim_fails(self):
        blocks = load("04-draft.json")["blocks"]
        gt = load("02-synth.json")
        blocks[0]["citations"].append({"claim_id": "claim-99"})
        issues = checks.rule_citations(blocks, gt)
        self.assertTrue(
            any("claim-99" in i["message"] and i["severity"] == "fatal" for i in issues)
        )


class TestSelfContainment(unittest.TestCase):
    def test_clean_lesson_passes(self):
        blocks = load("04-draft.json")["blocks"]
        lesson = load("03-explain.json")
        issues = checks.rule_self_containment(blocks, lesson)
        self.assertEqual([i for i in issues if i["severity"] == "fatal"], [])

    def test_external_reference_caught(self):
        lesson = load("03-explain.json")
        lesson["sections"][0]["paragraphs"][0] += (
            " We studied this in the previous chapter."
        )
        issues = checks.rule_self_containment([], lesson)
        self.assertTrue(any("previous chapter" in i["message"] for i in issues))

    def test_url_caught(self):
        blocks = load("04-draft.json")["blocks"]
        lesson = load("03-explain.json")
        blocks[0]["spec"]["paragraphs"][0] += " See https://example.com for more."
        issues = checks.rule_self_containment(blocks, lesson)
        self.assertTrue(any("URL" in i["message"] for i in issues))


class TestNumbers(unittest.TestCase):
    def test_traceable_numbers_pass(self):
        blocks = load("04-draft.json")["blocks"]
        gt = load("02-synth.json")
        pack = {"ncert_text": load_source_text()}
        self.assertEqual(checks.rule_numbers(blocks, gt, pack), [])

    def test_invented_number_fails(self):
        blocks = load("04-draft.json")["blocks"]
        gt = load("02-synth.json")
        pack = {"ncert_text": load_source_text()}
        blocks[2]["spec"]["answer"] = "73 m/s2"  # 73 appears nowhere
        issues = checks.rule_numbers(blocks, gt, pack)
        self.assertTrue(
            any("73" in i["message"] and i["severity"] == "fatal" for i in issues)
        )


class TestDiagramSvg(unittest.TestCase):
    def test_clean_svg_passes(self):
        blocks = load("04-draft.json")["blocks"]
        self.assertEqual(checks.rule_diagram_svg(blocks), [])

    def test_script_in_svg_fails(self):
        blocks = load("04-draft.json")["blocks"]
        blocks[4]["spec"]["svg"] = (
            "<svg viewBox='0 0 1 1'><script>alert(1)</script></svg>"
        )
        issues = checks.rule_diagram_svg(blocks)
        self.assertTrue(any("script" in i["message"] for i in issues))

    def test_url_in_svg_fails_but_xmlns_ok(self):
        blocks = load("04-draft.json")["blocks"]
        blocks[4]["spec"]["svg"] = blocks[4]["spec"]["svg"].replace(
            "</svg>", '<a href="https://evil.example">x</a></svg>'
        )
        issues = checks.rule_diagram_svg(blocks)
        self.assertTrue(any("external URL" in i["message"] for i in issues))


def load_source_text() -> str:
    from pypdf import PdfReader

    reader = PdfReader(FIXTURES / "pdfs" / "ch01.pdf")
    return "\n".join(p.extract_text() for p in reader.pages)


if __name__ == "__main__":
    unittest.main()
