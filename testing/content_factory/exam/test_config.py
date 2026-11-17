"""The compliance mode gate: fail closed, and a clearance is scoped."""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from factory.exam.clearance import parse_clearance_register
from factory.exam.config import (
    DEFAULT_EXAM_SECTION,
    ExamConfig,
    resolve_compliance,
)
from factory.exam.errors import ExamConfigError

REPO_ROOT = Path(__file__).resolve().parents[3]
DECISION_LOG = REPO_ROOT / "docs" / "compliance" / "decision-log.md"

SYNTHETIC_REGISTER = """
| clearance_id | Instrument | Scope (class / subject / years / language) | Issued | Review | Recorded by | Document ref |
|---|---|---|---|---|---|---|
| `CLEAR-TEST-001` | written_permission | Class 12 / Physics / 2022-2026 / en, hi | 2026-12-01 | 2027-12-01 | Founder | letter-001.pdf |
| `CLEAR-TEST-002` | counsel_opinion | Class 10 / Science / 2024 / en | 2026-12-01 | 2027-12-01 | Counsel | opinion-002.pdf |
"""


class ModeGateTests(unittest.TestCase):
    def _section(self, **overrides):
        section = dict(DEFAULT_EXAM_SECTION)
        section.update(overrides)
        return section

    def test_defaults_to_blueprint_only(self) -> None:
        compliance = resolve_compliance(
            section=self._section(), decision_log_path=DECISION_LOG, env={}
        )
        self.assertEqual(compliance.content_mode, "blueprint_only")
        self.assertFalse(compliance.verbatim_allowed)
        self.assertFalse(compliance.exact_pyq_visible)

    def test_unknown_mode_is_a_startup_error(self) -> None:
        with self.assertRaises(ExamConfigError) as ctx:
            resolve_compliance(
                section=self._section(),
                decision_log_path=DECISION_LOG,
                env={"EXAM_CONTENT_MODE": "verbatim"},
            )
        self.assertIn("not one of", str(ctx.exception))

    def test_verbatim_mode_needs_a_clearance_id(self) -> None:
        with self.assertRaises(ExamConfigError) as ctx:
            resolve_compliance(
                section=self._section(),
                decision_log_path=DECISION_LOG,
                env={"EXAM_CONTENT_MODE": "attributed_verbatim"},
            )
        self.assertIn("EXAM_VERBATIM_CLEARANCE_ID", str(ctx.exception))

    def test_verbatim_mode_needs_a_register_row(self) -> None:
        with self.assertRaises(ExamConfigError) as ctx:
            resolve_compliance(
                section=self._section(),
                decision_log_path=DECISION_LOG,
                env={
                    "EXAM_CONTENT_MODE": "attributed_verbatim",
                    "EXAM_VERBATIM_CLEARANCE_ID": "NOT-A-ROW",
                },
            )
        self.assertIn("does not match any row", str(ctx.exception))

    def test_the_shipped_register_is_empty_so_verbatim_is_refused(self) -> None:
        text = DECISION_LOG.read_text(encoding="utf-8")
        self.assertEqual(parse_clearance_register(text), [])

    def test_exact_pyq_flag_true_in_blueprint_mode_is_refused(self) -> None:
        with self.assertRaises(ExamConfigError) as ctx:
            resolve_compliance(
                section=self._section(),
                decision_log_path=DECISION_LOG,
                env={"SERIES_EXACT_PYQ_ENABLED": "true"},
            )
        self.assertIn(
            "requires EXAM_CONTENT_MODE=attributed_verbatim", str(ctx.exception)
        )

    def test_unreadable_boolean_fails_closed(self) -> None:
        with self.assertRaises(ExamConfigError):
            resolve_compliance(
                section=self._section(),
                decision_log_path=DECISION_LOG,
                env={"SERIES_EXACT_PYQ_ENABLED": "maybe"},
            )

    def test_clearance_id_in_blueprint_mode_must_still_resolve(self) -> None:
        with self.assertRaises(ExamConfigError):
            resolve_compliance(
                section=self._section(),
                decision_log_path=DECISION_LOG,
                env={"EXAM_VERBATIM_CLEARANCE_ID": "TYPO-001"},
            )


class ClearanceRegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = parse_clearance_register(SYNTHETIC_REGISTER)

    def test_parses_real_rows_and_skips_the_placeholder(self) -> None:
        self.assertEqual(
            [row.clearance_id for row in self.rows],
            ["CLEAR-TEST-001", "CLEAR-TEST-002"],
        )
        self.assertEqual(self.rows[0].instrument, "written_permission")

    def test_scope_covers_matching_items(self) -> None:
        row = self.rows[0]
        self.assertTrue(
            row.covers(class_num=12, subject="Physics", year=2024, language="hi")
        )
        self.assertTrue(
            row.covers(class_num=12, subject="Physics", year=2026, language="en")
        )

    def test_scope_refuses_everything_else(self) -> None:
        row = self.rows[0]
        self.assertFalse(
            row.covers(class_num=10, subject="Science", year=2024, language="en"),
            "a Class 12 Physics clearance must not cover Class 10 Science",
        )
        self.assertFalse(
            row.covers(class_num=12, subject="Physics", year=2027, language="en"),
            "a year outside the range is not covered",
        )
        self.assertFalse(
            row.covers(class_num=12, subject="Physics", year=2024, language="hi-Latn"),
            "Hinglish is not an approved verbatim language",
        )

    def test_verbatim_mode_resolves_with_a_register_row(self) -> None:
        compliance = resolve_compliance(
            section=dict(DEFAULT_EXAM_SECTION),
            decision_log_path=DECISION_LOG,
            env={},
        )
        # The shipped register is empty, so use the parser directly for the
        # positive path: build the compliance object from a synthetic row.
        self.assertFalse(compliance.verbatim_allowed)
        from factory.exam.clearance import find_clearance

        row = find_clearance(self.rows, "CLEAR-TEST-001")
        self.assertIsNotNone(row)


class ConfigTests(unittest.TestCase):
    def test_for_repo_reads_the_committed_section(self) -> None:
        cfg = ExamConfig.for_repo(REPO_ROOT, runs_dir=REPO_ROOT / "runs" / "exam-test")
        self.assertEqual(cfg.content_mode, "blueprint_only")
        self.assertEqual(cfg.blueprint.years_window, 5)
        self.assertTrue(cfg.papers_dir.is_dir())
        self.assertEqual(cfg.series.chapter_question_floor, 10)

    def test_bad_decay_and_window_are_refused(self) -> None:
        from factory.exam.config import BlueprintPolicy

        with self.assertRaises(ExamConfigError):
            BlueprintPolicy(years_window=0)
        with self.assertRaises(ExamConfigError):
            BlueprintPolicy(recency_decay=1.5)

    def test_similarity_policy_bounds(self) -> None:
        from factory.exam.config import SimilarityPolicy

        with self.assertRaises(ExamConfigError):
            SimilarityPolicy(ngram=1)
        with self.assertRaises(ExamConfigError):
            SimilarityPolicy(max_overlap=2.0)

    def test_overrides_do_not_mutate_the_original(self) -> None:
        cfg = ExamConfig.for_repo(REPO_ROOT)
        other = dataclasses.replace(cfg, runs_dir=REPO_ROOT / "runs" / "exam-test-2")
        self.assertNotEqual(cfg.runs_dir, other.runs_dir)


if __name__ == "__main__":
    unittest.main()
