"""Concurrency, threshold, profile-toggle, and ceiling tests for CreditGuard (ADR-0015)."""

from __future__ import annotations

import concurrent.futures
import unittest
import uuid

from db import DatabaseEngine
from guard import CreditGuard, GuardStatus


class TestCreditGuardConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:")
        self.guard = CreditGuard(self.db)

    def test_concurrent_device_cap_decrement_never_overspends(self) -> None:
        """24 threads each trying to reserve 5 credits against a 30-credit device cap."""
        device_id = str(uuid.uuid4())

        def worker(_i: int) -> bool:
            res = self.guard.check_and_reserve(device_id, 5.0)
            return res.allowed

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(worker, range(24)))

        allowed_count = sum(1 for ok in outcomes if ok)
        self.assertEqual(allowed_count, 6)

        status = self.guard.get_status(device_pseudo_id=device_id)
        self.assertEqual(status.device_used, 30.0)
        self.assertEqual(status.device_remaining, 0.0)
        self.assertEqual(status.device_state, "exhausted")
        self.assertEqual(status.effective_state, "exhausted")
        self.assertEqual(status.voice_flag, "typed_only")

    def test_concurrent_global_tranche_decrement_never_overspends(self) -> None:
        """25 distinct devices each trying to reserve 50 credits in demo mode (1,000 global tranche)."""
        self.guard.set_profile_mode("demo", actor="test")
        devices = [str(uuid.uuid4()) for _ in range(25)]

        def worker(dev: str) -> bool:
            return self.guard.check_and_reserve(dev, 50.0).allowed

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            outcomes = list(pool.map(worker, devices))

        allowed_count = sum(1 for ok in outcomes if ok)
        self.assertEqual(allowed_count, 20)

        status = self.guard.get_status()
        self.assertEqual(status.global_used, 1000.0)
        self.assertEqual(status.global_remaining, 0.0)
        self.assertEqual(status.global_state, "exhausted")

    def test_warn_threshold_15_pct_and_state_push_listener(self) -> None:
        pushed: list[GuardStatus] = []
        self.guard.register_listener(pushed.append)
        dev_id = str(uuid.uuid4())

        # Spend 24 of 30 (20% remaining > 15% warn threshold) -> state stays 'ok'
        d1 = self.guard.check_and_reserve(dev_id, 24.0)
        self.assertTrue(d1.allowed)
        self.assertEqual(d1.status.device_state, "ok")

        # Spend 2 more -> 26 of 30 used (13.33% remaining <= 15% warn threshold) -> 'warn'
        d2 = self.guard.check_and_reserve(dev_id, 2.0)
        self.assertTrue(d2.allowed)
        self.assertEqual(d2.status.device_state, "warn")
        self.assertEqual(d2.status.effective_state, "warn")
        self.assertTrue(any(s.effective_state == "warn" for s in pushed))

        # Toggle to demo mode -> cap becomes 100, 26/100 used (74% remaining) -> 'reserved_mode'
        st_demo = self.guard.set_profile_mode("demo", actor="founder")
        self.assertEqual(st_demo.mode, "demo")
        self.assertEqual(st_demo.global_state, "reserved_mode")

    def test_hard_total_programme_ceiling_protects_demo_reserve(self) -> None:
        """Normal mode stops at 6,000 credits (preserving the 40% = 4,000 demo reserve); demo mode reaches 10,000."""
        # Seed 6 previous days with 1,000 credits each = 6,000 total used
        for day_num in range(1, 7):
            period = f"2026-11-0{day_num}"
            self.db.execute(
                """
                INSERT INTO guard_counter (counter_id, period, scope, scope_key, used_credits, state, updated_at)
                VALUES (?, ?, 'global', 'global', 1000, 'exhausted', '2026-11-07T00:00:00Z')
                """,
                (f"cnt-{day_num}", period),
            )

        dev_id = str(uuid.uuid4())
        # In normal mode, ceiling is 6,000 -> blocked by total_ceiling_exhausted
        d_norm = self.guard.check_and_reserve(dev_id, 10.0, period="2026-11-09")
        self.assertFalse(d_norm.allowed)
        self.assertEqual(d_norm.reason, "total_ceiling_exhausted")

        # Flip to demo mode -> ceiling is 10,000 -> allowed!
        self.guard.set_profile_mode("demo", actor="founder")
        d_demo = self.guard.check_and_reserve(dev_id, 10.0, period="2026-11-09")
        self.assertTrue(d_demo.allowed)
        self.assertEqual(d_demo.status.total_programme_used, 6010.0)

    def test_ledger_recording_and_reconciliation_drift(self) -> None:
        dev_id = str(uuid.uuid4())
        self.db.upsert_device(dev_id)
        self.guard.check_and_reserve(dev_id, 10.0, period="2026-11-09")
        self.guard.record_ledger_entry(
            device_pseudo_id=dev_id,
            model="prisma",
            units="seconds",
            amount=15.0,
            cost_credits=4.0,
            created_at="2026-11-09T10:00:00.000Z",
        )
        self.guard.record_ledger_entry(
            device_pseudo_id=dev_id,
            model="timbre",
            units="chars",
            amount=600.0,
            cost_credits=5.9,
            created_at="2026-11-09T10:00:02.000Z",
        )
        report = self.guard.get_reconciliation_report(period="2026-11-09")
        self.assertEqual(report["counter_used_credits"], 10.0)
        self.assertAlmostEqual(report["ledger_used_credits"], 9.9, places=2)
        self.assertLessEqual(report["drift_pct"], 2.0)
        self.assertTrue(report["drift_within_slo"])


if __name__ == "__main__":
    unittest.main()
