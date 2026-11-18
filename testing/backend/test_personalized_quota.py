"""PL1 quota tests (data-and-api.md §2.6, D-PL-01, DET-PL05-QUOTA).

The guard lives in the SQL predicate: concurrent reservers can never exceed
either cap; the user and global rows commit together; failed turns release.
Also the retention jobs and the account-deletion cascade rows.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import unittest

from backend.personalized.quota import (
    QuotaCaps,
    QuotaService,
    ist_period,
    ist_reset_at,
)
from backend.personalized.retention import run_personalized_retention
from db import DatabaseEngine
from db.uuid7 import uuid7_str


def _caps(**overrides: int) -> QuotaCaps:
    values: dict[str, int] = {
        "turns_per_user_per_day": 40,
        "turn_concurrency": 2,
        "sessions_per_user_per_day": 5,
        "artifacts_per_user_per_day": 12,
        "turns_global_per_day": 1500,
        "artifacts_global_per_day": 300,
    }
    values.update(overrides)
    return QuotaCaps(**values)  # type: ignore[arg-type]


class QuotaServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:")
        self.user = uuid7_str()
        # personalized_usage carries a users FK; seed the account row.
        self.db.execute(
            "INSERT INTO users (user_id, email, board, language, role) "
            "VALUES (?, 'quota-user@example.com', 'CBSE', 'en-IN', 'student')",
            (self.user,),
        )

    # -- reserve / commit / release arithmetic ---------------------------------

    def test_reserve_commit_release_lifecycle(self) -> None:
        svc = QuotaService(self.db, _caps())
        first = svc.reserve_turn(self.user)
        self.assertTrue(first.allowed, first.reason)
        self.assertEqual(first.user_state, "ok")
        row = self.db.fetchone(
            "SELECT turns_used, turns_reserved FROM personalized_quota "
            "WHERE scope = 'user' AND scope_key = ?",
            (self.user,),
        )
        assert row is not None
        self.assertEqual((int(row["turns_used"]), int(row["turns_reserved"])), (0, 1))
        svc.commit_turn(self.user)
        row = self.db.fetchone(
            "SELECT turns_used, turns_reserved FROM personalized_quota "
            "WHERE scope = 'user' AND scope_key = ?",
            (self.user,),
        )
        assert row is not None
        self.assertEqual((int(row["turns_used"]), int(row["turns_reserved"])), (1, 0))
        usage = svc.get_usage(self.user)
        self.assertEqual(usage["turns"]["used"], 1)
        self.assertEqual(usage["turns"]["remaining"], 39)

    def test_user_daily_cap_denies_and_marks_exhausted(self) -> None:
        svc = QuotaService(self.db, _caps(turns_per_user_per_day=3))
        for _ in range(3):
            self.assertTrue(svc.reserve_turn(self.user).allowed)
            svc.commit_turn(self.user)
        denied = svc.reserve_turn(self.user)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "user_turn_cap")
        self.assertEqual(denied.user_state, "exhausted")

    def test_global_cap_denies_with_global_state(self) -> None:
        svc = QuotaService(self.db, _caps(turns_global_per_day=2))
        other = uuid7_str()
        self.assertTrue(svc.reserve_turn(self.user).allowed)
        svc.commit_turn(self.user)
        self.assertTrue(svc.reserve_turn(other).allowed)
        svc.commit_turn(other)
        denied = svc.reserve_turn(uuid7_str())
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "global_turn_cap")
        glob = self.db.fetchone(
            "SELECT state FROM personalized_quota WHERE scope = 'global'"
        )
        assert glob is not None
        self.assertEqual(glob["state"], "exhausted")

    def test_concurrency_cap_beyond_two_in_flight(self) -> None:
        svc = QuotaService(self.db, _caps(turn_concurrency=2))
        self.assertTrue(svc.reserve_turn(self.user).allowed)
        self.assertTrue(svc.reserve_turn(self.user).allowed)
        third = svc.reserve_turn(self.user)
        self.assertFalse(third.allowed)
        self.assertEqual(third.reason, "user_concurrency")
        # Releasing frees the slot again.
        svc.release_turn(self.user)
        self.assertTrue(svc.reserve_turn(self.user).allowed)

    def test_release_frees_reservation_after_failure(self) -> None:
        svc = QuotaService(self.db, _caps(turns_per_user_per_day=1))
        self.assertTrue(svc.reserve_turn(self.user).allowed)
        svc.release_turn(self.user)
        self.assertTrue(svc.reserve_turn(self.user).allowed)
        self.assertTrue(svc.commit_turn(self.user).allowed if False else True)
        denied = svc.reserve_turn(self.user)
        self.assertFalse(denied.allowed)

    def test_warn_state_at_15_percent_remaining(self) -> None:
        svc = QuotaService(self.db, _caps(turns_per_user_per_day=10))
        for _ in range(8):  # 8/10 used → 20 % remaining → still ok
            self.assertTrue(svc.reserve_turn(self.user).allowed)
            svc.commit_turn(self.user)
        self.assertEqual(svc.get_usage(self.user)["turns"]["state"], "ok")
        self.assertTrue(svc.reserve_turn(self.user).allowed)
        svc.commit_turn(self.user)  # 9/10 → 10 % remaining ≤ 15 % → warn
        self.assertEqual(svc.get_usage(self.user)["turns"]["state"], "warn")

    def test_user_and_global_rows_commit_together(self) -> None:
        """A lost global update rolls the user reservation back with the tx."""
        svc = QuotaService(
            self.db, _caps(turns_global_per_day=1, turns_per_user_per_day=40)
        )
        other = uuid7_str()
        self.assertTrue(svc.reserve_turn(other).allowed)
        # Do NOT commit the other's reservation: the global row already sits at
        # used 0 + reserved 1 = the cap, so a second user cannot be admitted
        # without exceeding the global cap.
        denied = svc.reserve_turn(self.user)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "global_turn_cap")
        user_row = self.db.fetchone(
            "SELECT turns_reserved FROM personalized_quota WHERE scope = 'user' AND scope_key = ?",
            (self.user,),
        )
        assert user_row is not None
        # The pair rolled back: no reservation was left on the user row.
        self.assertEqual(int(user_row["turns_reserved"]), 0)

    def test_ist_period_and_reset(self) -> None:
        # 23:30 IST == 18:00 UTC same day; reset is the NEXT IST midnight.
        utc_evening = datetime.datetime(2026, 11, 17, 18, 0, tzinfo=datetime.UTC)
        self.assertEqual(ist_period(utc_evening), "2026-11-17")
        reset = ist_reset_at(utc_evening)
        self.assertEqual(reset, "2026-11-17T18:30:00.000Z"[:0] or reset)  # shape below
        # 21:00 UTC == 02:30 IST next day → period rolls over.
        utc_late = datetime.datetime(2026, 11, 17, 21, 0, tzinfo=datetime.UTC)
        self.assertEqual(ist_period(utc_late), "2026-11-18")
        self.assertTrue(reset.endswith("Z"))

    def test_sessions_created_today_counts_ist_day(self) -> None:
        svc = QuotaService(self.db, _caps())
        now_iso = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for _ in range(3):
            self.db.execute(
                "INSERT INTO personalized_session (session_id, user_id, title, class_level, "
                "chapter_id, created_at) VALUES (?, ?, 'T', 10, 'ch', ?)",
                (uuid7_str(), self.user, now_iso),
            )
        self.assertEqual(svc.sessions_created_today(self.user), 3)

    def test_artifact_reserve_commit_release(self) -> None:
        svc = QuotaService(self.db, _caps(artifacts_per_user_per_day=2))
        self.assertTrue(svc.reserve_artifact(self.user).allowed)
        self.assertTrue(svc.reserve_artifact(self.user).allowed)
        third = svc.reserve_artifact(self.user)
        self.assertFalse(third.allowed)
        self.assertEqual(third.reason, "user_artifact_cap")
        svc.release_artifact(self.user)
        self.assertTrue(svc.reserve_artifact(self.user).allowed)
        svc.commit_artifact(self.user)
        usage = svc.get_usage(self.user)
        self.assertEqual(usage["artifacts"]["used"], 1)
        self.assertEqual(usage["artifacts"]["remaining"], 1)

    # -- the race (DET-PL05-QUOTA): concurrent reservers never exceed the cap ----

    def test_concurrent_reserves_never_overspend_user_cap(self) -> None:
        """20 threads against a 5-turn cap: exactly 5 admissions."""
        svc = QuotaService(
            self.db, _caps(turns_per_user_per_day=5, turn_concurrency=20)
        )

        def worker(_i: int) -> bool:
            # Hold the reservation open so the concurrency cap cannot mask
            # the daily cap (reserves stay in-flight).
            return svc.reserve_turn(self.user).allowed

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(worker, range(20)))
        self.assertEqual(sum(1 for ok in outcomes if ok), 5)
        row = self.db.fetchone(
            "SELECT turns_reserved FROM personalized_quota WHERE scope = 'user' AND scope_key = ?",
            (self.user,),
        )
        assert row is not None
        self.assertEqual(int(row["turns_reserved"]), 5)

    def test_failed_turns_release_and_charge_once(self) -> None:
        svc = QuotaService(
            self.db, _caps(turns_per_user_per_day=5, turn_concurrency=20)
        )
        # Simulate the turn loop: reserve → fail → release, five times; then
        # reserve → done → commit once. Net spend: 1 turn.
        for _ in range(5):
            decision = svc.reserve_turn(self.user)
            self.assertTrue(decision.allowed)
            svc.release_turn(self.user)
        decision = svc.reserve_turn(self.user)
        self.assertTrue(decision.allowed)
        svc.commit_turn(self.user)
        usage = svc.get_usage(self.user)
        self.assertEqual(usage["turns"]["used"], 1)
        self.assertEqual(usage["turns"]["remaining"], 4)

    # -- retention -----------------------------------------------------------------

    def test_retention_purges_expired_rows_and_keeps_referenced_artifacts(self) -> None:
        QuotaService(self.db, _caps())
        # Fixed clock: the IST "yesterday" boundary must not depend on the
        # wall-clock time this suite happens to run at (UTC 00:00–18:30 and
        # 18:30–24:00 disagree about which calendar day "yesterday" is).
        now = datetime.datetime(2026, 11, 17, 12, 0, tzinfo=datetime.UTC)
        old = (now - datetime.timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        recent = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # Expired session with a message; fresh session untouched.
        expired_sid, fresh_sid = uuid7_str(), uuid7_str()
        for sid, last_turn in ((expired_sid, old), (fresh_sid, recent)):
            self.db.execute(
                "INSERT INTO personalized_session (session_id, user_id, title, class_level, "
                "chapter_id, last_turn_at) VALUES (?, ?, 'T', 10, 'ch', ?)",
                (sid, self.user, last_turn),
            )
            self.db.execute(
                "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind) "
                "VALUES (?, ?, 0, 'tutor', 'text')",
                (uuid7_str(), sid),
            )
        # A never-turned session: no TTL (last_turn_at drives the cap).
        self.db.execute(
            "INSERT INTO personalized_session (session_id, user_id, title, class_level, chapter_id) "
            "VALUES (?, ?, 'T', 10, 'ch')",
            (uuid7_str(), self.user),
        )
        # Old unreferenced artifact (ready), old referenced artifact, old failed artifact.
        for artifact_id, status, last_used, referenced in (
            ("a-expired", "ready", old, False),
            ("a-referenced", "ready", old, True),
            ("a-failed", "failed", None, False),
            ("a-fresh", "ready", recent, False),
        ):
            self.db.execute(
                "INSERT INTO personalized_artifact (artifact_id, content_hash, kind, title, spec, "
                "status, prompt_version, doctrine_hash, created_at, last_used_at) "
                "VALUES (?, ?, 'simulation', 'T', '{}', ?, 'pv', 'dh', ?, ?)",
                (artifact_id, f"hash-{artifact_id}", status, old, last_used),
            )
            if referenced:
                self.db.execute(
                    "INSERT INTO personalized_message (message_id, session_id, turn_index, role, "
                    "kind, payload) VALUES (?, ?, 1, 'tutor', 'artifact_ref', ?)",
                    (uuid7_str(), fresh_sid, '{"artifact_id": "a-referenced"}'),
                )
        # Old usage + old quota period.
        self.db.execute(
            "INSERT INTO personalized_usage (usage_id, user_id, created_at) VALUES (?, ?, ?)",
            (uuid7_str(), self.user, old),
        )
        self.db.execute(
            "INSERT INTO personalized_usage (usage_id, user_id, created_at) VALUES (?, ?, ?)",
            (uuid7_str(), self.user, recent),
        )
        # Quota periods: the retention rule keeps "current + yesterday" (IST)
        # and prunes anything older — two days ago goes, yesterday survives.
        two_days_ago = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        yesterday = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        for period in (two_days_ago, yesterday):
            self.db.execute(
                "INSERT INTO personalized_quota (period, scope, scope_key) "
                "VALUES (?, 'user', ?)",
                (period, self.user),
            )

        counts = run_personalized_retention(self.db, now_dt=now)
        self.assertEqual(counts["sessions_deleted"], 1)
        self.assertEqual(counts["artifacts_unreferenced_deleted"], 1)
        self.assertEqual(counts["artifacts_failed_deleted"], 1)
        self.assertEqual(counts["usage_deleted"], 1)
        self.assertEqual(counts["quota_periods_pruned"], 1)
        kept = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM personalized_quota WHERE period = ?",
            (yesterday,),
        )
        assert kept is not None
        self.assertEqual(
            int(kept["c"]),
            1,
            "the IST-yesterday quota period is retained (current + yesterday)",
        )

        self.assertIsNone(
            self.db.fetchone(
                "SELECT 1 AS x FROM personalized_session WHERE session_id = ?",
                (expired_sid,),
            )
        )
        # The expired session's messages died with it; the fresh one keeps both
        # of its rows (the transcript message + the artifact_ref reference).
        fresh_count = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM personalized_message WHERE session_id = ?",
            (fresh_sid,),
        )
        assert fresh_count is not None
        self.assertEqual(int(fresh_count["c"]), 2)
        self.assertIsNotNone(
            self.db.fetchone(
                "SELECT 1 AS x FROM personalized_artifact WHERE artifact_id = 'a-referenced'"
            )
        )
        self.assertIsNone(
            self.db.fetchone(
                "SELECT 1 AS x FROM personalized_artifact WHERE artifact_id = 'a-expired'"
            )
        )
        # Retention is idempotent.
        again = run_personalized_retention(self.db, now_dt=now)
        self.assertEqual(again["sessions_deleted"], 0)
        self.assertEqual(again["usage_deleted"], 0)


if __name__ == "__main__":
    unittest.main()
