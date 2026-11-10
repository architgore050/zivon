"""Tests for `evals/telemetry.py` (single-write emission + honest metrics)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evals.telemetry import (
    ErrorClass,
    Severity,
    emit_eval_event,
    format_prometheus_metrics,
)


class TestEvalTelemetry(unittest.TestCase):
    def test_no_fallback_double_write_when_logging_manager_present(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class _FakeManager:
            Severity = Severity
            ErrorClass = ErrorClass

            @staticmethod
            def current_context() -> dict[str, str]:
                return {}

            @staticmethod
            def log_event(event: str, fields: dict[str, object], **_kw: object) -> None:
                calls.append((event, fields))

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.dict(sys.modules, {"logging_manager": _FakeManager}):
                record = emit_eval_event(
                    "EVT-EVAL-RUN-STARTED",
                    {"eval_run_id": "eval-x"},
                    run_id="eval-x",
                    fallback_dir=tmp,
                )
            self.assertEqual(len(calls), 1)
            self.assertFalse((tmp / "logs").exists())
            self.assertEqual(record["component"], "evals")

    def test_fallback_jsonl_written_when_logging_manager_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with mock.patch.dict(sys.modules, {"logging_manager": None}):
                record = emit_eval_event(
                    "EVT-EVAL-RUN-COMPLETED",
                    {"eval_run_id": "eval-y"},
                    run_id="eval-y",
                    fallback_dir=tmp,
                )
            log_files = list((tmp / "logs").glob("*-evals.jsonl"))
            self.assertEqual(len(log_files), 1)
            row = json.loads(log_files[0].read_text(encoding="utf-8").strip())
            self.assertEqual(row["component"], "evals")
            self.assertEqual(record["component"], "evals")

    def test_gate_b_metric_absent_not_fabricated(self) -> None:
        prom = format_prometheus_metrics(
            {
                "suite": "smoke",
                "duration_s": 1.0,
                "cards": [],
                "summary": {"gate_b_comprehension_rate": None},
            }
        )
        self.assertNotIn('zivon_eval_gate_b_pass_rate{round="current"}', prom)
        self.assertIn("absent: no kid-comprehension sessions", prom)

        measured = format_prometheus_metrics(
            {
                "suite": "full",
                "duration_s": 1.0,
                "cards": [],
                "summary": {"gate_b_comprehension_rate": 0.6667},
            }
        )
        self.assertIn('zivon_eval_gate_b_pass_rate{round="current"} 0.6667', measured)


if __name__ == "__main__":
    unittest.main()
