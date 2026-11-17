"""The assessment eval cards, their checkers and the seeded-defect corpus."""

from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from evals.checkers import assessment_checks, run_deterministic_check
from evals.config import EvalConfig
from evals.models import load_all_cards
from factory.assessment.config import AssessmentConfig, catalog_book_ids
from factory.assessment.pipeline import assemble_chapter_pack
from factory.assessment.schemas import (
    ASSESSMENT_DEFECT_SAMPLE,
    ASSESSMENT_GOLDEN_EXPECTED,
)
from factory.assessment.validators import (
    apply_defect_mutations,
    apply_prior_defect,
    validate_item_bank,
    validate_schema,
    validate_time_priors,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ASM_CARDS = ("EV-ASM-001", "EV-ASM-002", "EV-ASM-003", "EV-ASM-004")


class EvalTestBase(unittest.TestCase):
    cfg: EvalConfig
    cards: dict
    asm_cfg: AssessmentConfig
    syllabus: dict
    chapters: dict[str, dict]

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = EvalConfig.from_env({})
        cls.cards = load_all_cards(cls.cfg.cards_dir)
        cls.asm_cfg = AssessmentConfig.for_repo(REPO_ROOT)
        cls.syllabus = json.loads(cls.asm_cfg.syllabus_path.read_text(encoding="utf-8"))
        cls.chapters = {
            chapter["chapter_id"]: chapter
            for entry in cls.syllabus["classes"]
            for chapter in entry["chapters"]
        }

    def pack(self, chapter_id: str) -> dict:
        return assemble_chapter_pack(self.asm_cfg, chapter_id)

    def bank(self, chapter_id: str) -> dict:
        return json.loads(
            self.asm_cfg.chapter_items_path(chapter_id).read_text(encoding="utf-8")
        )


class TestCards(EvalTestBase):
    def test_all_four_cards_are_shipped(self) -> None:
        for card_id in ASM_CARDS:
            self.assertIn(card_id, self.cards)
            self.assertIn("smoke", self.cards[card_id].suites)

    def test_cards_declare_no_model_calls(self) -> None:
        for card_id in ASM_CARDS:
            card = self.cards[card_id]
            self.assertEqual(card.cost_budget["smoke_model_calls"], 0)
            self.assertIsNone(card.llm_judge)

    def test_every_checker_runs_with_no_blocking_issue(self) -> None:
        for card_id in ASM_CARDS:
            card = self.cards[card_id]
            context: dict = {}
            for check in card.deterministic_checks:
                issues = run_deterministic_check(
                    check.entrypoint, self.cfg, card, context
                )
                blocking = [i for i in issues if i.severity in ("fatal", "major")]
                self.assertEqual(blocking, [], (card_id, check.id))

    def test_every_checker_returns_the_skipped_contract_when_data_is_missing(
        self,
    ) -> None:
        context: dict = {}
        card = dataclasses.replace(
            self.cards["EV-ASM-001"],
            golden_inputs={
                **self.cards["EV-ASM-001"].golden_inputs,
                "topics": ["evals/goldens/assessment/not-there"],
            },
        )
        issues = assessment_checks.check_practice_pack_integrity(
            self.cfg, card, context
        )
        self.assertEqual(issues, [])
        self.assertIn(assessment_checks.CHECK_001, context["skipped_checks"])


class TestGoldens(EvalTestBase):
    def test_goldens_validate_and_point_at_shipped_chapters(self) -> None:
        manifest = json.loads(
            (self.cfg.goldens_dir / "manifest.json").read_text(encoding="utf-8")
        )
        goldens = manifest["assessment_goldens"]
        self.assertEqual([g["golden_id"] for g in goldens], ["GA-01", "GA-02"])
        for golden in goldens:
            directory = REPO_ROOT / golden["directory"]
            expected = json.loads((directory / "expected.json").read_text())
            validate_schema(expected, ASSESSMENT_GOLDEN_EXPECTED, golden["golden_id"])
            self.assertIn(expected["chapter_id"], self.chapters)
            self.assertTrue((directory / "artifact_ref.json").is_file())

    def test_defect_corpus_is_registered_and_valid(self) -> None:
        manifest = json.loads(
            (self.cfg.goldens_dir / "manifest.json").read_text(encoding="utf-8")
        )
        registered = {
            defect_id
            for ids in manifest["assessment_seeded_defect_sets"].values()
            for defect_id in ids
        }
        files = sorted(
            (self.cfg.goldens_dir / "assessment" / "defects").glob("SD-ASM-*.json")
        )
        self.assertEqual({path.stem for path in files}, registered)
        for path in files:
            sample = json.loads(path.read_text(encoding="utf-8"))
            validate_schema(sample, ASSESSMENT_DEFECT_SAMPLE, path.name)
            self.assertIn(sample["chapter_id"], self.chapters)

    def test_each_bank_defect_makes_its_rule_fire(self) -> None:
        for defect_id in (
            "SD-ASM-001",
            "SD-ASM-002",
            "SD-ASM-003",
            "SD-ASM-004",
            "SD-ASM-005",
        ):
            path = self.cfg.goldens_dir / "assessment" / "defects" / f"{defect_id}.json"
            defect = json.loads(path.read_text(encoding="utf-8"))
            chapter = self.chapters[defect["chapter_id"]]
            bank = self.bank(defect["chapter_id"])
            mutated = apply_defect_mutations(bank, defect)
            rules = {
                issue.rule
                for issue in validate_item_bank(
                    mutated,
                    chapter,
                    self.asm_cfg.policy,
                    catalog_book_ids=catalog_book_ids(self.asm_cfg.catalog_path),
                )
                if issue.severity in ("fatal", "major")
            }
            self.assertIn(defect["expected_rule"], rules, defect_id)

    def test_the_prior_defect_makes_its_rule_fire(self) -> None:
        defect = json.loads(
            (
                self.cfg.goldens_dir / "assessment" / "defects" / "SD-ASM-006.json"
            ).read_text(encoding="utf-8")
        )
        result = self.pack(defect["chapter_id"])
        priors = {
            key: result["priors"][key]
            for key in ("schema_version", "formula_version", "questions", "topics")
        }
        mutated = apply_prior_defect(priors, defect)
        rules = {
            issue.rule
            for issue in validate_time_priors(
                mutated,
                result["chapter"],
                result["items"]["items"],
                self.asm_cfg.policy,
            )
            if issue.severity in ("fatal", "major")
        }
        self.assertIn(defect["expected_rule"], rules)


if __name__ == "__main__":
    unittest.main()
