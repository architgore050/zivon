"""A1-syllabus: four-class map integrity, honest weights, resolving prerequisites."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from factory.assessment import syllabus as syllabus_stage
from factory.assessment.config import AssessmentConfig, catalog_book_ids
from factory.assessment.errors import AssessmentStageError
from factory.assessment.validators import (
    gate_report,
    validate_syllabus,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


class SyllabusTestBase(unittest.TestCase):
    cfg: AssessmentConfig
    syllabus: dict
    book_ids: set[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AssessmentConfig.for_repo(REPO_ROOT)
        cls.syllabus = json.loads(cls.cfg.syllabus_path.read_text(encoding="utf-8"))
        cls.book_ids = catalog_book_ids(cls.cfg.catalog_path)

    def validate(self, syllabus: dict) -> list:
        return validate_syllabus(syllabus, catalog_book_ids=self.book_ids)

    def rules(self, syllabus: dict) -> set[str]:
        return {issue.rule for issue in self.validate(syllabus)}


class TestShippedSyllabus(SyllabusTestBase):
    def test_shipped_syllabus_passes_its_gate(self) -> None:
        report = gate_report(self.validate(self.syllabus))
        self.assertEqual(report["verdict"], "pass", report["issues"])

    def test_covers_classes_9_to_12_once(self) -> None:
        self.assertEqual(
            [entry["class"] for entry in self.syllabus["classes"]], [9, 10, 11, 12]
        )

    def test_chapter_and_concept_counts_are_pinned(self) -> None:
        # Deliberate pins: a content change that adds/removes a chapter or a
        # curated concept must update this test and the docs in the same PR.
        chapters = sum(len(entry["chapters"]) for entry in self.syllabus["classes"])
        concepts = sum(
            len(chapter["concepts"])
            for entry in self.syllabus["classes"]
            for chapter in entry["chapters"]
        )
        curated = [
            chapter
            for entry in self.syllabus["classes"]
            for chapter in entry["chapters"]
            if chapter["concepts_status"] == "curated"
        ]
        self.assertEqual(chapters, 36)
        self.assertEqual(concepts, 49)
        self.assertEqual(len(curated), 8)

    def test_every_chapter_has_contiguous_order_and_unique_number(self) -> None:
        for entry in self.syllabus["classes"]:
            numbers = [c["number"] for c in entry["chapters"]]
            orders = [c["order"] for c in entry["chapters"]]
            self.assertEqual(len(numbers), len(set(numbers)), entry)
            self.assertEqual(orders, list(range(1, len(orders) + 1)))

    def test_exam_weight_is_absent_until_p3_owns_it(self) -> None:
        for entry in self.syllabus["classes"]:
            for chapter in entry["chapters"]:
                self.assertIsNone(chapter["exam_weight"], chapter["chapter_id"])
                self.assertEqual(chapter["exam_weight_status"], "pending_p3_blueprint")

    def test_class_11_and_12_concepts_are_explicitly_pending(self) -> None:
        for entry in self.syllabus["classes"]:
            if entry["class"] not in (11, 12):
                continue
            for chapter in entry["chapters"]:
                self.assertEqual(chapter["concepts_status"], "pending_r1_5")
                self.assertEqual(chapter["concepts"], [])

    def test_every_curated_concept_is_unique_and_chapter_scoped(self) -> None:
        seen: set[str] = set()
        for entry in self.syllabus["classes"]:
            for chapter in entry["chapters"]:
                for concept in chapter["concepts"]:
                    self.assertNotIn(concept["concept_id"], seen)
                    seen.add(concept["concept_id"])
                    self.assertTrue(
                        concept["concept_id"].startswith(chapter["chapter_id"] + "-")
                    )

    def test_lesson_topic_slugs_match_the_published_tree(self) -> None:
        published = []
        for entry in self.syllabus["classes"]:
            for chapter in entry["chapters"]:
                slug = chapter["lesson_topic_slug"]
                if slug is None:
                    continue
                manifest = (
                    REPO_ROOT
                    / "frontend"
                    / "courses"
                    / f"class-{chapter['class']}-physics"
                    / slug
                    / "manifest.json"
                )
                self.assertTrue(manifest.is_file(), manifest)
                published.append(chapter["chapter_id"])
        self.assertEqual(
            published,
            [
                "class-9-describing-motion-around-us",
                "class-9-how-forces-affect-motion",
                "class-11-units-and-measurement",
                "class-11-motion-in-a-straight-line",
                "class-11-motion-in-a-plane",
                "class-11-laws-of-motion",
            ],
        )


class TestSyllabusRuleFailures(SyllabusTestBase):
    def test_duplicate_chapter_id_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][1]["chapter_id"] = broken["classes"][0][
            "chapters"
        ][0]["chapter_id"]
        self.assertIn("syllabus.chapter_duplicate", self.rules(broken))

    def test_unknown_prerequisite_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][0]["concepts"][1]["prerequisites"] = [
            "class-9-not-a-concept"
        ]
        self.assertIn("syllabus.prerequisite_unknown", self.rules(broken))

    def test_self_prerequisite_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        concept = broken["classes"][0]["chapters"][0]["concepts"][0]
        concept["prerequisites"] = [concept["concept_id"]]
        self.assertIn("syllabus.prerequisite_self", self.rules(broken))

    def test_curated_chapter_without_concepts_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][0]["concepts"] = []
        self.assertIn("syllabus.concepts_thin", self.rules(broken))

    def test_weight_set_while_pending_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][0]["exam_weight"] = 0.2
        self.assertIn("syllabus.exam_weight", self.rules(broken))

    def test_section_ref_outside_chapter_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][0]["concepts"][0]["section_refs"] = ["9.1"]
        self.assertIn("syllabus.section_ref", self.rules(broken))

    def test_unknown_catalog_book_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][0]["book_id"] = "not-a-book"
        self.assertIn("syllabus.book_unknown", self.rules(broken))

    def test_non_contiguous_order_fails(self) -> None:
        broken = copy.deepcopy(self.syllabus)
        broken["classes"][0]["chapters"][1]["order"] = 9
        self.assertIn("syllabus.chapter_order", self.rules(broken))


class TestSyllabusLoader(SyllabusTestBase):
    def test_run_stage_writes_a_digest_and_gate(self) -> None:
        output = syllabus_stage.run_stage(self.cfg)
        self.assertEqual(output["gate"]["verdict"], "pass")
        self.assertRegex(output["syllabus_sha256"], "^[0-9a-f]{64}$")
        self.assertEqual(output["counts"]["chapters"], 36)

    def test_missing_syllabus_raises_with_the_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = AssessmentConfig.for_repo(REPO_ROOT)
            cfg = cfg.with_overrides(runs_dir=Path(td))
            cfg = type(cfg)(
                repo_root=cfg.repo_root,
                runs_dir=cfg.runs_dir,
                syllabus_path=Path(td) / "missing.json",
                chapters_dir=cfg.chapters_dir,
                frontend_dir=cfg.frontend_dir,
                catalog_path=cfg.catalog_path,
                generator=cfg.generator,
                languages=cfg.languages,
                policy=cfg.policy,
                repair_rounds=cfg.repair_rounds,
            )
            with self.assertRaises(AssessmentStageError):
                syllabus_stage.load_syllabus(cfg)

    def test_unknown_chapter_lists_valid_ids(self) -> None:
        with self.assertRaises(AssessmentStageError) as ctx:
            syllabus_stage.require_chapter(self.syllabus, "class-9-nope")
        self.assertIn("class-9-describing-motion-around-us", str(ctx.exception))

    def test_pending_chapter_refuses_practice(self) -> None:
        chapter = syllabus_stage.require_chapter(
            self.syllabus, "class-11-motion-in-a-straight-line"
        )
        with self.assertRaises(AssessmentStageError):
            syllabus_stage.require_curated(chapter)


if __name__ == "__main__":
    unittest.main()
