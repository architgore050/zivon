"""Tests for `evals/telemetry.py` (single-write emission + honest metrics)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evals.telemetry import (
    EVAL_EVENT_MAP,
    ErrorClass,
    Severity,
    emit_eval_event,
    format_prometheus_metrics,
)
from logging_manager import events as log_events


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


class TestEvalEventMap(unittest.TestCase):
    """Map-lint for every eval event (P-GAP-14 closure).

    `emit_eval_event` routes through `logging_manager`, so a missing map row
    lands as `log.event_unknown` with the wrong component. These assertions
    make that impossible to merge.
    """

    def test_every_eval_event_resolves_to_an_evals_row(self) -> None:
        for evt_id, (dot_event, severity) in EVAL_EVENT_MAP.items():
            with self.subTest(evt_id=evt_id):
                row = log_events.known_event(dot_event)
                self.assertIsNotNone(row, f"{dot_event} has no map row")
                assert row is not None
                self.assertEqual(row.component, "evals")
                self.assertEqual(row.severity, severity.value)
                self.assertEqual(log_events.component_for(dot_event), "evals")

    def test_evals_is_a_declared_component(self) -> None:
        self.assertIn("evals", log_events.COMPONENTS)

    def test_run_events_split_start_and_completion(self) -> None:
        self.assertIn("EVT-EVAL-RUN-STARTED", EVAL_EVENT_MAP)
        self.assertIn("EVT-EVAL-RUN-COMPLETED", EVAL_EVENT_MAP)
        completed = log_events.known_event("factory.eval.run_completed")
        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertTrue(completed.latency_ms)

    def test_regression_alert_carries_the_gate_fail_class(self) -> None:
        row = log_events.known_event("factory.eval.regression_alert")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.error_class, "gate_fail")
        self.assertEqual(row.severity, "ERROR")

    def test_runner_records_the_real_pipeline_version(self) -> None:
        from evals.runner import _pipeline_version
        from factory.stages import PIPELINE_VERSION

        self.assertEqual(_pipeline_version(), int(PIPELINE_VERSION))
        self.assertNotEqual(int(PIPELINE_VERSION), 1)


if __name__ == "__main__":
    unittest.main()
