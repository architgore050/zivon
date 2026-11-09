"""Unit and calibration tests for `evals/judges/*` and `evals/runner.py`.

Proves:
1. Calibrated rubric responder achieves 100% fatal recall, 100% blocking recall,
   and 100% clean specificity across `EV-REV-001` (8 samples) and `EV-REV-002`
   (11 samples: 5 security + 6 model).
2. A permissive/blind judge that misses planted defects FAILS calibration (`fatal_recall == 0.0`).
3. An over-eager adversarial judge that flags clean samples as fatal FAILS calibration
   (`clean_specificity < 1.0`).
4. Deterministic-first funnel skips LLM judge when any deterministic check fails (`model_calls == 0`).
"""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any

from evals.config import EvalConfig
from evals.judges import JudgeClient, run_judge, verify_source_quote
from evals.models import DeterministicCheckSpec, IssueRecord, load_all_cards
from evals.runner import run_single_card


class TestCalibrationAndJudges(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({"EVAL_MOCK_MODE": "1"})
        self.cards = load_all_cards(self.cfg.cards_dir)

    def test_calibrated_judge_passes_all_cards_and_19_seeded_defects(self) -> None:
        client = JudgeClient.mock(self.cfg)
        rev1 = self.cards["EV-REV-001"]
        assert rev1.llm_judge is not None
        out1 = run_judge(rev1.llm_judge.entrypoint, self.cfg, rev1, client)
        self.assertEqual(out1.verdict, "pass")
        self.assertEqual(out1.metrics["fatal_recall"], 1.0)
        self.assertEqual(out1.metrics["blocking_recall"], 1.0)
        self.assertEqual(out1.metrics["clean_specificity"], 1.0)
        self.assertEqual(len(out1.defect_samples), 8)

        rev2 = self.cards["EV-REV-002"]
        assert rev2.llm_judge is not None
        out2 = run_judge(rev2.llm_judge.entrypoint, self.cfg, rev2, client)
        self.assertEqual(out2.verdict, "pass")
        self.assertEqual(out2.metrics["fatal_recall"], 1.0)
        self.assertEqual(out2.metrics["blocking_recall"], 1.0)
        self.assertEqual(out2.metrics["clean_specificity"], 1.0)
        self.assertEqual(len(out2.defect_samples), 6)

    def test_blind_permissive_judge_fails_calibration(self) -> None:
        """A judge that rubber-stamps every draft must fail EV-REV-001 and EV-REV-002."""

        def blind_responder(
            stage_id: str, _messages: list[dict[str, str]], meta: dict[str, Any]
        ) -> dict[str, Any]:
            if stage_id == "09-review" or meta.get("round_tag") in ("facts", "design"):
                return {"issues": []}
            return {"verdict": "pass", "issues": []}

        blind_client = JudgeClient(self.cfg, responder=blind_responder)
        rev1 = self.cards["EV-REV-001"]
        assert rev1.llm_judge is not None
        out1 = run_judge(rev1.llm_judge.entrypoint, self.cfg, rev1, blind_client)
        self.assertEqual(out1.verdict, "fail")
        self.assertEqual(out1.metrics["fatal_recall"], 0.0)
        fn_samples = [s for s in out1.defect_samples if s.outcome_class == "FN"]
        self.assertGreaterEqual(len(fn_samples), 3)

        rev2 = self.cards["EV-REV-002"]
        assert rev2.llm_judge is not None
        out2 = run_judge(rev2.llm_judge.entrypoint, self.cfg, rev2, blind_client)
        self.assertEqual(out2.verdict, "fail")
        self.assertEqual(out2.metrics["fatal_recall"], 0.0)

    def test_adversarial_false_positive_judge_fails_specificity(self) -> None:
        """A judge that invents fatal issues on clean pages must fail clean_specificity."""

        def over_eager_responder(
            stage_id: str, _messages: list[dict[str, str]], _meta: dict[str, Any]
        ) -> dict[str, Any]:
            return {
                "verdict": "fail",
                "issues": [
                    {
                        "block_id": "b-01",
                        "severity": "fatal",
                        "message": "Invented nitpick on a clean block [ncert page 98].",
                    }
                ],
            }

        eager_client = JudgeClient(self.cfg, responder=over_eager_responder)
        rev1 = self.cards["EV-REV-001"]
        assert rev1.llm_judge is not None
        out1 = run_judge(rev1.llm_judge.entrypoint, self.cfg, rev1, eager_client)
        self.assertEqual(out1.verdict, "fail")
        self.assertLess(out1.metrics["clean_specificity"], 1.0)

    def test_deterministic_first_funnel_skips_judge_on_deterministic_failure(self) -> None:
        """When a deterministic check fails, `run_single_card` must skip the LLM judge (`model_calls == 0`)."""
        base_card = self.cards["EV-CUR-001"]
        failing_spec = DeterministicCheckSpec(
            id="DET-TEST-FAIL",
            entrypoint="testing.evals.test_calibration_and_judges:_failing_check_helper",
            severity_on_fail="fatal",
            description="Synthetic failing deterministic check",
        )
        broken_card = dataclasses.replace(
            base_card, deterministic_checks=[failing_spec]
        )
        client = JudgeClient.mock(self.cfg)
        res = run_single_card(
            broken_card, self.cfg, client, execute_judge=True
        )
        self.assertEqual(res.verdict, "fail")
        self.assertEqual(res.model_calls, 0)
        self.assertIsNone(res.judge_score)

    def test_verify_source_quote_grounding(self) -> None:
        corpus = "According to NCERT Section 8.2, the SI unit of speed is metre per second (m s-1)."
        self.assertTrue(
            verify_source_quote(
                "Block states km/h; source [ncert Section 8.2] states 'metre per second'.",
                corpus,
                ["metre per second"],
            )
        )
        self.assertFalse(verify_source_quote("", corpus))
        self.assertFalse(
            verify_source_quote("Completely unrelated hallucination", corpus, ["kelvin"])
        )


def _failing_check_helper(
    _cfg: EvalConfig, _card: Any, _context: dict[str, Any]
) -> list[IssueRecord]:
    return [
        IssueRecord(
            severity="fatal",
            check_id="DET-TEST-FAIL",
            message="Synthetic deterministic failure to test short-circuit funnel",
        )
    ]


if __name__ == "__main__":
    unittest.main()
