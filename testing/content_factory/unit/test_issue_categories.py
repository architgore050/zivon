"""Tests for the P4 deterministic gates: issue categories, numeric recompute,
and glossary coverage.

The contracts under test:
- every rule id maps to exactly one ledger category, and the model-review
  vocabulary stays a subset of the ledger vocabulary;
- a 03-check issue without a model category lands in the ledger with the
  category its rule id implies (never a blanket "other");
- arithmetic that is provably wrong is fatal, and anything the rule cannot
  parse is an `unverified:` minor - never a false blocker;
- a glossary term used on the page must exist in every promised locale.
"""

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import checks, numeric
from factory.issue_categories import (
    LEDGER_CATEGORIES,
    RULE_CATEGORY,
    categorize,
    issue_category,
    normalize_category,
)
from factory.ledger import issue_entry
from factory.schemas import REVIEW_CATEGORIES

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"
GLOSSARY = REPO_ROOT / "sources" / "glossary" / "physics_glossary.json"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestIssueCategories(unittest.TestCase):
    def test_model_review_vocabulary_is_a_subset_of_the_ledger_vocabulary(self):
        missing = set(REVIEW_CATEGORIES) - set(LEDGER_CATEGORIES)
        self.assertEqual(missing, set())

    def test_every_checks_rule_id_is_mapped(self):
        for rule in (
            "shape",
            "answer_key",
            "citations",
            "self_containment",
            "numbers",
            "numeric_recompute",
            "glossary_coverage",
            "diagram_svg",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, RULE_CATEGORY)
                self.assertIn(categorize(rule), LEDGER_CATEGORIES)

    def test_unknown_eval_check_family_uses_its_prefix(self):
        self.assertEqual(categorize("DET-VIS02-FUTURE-RULE"), "accessibility")
        self.assertEqual(categorize("DET-SYN03-FUTURE-RULE"), "numeric")
        self.assertIsNone(categorize("DET-NOPE-001"))

    def test_category_aliases_normalize(self):
        self.assertEqual(normalize_category("A11Y"), "accessibility")
        self.assertEqual(normalize_category("answer-key"), "answer_key")
        self.assertIsNone(normalize_category("nonsense"))

    def test_issue_category_precedence(self):
        self.assertEqual(
            issue_category({"category": "frame", "rule": "numbers"}), "frame"
        )
        self.assertEqual(issue_category({"rule": "numbers"}), "fact")
        self.assertEqual(
            issue_category({"check_id": "DET-VIS02-A11Y-STATIC"}), "accessibility"
        )
        self.assertEqual(issue_category({}, "content"), "content")


class TestLedgerCategories(unittest.TestCase):
    def test_rule_issue_gets_mapped_category_and_rule(self):
        row = issue_entry(
            "03-check",
            "static",
            None,
            {
                "block_id": "b-03",
                "severity": "fatal",
                "rule": "numbers",
                "message": "x",
            },
            "content",
        )
        self.assertEqual(row["category"], "fact")
        self.assertEqual(row["rule"], "numbers")

    def test_model_issue_keeps_its_own_category(self):
        row = issue_entry(
            "09-review",
            "facts",
            "round-01",
            {"severity": "major", "category": "answer_key", "message": "x"},
        )
        self.assertEqual(row["category"], "answer_key")

    def test_uncategorized_issue_falls_back_to_the_stage_default(self):
        row = issue_entry(
            "03-check", "check", None, {"severity": "minor", "message": "x"}, "content"
        )
        self.assertEqual(row["category"], "content")


