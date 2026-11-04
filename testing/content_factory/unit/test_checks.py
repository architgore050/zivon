"""Unit tests for the rule-based checker (factory/checks.py)."""

import json
import sys
import unittest
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import checks

FIXTURES = Path(REPO_ROOT) / "testing" / "content_factory" / "mocks" / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class TestAnswerKeys(unittest.TestCase):
    def test_mcq_ok(self):
        blocks = load("blocks.json")["blocks"]
        self.assertEqual(checks.rule_answer_keys(blocks), [])

    def test_mcq_index_out_of_range(self):
        blocks = load("blocks.json")["blocks"]
        blocks[3]["spec"]["answer_index"] = 9
        issues = checks.rule_answer_keys(blocks)
        self.assertTrue(any(i["severity"] == "fatal" for i in issues))

    def test_mcq_answer_mismatch(self):
        blocks = load("blocks.json")["blocks"]
        blocks[3]["spec"]["answer"] = "Speed"  # answer_index points at Acceleration
        issues = checks.rule_answer_keys(blocks)
        self.assertTrue(any("mismatch" in i["message"] for i in issues))

    def test_numeric_answer_not_a_number(self):
        blocks = load("blocks.json")["blocks"]
        blocks[6]["spec"]["answer"] = "fast"
        issues = checks.rule_answer_keys(blocks)
        self.assertTrue(any("not a number" in i["message"] for i in issues))


class TestCitations(unittest.TestCase):
    def test_known_claims_pass(self):
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        self.assertEqual(checks.rule_citations(blocks, gt, make_pack()), [])

    def test_unknown_claim_fails(self):
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        blocks[0]["citations"].append({"claim_id": "claim-99"})
        issues = checks.rule_citations(blocks, gt, make_pack())
        self.assertTrue(
            any("claim-99" in i["message"] and i["severity"] == "fatal" for i in issues)
        )

    def test_factual_block_without_citation_is_fatal(self):
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        blocks[0]["citations"] = []  # a text block citing nothing
        issues = checks.rule_citations(blocks, gt, make_pack())
        self.assertTrue(
            any(
                "no citations" in i["message"] and i["severity"] == "fatal"
                for i in issues
            )
        )

    def test_source_ids_are_derived_from_the_pack(self):
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        # a supplement id from the pack is fine...
        blocks[0]["citations"].append({"source_id": "alt-open-physics#c0001"})
        self.assertEqual(checks.rule_citations(blocks, gt, make_pack()), [])
        # ...an id nobody fetched is flagged (major: suspicious provenance)
        blocks[0]["citations"].append({"source_id": "wikipedia-random-article"})
        issues = checks.rule_citations(blocks, gt, make_pack())
        self.assertTrue(
            any(
                "wikipedia-random-article" in i["message"] and i["severity"] == "major"
                for i in issues
            )
        )


class TestSelfContainment(unittest.TestCase):
    def test_clean_lesson_passes(self):
        blocks = load("blocks.json")["blocks"]
        lesson = load("lesson.json")
        issues = checks.rule_self_containment(blocks, lesson)
        self.assertEqual([i for i in issues if i["severity"] == "fatal"], [])

    def test_external_reference_caught(self):
        lesson = load("lesson.json")
        lesson["sections"][0]["paragraphs"][0] += (
            " We studied this in the previous chapter."
        )
        issues = checks.rule_self_containment([], lesson)
        self.assertTrue(any("previous chapter" in i["message"] for i in issues))

    def test_url_caught(self):
        blocks = load("blocks.json")["blocks"]
        lesson = load("lesson.json")
        blocks[0]["spec"]["paragraphs"][0] += " See https://example.com for more."
        issues = checks.rule_self_containment(blocks, lesson)
        self.assertTrue(any("URL" in i["message"] for i in issues))


class TestNumbers(unittest.TestCase):
    def test_traceable_numbers_pass(self):
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        pack = {"ncert_text": load_source_text()}
        self.assertEqual(checks.rule_numbers(blocks, gt, pack), [])

    def test_invented_problem_number_fails(self):
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        pack = {"ncert_text": load_source_text()}
        blocks[2]["spec"]["problem"] = (
            "A body gains a speed of 73 m/s in 5 s. What is its acceleration?"  # 73 appears nowhere
        )
        issues = checks.rule_numbers(blocks, gt, pack)
        self.assertTrue(
            any("73" in i["message"] and i["severity"] == "fatal" for i in issues)
        )

    def test_computed_answer_is_the_reviewers_gate_not_the_rules(self):
        # NCERT exercises are meant to be computed; answers are verified by
        # 03-check recomputation. This rule guards PROBLEM data only.
        blocks = load("blocks.json")["blocks"]
        gt = load("gt.json")
        pack = {"ncert_text": load_source_text()}
        blocks[2]["spec"]["answer"] = (
            "5.5 m/s"  # wrong on purpose - not this rule's job
        )
        self.assertEqual(checks.rule_numbers(blocks, gt, pack), [])


