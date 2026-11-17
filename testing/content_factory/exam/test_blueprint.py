"""E2 blueprint: recency weighting, shares, structure, confidence."""

from __future__ import annotations

import copy
import unittest
from typing import Any

from factory.exam.blueprint import build_blueprint, recency_weights
from factory.exam.config import BlueprintPolicy
from factory.exam.errors import ExamGateError
from factory.exam.ingest import run_stage as ingest_run
from factory.exam.syllabus import chapters_for_class, load_syllabus
from testing.content_factory.exam.support import REPO_ROOT, temp_exam_config

SYLLABUS = REPO_ROOT / "sources" / "syllabus" / "syllabus.json"


def rules(report: dict) -> set[str]:
    return {issue["rule"] for issue in report["issues"]}


class BlueprintTestBase(unittest.TestCase):
    cfg: Any
    ingest: dict[str, Any]
    syllabus: dict[str, Any]
    _handle: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg, handle = temp_exam_config()
        cls._handle = handle
        cls.ingest = ingest_run(cls.cfg)
        cls.syllabus = load_syllabus(SYLLABUS)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._handle.cleanup()

    def blueprint(self, class_num: int, policy: BlueprintPolicy | None = None):
        return build_blueprint(
            self.ingest,
            class_num=class_num,
            chapters=chapters_for_class(self.syllabus, class_num),
            policy=policy or self.cfg.blueprint,
        )


class RecencyTests(BlueprintTestBase):
    def test_weights_follow_the_decay(self) -> None:
        weights = recency_weights([2022, 2023, 2024], decay=0.8, latest_year=2024)
        self.assertEqual(weights[2024], 1.0)
        self.assertEqual(weights[2023], 0.8)
        self.assertEqual(weights[2022], 0.64)

    def test_the_blueprint_weights_the_latest_paper_at_one(self) -> None:
        bp = self.blueprint(12)
        weights = bp["recency"]["weights"]
        self.assertEqual(weights["2026"], 1.0)
        self.assertAlmostEqual(weights["2022"], 0.8**4, places=6)
        self.assertEqual(
            bp["window"], {"start_year": 2022, "end_year": 2026, "years": 5}
        )

    def test_compartment_papers_are_ingested_but_not_weighted(self) -> None:
        bp = self.blueprint(12)
        self.assertNotIn("cbse-c12-physics-2024-compartment", bp["papers_used"])
        self.assertIn("cbse-c12-physics-2024-main", bp["papers_used"])
        self.assertIn("cbse-c12-physics-2026-sample", bp["papers_used"])
        self.assertEqual(len(bp["papers_used"]), 6)


