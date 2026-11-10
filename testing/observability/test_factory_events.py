"""Factory + llm_manager instrumentation conformance: the event rows these
call sites emit carry the map's correlation IDs and content-free fields;
the llm_manager error markers map onto node rows without message parsing."""

from __future__ import annotations

import json
import unittest

from factory.artifacts import RunContext
from factory.errors import BudgetError, ConfigError, MissingArtifactError, StageError
from factory.llm import _CALL_INTENT
from factory.stages import _error_class_for, _reason_code_for
from llm_manager import LLMConfig, TransportError
from llm_manager.client import LLMManager, _CallState
from llm_manager.service.app import _error_class, _NodeObserver
from logging_manager import sink

from .support import ObservabilityTest


class RunContextEventTests(ObservabilityTest):
    def setUp(self) -> None:
        super().setUp()
        self.ctx = RunContext(self.runs_dir, "motion-c9")

    def test_stage_transitions_emit_the_three_rows(self) -> None:
        self.ctx.mark_stage("02-generate", "running")
        self.ctx.mark_stage(
            "02-generate", "ok", detail="blocks=14", blocks=14, attempts=1
        )
        started = self.last_event("factory.stage.start")
        self.assertEqual(started["run_id"], "motion-c9")
        self.assertEqual(started["stage"], "02-generate")
        ok = self.last_event("factory.stage.ok")
        self.assertEqual(ok["fields"], {"blocks": 14, "attempts": 1})
        self.assertIsNotNone(ok["latency_ms"])
        self.assertEqual(ok["component"], "factory")

    def test_failed_transition_carries_reason_and_class(self) -> None:
        from logging_manager import ErrorClass

        self.ctx.mark_stage("03-check", "running")
        self.ctx.mark_stage(
            "03-check",
            "failed",
            detail="model fail issues",
            reason_code="check_blocking",
            error_class=ErrorClass.GATE_FAIL,
        )
        failed = self.last_event("factory.stage.fail")
        self.assertEqual(failed["severity"], "ERROR")
        self.assertEqual(failed["error_class"], "gate_fail")
        self.assertEqual(
            failed["fields"], {"reason_code": "check_blocking", "attempt": 0}
        )
        # the free-form detail string NEVER rides the event (content stays out)
        self.assertNotIn("issues", str(failed))


class ReasonCodeTests(unittest.TestCase):
    def test_reason_codes_are_content_free(self) -> None:
        self.assertEqual(
            _reason_code_for(ConfigError("...fingerprint detail...")), "config_mismatch"
        )
        self.assertEqual(
            _reason_code_for(StageError("03-check", "issue text")), "catcher_exhausted"
        )
        self.assertEqual(
            _reason_code_for(BudgetError("07-perf", "miss", fixable=False)),
            "budget_unfixable",
        )
        self.assertEqual(
            _reason_code_for(BudgetError("07-perf", "miss", fixable=True)),
            "budget_fixable",
        )

    def test_error_class_overrides(self) -> None:
        from logging_manager import ErrorClass

        self.assertEqual(
            _error_class_for(ConfigError("x")), ErrorClass.VALIDATION_ERROR
        )
        self.assertEqual(
            _error_class_for(MissingArtifactError("x")), ErrorClass.INFRA_ERROR
        )
        self.assertIsNone(_error_class_for(StageError("03-check", "x")))


class CallIntentTests(unittest.TestCase):
    def test_intent_enum_matches_the_map(self) -> None:
        self.assertEqual(
            sorted(set(_CALL_INTENT.values())),
            sorted(["generate", "check", "repair", "review", "reviewfix", "fixloop"]),
        )
        self.assertEqual(_CALL_INTENT["02-generate"], "generate")
        self.assertEqual(_CALL_INTENT["10-reviewfix"], "reviewfix")


class LlmManagerMarkerTests(ObservabilityTest):
    def test_deadline_abort_marker(self) -> None:
        config = LLMConfig(
            base_url="http://127.0.0.1:9/v1", model="m", call_deadline_s=10
        )
        manager = LLMManager(config)
        error = manager._deadline_abort(3, _CallState())
        self.assertIsInstance(error, TransportError)
        self.assertTrue(getattr(error, "deadline_abort", False))
        self.assertEqual(getattr(error, "chunks_received", 0), 3)
        self.assertEqual(getattr(error, "deadline_s", 0), 10)

    def test_retry_hook_reason_enum(self) -> None:

        observer = _NodeObserver()
        original = sink._write_stdout
        collected: list[str] = []
        sink._write_stdout = collected.append  # type: ignore[assignment]
        try:
            observer.on_retry(2, "rate_limited")
        finally:
            sink._write_stdout = original
        self.assertEqual(len(collected), 1)
        record = json.loads(collected[0])
        self.assertEqual(record["event"], "node.call.transport_retry")
        self.assertEqual(record["component"], "llm_node")
        self.assertEqual(
            record["fields"], {"attempt": 2, "reason_code": "rate_limited"}
        )

    def test_error_class_helper(self) -> None:
        from logging_manager import ErrorClass

        self.assertEqual(_error_class("transport_error"), ErrorClass.TRANSPORT_ERROR)
        self.assertIsNone(_error_class("not_a_class"))


if __name__ == "__main__":
    unittest.main()