class TestNumbersBoundary(unittest.TestCase):
    """Substring matching used to let '5' 'appear' in '15'. The rule must
    match whole numerals only."""

    GT: ClassVar[dict] = {
        "claims": [
            {
                "id": "claim-01",
                "statement": "A car reaches 15 m/s; another reaches 5.0 m/s.",
            }
        ],
        "key_terms": [],
        "equations": [],
        "misconceptions": [],
        "uncertain": [],
    }
    PACK: ClassVar[dict] = {"ncert_text": "The distance is 10 m."}

    def _problems(self, problem: str) -> list[dict]:
        blocks = [
            {
                "id": "b-x",
                "type": "worked_example",
                # the answer is deliberately untraceable ('73'): answers are
                # 03-check's job, this rule guards problem data
                "spec": {"problem": problem, "steps": [], "answer": "73 m/s2"},
                "citations": [],
            }
        ]
        return checks.rule_numbers(blocks, self.GT, self.PACK)

    def test_whole_numerals_traceable(self):
        self.assertEqual(self._problems("A car reaches 15 m/s in 10 s"), [])
        self.assertEqual(
            self._problems("another car reaches 5.0 m/s"), []
        )  # matches '5.0'
        self.assertEqual(self._problems("The distance is 10 m"), [])

    def test_substring_smuggling_rejected(self):
        self.assertTrue(
            any("number 1 " in i["message"] for i in self._problems("1 m/s"))
        )
        self.assertTrue(
            any("number 50 " in i["message"] for i in self._problems("50 m/s"))
        )
        self.assertTrue(
            any("number 1.5 " in i["message"] for i in self._problems("1.5 m/s"))
        )

    def test_computed_answer_figures_are_not_code_checked(self):
        self.assertEqual(self._problems("A car reaches 15 m/s"), [])

    def test_check_question_numbers_are_checked(self):
        def mcq(question: str) -> list[dict]:
            blocks = [
                {
                    "id": "b-m",
                    "type": "check",
                    "spec": {
                        "question": question,
                        "format": "mcq",
                        "options": ["15 m/s", "99 m/s"],
                        "answer_index": 1,
                        "explanation": "e",
                    },
                    "citations": [],
                }
            ]
            return checks.rule_numbers(blocks, self.GT, self.PACK)

        # traceable question data -> clean, even with an untraceable option
        self.assertEqual(
            mcq("A car reaches 15 m/s. After 10 s, what is its speed?"), []
        )
        # invented question data -> fatal
        self.assertTrue(
            any("99" in i["message"] for i in mcq("A car reaches 99 m/s. Why?"))
        )


class TestDiagramSvg(unittest.TestCase):
    def test_clean_svg_passes(self):
        blocks = load("blocks.json")["blocks"]
        self.assertEqual(checks.rule_diagram_svg(blocks), [])

    def test_script_in_svg_fails(self):
        blocks = load("blocks.json")["blocks"]
        blocks[4]["spec"]["svg"] = (
            "<svg viewBox='0 0 1 1'><script>alert(1)</script></svg>"
        )
        issues = checks.rule_diagram_svg(blocks)
        self.assertTrue(any("script" in i["message"] for i in issues))

    def test_url_in_svg_fails_but_xmlns_ok(self):
        blocks = load("blocks.json")["blocks"]
        blocks[4]["spec"]["svg"] = blocks[4]["spec"]["svg"].replace(
            "</svg>", '<a href="https://evil.example">x</a></svg>'
        )
        issues = checks.rule_diagram_svg(blocks)
        self.assertTrue(any("external URL" in i["message"] for i in issues))


def load_source_text() -> str:
    import pdfplumber

    with pdfplumber.open(FIXTURES / "pdfs" / "ch01.pdf") as pdf:
        return "\n".join((p.extract_text(use_text_flow=True) or "") for p in pdf.pages)


def make_pack() -> dict:
    """A source pack shaped like stage 01-locate's output (the fixture set has
    no 01-locate.json; locate runs live in the integration test)."""
    return {
        "ncert_text": load_source_text(),
        "chapter": {"book_id": "ncert-class-9-science-ch08-motion"},
        "supplements": [
            {"source_id": "alt-open-physics#c0001", "book_id": "alt-open-physics"}
        ],
    }


if __name__ == "__main__":
    unittest.main()
