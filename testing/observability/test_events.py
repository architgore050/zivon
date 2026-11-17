"""Map conformance (spec.md §8, logging-api.md §2/§12): every emitted event
resolves to an instrumentation-map.csv row; the CSV parses cleanly; the
factory/node call sites emit only mapped names. This is the module-side
half of CI's map-lint."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from logging_manager import events as ev

from .support import ObservabilityTest

MAP_PATH = Path("docs/specs/observability/instrumentation-map.csv")

# The events THIS branch's code emits (the merge agent swaps other agents'
# shims onto the module — they must all resolve too; their names are the
# rows they declared in the map).
EMITTED_BY_THIS_BRANCH = [
    # factory/stages.py + factory/artifacts.py
    "factory.run.started",
    "factory.run.resumed",
    "factory.run.completed",
    "factory.run.failed",
    "factory.stage.start",
    "factory.stage.ok",
    "factory.stage.fail",
    "factory.repair.exhausted",
    # factory/llm.py
    "factory.call.started",
    "factory.call.finished",
    "factory.call.rejected",
    "factory.call.transport_exhausted",
    # factory/fixloop.py + reviewfix.py
    "factory.repair.round",
    # factory/perf.py
    "factory.perf.budget_fail",
    # llm_manager node + client adapter
    "node.call.received",
    "node.call.finished",
    "node.call.transport_retry",
    "node.call.deadline_abort",
    "node.upstream_sse_error",
    "node.model_mismatch",
    # dashboard
    "dashboard.session_started",
    "dashboard.auth_failure",
    "dashboard.auth_lockout",
    "dashboard.auth_unconfigured",
    "dashboard.action_triggered",
    # backend/routes/progress.py (F3)
    "progress.events.ingested",
    "progress.events.rejected",
    "progress.bookmark.changed",
    # backend/routes/practice.py + backend/practice/service.py (F5)
    "practice.session.created",
    "practice.answer.recorded",
    "practice.session.completed",
    "practice.answer.progress_sync_failed",
    # backend/routes/speaking.py + backend/speaking/pipeline.py (F6)
    "speaking.prompts.listed",
    "speaking.attempt.started",
    "speaking.attempt.transcribed",
    "speaking.attempt.evaluated",
    "speaking.attempt.evaluation_unavailable",
    "speaking.attempt.no_speech",
    "speaking.attempt.failed",
    "speaking.attempt.saved",
    "speaking.attempt.self_check",
    "speaking.attempt.deleted",
    "speaking.attempt.ledger_failed",
    "speaking.consent.blocked",
    "speaking.quota.blocked",
    "speaking.mock.refused",
    # backend/routes/tests.py + backend/test_engine/service.py (F7)
    "test.session.created",
    "test.attempt.started",
    "test.answer.saved",
    "test.attempt.submitted",
    "test.attempt.progress_sync_failed",
    # logging_manager module-own events
    "log.store_fallback",
    "log.store_recovered",
    "log.redaction_violation",
    "log.event_unknown",
    # guardian deletion
    "privacy.subject_deleted",
    # voice backend (voice/ package)
    "voice.brain.first_event_breach",
    "voice.brain.transport_retry",
    "voice.ratelimit.unsalted",
    "voice.session.closed",
    "voice.snapshot.rejected",
    "voice.stt.connect_retry",
    "voice.tts.connect_retry",
    "voice.turn.e2e_latency",
    "voice.turn.ledger_failed",
    "voice.ws.heartbeat_lost",
    "voice.ws.oversized_frame",
    "voice.ws.unknown_message",
    # evals/telemetry.py + runner.py + diff.py + store.py (P4, 2026-11-15)
    "factory.eval.run_started",
    "factory.eval.run_completed",
    "factory.eval.regression_alert",
    "factory.eval.human_edit_recorded",
    "factory.eval.kid_session_logged",
    # factory/assessment/pipeline.py (P2, 2026-11-17) - the separate
    # assessment entrypoint's run edges; its stage transitions reuse
    # factory.stage.start/ok/fail with A1-A6 stage ids.
    "factory.assessment.run.started",
    "factory.assessment.run.completed",
    "factory.assessment.run.failed",
    "factory.assessment.pack.written",
    # factory/exam/pipeline.py (P3, 2026-11-17) - the exam/series entrypoint's
    # run edges; its stage transitions reuse factory.stage.start/ok/fail with
    # E1-E4 stage ids.
    "factory.exam.run.started",
    "factory.exam.run.completed",
    "factory.exam.run.failed",
    "factory.exam.pack.written",
    "exam.item.ingested",
    "exam.publish.blocked",
    "exam.series.blocked",
]

# Declared-but-not-yet-emitted rows (other agents / future wiring): naming
# them here documents that the map is a superset of this branch's emissions.
RESERVED_ROWS = [
    "factory.coverage.gap_fatal",  # no coverage check exists in checks.py yet
    "factory.publish.ok",  # scripts/publish-frontend.sh is outside this brief's boundary
    "factory.publish.fail",
    "voice.session.started",  # the voice backend (S2) emits these
    "frontend.page_view",  # the frontend shell (F-2) emits these
    "credit.counter_update",  # the credit guard (S2) emits these
    "translator.translate.ok",
]


class MapParsingTests(unittest.TestCase):
    def test_map_parses_rfc4180_with_consistent_columns(self) -> None:
        text = MAP_PATH.read_text(encoding="utf-8")
        rows = list(csv.DictReader(text.splitlines()))
        # The map is additive by design ("components add rows in the same PR as
        # their code"), so the contract is shape + no truncation, not a frozen
        # count. 78 was the baseline when this test was written (F4's three
        # frontend rows made it 81).
        self.assertGreaterEqual(len(rows), 78, "the instrumentation map lost rows")
        expected_columns = [
            "component",
            "event",
            "severity",
            "correlation_ids",
            "required_fields",
            "latency_ms",
            "error_class",
            "privacy_class",
            "emitter",
            "notes",
        ]
        for row in rows:
            self.assertEqual(list(row.keys()), expected_columns, row["event"])
            self.assertTrue(row["event"])
            self.assertIn(
                row["severity"], {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            )

    def test_map_rows_have_valid_severities_and_privacy_classes(self) -> None:
        rows = list(csv.DictReader(MAP_PATH.read_text(encoding="utf-8").splitlines()))
        for row in rows:
            self.assertIn(row["privacy_class"], {"L1", "L2", "L3", "CR"})


class MapConformanceTests(ObservabilityTest):
    def test_every_emitted_name_resolves_to_a_row(self) -> None:
        for name in EMITTED_BY_THIS_BRANCH:
            with self.subTest(event=name):
                self.assertIsNotNone(ev.known_event(name))

    def test_emitted_severity_matches_the_map_declaration(self) -> None:
        from logging_manager import Severity

        for name in EMITTED_BY_THIS_BRANCH:
            row = ev.known_event(name)
            with self.subTest(event=name):
                self.assertEqual(ev.severity_for(name).value, row.severity)  # type: ignore[union-attr]
        # spot-check the load-bearing rows
        self.assertEqual(ev.severity_for("factory.stage.fail"), Severity.ERROR)
        self.assertEqual(ev.severity_for("credit.guard_blocked"), Severity.CRITICAL)
        self.assertEqual(ev.severity_for("log.store_fallback"), Severity.WARNING)

    def test_module_own_events_carry_the_log_component(self) -> None:
        self.assertEqual(ev.component_for("log.store_fallback"), "log")
        self.assertEqual(ev.component_for("log.redaction_violation"), "log")

    def test_component_inference_for_undeclared_events(self) -> None:
        self.assertEqual(ev.component_for("anything", "factory.something"), "factory")
        self.assertEqual(ev.component_for("anything", "llm_manager.client"), "llm")
        self.assertEqual(
            ev.component_for("anything", "llm_manager.service.app"), "llm_node"
        )
        self.assertEqual(ev.component_for("anything", "dashboard.app"), "dashboard")
        self.assertEqual(ev.component_for("anything", "unknownpkg.mod"), "log")

    def test_emitting_a_declared_event_uses_the_map_component(self) -> None:
        from logging_manager import sink

        sink.log_event("node.call.received", {"stream": True, "attempt": 1})
        record = self.last_event("node.call.received")
        self.assertEqual(record["component"], "llm_node")


class ContractSurfaceTests(unittest.TestCase):
    def test_public_surface_is_exact(self) -> None:
        import logging_manager

        self.assertEqual(
            sorted(logging_manager.__all__),
            sorted(
                [
                    "LOG_SCHEMA_VERSION",
                    "ErrorClass",
                    "Severity",
                    "bind_context",
                    "context_scope",
                    "current_context",
                    "delete_subject",
                    "log_event",
                ]
            ),
        )

    def test_log_event_signature_is_the_contract(self) -> None:
        import inspect

        import logging_manager

        params = inspect.signature(logging_manager.log_event).parameters
        self.assertEqual(
            list(params),
            [
                "event",
                "fields",
                "severity",
                "error_class",
                "latency_ms",
                "run_id",
                "session_id",
                "turn_id",
                "request_id",
                "stage",
            ],
        )
        for name in list(params)[2:]:
            self.assertEqual(params[name].kind, inspect.Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()
