"""The exam/series eval cards, their checkers and the seeded-defect corpus."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from evals.checkers import exam_checks, run_deterministic_check
from evals.config import EvalConfig
from evals.models import load_all_cards
from factory.exam.schemas import EXAM_DEFECT_SAMPLE, EXAM_GOLDEN_EXPECTED

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAM_CARDS = ("EV-EXM-001", "EV-SER-001", "EV-SER-002", "EV-SER-003")


class EvalTestBase(unittest.TestCase):
    cfg: EvalConfig
    cards: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = EvalConfig.from_env({})
        cls.cards = load_all_cards(cls.cfg.cards_dir)

    def run_checker(self, card_id: str) -> list:
        card = self.cards[card_id]
        issues = []
        for check in card.deterministic_checks:
            issues.extend(run_deterministic_check(check.entrypoint, self.cfg, card, {}))
        return issues


class CardTests(EvalTestBase):
    def test_all_four_cards_are_shipped(self) -> None:
        self.assertEqual(set(EXAM_CARDS) - set(self.cards), set())

    def test_cards_are_key_free_and_smoke_safe(self) -> None:
        for card_id in EXAM_CARDS:
            card = self.cards[card_id]
            with self.subTest(card=card_id):
                self.assertIn("smoke", card.suites)
                self.assertIn("full", card.suites)
                self.assertIsNone(card.llm_judge)
                self.assertEqual(card.cost_budget["smoke_model_calls"], 0)
                self.assertEqual(card.cost_budget["full_model_calls_per_topic"], 0)
                for check in card.deterministic_checks:
                    self.assertEqual(check.severity_on_fail, "fatal")

    def test_every_checker_entrypoint_resolves(self) -> None:
        for card_id in EXAM_CARDS:
            for check in self.cards[card_id].deterministic_checks:
                module, function = check.entrypoint.split(":")
                self.assertEqual(module, "evals.checkers.exam_checks")
                self.assertTrue(callable(getattr(exam_checks, function)))


class GoldenTests(EvalTestBase):
    def test_goldens_validate_and_name_the_right_class(self) -> None:
        for class_num, rel in exam_checks.GOLDENS.items():
            path = REPO_ROOT / rel / "expected.json"
            with self.subTest(class_num=class_num):
                self.assertTrue(path.is_file(), path)
                payload = json.loads(path.read_text(encoding="utf-8"))
                from evals.models import validate_schema

                validate_schema(payload, EXAM_GOLDEN_EXPECTED, str(path))
                self.assertEqual(payload["class_num"], class_num)

    def test_golden_blueprint_matches_the_syllabus(self) -> None:
        from factory.exam.syllabus import chapters_for_class, load_syllabus

        syllabus = load_syllabus(REPO_ROOT / "sources" / "syllabus" / "syllabus.json")
        for class_num, rel in exam_checks.GOLDENS.items():
            expected = json.loads(
                (REPO_ROOT / rel / "expected.json").read_text(encoding="utf-8")
            )
            with self.subTest(class_num=class_num):
                self.assertEqual(
                    expected["blueprint"]["chapter_ids"],
                    [
                        chapter["chapter_id"]
                        for chapter in chapters_for_class(syllabus, class_num)
                    ],
                )


class DefectTests(EvalTestBase):
    def test_every_registered_defect_exists_and_validates(self) -> None:
        from evals.models import validate_schema

        registered: set[str] = set()
        for card_id in EXAM_CARDS:
            registered.update(
                self.cards[card_id].golden_inputs.get("seeded_defects", [])
            )
        self.assertEqual(len(registered), 11)
        for sample_id in sorted(registered):
            path = self.cfg.goldens_dir / "exam" / "defects" / f"{sample_id}.json"
            with self.subTest(defect=sample_id):
                self.assertTrue(path.is_file(), path)
                payload = json.loads(path.read_text(encoding="utf-8"))
                validate_schema(payload, EXAM_DEFECT_SAMPLE, sample_id)
                self.assertEqual(payload["sample_id"], sample_id)

    def test_the_manifest_registers_every_defect(self) -> None:
        manifest = json.loads(
            (self.cfg.goldens_dir / "manifest.json").read_text(encoding="utf-8")
        )
        registered = {
            sample_id
            for values in manifest["exam_seeded_defect_sets"].values()
            for sample_id in values
        }
        card_registered: set[str] = set()
        for card_id in EXAM_CARDS:
            card_registered.update(
                self.cards[card_id].golden_inputs.get("seeded_defects", [])
            )
        self.assertEqual(registered, card_registered)


class CheckerTests(EvalTestBase):
    def test_ingest_fidelity_is_clean_on_the_tracked_fixtures(self) -> None:
        issues = self.run_checker("EV-EXM-001")
        self.assertEqual(
            [issue.message for issue in issues if issue.severity in ("fatal", "major")],
            [],
        )

    def test_blueprint_alignment_is_clean(self) -> None:
        issues = self.run_checker("EV-SER-001")
        self.assertEqual(
            [issue.message for issue in issues if issue.severity in ("fatal", "major")],
            [],
        )

    def test_volume_gate_is_clean_and_proves_both_directions(self) -> None:
        issues = self.run_checker("EV-SER-002")
        self.assertEqual(
            [issue.message for issue in issues if issue.severity in ("fatal", "major")],
            [],
        )

    def test_copy_compliance_is_clean(self) -> None:
        issues = self.run_checker("EV-SER-003")
        self.assertEqual(
            [issue.message for issue in issues if issue.severity in ("fatal", "major")],
            [],
        )

    def test_an_unfired_defect_is_reported(self) -> None:
        """If a defect stops reproducing, the checker must say so, not pass."""
        card = self.cards["EV-EXM-001"]
        original = exam_checks.apply_document_defect

        def noop(document, defect):
            return document

        exam_checks.apply_document_defect = noop
        try:
            issues = exam_checks.check_ingest_fidelity(self.cfg, card, {})
        finally:
            exam_checks.apply_document_defect = original
        self.assertTrue(
            any("exam.defect.unfired" in issue.message for issue in issues),
            [issue.message for issue in issues],
        )


if __name__ == "__main__":
    unittest.main()
