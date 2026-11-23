"""E3 series: six manifests, item metadata, slot honesty, item rules."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from factory.exam.blueprint import build_blueprint
from factory.exam.ingest import run_stage as ingest_run
from factory.exam.syllabus import chapters_for_class, load_syllabus
from factory.exam.validators import validate_item, validate_series_manifest
from factory.series import SERIES_ORDER
from factory.series.assembly import (
    allocate_chapters,
    assemble_class,
    build_slot_plan,
    fill_slots,
)
from testing.content_factory.exam.support import REPO_ROOT, temp_exam_config

SYLLABUS = REPO_ROOT / "sources" / "syllabus" / "syllabus.json"


class SeriesTestBase(unittest.TestCase):
    cfg: Any
    syllabus: dict[str, Any]
    chapters: list[dict[str, Any]]
    ingest: dict[str, Any]
    blueprint: dict[str, Any]
    result: dict[str, Any]
    series: dict[str, Any]
    items: dict[str, Any]
    _handle: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg, handle = temp_exam_config()
        cls._handle = handle
        cls.syllabus = load_syllabus(SYLLABUS)
        cls.chapters = chapters_for_class(cls.syllabus, 10)
        cls.ingest = ingest_run(cls.cfg)
        cls.blueprint = build_blueprint(
            cls.ingest, class_num=10, chapters=cls.chapters, policy=cls.cfg.blueprint
        )
        cls.result = assemble_class(
            cls.cfg,
            blueprint=cls.blueprint,
            ingest=cls.ingest,
            chapters=cls.chapters,
            generated_at="2026-11-17T00:00:00+00:00",
        )
        cls.series = {s["series_id"]: s for s in cls.result["series"]}
        cls.items = {item["item_id"]: item for item in cls.result["items"]}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._handle.cleanup()


class ManifestTests(SeriesTestBase):
    def test_all_six_series_exist_in_the_product_order(self) -> None:
        self.assertEqual(
            [s["series_id"] for s in self.result["series"]], list(SERIES_ORDER)
        )

    def test_exact_pyq_is_dark_with_a_reason(self) -> None:
        exact = self.series["exact_pyq"]
        self.assertEqual(exact["status"], "disabled")
        self.assertFalse(exact["enabled"])
        self.assertEqual(exact["disabled_reason"], "no_verbatim_clearance")
        self.assertIsNone(exact["notice_id"])
        self.assertEqual(exact["item_ids"], [])

    def test_every_active_series_carries_n01_and_approved_copy(self) -> None:
        for manifest in self.result["series"]:
            if not manifest["enabled"]:
                continue
            with self.subTest(series=manifest["series_id"]):
                self.assertEqual(manifest["notice_id"], "N-01")
                self.assertTrue(manifest["copy"])
                self.assertIn("practice", manifest["copy"].lower())

    def test_language_policies_follow_the_feature_map(self) -> None:
        tri = {"ai_lesson", "challenge", "loop"}
        for manifest in self.result["series"]:
            expected = (
                ["en", "hi", "hi-Latn"]
                if manifest["series_id"] in tri
                else ["en", "hi"]
            )
            self.assertEqual(manifest["language_policy"], expected)

    def test_the_volume_gate_has_something_to_say(self) -> None:
        from factory.series.volume import check_volume

        volume = check_volume(
            class_num=10,
            blueprint=self.blueprint,
            chapters=self.chapters,
            series=self.result["series"],
            items=self.result["items"],
            chapter_floor=self.cfg.series.chapter_question_floor,
        )
        rules = {issue.rule for issue in volume["issues"]}
        self.assertIn("series.minimum.challenge", rules)
        self.assertIn("series.chapter_floor", rules)
        self.assertIn("series.chapter_coverage", rules)
        self.assertIn("series.minimum.board_practice", rules)

    def test_series_manifests_carry_no_structurally_invalid_item(self) -> None:
        compliance = self.cfg.compliance.to_dict()
        for manifest in self.result["series"]:
            issues = validate_series_manifest(
                manifest, items_by_id=self.items, compliance=compliance
            )
            self.assertEqual(issues, [], manifest["series_id"])


class ItemMetadataTests(SeriesTestBase):
    def test_every_item_carries_source_metadata_and_a_similarity_record(self) -> None:
        self.assertTrue(self.items)
        for item in self.items.values():
            with self.subTest(item=item["item_id"]):
                self.assertEqual(item["source_type"], "generated_blueprint")
                self.assertTrue(item["pattern_ref"].count(":"))
                self.assertEqual(item["similarity"]["verdict"], "vacuously_clear")
                self.assertEqual(item["similarity"]["corpus_size"], 0)
                self.assertEqual(item["licence_basis"], "none")
                self.assertIsNone(item["source_ref"])
                self.assertTrue(item["series_ids"])
                self.assertIn("en", item["languages"])
                self.assertIn("hi", item["languages"])

    def test_items_are_traceable_to_the_assessment_bank(self) -> None:
        for item in self.items.values():
            self.assertEqual(item["item_id"], f"exam-{item['base_item_id']}")
            self.assertEqual(item["origin"], "assessment_bank")

    def test_a_verbatim_item_in_blueprint_mode_is_fatal(self) -> None:
        item = copy.deepcopy(next(iter(self.items.values())))
        item["source_type"] = "verbatim_cbse_paper"
        item["source_ref"] = {
            "source_url": "https://www.cbse.gov.in/x.pdf",
            "retrieved_at": "2026-11-17",
            "file_sha256": "0" * 64,
            "page": 3,
            "third_party_content": False,
        }
        issues = validate_item(
            item,
            series={"series_id": "board_practice", "language_policy": ["en", "hi"]},
            chapters=self.chapters,
            similarity_max_overlap=0.2,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.item.verbatim_in_blueprint", {i.rule for i in issues})
        self.assertIn("series.item.licence_basis", {i.rule for i in issues})

    def test_a_generated_item_without_a_pattern_ref_is_fatal(self) -> None:
        item = copy.deepcopy(next(iter(self.items.values())))
        item["pattern_ref"] = "   "
        issues = validate_item(
            item,
            series={
                "series_id": "ai_lesson",
                "language_policy": ["en", "hi", "hi-Latn"],
            },
            chapters=self.chapters,
            similarity_max_overlap=0.2,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.item.pattern_ref", {i.rule for i in issues})

    def test_a_similarity_breach_is_fatal(self) -> None:
        item = copy.deepcopy(next(iter(self.items.values())))
        item["similarity"] = {
            "max_ngram_overlap": 0.9,
            "nearest_source_item_id": "src-001",
        }
        issues = validate_item(
            item,
            series={
                "series_id": "ai_lesson",
                "language_policy": ["en", "hi", "hi-Latn"],
            },
            chapters=self.chapters,
            similarity_max_overlap=0.2,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.item.similarity", {i.rule for i in issues})

    def test_a_missing_similarity_record_is_fatal(self) -> None:
        item = copy.deepcopy(next(iter(self.items.values())))
        item["similarity"] = {}
        issues = validate_item(
            item,
            series={
                "series_id": "ai_lesson",
                "language_policy": ["en", "hi", "hi-Latn"],
            },
            chapters=self.chapters,
            similarity_max_overlap=0.2,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.item.similarity_missing", {i.rule for i in issues})

    def test_a_hindi_prompt_without_devanagari_is_fatal(self) -> None:
        item = copy.deepcopy(next(iter(self.items.values())))
        item["locales"]["hi"]["prompt"] = "English text pretending to be Hindi"
        issues = validate_item(
            item,
            series={
                "series_id": "ai_lesson",
                "language_policy": ["en", "hi", "hi-Latn"],
            },
            chapters=self.chapters,
            similarity_max_overlap=0.2,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.item.language", {i.rule for i in issues})

    def test_a_series_missing_a_promised_language_is_fatal(self) -> None:
        item = copy.deepcopy(next(iter(self.items.values())))
        item["languages"] = ["en"]
        item["locales"].pop("hi")
        issues = validate_item(
            item,
            series={"series_id": "board_practice", "language_policy": ["en", "hi"]},
            chapters=self.chapters,
            similarity_max_overlap=0.2,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.item.language", {i.rule for i in issues})


class SlotPlanTests(SeriesTestBase):
    def test_the_slot_plan_matches_the_latest_paper(self) -> None:
        slots = build_slot_plan(self.ingest, self.blueprint)
        self.assertEqual(len(slots), 14)
        self.assertEqual(sum(slot["marks"] for slot in slots), 27)
        sections = [slot["section"] for slot in slots]
        self.assertEqual(sections, sorted(sections), "sections must be A..E in order")

    def test_chapter_allocation_covers_every_weighted_chapter(self) -> None:
        slots = build_slot_plan(self.ingest, self.blueprint)
        allocation = allocate_chapters(slots, self.blueprint)
        self.assertEqual(len(allocation), len(slots))
        for row in self.blueprint["chapters"]:
            if float(row["share"]) > 0:
                self.assertIn(row["chapter_id"], allocation)

    def test_an_empty_slot_stays_empty_instead_of_borrowing_another_chapter(
        self,
    ) -> None:
        slots = [
            {"section": "A", "type": "mcq", "marks": 1},
            {"section": "A", "type": "mcq", "marks": 1},
        ]
        pool = [
            {
                "item_id": "i-1",
                "chapter_id": "chapter-a",
                "type": "mcq",
                "marks": 1,
            }
        ]
        chosen = fill_slots(slots, ["chapter-a", "chapter-b"], pool)
        self.assertIs(chosen[0], pool[0])
        self.assertIsNone(chosen[1], "an unfillable slot must not borrow a question")

    def test_a_slot_is_not_filled_by_the_wrong_type(self) -> None:
        slots = [{"section": "E", "type": "long", "marks": 5}]
        pool = [{"item_id": "i-1", "chapter_id": "c", "type": "mcq", "marks": 1}]
        self.assertEqual(fill_slots(slots, ["c"], pool), [None])

    def test_papers_do_not_repeat_an_item(self) -> None:
        for series_id in ("pyq_pattern", "board_practice"):
            for paper in self.series[series_id]["papers"]:
                ids = [slot["item_id"] for slot in paper["sections"] if slot["item_id"]]
                self.assertEqual(len(ids), len(set(ids)), paper["paper_id"])

    def test_the_prototype_gap_is_named_not_smoothed(self) -> None:
        board = self.series["board_practice"]
        self.assertEqual(board["papers"][0]["total_slots"], 14)
        self.assertLess(board["papers"][0]["filled_slots"], 14)
        self.assertGreater(board["gap"]["filled_slots"], 0)
        self.assertEqual(board["gap"]["full_papers"], 5)

    def test_the_remaining_class_10_chapter_is_reported_as_a_bank_gap(self) -> None:
        gaps = self.result["bank_gaps"]
        self.assertIn("class-10-magnetic-effects-of-electric-current", gaps)
        self.assertNotIn("class-10-electricity", gaps)
        self.assertNotIn("class-10-the-human-eye-and-the-colourful-world", gaps)
        self.assertNotIn("class-10-light-reflection-and-refraction", gaps)


class CopyGateTests(SeriesTestBase):
    def test_a_forbidden_claim_in_series_copy_is_fatal(self) -> None:
        manifest = copy.deepcopy(self.series["board_practice"])
        manifest["copy"] = "This is an official CBSE paper."
        issues = validate_series_manifest(
            manifest,
            items_by_id=self.items,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.copy.claim", {i.rule for i in issues})

    def test_a_disabled_series_with_no_notice_is_allowed(self) -> None:
        issues = validate_series_manifest(
            self.series["exact_pyq"],
            items_by_id=self.items,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertEqual(issues, [])

    def test_a_repeated_complete_paper_is_fatal(self) -> None:
        manifest = copy.deepcopy(self.series["board_practice"])
        first = manifest["papers"][0]
        first["filled_slots"] = first["total_slots"]
        second = copy.deepcopy(first)
        second["paper_id"] = "board-practice-p02"
        manifest["papers"] = [first, second]
        issues = validate_series_manifest(
            manifest,
            items_by_id=self.items,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.paper_duplicate", {i.rule for i in issues})

    def test_two_honestly_incomplete_papers_are_not_duplicates(self) -> None:
        manifest = copy.deepcopy(self.series["board_practice"])
        for paper in manifest["papers"]:
            paper["filled_slots"] = 0
            paper["item_ids"] = []
            for slot in paper["sections"]:
                slot["item_id"] = None
        issues = validate_series_manifest(
            manifest,
            items_by_id=self.items,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertNotIn("series.paper_duplicate", {i.rule for i in issues})

    def test_an_enabled_series_without_a_notice_is_fatal(self) -> None:
        manifest = copy.deepcopy(self.series["ai_lesson"])
        manifest["notice_id"] = None
        issues = validate_series_manifest(
            manifest,
            items_by_id=self.items,
            compliance=self.cfg.compliance.to_dict(),
        )
        self.assertIn("series.copy.notice", {i.rule for i in issues})


if __name__ == "__main__":
    unittest.main()
