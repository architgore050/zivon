"""Unit tests for the PL judges (`evals/judges/pl_judges.py`, 2026-11-21).

Deterministic, key-free, no LLM (the `testing/` vs `evals/` rule — the judge
*logic* is tested here; the judge *quality* is the calibration corpus under
`evals/goldens/personalized/judge-calibration/` run by the calibrate suite).

Covers:
1. The calibration corpus validates against `PL_JUDGE_SAMPLE_SCHEMA` and is
   byte-identical to `scripts/gen_pl_judge_corpus.py` (no hand edits).
2. The calibrated mock judge passes all three PL judges on the seeded corpus
   (100% fatal/blocking recall, 100% clean specificity) and on the golden
   transcripts.
3. Suite routing: `suite=calibrate` grades the seeded corpus, `suite=full`
   grades the golden transcripts (never both).
4. A blind/permissive judge FAILS calibration (FNs); an over-eager judge
   FAILS clean specificity (FPs).
5. The deterministic output gates: verdict recomputed from issues (never
   trusted), fatal findings must quote the material or are downgraded to
   `unverified:` minor, unknown turn ids are downgraded, duplicates dropped,
   and a mis-targeted corpus sample fails the judge loudly.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from evals.config import EvalConfig
from evals.judges import JudgeClient, run_judge
from evals.judges.pl_judges import (
    _load_samples,
    _validated_issues,
)
from evals.models import (
    PL_JUDGE_SAMPLE_SCHEMA,
    load_all_cards,
    validate_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class CorpusIntegrity(unittest.TestCase):
    """The seeded corpus is a golden: schema-valid and generator-owned."""

    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({})
        self.cards = load_all_cards(self.cfg.cards_dir)

    def test_all_18_samples_validate_against_the_pl_schema(self) -> None:
        total = 0
        for card_id in ("EV-PL-001", "EV-PL-002", "EV-PL-004"):
            card = self.cards[card_id]
            rels = card.golden_inputs["seeded_defects"]
            self.assertTrue(rels, f"{card_id} must list its calibration corpus")
            for rel in rels:
                sample = (self.cfg.repo_root / rel).read_text(encoding="utf-8")
                import json

                validate_schema(
                    json.loads(sample), PL_JUDGE_SAMPLE_SCHEMA, Path(rel).name
                )
                total += 1
        self.assertEqual(total, 18)

    def test_corpus_matches_the_generator_byte_for_byte(self) -> None:
        res = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "gen_pl_judge_corpus.py"),
                "--check",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"corpus drifted from the generator: {res.stdout}{res.stderr}",
        )

    def test_mistargeted_sample_fails_the_judge_loudly(self) -> None:
        """A corpus sample pointed at the wrong judge is a corpus bug — it
        must raise, never silently skip and fabricate a recall number."""
        card = self.cards["EV-PL-001"]
        tampered = dict(card.golden_inputs)
        tampered["seeded_defects"] = [
            "evals/goldens/personalized/judge-calibration/adversarial/SD-PLJ-A01.json"
        ]
        from dataclasses import replace

        wrong_card = replace(card, golden_inputs=tampered)
        with self.assertRaises(ValueError):
            _load_samples(self.cfg, wrong_card, "pedagogy")


class MockCalibration(unittest.TestCase):
    """The calibrated mock judge passes all three judges, both scopes."""

    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({})
        self.cards = load_all_cards(self.cfg.cards_dir)
        self.client = JudgeClient.mock(self.cfg)

    def _run_card(self, card_id: str, suite: str):
        card = self.cards[card_id]
        assert card.llm_judge is not None
        return run_judge(
            card.llm_judge.entrypoint,
            self.cfg,
            card,
            JudgeClient.mock(self.cfg),
            {"suite": suite},
        )

    def test_seeded_corpus_calibration_passes_for_all_three_judges(self) -> None:
        for card_id, samples in (
            ("EV-PL-001", 5),
            ("EV-PL-002", 7),
            ("EV-PL-004", 6),
        ):
            with self.subTest(card=card_id):
                out = self._run_card(card_id, "calibrate")
                self.assertEqual(out.verdict, "pass", out.issues)
                self.assertEqual(out.metrics["scope"], "seeded_corpus")
                self.assertEqual(out.metrics["fatal_recall"], 1.0)
                self.assertEqual(out.metrics["blocking_recall"], 1.0)
                self.assertEqual(out.metrics["clean_specificity"], 1.0)
                self.assertEqual(out.metrics["false_negatives"], 0)
                self.assertEqual(out.metrics["false_positives"], 0)
                self.assertEqual(out.metrics["samples_tested"], samples)
                self.assertEqual(len(out.defect_samples), samples)
                outcome_classes = {s.outcome_class for s in out.defect_samples}
                self.assertIn("TP", outcome_classes)
                self.assertIn("TN", outcome_classes)

    def test_golden_transcripts_judge_passes_in_the_full_suite(self) -> None:
        out = self._run_card("EV-PL-001", "full")
        self.assertEqual(out.verdict, "pass", out.issues)
        self.assertEqual(out.metrics["scope"], "golden_transcripts")
        self.assertEqual(out.metrics["transcripts_judged"], 3)
        self.assertEqual(out.stats.calls, 3)

    def test_suite_routing_never_blends_the_two_scopes(self) -> None:
        cal_out = self._run_card("EV-PL-001", "calibrate")
        self.assertEqual(cal_out.metrics["scope"], "seeded_corpus")
        self.assertEqual(len(cal_out.defect_samples), 5)
        full_out = self._run_card("EV-PL-001", "full")
        self.assertEqual(full_out.metrics["scope"], "golden_transcripts")
        self.assertEqual(full_out.defect_samples, [])


class CalibrationFailsOnBadJudges(unittest.TestCase):
    """A judge that cannot fail is not a judge; one that cannot pass either."""

    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({})
        self.cards = load_all_cards(self.cfg.cards_dir)

    def _run(self, card_id: str, responder) -> Any:
        card = self.cards[card_id]
        assert card.llm_judge is not None
        return run_judge(
            card.llm_judge.entrypoint,
            self.cfg,
            card,
            JudgeClient(self.cfg, responder=responder),
            {"suite": "calibrate"},
        )

    def test_blind_judge_fails_all_three_calibrations(self) -> None:
        def blind(stage_id: str, _messages: list[dict[str, str]], _meta: dict) -> dict:
            return {"issues": []}

        for card_id in ("EV-PL-001", "EV-PL-002", "EV-PL-004"):
            with self.subTest(card=card_id):
                out = self._run(card_id, blind)
                self.assertEqual(out.verdict, "fail")
                self.assertEqual(out.metrics["fatal_recall"], 0.0)
                self.assertGreater(out.metrics["false_negatives"], 0)

    def test_over_eager_judge_fails_clean_specificity(self) -> None:
        def eager(stage_id: str, _messages: list[dict[str, str]], _meta: dict) -> dict:
            # The invented fatal quotes "section " so the quote-grounding gate
            # lets it through as a real finding (that gate is tested below).
            return {
                "issues": [
                    {
                        "severity": "fatal",
                        "message": (
                            "Invented violation, contradicted by section 2 of "
                            "the material."
                        ),
                    }
                ]
            }

        for card_id in ("EV-PL-001", "EV-PL-002", "EV-PL-004"):
            with self.subTest(card=card_id):
                out = self._run(card_id, eager)
                self.assertEqual(out.verdict, "fail")
                self.assertLess(out.metrics["clean_specificity"], 1.0)
                self.assertGreater(out.metrics["false_positives"], 0)


class OutputGates(unittest.TestCase):
    """The deterministic gates between the model's JSON and the IssueRecord list."""

    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({})

    def _validated(
        self,
        raw: list[dict],
        corpus: str = "the corpus text",
        allowed: set[str] | None = None,
    ) -> Any:
        return _validated_issues(
            raw, corpus_text=corpus, allowed_turn_ids=allowed or {"t-1"}
        )

    def test_fatal_without_a_grounded_quote_is_downgraded_unverified_minor(
        self,
    ) -> None:
        issues = self._validated(
            [{"severity": "fatal", "message": "Total hallucination with no quote."}]
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "minor")
        self.assertTrue(issues[0].unverified)
        self.assertTrue(issues[0].message.startswith("unverified:"))

    def test_fatal_with_a_quoted_corpus_substring_survives(self) -> None:
        corpus = "The angle of incidence is equal to the angle of reflection."
        issues = self._validated(
            [
                {
                    "severity": "fatal",
                    "message": "Claim contradicted by the taught 'angle of incidence is equal'.",
                }
            ],
            corpus=corpus,
        )
        self.assertEqual(issues[0].severity, "fatal")
        self.assertFalse(issues[0].unverified)

    def test_unknown_turn_id_is_downgraded_and_attributed_to_the_sample(self) -> None:
        issues = self._validated(
            [
                {
                    "severity": "major",
                    "turn_id": "t-99",
                    "message": "A finding citing a turn that does not exist.",
                }
            ]
        )
        self.assertEqual(issues[0].severity, "minor")
        self.assertTrue(issues[0].unverified)
        self.assertIsNone(issues[0].block_id)

    def test_duplicate_findings_are_dropped(self) -> None:
        dup = {"severity": "minor", "message": "Same wording twice."}
        issues = self._validated([dup, dict(dup)])
        self.assertEqual(len(issues), 1)

    def test_empty_messages_are_dropped(self) -> None:
        issues = self._validated([{"severity": "minor", "message": "   "}])
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