class ShareTests(BlueprintTestBase):
    def test_chapter_shares_sum_to_one_and_cover_the_syllabus(self) -> None:
        for class_num, expected_chapters in ((10, 4), (12, 14)):
            with self.subTest(class_num=class_num):
                bp = self.blueprint(class_num)
                self.assertEqual(len(bp["chapters"]), expected_chapters)
                self.assertAlmostEqual(
                    sum(row["share"] for row in bp["chapters"]), 1.0, places=6
                )
                for row in bp["chapters"]:
                    self.assertEqual(row["papers_observed"], 6)

    def test_weighted_marks_are_recomputable_from_the_inputs(self) -> None:
        bp = self.blueprint(12)
        weights = {
            int(year): weight for year, weight in bp["recency"]["weights"].items()
        }
        papers = {
            paper["paper_id"]: paper
            for paper in self.ingest["papers"]
            if paper["paper_id"] in set(bp["papers_used"])
        }
        expected: dict[str, float] = {row["chapter_id"]: 0.0 for row in bp["chapters"]}
        for question in self.ingest["questions"]:
            if question["paper_id"] not in papers:
                continue
            year = int(papers[question["paper_id"]]["year"])
            expected[question["chapter_id"]] += question["marks"] * weights[year]
        for row in bp["chapters"]:
            self.assertAlmostEqual(
                row["weighted_marks"], round(expected[row["chapter_id"]], 3), places=3
            )

    def test_type_mix_covers_every_observed_type(self) -> None:
        bp = self.blueprint(12)
        types = {row["type"] for row in bp["type_mix"]}
        self.assertEqual(
            types,
            {"mcq", "assertion_reason", "very_short", "short", "case_based", "long"},
        )
        self.assertAlmostEqual(
            sum(row["share"] for row in bp["type_mix"]), 1.0, places=6
        )

    def test_archetypes_are_ranked_and_sum_to_one(self) -> None:
        bp = self.blueprint(12)
        shares = [row["share"] for row in bp["archetypes"]]
        self.assertAlmostEqual(sum(shares), 1.0, places=6)
        self.assertEqual(shares, sorted(shares, reverse=True))
        for row in bp["archetypes"]:
            self.assertEqual(
                row["archetype_id"],
                f"{row['chapter_id']}:{row['type']}:{row['marks']}",
            )

    def test_section_template_matches_the_latest_paper(self) -> None:
        bp = self.blueprint(12)
        self.assertEqual(
            [
                (row["id"], row["question_count"], row["marks_each"])
                for row in bp["section_template"]
            ],
            [("A", 16, 1), ("B", 5, 2), ("C", 7, 3), ("D", 2, 4), ("E", 3, 5)],
        )
        self.assertEqual(sum(row["marks_total"] for row in bp["section_template"]), 70)
        class_10 = self.blueprint(10)
        self.assertEqual(
            sum(row["marks_total"] for row in class_10["section_template"]), 27
        )

    def test_confidence_is_honest_about_the_question_map(self) -> None:
        bp = self.blueprint(12)
        self.assertEqual(bp["confidence"]["verified_papers"], 0)
        self.assertEqual(bp["confidence"]["unverified_papers"], 6)
        self.assertEqual(bp["confidence"]["question_map_basis"], "authored_estimate")
        self.assertIn("blueprint.confidence", rules(bp["gate"]))


class WindowTests(BlueprintTestBase):
    def test_a_short_window_drops_older_papers(self) -> None:
        bp = self.blueprint(
            12,
            policy=BlueprintPolicy(
                years_window=3,
                recency_decay=0.8,
                include_paper_types=("main", "sample"),
            ),
        )
        self.assertEqual(bp["window"]["start_year"], 2024)
        self.assertNotIn("cbse-c12-physics-2022-main", bp["papers_used"])
        self.assertNotIn("cbse-c12-physics-2023-main", bp["papers_used"])

    def test_excluding_sample_papers_changes_the_inputs(self) -> None:
        bp = self.blueprint(
            12,
            policy=BlueprintPolicy(
                years_window=5, recency_decay=0.8, include_paper_types=("main",)
            ),
        )
        self.assertNotIn("cbse-c12-physics-2026-sample", bp["papers_used"])
        self.assertEqual(len(bp["papers_used"]), 5)


class UncoveredChapterTests(BlueprintTestBase):
    def test_a_chapter_with_no_marks_is_a_major_gap(self) -> None:
        ingest = copy.deepcopy(self.ingest)
        chapter = "class-12-electromagnetic-waves"
        # Move every question of the chapter onto another chapter without
        # touching the paper totals: the gate must notice the chapter is gone.
        for question in ingest["questions"]:
            if question["chapter_id"] == chapter:
                question["chapter_id"] = "class-12-atoms"
        with self.assertRaises(ExamGateError) as ctx:
            build_blueprint(
                ingest,
                class_num=12,
                chapters=chapters_for_class(self.syllabus, 12),
                policy=self.cfg.blueprint,
            )
        self.assertIn("blueprint.chapter_uncovered", rules(ctx.exception.report))


class EmptyInputTests(BlueprintTestBase):
    def test_no_papers_is_refused(self) -> None:
        from factory.exam.errors import ExamStageError

        with self.assertRaises(ExamStageError):
            build_blueprint(
                {"papers": [], "questions": []},
                class_num=12,
                chapters=chapters_for_class(self.syllabus, 12),
                policy=self.cfg.blueprint,
            )


if __name__ == "__main__":
    unittest.main()
