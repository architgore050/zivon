"""A4-speaking-rubrics: key ideas, model answers, thresholds and languages."""

from __future__ import annotations

import copy
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from factory.assessment.config import AssessmentConfig, catalog_book_ids
from factory.assessment.errors import AssessmentGateError
from factory.assessment.speaking import run_stage
from factory.assessment.validators import (
    ItemGatePolicy,
    gate_report,
    validate_speaking_bank,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_CHAPTERS = (
    "class-9-describing-motion-around-us",
    "class-10-light-reflection-and-refraction",
)


class SpeakingTestBase(unittest.TestCase):
    cfg: AssessmentConfig
    syllabus: dict
    chapters: dict[str, dict]
    book_ids: set[str]
    policy: ItemGatePolicy

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AssessmentConfig.for_repo(REPO_ROOT)
        cls.syllabus = json.loads(cls.cfg.syllabus_path.read_text(encoding="utf-8"))
        cls.chapters = {
            chapter["chapter_id"]: chapter
            for entry in cls.syllabus["classes"]
            for chapter in entry["chapters"]
        }
        cls.book_ids = catalog_book_ids(cls.cfg.catalog_path)
        cls.policy = ItemGatePolicy()

    def bank(self, chapter_id: str) -> dict:
        return json.loads(
            self.cfg.chapter_speaking_path(chapter_id).read_text(encoding="utf-8")
        )

    def rules(self, bank: dict, chapter_id: str) -> set[str]:
        return {
            issue.rule
            for issue in validate_speaking_bank(
                bank,
                self.chapters[chapter_id],
                self.policy,
                catalog_book_ids=self.book_ids,
            )
        }


class TestShippedRubrics(SpeakingTestBase):
    def test_both_banks_pass_the_gate(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            with self.subTest(chapter=chapter_id):
                report = gate_report(
                    validate_speaking_bank(
                        self.bank(chapter_id),
                        self.chapters[chapter_id],
                        self.policy,
                        catalog_book_ids=self.book_ids,
                    )
                )
                self.assertEqual(report["verdict"], "pass", report["issues"])

    def test_each_chapter_has_three_prompts_in_three_languages(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            bank = self.bank(chapter_id)
            self.assertGreaterEqual(len(bank["prompts"]), 3)
            for prompt in bank["prompts"]:
                self.assertEqual(
                    set(prompt["locales"]), {"en", "hi", "hi-Latn"}, prompt["prompt_id"]
                )

    def test_every_prompt_has_three_to_five_key_ideas_and_a_model_answer(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            for prompt in self.bank(chapter_id)["prompts"]:
                for lang, payload in prompt["locales"].items():
                    with self.subTest(prompt=prompt["prompt_id"], lang=lang):
                        self.assertGreaterEqual(len(payload["key_ideas"]), 3)
                        self.assertLessEqual(len(payload["key_ideas"]), 5)
                        self.assertGreaterEqual(len(payload["model_answer"]), 40)

    def test_every_key_idea_concept_exists_in_the_chapter(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            known = {c["concept_id"] for c in self.chapters[chapter_id]["concepts"]}
            for prompt in self.bank(chapter_id)["prompts"]:
                for concept_id in prompt["concept_ids"]:
                    self.assertIn(concept_id, known)

    def test_thresholds_are_ordered_and_bounded(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            for prompt in self.bank(chapter_id)["prompts"]:
                thresholds = prompt["thresholds"]
                self.assertLessEqual(
                    thresholds["pass_ratio"], thresholds["strong_ratio"]
                )
                self.assertGreaterEqual(thresholds["min_key_ideas"], 3)
                self.assertLessEqual(thresholds["max_duration_s"], 300)

    def test_run_stage_emits_counts_and_gate(self) -> None:
        chapter = self.chapters["class-10-light-reflection-and-refraction"]
        output = run_stage(self.cfg, chapter)
        self.assertEqual(output["gate"]["verdict"], "pass")
        self.assertEqual(output["counts"]["prompts"], 3)

    def test_stage_refuses_a_thin_prompt_set(self) -> None:
        chapter = self.chapters["class-9-describing-motion-around-us"]
        original = self.bank("class-9-describing-motion-around-us")
        with tempfile.TemporaryDirectory() as td:
            chapters = Path(td) / "chapters"
            chapters.mkdir()
            broken = copy.deepcopy(original)
            broken["prompts"] = broken["prompts"][:1]
            (chapters / f"{chapter['chapter_id']}.speaking.json").write_text(
                json.dumps(broken), encoding="utf-8"
            )
            cfg = dataclasses.replace(self.cfg, chapters_dir=chapters)
            with self.assertRaises(AssessmentGateError) as ctx:
                run_stage(cfg, chapter)
            self.assertIn("rubric.prompt_count", str(ctx.exception))


class TestSpeakingRuleFailures(SpeakingTestBase):
    def mutate(self, chapter_id: str, fn) -> dict:
        bank = copy.deepcopy(self.bank(chapter_id))
        fn(bank)
        return bank

    def test_unknown_concept_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            lambda b: b["prompts"][0].update({"concept_ids": ["class-9-not-real"]}),
        )
        self.assertIn(
            "rubric.concept_unknown",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_source_outside_chapter_fails(self) -> None:
        bank = self.mutate(
            "class-10-light-reflection-and-refraction",
            lambda b: b["prompts"][0]["source_ref"].update({"section": "12.1"}),
        )
        self.assertIn(
            "rubric.source_off_chapter",
            self.rules(bank, "class-10-light-reflection-and-refraction"),
        )

    def test_source_outside_the_prompt_concepts_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            lambda b: b["prompts"][0]["source_ref"].update({"section": "4.3"}),
        )
        self.assertIn(
            "rubric.source_concept",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_inverted_thresholds_fail(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            lambda b: b["prompts"][0]["thresholds"].update(
                {"pass_ratio": 0.9, "strong_ratio": 0.5}
            ),
        )
        self.assertIn(
            "rubric.thresholds", self.rules(bank, "class-9-describing-motion-around-us")
        )

    def test_hindi_prompt_without_devanagari_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            lambda b: b["prompts"][0]["locales"]["hi"].update(
                {"prompt": "Explain distance and displacement."}
            ),
        )
        self.assertIn(
            "rubric.language_script",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_key_idea_counts_must_agree_across_languages(self) -> None:
        bank = self.mutate(
            "class-10-light-reflection-and-refraction",
            lambda b: b["prompts"][0]["locales"]["hi"].update(
                {"key_ideas": b["prompts"][0]["locales"]["hi"]["key_ideas"][:3]}
            ),
        )
        self.assertIn(
            "rubric.key_ideas",
            self.rules(bank, "class-10-light-reflection-and-refraction"),
        )

    def test_too_few_prompts_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            lambda b: b.update({"prompts": b["prompts"][:1]}),
        )
        self.assertIn(
            "rubric.prompt_count",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )


if __name__ == "__main__":
    unittest.main()
