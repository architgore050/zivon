"""A3-practice-items: schema, answer keys, sources, duplicates, language, mix."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from factory.assessment.config import AssessmentConfig, catalog_book_ids
from factory.assessment.generator import (
    LLMItemGenerator,
    SeedItemGenerator,
    make_generator,
)
from factory.assessment.items import bank_counts, generate_with_repair
from factory.assessment.validators import (
    ItemGatePolicy,
    apply_defect_mutations,
    gate_report,
    validate_item_bank,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_CHAPTERS = (
    "class-9-describing-motion-around-us",
    "class-10-light-reflection-and-refraction",
)


class ItemTestBase(unittest.TestCase):
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
            self.cfg.chapter_items_path(chapter_id).read_text(encoding="utf-8")
        )

    def rules(self, bank: dict, chapter_id: str) -> set[str]:
        return {
            issue.rule
            for issue in validate_item_bank(
                bank,
                self.chapters[chapter_id],
                self.policy,
                catalog_book_ids=self.book_ids,
            )
        }

    def defect(self, **mutations) -> dict:
        return {
            "sample_id": "SD-ASM-900",
            "chapter_id": "class-9-describing-motion-around-us",
            "defect_class": "unit-test",
            "expected_rule": "unit.test",
            "expected_severity": "fatal",
            "mutations": mutations,
        }


class TestShippedBanks(ItemTestBase):
    def test_both_golden_banks_pass_the_gate(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            with self.subTest(chapter=chapter_id):
                issues = validate_item_bank(
                    self.bank(chapter_id),
                    self.chapters[chapter_id],
                    self.policy,
                    catalog_book_ids=self.book_ids,
                )
                report = gate_report(issues)
                self.assertEqual(report["verdict"], "pass", report["issues"])

    def test_each_chapter_has_fifteen_items_with_type_and_difficulty_mix(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            bank = self.bank(chapter_id)
            counts = bank_counts(bank)
            self.assertEqual(counts["items"], 15)
            self.assertGreaterEqual(counts["by_type"]["mcq"], 5)
            self.assertGreaterEqual(counts["by_type"]["numeric"], 2)
            self.assertGreaterEqual(counts["by_type"]["assertion_reason"], 1)
            for difficulty in ("easy", "medium", "hard"):
                self.assertGreaterEqual(counts["by_difficulty"][difficulty], 1)

    def test_every_curated_concept_is_practised(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            bank = self.bank(chapter_id)
            concepts = {c["concept_id"] for c in self.chapters[chapter_id]["concepts"]}
            used = {item["concept_id"] for item in bank["items"]}
            self.assertEqual(concepts, used)

    def test_all_three_languages_are_present_on_every_item(self) -> None:
        for chapter_id in GOLDEN_CHAPTERS:
            for item in self.bank(chapter_id)["items"]:
                self.assertEqual(set(item["locales"]), {"en", "hi", "hi-Latn"})


class TestRuleFailures(ItemTestBase):
    def mutate(self, chapter_id: str, **mutations) -> dict:
        return apply_defect_mutations(self.bank(chapter_id), self.defect(**mutations))

    def test_wrong_answer_index_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="patch_item",
            item_id="q-c9-motion-001",
            patch={"answer": {"index": 7}},
        )
        self.assertIn(
            "item.answer.index", self.rules(bank, "class-9-describing-motion-around-us")
        )

    def test_missing_explanation_fails(self) -> None:
        bank = self.mutate(
            "class-10-light-reflection-and-refraction",
            operation="patch_item",
            item_id="q-c10-light-002",
            patch={"locales": {"en": {"explanation": "No."}}},
        )
        self.assertIn(
            "item.explanation",
            self.rules(bank, "class-10-light-reflection-and-refraction"),
        )

    def test_off_chapter_concept_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="patch_item",
            item_id="q-c9-motion-007",
            patch={"concept_id": "class-9-describing-motion-around-us-thermodynamics"},
        )
        self.assertIn(
            "item.concept_unknown",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_duplicate_prompt_fails(self) -> None:
        bank = self.mutate(
            "class-10-light-reflection-and-refraction",
            operation="duplicate_item",
            source_item_id="q-c10-light-003",
            new_item_id="q-c10-light-003-copy",
        )
        self.assertIn(
            "item.duplicate_prompt",
            self.rules(bank, "class-10-light-reflection-and-refraction"),
        )

    def test_missing_language_variant_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="delete_locale",
            item_id="q-c9-motion-009",
            locale="hi-Latn",
        )
        self.assertIn(
            "item.language_missing",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_hindi_without_devanagari_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="patch_item",
            item_id="q-c9-motion-003",
            patch={
                "locales": {
                    "hi": {
                        "prompt": "A car covers 120 m in 8 s.",
                        "explanation": "Average speed is distance divided by time.",
                    }
                }
            },
        )
        self.assertIn(
            "item.language_script",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_latin_script_with_devanagari_fails(self) -> None:
        bank = self.mutate(
            "class-10-light-reflection-and-refraction",
            operation="patch_item",
            item_id="q-c10-light-001",
            patch={"locales": {"hi-Latn": {"prompt": "किरण दर्पण पर गिरती है।"}}},
        )
        self.assertIn(
            "item.language_script",
            self.rules(bank, "class-10-light-reflection-and-refraction"),
        )

    def test_source_outside_the_chapter_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="patch_item",
            item_id="q-c9-motion-011",
            patch={"source_ref": {"book_id": "ncert-science-9", "section": "6.1"}},
        )
        self.assertIn(
            "item.source_off_chapter",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_unknown_source_book_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="patch_item",
            item_id="q-c9-motion-011",
            patch={"source_ref": {"book_id": "some-other-book", "section": "4.3"}},
        )
        self.assertIn(
            "item.source_unknown_book",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_distractor_pointing_at_the_answer_fails(self) -> None:
        bank = self.mutate(
            "class-9-describing-motion-around-us",
            operation="patch_item",
            item_id="q-c9-motion-001",
            patch={"distractor_index": 0},
        )
        self.assertIn(
            "item.answer.distractor",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_too_few_items_fails_the_count(self) -> None:
        bank = copy.deepcopy(self.bank("class-9-describing-motion-around-us"))
        bank["items"] = bank["items"][:5]
        self.assertIn(
            "bank.count", self.rules(bank, "class-9-describing-motion-around-us")
        )

    def test_unpractised_concept_fails_coverage(self) -> None:
        bank = copy.deepcopy(self.bank("class-9-describing-motion-around-us"))
        bank["items"] = [
            item
            for item in bank["items"]
            if item["concept_id"]
            != "class-9-describing-motion-around-us-position-distance-displacement"
        ]
        self.assertIn(
            "bank.concept_coverage",
            self.rules(bank, "class-9-describing-motion-around-us"),
        )

    def test_one_answer_index_dominating_is_a_warning_not_a_gate(self) -> None:
        bank = copy.deepcopy(self.bank("class-9-describing-motion-around-us"))
        for item in bank["items"]:
            if item["type"] in ("mcq", "assertion_reason"):
                item["answer"] = {"index": 0}
                if item.get("distractor_index") == 0:
                    item["distractor_index"] = 1
        issues = validate_item_bank(
            bank,
            self.chapters["class-9-describing-motion-around-us"],
            self.policy,
            catalog_book_ids=self.book_ids,
        )
        warnings = {i.rule for i in issues if i.severity == "minor"}
        self.assertIn("bank.answer_balance", warnings)
        self.assertEqual(gate_report(issues)["verdict"], "pass")


class FakeClient:
    """A stand-in for `factory.llm.LLMClient`: records the call contract and
    returns whatever bank the test hands it."""

    def __init__(self, banks: list[dict]):
        self.banks = banks
        self.calls: list[dict] = []

    def call(self, stage_id, messages, schema, schema_name, **kwargs):
        self.calls.append(
            {
                "stage_id": stage_id,
                "messages": messages,
                "schema_name": schema_name,
                "extra_validator": kwargs.get("extra_validator"),
                "round_tag": kwargs.get("round_tag"),
            }
        )
        bank = copy.deepcopy(self.banks[min(len(self.calls) - 1, len(self.banks) - 1)])
        validator = kwargs.get("extra_validator")
        if validator is not None:
            self.last_problems = validator(bank)
        return bank


class TestGeneratorSeam(ItemTestBase):
    def test_seed_generator_reads_the_tracked_bank_and_cannot_repair(self) -> None:
        generator = SeedItemGenerator(self.cfg)
        result = generator.generate_items(
            self.chapters["class-9-describing-motion-around-us"]
        )
        self.assertEqual(result.generator, "seed-asm-1")
        self.assertEqual(len(result.bank["items"]), 15)
        self.assertIsNone(
            generator.repair_items(
                self.chapters["class-9-describing-motion-around-us"],
                result.bank,
                {"issues": []},
            )
        )

    def test_llm_generator_calls_the_schema_and_validator(self) -> None:
        chapter = self.chapters["class-9-describing-motion-around-us"]
        bank = self.bank("class-9-describing-motion-around-us")
        client = FakeClient([bank])
        generator = LLMItemGenerator(self.cfg, chapter, client, self.policy)
        result = generator.generate_items(chapter)
        self.assertEqual(result.generator, "llm-asm-1")
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["stage_id"], "A3-practice-items")
        self.assertEqual(call["schema_name"], "ASSESSMENT_ITEM_BANK")
        self.assertEqual(call["messages"][0]["role"], "system")
        self.assertEqual(client.last_problems, [])

    def test_llm_repair_feeds_the_gate_findings_back(self) -> None:
        chapter = self.chapters["class-9-describing-motion-around-us"]
        good = self.bank("class-9-describing-motion-around-us")
        broken = copy.deepcopy(good)
        broken["items"][0]["answer"] = {"index": 99}
        client = FakeClient([broken, good])
        generator = LLMItemGenerator(self.cfg, chapter, client, self.policy)
        generated = generator.generate_items(chapter)
        issues = validate_item_bank(
            generated.bank,
            chapter,
            self.policy,
            catalog_book_ids=self.book_ids,
        )
        report = gate_report(issues)
        repaired = generator.repair_items(chapter, generated.bank, report)
        self.assertIsNotNone(repaired)
        self.assertEqual(len(client.calls), 2)
        repair_prompt = client.calls[1]["messages"][1]["content"]
        self.assertIn("item.answer.index", repair_prompt)
        self.assertIn("COMPLETE corrected bank", repair_prompt)

    def test_generation_and_repair_converge_through_the_catcher(self) -> None:
        chapter = self.chapters["class-9-describing-motion-around-us"]
        good = self.bank("class-9-describing-motion-around-us")
        broken = copy.deepcopy(good)
        broken["items"][0]["answer"] = {"index": 99}
        client = FakeClient([broken, good])
        generator = LLMItemGenerator(self.cfg, chapter, client, self.policy)
        bank, report, repair = generate_with_repair(self.cfg, chapter, generator)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(repair["rounds"], 1)
        self.assertGreater(repair["history"][0]["error_count"], 0)
        self.assertEqual(repair["history"][-1]["error_count"], 0)
        self.assertEqual(len(bank["items"]), 15)

    def test_llm_generator_without_a_client_is_refused(self) -> None:
        cfg = AssessmentConfig.for_repo(REPO_ROOT, generator="llm")
        from factory.assessment.errors import AssessmentStageError

        with self.assertRaises(AssessmentStageError):
            make_generator(cfg, self.chapters["class-9-describing-motion-around-us"])


if __name__ == "__main__":
    unittest.main()
