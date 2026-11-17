"""A5-time-priors: deterministic formula, sane bounds, topic coverage."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from factory.assessment import timepriors
from factory.assessment.config import AssessmentConfig
from factory.assessment.validators import ItemGatePolicy, validate_time_priors

REPO_ROOT = Path(__file__).resolve().parents[3]


def _item(**overrides) -> dict:
    base = {
        "item_id": "q-test-001",
        "concept_id": "class-9-describing-motion-around-us-speed-and-velocity",
        "type": "mcq",
        "difficulty": "medium",
        "marks": 1,
        "computation_steps": 0,
        "locales": {
            "en": {
                "prompt": "A short question about speed and distance.",
                "explanation": "x" * 20,
            },
            "hi": {"prompt": "चाल और दूरी पर एक छोटा प्रश्न।", "explanation": "x" * 20},
            "hi-Latn": {
                "prompt": "Speed aur distance par ek chhota sawaal.",
                "explanation": "x" * 20,
            },
        },
    }
    base.update(overrides)
    return base


class TestFormula(unittest.TestCase):
    policy = ItemGatePolicy()

    def test_same_inputs_give_the_same_prior(self) -> None:
        item = _item()
        first = timepriors.expected_time_ms(item, "en", self.policy)
        second = timepriors.expected_time_ms(copy.deepcopy(item), "en", self.policy)
        self.assertEqual(first, second)

    def test_harder_items_get_more_time(self) -> None:
        easy = timepriors.expected_time_ms(_item(difficulty="easy"), "en", self.policy)
        medium = timepriors.expected_time_ms(
            _item(difficulty="medium"), "en", self.policy
        )
        hard = timepriors.expected_time_ms(_item(difficulty="hard"), "en", self.policy)
        self.assertLess(easy, medium)
        self.assertLess(medium, hard)

    def test_more_marks_get_more_time(self) -> None:
        one = timepriors.expected_time_ms(_item(marks=1), "en", self.policy)
        two = timepriors.expected_time_ms(_item(marks=2), "en", self.policy)
        self.assertLess(one, two)

    def test_more_computation_steps_get_more_time(self) -> None:
        none = timepriors.expected_time_ms(
            _item(computation_steps=0), "en", self.policy
        )
        two = timepriors.expected_time_ms(_item(computation_steps=2), "en", self.policy)
        self.assertLess(none, two)

    def test_hindi_reads_slower_than_english(self) -> None:
        item = _item()
        en = timepriors.expected_time_ms(item, "en", self.policy)
        hi = timepriors.expected_time_ms(item, "hi", self.policy)
        self.assertGreater(hi, en)

    def test_priors_stay_inside_the_policy_bounds(self) -> None:
        huge = _item(
            difficulty="hard",
            marks=5,
            computation_steps=12,
            locales={
                lang: {"prompt": "word " * 400, "explanation": "x" * 20}
                for lang in ("en", "hi", "hi-Latn")
            },
        )
        tiny = _item(
            difficulty="easy",
            marks=1,
            computation_steps=0,
            locales={
                lang: {"prompt": "1 + 1?", "explanation": "x" * 20}
                for lang in ("en", "hi", "hi-Latn")
            },
        )
        self.assertEqual(
            timepriors.expected_time_ms(huge, "en", self.policy),
            self.policy.time_prior_max_ms,
        )
        tiny_prior = timepriors.expected_time_ms(tiny, "en", self.policy)
        self.assertGreaterEqual(tiny_prior, self.policy.time_prior_min_ms)
        self.assertLessEqual(tiny_prior, self.policy.time_prior_max_ms)

    def test_formula_constants_are_documented(self) -> None:
        constants = timepriors.formula_constants()
        self.assertEqual(constants["formula_version"], timepriors.FORMULA_VERSION)
        self.assertEqual(
            set(constants["base_ms"]), {"mcq", "numeric", "assertion_reason"}
        )
        self.assertEqual(set(constants["language_factor"]), {"en", "hi", "hi-Latn"})


class TestPriorsPayload(unittest.TestCase):
    cfg: AssessmentConfig
    syllabus: dict
    chapter: dict
    bank: dict
    items_output: dict
    priors: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AssessmentConfig.for_repo(REPO_ROOT)
        cls.syllabus = json.loads(cls.cfg.syllabus_path.read_text(encoding="utf-8"))
        cls.chapter = {
            chapter["chapter_id"]: chapter
            for entry in cls.syllabus["classes"]
            for chapter in entry["chapters"]
        }["class-9-describing-motion-around-us"]
        cls.bank = json.loads(
            cls.cfg.chapter_items_path(cls.chapter["chapter_id"]).read_text(
                encoding="utf-8"
            )
        )
        cls.items_output = {"items": cls.bank["items"]}
        cls.priors = timepriors.build(cls.cfg, cls.chapter, cls.items_output)

    def test_one_prior_per_item_variant(self) -> None:
        ids = {row["question_id"] for row in self.priors["questions"]}
        expected = {
            f"{item['item_id']}-{lang}"
            for item in self.bank["items"]
            for lang in ("en", "hi", "hi-Latn")
        }
        self.assertEqual(ids, expected)

    def test_topic_priors_cover_the_chapter_and_every_concept(self) -> None:
        scopes = {(t["scope"], t["scope_id"]) for t in self.priors["topics"]}
        self.assertIn(("chapter", self.chapter["chapter_id"]), scopes)
        for concept in self.chapter["concepts"]:
            self.assertIn(("concept", concept["concept_id"]), scopes)

    def test_chapter_prior_is_the_mark_weighted_english_mean(self) -> None:
        english = [
            row for row in self.priors["questions"] if row["basis"]["language"] == "en"
        ]
        weight = sum(row["basis"]["marks"] for row in english)
        expected = round(
            sum(row["expected_time_ms"] * row["basis"]["marks"] for row in english)
            / weight
        )
        chapter_row = next(t for t in self.priors["topics"] if t["scope"] == "chapter")
        self.assertEqual(chapter_row["expected_time_ms"], expected)
        self.assertEqual(chapter_row["questions"], len(english))

    def test_prior_basis_records_every_formula_input(self) -> None:
        row = self.priors["questions"][0]
        self.assertEqual(
            set(row["basis"]),
            {
                "type",
                "difficulty",
                "marks",
                "language",
                "word_count",
                "computation_steps",
                "formula_version",
            },
        )
        self.assertEqual(row["basis"]["formula_version"], timepriors.FORMULA_VERSION)


class TestPriorRules(unittest.TestCase):
    cfg: AssessmentConfig
    chapter: dict
    bank: dict
    priors: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AssessmentConfig.for_repo(REPO_ROOT)
        syllabus = json.loads(cls.cfg.syllabus_path.read_text(encoding="utf-8"))
        cls.chapter = {
            chapter["chapter_id"]: chapter
            for entry in syllabus["classes"]
            for chapter in entry["chapters"]
        }["class-9-describing-motion-around-us"]
        cls.bank = json.loads(
            cls.cfg.chapter_items_path(cls.chapter["chapter_id"]).read_text(
                encoding="utf-8"
            )
        )
        cls.priors = timepriors.build(
            cls.cfg, cls.chapter, {"items": cls.bank["items"]}
        )

    def rules(self, priors: dict) -> set[str]:
        return {
            issue.rule
            for issue in validate_time_priors(
                priors, self.chapter, self.bank["items"], self.cfg.policy
            )
        }

    def test_shipped_priors_pass(self) -> None:
        self.assertEqual(self.rules(self.priors), set())

    def test_out_of_bounds_prior_fails(self) -> None:
        broken = copy.deepcopy(self.priors)
        broken["questions"][0]["expected_time_ms"] = 900_000
        self.assertIn("time_prior.bounds", self.rules(broken))

    def test_missing_prior_fails(self) -> None:
        broken = copy.deepcopy(self.priors)
        broken["questions"] = broken["questions"][:-1]
        self.assertIn("time_prior.missing", self.rules(broken))

    def test_unknown_topic_scope_fails(self) -> None:
        broken = copy.deepcopy(self.priors)
        broken["topics"][1]["scope_id"] = "class-9-not-a-concept"
        self.assertIn("time_prior.topic_scope", self.rules(broken))

    def test_duplicate_prior_row_fails(self) -> None:
        broken = copy.deepcopy(self.priors)
        broken["questions"].append(copy.deepcopy(broken["questions"][0]))
        self.assertIn("time_prior.duplicate", self.rules(broken))


if __name__ == "__main__":
    unittest.main()
