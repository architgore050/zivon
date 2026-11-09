"""Tests for the A-15 narration budget guard (refuse-before-exceed)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.narration.budget import (
    estimate_credits,
    load_state,
    record_run_usage,
    refusal_message,
    save_state,
    spend,
    would_exceed,
)
from factory.narration.env import NarrationEnv


def _env(budget: float = 1500.0, price: float = 0.0167) -> NarrationEnv:
    return NarrationEnv(
        enabled=True,
        mode="mock",
        langs=("en",),
        budget_credits=budget,
        repair_rounds=2,
        timbre_base_url=None,
        timbre_api_key=None,
        timbre_tts_path="/v1/tts",
        timbre_voice="",
        credits_per_char=price,
        timbre_timeout_s=30.0,
        timbre_connect_timeout_s=5.0,
        timbre_max_attempts=3,
        timbre_backoff_base_s=0.0,
        coldstore_upload_cmd=None,
        coldstore_readback_cmd=None,
        coldstore_prefix="narration",
        coldstore_timeout_s=60.0,
    )


class TestBudgetLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="zivon-budget-")
        self.runs_dir = Path(self.tmp)

    def test_fresh_state_starts_at_zero(self):
        state = load_state(self.runs_dir, _env())
        self.assertEqual(state["total_credits_used"], 0.0)
        self.assertEqual(state["tranche_credits"], 1500.0)
        self.assertEqual(state["runs"], [])

    def test_estimate_is_chars_times_price(self):
        env = _env(price=0.02)
        self.assertEqual(estimate_credits(1000, env), 20.0)

    def test_exact_fit_allowed_overfit_refused(self):
        state = load_state(self.runs_dir, _env(budget=10.0))
        state["total_credits_used"] = 8.0
        self.assertFalse(would_exceed(state, 2.0))  # exactly 10.0 fits
        self.assertTrue(would_exceed(state, 2.001))

    def test_usage_recorded_and_persisted_across_instances(self):
        env = _env()
        state = load_state(self.runs_dir, env)
        spend(state, 16.7)  # per-block fold, persisted immediately
        save_state(self.runs_dir, state)
        reloaded = load_state(self.runs_dir, env)
        self.assertAlmostEqual(reloaded["total_credits_used"], 16.7, places=3)
        record_run_usage(
            reloaded,
            "run-a",
            mode="mock",
            chars=1000,
            credits=16.7,
            narrated=5,
            failed=1,
            refused=0,
        )
        save_state(self.runs_dir, reloaded)
        final = load_state(self.runs_dir, env)
        # record_run_usage stamps the run row WITHOUT re-adding to the total
        # (spend() already folded it per block).
        self.assertAlmostEqual(final["total_credits_used"], 16.7, places=3)
        self.assertEqual(final["runs"][0]["run_id"], "run-a")
        self.assertEqual(final["runs"][0]["narrated"], 5)

    def test_env_tranche_is_authoritative_over_the_persisted_one(self):
        state = load_state(self.runs_dir, _env(budget=2.5))
        save_state(self.runs_dir, state)
        # The founder raises the cap in the env: the next load obeys the env.
        reloaded = load_state(self.runs_dir, _env(budget=1500.0))
        self.assertEqual(reloaded["tranche_credits"], 1500.0)

    def test_corrupt_file_rebuilds_from_zero_not_inflated(self):
        (self.runs_dir / "narration-budget.json").write_text("{torn", encoding="utf-8")
        state = load_state(self.runs_dir, _env())
        self.assertEqual(state["total_credits_used"], 0.0)

    def test_invalid_shape_raises_loudly(self):
        (self.runs_dir / "narration-budget.json").write_text("[1,2]", encoding="utf-8")
        from factory.narration.errors import NarrationError

        with self.assertRaises(NarrationError):
            load_state(self.runs_dir, _env())

    def test_save_is_atomic_no_tmp_left_behind(self):
        state = load_state(self.runs_dir, _env())
        save_state(self.runs_dir, state)
        self.assertFalse((self.runs_dir / "narration-budget.json.tmp").exists())
        payload = json.loads((self.runs_dir / "narration-budget.json").read_text())
        self.assertIn("tranche_credits", payload)

    def test_refusal_message_names_the_recovery_path(self):
        state = load_state(self.runs_dir, _env(budget=10.0))
        state["total_credits_used"] = 9.5
        message = refusal_message(state, 1.0)
        self.assertIn("ZIVON_NARRATION_BUDGET_CREDITS", message)
        self.assertIn("founder approval", message)
        self.assertIn("content hash", message)  # resume skips completed blocks


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
