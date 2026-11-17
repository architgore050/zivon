"""The volume/coverage gate: honest on real data, proven on a full syllabus.

Two directions matter and both are tested:

- the shipped prototype (two chapters with item banks) **fails** the gate, and
  the failure names the missing chapters and series instead of hiding them;
- a full-syllabus synthetic pool **passes** the same gate, so the gate is not
  an impossible bar - it is a real one that the content backlog has to meet.
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path
from typing import Any

from factory.exam.blueprint import build_blueprint
from factory.exam.ingest import run_stage as ingest_run
from factory.exam.syllabus import chapters_for_class, load_syllabus
from factory.series.assembly import assemble_class
from factory.series.publish import assemble_pack
from factory.series.volume import check_volume
from testing.content_factory.exam.support import (
    REPO_ROOT,
    temp_exam_config,
    write_synthetic_banks,
)

SYLLABUS = REPO_ROOT / "sources" / "syllabus" / "syllabus.json"
GENERATED_AT = "2026-11-17T00:00:00+00:00"


class RealDataTestBase(unittest.TestCase):
    cfg: Any
    syllabus: dict[str, Any]
    ingest: dict[str, Any]
    _handle: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg, handle = temp_exam_config()
        cls._handle = handle
        cls.syllabus = load_syllabus(SYLLABUS)
        cls.ingest = ingest_run(cls.cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._handle.cleanup()

    def assembled(self, class_num: int) -> tuple[dict, dict, dict]:
        chapters = chapters_for_class(self.syllabus, class_num)
        blueprint = build_blueprint(
            self.ingest,
            class_num=class_num,
            chapters=chapters,
            policy=self.cfg.blueprint,
        )
        series = assemble_class(
            self.cfg,
            blueprint=blueprint,
            ingest=self.ingest,
            chapters=chapters,
            generated_at=GENERATED_AT,
        )
        pack = assemble_pack(
            cfg=self.cfg,
            blueprint=blueprint,
            ingest=self.ingest,
            class_series=series,
            chapters=chapters,
            run_id=f"exam-class-{class_num}",
            generated_at=GENERATED_AT,
        )
        return blueprint, series, pack


class RealClass10Tests(RealDataTestBase):
    def test_the_prototype_is_blocked_and_the_blockers_are_named(self) -> None:
        _blueprint, _series, pack = self.assembled(10)
        manifest = pack["manifest"]
        self.assertEqual(manifest["publish"]["status"], "blocked")
        self.assertIn("volume", manifest["publish"]["reason_codes"])
        rules = {blocker["rule"] for blocker in manifest["publish"]["blockers"]}
        self.assertIn("series.minimum.ai_lesson", rules)
        self.assertIn("series.minimum.pyq_pattern", rules)
        self.assertIn("series.minimum.board_practice", rules)
        self.assertIn("series.minimum.challenge", rules)
        self.assertIn("series.minimum.loop", rules)
        self.assertIn("series.chapter_floor", rules)
        self.assertIn("series.chapter_coverage", rules)
        self.assertNotIn(
            "series.minimum.exact_pyq",
            rules,
            "the dark series is excluded from the minimum check, not failed",
        )

    def test_the_three_uncharted_chapters_are_the_named_gap(self) -> None:
        _blueprint, _series, pack = self.assembled(10)
        floor = {
            blocker["chapter_id"]
            for blocker in pack["manifest"]["publish"]["blockers"]
            if blocker["rule"] == "series.chapter_floor"
        }
        self.assertEqual(
            floor,
            {
                "class-10-the-human-eye-and-the-colourful-world",
                "class-10-electricity",
                "class-10-magnetic-effects-of-electric-current",
            },
        )

    def test_the_coverage_table_reports_zero_for_uncharted_chapters(self) -> None:
        _, _, pack = self.assembled(10)
        chapters = pack["manifest"]["coverage"]["chapters"]
        self.assertEqual(len(chapters["class-10-electricity"]), 0)
        self.assertGreater(
            chapters["class-10-light-reflection-and-refraction"].get("ai_lesson", 0), 0
        )

    def test_the_dark_series_is_recorded_as_disabled(self) -> None:
        _, series, pack = self.assembled(10)
        exact = next(s for s in series["series"] if s["series_id"] == "exact_pyq")
        self.assertEqual(exact["status"], "disabled")
        self.assertEqual(
            pack["manifest"]["compliance"]["exact_pyq_status"],
            "disabled:no_verbatim_clearance",
        )

    def test_a_blocked_pack_refuses_to_mirror(self) -> None:
        _, _, pack = self.assembled(10)
        self.assertEqual(pack["manifest"]["publish"]["status"], "blocked")
        # `run_stage` mirrors only a ready pack; assembly itself never writes.
        self.assertFalse(pack["manifest"]["compliance"]["exact_pyq_visible"])


class RealClass12Tests(RealDataTestBase):
    def test_class_12_has_no_item_banks_and_says_so(self) -> None:
        _blueprint, series, pack = self.assembled(12)
        self.assertEqual(pack["manifest"]["counts"]["base_items"], 0)
        self.assertEqual(pack["manifest"]["counts"]["question_rows"], 0)
        floor = {blocker["rule"] for blocker in pack["manifest"]["publish"]["blockers"]}
        self.assertIn("series.chapter_floor", floor)
        self.assertEqual(
            len(series["bank_gaps"]), len(chapters_for_class(self.syllabus, 12))
        )


class StructuralGateTests(RealDataTestBase):
    def test_a_dropped_section_is_a_fatal_structure_finding(self) -> None:
        blueprint, series, _ = self.assembled(10)
        broken_blueprint = dict(blueprint)
        broken_blueprint["section_template"] = [
            row for row in blueprint["section_template"] if row["id"] != "E"
        ]
        volume = check_volume(
            class_num=10,
            blueprint=broken_blueprint,
            chapters=chapters_for_class(self.syllabus, 10),
            series=series["series"],
            items=series["items"],
            chapter_floor=self.cfg.series.chapter_question_floor,
        )
        self.assertIn(
            "series.paper_structure", {issue.rule for issue in volume["issues"]}
        )

    def test_an_impossible_floor_fires_for_every_chapter(self) -> None:
        blueprint, series, _ = self.assembled(10)
        volume = check_volume(
            class_num=10,
            blueprint=blueprint,
            chapters=chapters_for_class(self.syllabus, 10),
            series=series["series"],
            items=series["items"],
            chapter_floor=10_000,
        )
        floor_issues = [i for i in volume["issues"] if i.rule == "series.chapter_floor"]
        self.assertEqual(len(floor_issues), 4)


class FullSyllabusFixtureTests(unittest.TestCase):
    """The gate must pass when the volume is real. Build real volume to prove it."""

    def _pack(self, class_num: int, per_chapter: int) -> dict:
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        root = Path(handle.name)
        chapters = chapters_for_class(load_syllabus(SYLLABUS), class_num)
        banks_dir = root / "chapters"
        write_synthetic_banks(banks_dir, chapters, per_chapter=per_chapter)
        cfg, cfg_handle = temp_exam_config(root)
        self.addCleanup(cfg_handle.cleanup)
        cfg = dataclasses.replace(cfg, chapters_dir=banks_dir)
        ingest = ingest_run(cfg)
        blueprint = build_blueprint(
            ingest, class_num=class_num, chapters=chapters, policy=cfg.blueprint
        )
        series = assemble_class(
            cfg,
            blueprint=blueprint,
            ingest=ingest,
            chapters=chapters,
            generated_at=GENERATED_AT,
        )
        return assemble_pack(
            cfg=cfg,
            blueprint=blueprint,
            ingest=ingest,
            class_series=series,
            chapters=chapters,
            run_id=f"exam-class-{class_num}",
            generated_at=GENERATED_AT,
        )

    def test_class_10_full_syllabus_is_publishable(self) -> None:
        pack = self._pack(10, per_chapter=70)
        manifest = pack["manifest"]
        blockers = manifest["publish"]["blockers"]
        self.assertEqual(
            manifest["publish"]["status"],
            "ready",
            msg="\n".join(f"{b['rule']}: {b['message']}" for b in blockers[:8]),
        )
        self.assertEqual(manifest["counts"]["series"], 6)
        self.assertGreater(manifest["counts"]["question_rows"], 0)
        self.assertEqual(manifest["compliance"]["verbatim_items"], 0)

    def test_class_12_full_syllabus_is_publishable(self) -> None:
        pack = self._pack(12, per_chapter=20)
        manifest = pack["manifest"]
        blockers = manifest["publish"]["blockers"]
        self.assertEqual(
            manifest["publish"]["status"],
            "ready",
            msg="\n".join(f"{b['rule']}: {b['message']}" for b in blockers[:8]),
        )
        board = next(
            s
            for s in pack["payloads"]["series.json"]["series"]
            if s["series_id"] == "board_practice"
        )
        self.assertEqual(board["delivered"]["full_papers"], 5)
        self.assertEqual(board["papers"][0]["total_slots"], 33)

    def test_five_full_papers_are_five_different_papers(self) -> None:
        for class_num, per_chapter in ((10, 70), (12, 20)):
            pack = self._pack(class_num, per_chapter=per_chapter)
            for manifest_row in pack["payloads"]["series.json"]["series"]:
                complete = [
                    tuple(sorted(paper["item_ids"]))
                    for paper in manifest_row["papers"]
                    if paper["filled_slots"] == paper["total_slots"]
                ]
                with self.subTest(
                    class_num=class_num, series=manifest_row["series_id"]
                ):
                    self.assertEqual(
                        len(complete),
                        len(set(complete)),
                        "a complete paper is repeated; the volume gate would count "
                        "one paper as several",
                    )


if __name__ == "__main__":
    unittest.main()
