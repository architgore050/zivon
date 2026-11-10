"""Tests for P0 TTL and retention jobs (`backend/privacy.py`, `GAP-005`)."""

from __future__ import annotations

import datetime
import json
import unittest
import uuid

from backend.privacy import DeletionAndRetentionService, main as privacy_cli_main
from db import DatabaseEngine
from db.uuid7 import uuid7_str


class TestTTLRetentionJobs(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:")
        self.svc = DeletionAndRetentionService(self.db)
        self.now = datetime.datetime(
            2026, 11, 9, 12, 0, 0, tzinfo=datetime.timezone.utc
        )

    def test_ttl_voice_turn_7_day_hard_delete(self) -> None:
        dev_id = str(uuid.uuid4())
        self.db.upsert_device(dev_id)
        sid = uuid7_str()
        self.db.execute(
            """
            INSERT INTO session (session_id, device_pseudo_id, lang, mode, flags, started_at)
            VALUES (?, ?, 'en-IN', 'guide', '{}', '2026-11-01T00:00:00.000Z')
            """,
            (sid, dev_id),
        )
        # Turn 1: 8 days old -> must be hard-deleted
        self.db.execute(
            """
            INSERT INTO voice_turn (turn_id, session_id, turn_seq, modality, transcript, tutor_text, created_at)
            VALUES (?, ?, 1, 'voice', 'expired transcript', 'expired reply', '2026-11-01T00:00:00.000Z')
            """,
            (uuid7_str(), sid),
        )
        # Turn 2: 2 days old -> must be retained
        self.db.execute(
            """
            INSERT INTO voice_turn (turn_id, session_id, turn_seq, modality, transcript, tutor_text, created_at)
            VALUES (?, ?, 2, 'voice', 'fresh transcript', 'fresh reply', '2026-11-07T12:00:00.000Z')
            """,
            (uuid7_str(), sid),
        )

        deleted = self.svc.purge_expired_voice_turns(now_dt=self.now, ttl_days=7)
        self.assertEqual(deleted, 1)

        rem = self.db.fetchall("SELECT turn_seq, transcript FROM voice_turn")
        self.assertEqual(len(rem), 1)
        self.assertEqual(rem[0]["turn_seq"], 2)

    def test_ttl_coverage_24h_idle_and_abuse_bucket_72h(self) -> None:
        dev_id = str(uuid.uuid4())
        self.db.upsert_device(dev_id)
        sid = uuid7_str()
        self.db.execute(
            """
            INSERT INTO session (
                session_id, device_pseudo_id, lang, mode, flags,
                coverage, coverage_updated_at, coverage_synced, started_at
            ) VALUES (?, ?, 'en-IN', 'guide', '{}', ?, '2026-11-08T00:00:00.000Z', 1, '2026-11-08T00:00:00.000Z')
            """,
            (sid, dev_id, json.dumps([{"block_id": "b-01", "type": "text", "status": "read"}])),
        )
        cleared = self.svc.purge_idle_coverage(now_dt=self.now, ttl_hours=24)
        self.assertEqual(cleared, 1)
        row = self.db.fetchone(
            "SELECT coverage, coverage_synced FROM session WHERE session_id = ?",
            (sid,),
        )
        assert row is not None
        self.assertEqual(row["coverage"], "[]")
        self.assertEqual(int(row["coverage_synced"]), 0)

        # Abuse bucket expiry
        self.db.execute(
            """
            INSERT INTO abuse_bucket (bucket_key, endpoint_family, window_start, count, expires_at)
            VALUES ('hash-expired', 'api', '2026-11-05T00:00:00Z', 10, '2026-11-08T00:00:00Z')
            """
        )
        self.db.execute(
            """
            INSERT INTO abuse_bucket (bucket_key, endpoint_family, window_start, count, expires_at)
            VALUES ('hash-active', 'api', '2026-11-09T11:59:00Z', 2, '2026-11-12T11:59:00Z')
            """
        )
        ab_del = self.svc.purge_expired_abuse_buckets(now_dt=self.now)
        self.assertEqual(ab_del, 1)
        ab_rem = self.db.fetchall("SELECT bucket_key FROM abuse_bucket")
        self.assertEqual(len(ab_rem), 1)
        self.assertEqual(ab_rem[0]["bucket_key"], "hash-active")

    def test_rollup_daily_stats_and_90d_telemetry_purge(self) -> None:
        dev_id = str(uuid.uuid4())
        self.db.upsert_device(dev_id)
        old_sid = uuid7_str()
        # 40-day-old session -> rolled up into daily_stats then deleted
        self.db.execute(
            """
            INSERT INTO session (session_id, device_pseudo_id, lang, mode, flags, started_at, turn_count)
            VALUES (?, ?, 'en-IN', 'guide', '{}', '2026-09-25T10:00:00.000Z', 4)
            """,
            (old_sid, dev_id),
        )
        roll_res = self.svc.rollup_daily_stats_and_prune_sessions(now_dt=self.now)
        self.assertEqual(roll_res["pruned_sessions"], 1)
        stat = self.db.fetchone(
            "SELECT * FROM daily_stats WHERE day = '2026-09-25'"
        )
        assert stat is not None
        self.assertEqual(int(stat["sessions"]), 1)
        self.assertEqual(int(stat["turns"]), 4)

        # 100-day-old telemetry event & resolved report -> deleted by ttl-telemetry
        self.db.execute(
            """
            INSERT INTO telemetry_event (event_id, evt_id, device_pseudo_id, props, ts)
            VALUES (?, 'EVT-001', ?, '{}', '2026-07-01T00:00:00.000Z')
            """,
            (uuid7_str(), dev_id),
        )
        self.db.execute(
            """
            INSERT INTO problem_report (report_id, course_id, category, status, created_at, resolved_at)
            VALUES (?, 'motion', 'other', 'fixed', '2026-06-01T00:00:00.000Z', '2026-07-01T00:00:00.000Z')
            """,
            (uuid7_str(),),
        )
        tel_res = self.svc.purge_expired_telemetry_and_reports(now_dt=self.now)
        self.assertEqual(tel_res["telemetry_deleted"], 1)
        self.assertEqual(tel_res["reports_deleted"], 1)

        # CLI smoke check
        rc = privacy_cli_main(["all-ttl"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