class TestNumericRecompute(unittest.TestCase):
    def test_clean_numeric_check_is_verified(self):
        blocks = load("blocks.json")["blocks"]
        for block in blocks:
            if block["type"] == "check" and block["spec"].get("format") == "numeric":
                block["spec"]["question"] = (
                    "An object covers 100 m in 20 s. What is its average speed in m/s?"
                )
                block["spec"]["answer"] = "5"
                block["spec"]["explanation"] = (
                    "Average speed is total distance divided by total time: 100 / 20 = 5 m/s."
                )
        report = numeric.recompute_blocks(blocks)
        self.assertGreaterEqual(report["verified"], 1)
        blocking = [i for i in report["issues"] if i["severity"] in ("fatal", "major")]
        self.assertEqual(blocking, [])

    def test_provably_wrong_arithmetic_is_fatal(self):
        block = {
            "id": "b-03",
            "type": "worked_example",
            "spec": {
                "problem": "A body gains speed 10 m/s in 5 s.",
                "steps": [{"title": "Divide", "detail": "a = 10 / 5 = 3 m/s2."}],
                "answer": "2 m/s2",
            },
        }
        report = numeric.recompute_blocks([block])
        fatals = [i for i in report["issues"] if i["severity"] == "fatal"]
        self.assertEqual(len(fatals), 1)
        self.assertEqual(fatals[0]["rule"], "numeric_recompute")
        self.assertIn("arithmetic does not hold", fatals[0]["message"])

    def test_unit_conversion_is_not_an_arithmetic_claim(self):
        block = {
            "id": "b-04",
            "type": "worked_example",
            "spec": {
                "problem": "Convert a time.",
                "steps": [
                    {"title": "Convert", "detail": "The trip takes 0.5 h = 30 min."}
                ],
                "answer": "0.5 h",
            },
        }
        report = numeric.recompute_blocks([block])
        self.assertEqual(
            [i for i in report["issues"] if i["severity"] in ("fatal", "major")], []
        )

    def test_symbolic_working_reports_unverified_never_fatal(self):
        block = {
            "id": "b-05",
            "type": "worked_example",
            "spec": {
                "problem": "Use v = u + a t.",
                "steps": [
                    {
                        "title": "Rearrange",
                        "detail": "Use v = u + a*t, so a = (v - u) / t with symbols.",
                    }
                ],
                "answer": "2 m/s2",
            },
        }
        report = numeric.recompute_blocks([block])
        self.assertEqual(
            [i for i in report["issues"] if i["severity"] in ("fatal", "major")], []
        )
        self.assertTrue(
            any(str(i["message"]).startswith("unverified:") for i in report["issues"])
        )

    def test_published_clean_fixture_has_no_blocking_numeric_issue(self):
        sample = json.loads(
            (
                REPO_ROOT
                / "evals"
                / "goldens"
                / "defects"
                / "03-check"
                / "SD-CHK-007.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [
                i
                for i in checks.rule_numeric_recompute(
                    sample["inputs"]["blocks"]["blocks"]
                )
                if i["severity"] in ("fatal", "major")
            ],
            [],
        )


class TestGlossaryCoverage(unittest.TestCase):
    def setUp(self):
        self.glossary = json.loads(GLOSSARY.read_text(encoding="utf-8"))

    def _lesson(self, term: str) -> dict:
        return {
            "title": "Motion",
            "objectives": ["Understand acceleration"],
            "sections": [
                {
                    "id": "sec-01",
                    "title": "Speed",
                    "paragraphs": [f"The {term} of a body changes."],
                }
            ],
            "glossary": [{"term": term, "definition": "a rate"}],
        }

    def test_tagged_term_with_complete_locale_entries_passes(self):
        issues = checks.rule_glossary_coverage(
            self._lesson("acceleration"), [], self.glossary, ["hi", "hi-Latn"]
        )
        self.assertEqual(issues, [])

    def test_tagged_term_missing_a_promised_locale_is_fatal(self):
        glossary = json.loads(json.dumps(self.glossary))
        for entry in glossary["terms"]:
            if entry["english_term"] == "acceleration":
                entry["locales"].pop("hi-Latn")
        issues = checks.rule_glossary_coverage(
            self._lesson("acceleration"), [], glossary, ["hi", "hi-Latn"]
        )
        self.assertTrue(issues)
        self.assertEqual(issues[0]["severity"], "fatal")
        self.assertEqual(issues[0]["category"], "glossary")

    def test_no_promised_locales_means_no_check(self):
        self.assertEqual(
            checks.rule_glossary_coverage(self._lesson("acceleration"), [], {}, []), []
        )


class TestRunAllRulesWiring(unittest.TestCase):
    def test_rule_issues_carry_a_category_and_the_numeric_summary(self):
        blocks = load("blocks.json")["blocks"]
        report = checks.run_all_rules(
            blocks, load("lesson.json"), load("gt.json"), _pack()
        )
        self.assertIn("numeric_recompute", report)
        for issue in report["rule_issues"]:
            self.assertIn("category", issue)
            self.assertIn(issue["category"], LEDGER_CATEGORIES)


def _pack() -> dict:
    return {
        "ncert_text": "Speed is distance divided by time. Acceleration is the rate of change of velocity with time.",
        "chapter": {"book_id": "ncert-fixture"},
        "supplements": [],
    }


if __name__ == "__main__":
    unittest.main()
