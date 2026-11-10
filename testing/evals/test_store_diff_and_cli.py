"""Unit tests for `evals/store.py`, `evals/diff.py`, `evals/migrations/`, and `evals/cli.py`."""

from __future__ import annotations

import dataclasses
import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from evals.cli import main as cli_main
from evals.config import EvalConfig
from evals.diff import compute_run_diff

mig_0001 = importlib.import_module("evals.migrations.versions.0001_eval_result_store")
from evals.models import load_all_cards
from evals.runner import run_eval_suite
from evals.store import EvalStore, generate_uuid7, validate_kid_session_dpdp


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql.strip())


class TestStoreDiffAndCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-eval-test-"))
        self.db_path = self.tmp / "evals.sqlite"
        self.cfg = EvalConfig.from_env(
            {
                "ZIVON_EVAL_RUNS_DIR": str(self.tmp / "evals_runs"),
                "ZIVON_DB_URL": f"sqlite:///{self.db_path}",
                "ZIVON_EVAL_STORE_BACKEND": "dual",
                "EVAL_MOCK_MODE": "1",
            }
        )

    def test_uuidv7_is_monotonic_and_rfc9562_version_7(self) -> None:
        u1 = generate_uuid7(1700000000000)
        u2 = generate_uuid7(1700000000001)
        self.assertLess(u1, u2)
        self.assertEqual(u1[14], "7")

    def test_dual_write_store_and_idempotent_backfill(self) -> None:
        report = run_eval_suite(self.cfg, suite="calibrate")
        self.assertTrue(report.overall_pass)
        self.assertTrue(self.db_path.is_file())

        store = EvalStore(self.cfg)
        counts1 = store.backfill_db()
        counts2 = store.backfill_db()
        self.assertEqual(counts1, counts2)
        self.assertEqual(counts1["runs"], 1)
        self.assertEqual(counts1["card_results"], 2)
        self.assertEqual(counts1["defect_samples"], 14)

        with sqlite3.connect(self.db_path) as conn:
            run_rows = conn.execute("SELECT COUNT(*) FROM eval_run").fetchone()[0]
            card_rows = conn.execute(
                "SELECT COUNT(*) FROM eval_card_result"
            ).fetchone()[0]
            sample_rows = conn.execute(
                "SELECT COUNT(*) FROM eval_defect_sample_result"
            ).fetchone()[0]
        self.assertEqual(run_rows, 1)
        self.assertEqual(card_rows, 2)
        self.assertEqual(sample_rows, 14)

    def test_store_degrades_to_jsonl_and_creates_outbox_when_db_unreachable(
        self,
    ) -> None:
        bad_cfg = dataclasses.replace(
            self.cfg,
            db_url="postgresql://invalid-host:5432/nonexistent",
            store_backend="dual",
        )
        report = run_eval_suite(bad_cfg, suite="smoke")
        self.assertTrue(report.overall_pass)
        outbox = bad_cfg.evals_runs_dir / "outbox" / f"{report.eval_run_id}.tar.zst"
        self.assertTrue(outbox.is_file())

    def test_regression_diff_detects_verdict_flip_and_recall_drop(self) -> None:
        cards = load_all_cards(self.cfg.cards_dir)
        base_run = run_eval_suite(self.cfg, suite="calibrate")
        clean_diff = compute_run_diff(base_run, base_run, cards)
        self.assertFalse(clean_diff.regression_detected)
        self.assertEqual(clean_diff.exit_code, 0)

        # Mutate current run to simulate a fatal_recall drop and verdict flip
        regressed_card = dataclasses.replace(
            base_run.cards[0],
            verdict="fail",
            judge_score=0.75,
            metrics={**base_run.cards[0].metrics, "fatal_recall": 0.6667},
        )
        regressed_run = dataclasses.replace(
            base_run,
            eval_run_id=base_run.eval_run_id + "-regressed",
            overall_pass=False,
            cards=[regressed_card, *base_run.cards[1:]],
        )
        bad_diff = compute_run_diff(base_run, regressed_run, cards)
        self.assertTrue(bad_diff.regression_detected)
        self.assertEqual(bad_diff.exit_code, 2)
        self.assertTrue(any("verdict flipped" in r for r in bad_diff.blocking_reasons))
        self.assertTrue(
            any("fatal_recall dropped" in r for r in bad_diff.blocking_reasons)
        )

    def test_dpdp_kid_session_guardrail_rejects_pii_and_accepts_anonymised(
        self,
    ) -> None:
        valid_payload = {
            "session_code": "kid-r2-01",
            "topic_slug": "how-forces-affect-motion",
            "tester_class": 9,
            "topic_class": 9,
            "is_above_class_level": False,
            "restated_in_own_words": True,
            "followup_1_correct": True,
            "followup_2_correct": True,
            "gate_b_pass": True,
            "confusion_blocks": [],
            "promoted_defect_id": None,
            "notes": "Completed lesson smoothly without hints.",
            "recorded_at": "2026-11-09T12:00:00Z",
        }
        validate_kid_session_dpdp(valid_payload)
        store = EvalStore(self.cfg)
        rec = store.record_kid_session(valid_payload)
        self.assertEqual(rec.session_code, "kid-r2-01")

        # Reject forbidden child PII field
        with self.assertRaises(ValueError) as ctx1:
            validate_kid_session_dpdp({**valid_payload, "student_name": "Aarav"})
        self.assertIn("DPDP privacy violation", str(ctx1.exception))

        # Reject email or phone inside notes
        with self.assertRaises(ValueError) as ctx2:
            validate_kid_session_dpdp(
                {**valid_payload, "notes": "Contact parent at parent@example.com"}
            )
        self.assertIn("DPDP privacy violation", str(ctx2.exception))

        # Verify CLI returns exit code 1 on PII payload
        rc = cli_main(
            [
                "record-kid-test",
                "--input",
                json.dumps({**valid_payload, "phone": "9876543210"}),
            ]
        )
        self.assertEqual(rc, 1)

    def test_record_human_edit_diff_calculation(self) -> None:
        base_dir = self.tmp / "base_page"
        pub_dir = self.tmp / "pub_dir"
        base_dir.mkdir()
        pub_dir.mkdir()
        (base_dir / "index.html").write_text(
            "line1\nline2\nline3\nline4\n", encoding="utf-8"
        )
        (pub_dir / "index.html").write_text(
            "line1\nline2-edited\nline3\nline4\n", encoding="utf-8"
        )

        store = EvalStore(self.cfg)
        rec = store.record_human_edit(
            course_id="class-9-physics",
            topic_slug="how-forces-affect-motion",
            baseline_dir=base_dir,
            published_dir=pub_dir,
        )
        self.assertEqual(rec.manual_added_lines, 1)
        self.assertEqual(rec.manual_deleted_lines, 1)
        self.assertEqual(rec.total_generated_lines, 4)
        self.assertEqual(rec.human_edit_rate, 0.5)

    def test_alembic_migration_0001_upgrade_and_downgrade_sql(self) -> None:
        op_up = _RecordingOp()
        mig_0001.upgrade(op_up)
        joined_up = "\n".join(op_up.statements)
        for tbl in (
            "eval_run",
            "eval_card_result",
            "eval_defect_sample_result",
            "eval_human_edit",
            "eval_kid_session",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {tbl}", joined_up)

        op_down = _RecordingOp()
        mig_0001.downgrade(op_down)
        self.assertEqual(len(op_down.statements), 5)


if __name__ == "__main__":
    unittest.main()
