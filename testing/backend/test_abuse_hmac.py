"""Tests for salted daily-rotating HMAC IP hashing and rate-limit middleware (A-12, §8.3)."""

from __future__ import annotations

import datetime
import unittest

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.abuse import AbuseRateLimiter, compute_ip_hmac
from db import DatabaseEngine


class TestAbuseHmacAndRateLimiting(unittest.TestCase):
    def test_daily_rotating_hmac_ip_hash_properties(self) -> None:
        raw_ip = "203.0.113.195"
        salt = "cluster-ip-hash-secret-salt"

        day1 = compute_ip_hmac(raw_ip, salt, utc_date="2026-11-09")
        day1_again = compute_ip_hmac(raw_ip, salt, utc_date="2026-11-09")
        day2 = compute_ip_hmac(raw_ip, salt, utc_date="2026-11-10")
        other_ip = compute_ip_hmac("203.0.113.196", salt, utc_date="2026-11-09")

        self.assertEqual(len(day1), 64)
        self.assertEqual(day1, day1_again)
        self.assertNotEqual(day1, day2, "Daily rotation must change digest across UTC days")
        self.assertNotEqual(day1, other_ip)
        self.assertNotIn(raw_ip, day1)

    def test_rate_limit_families_and_72h_expiry_stamp(self) -> None:
        db = DatabaseEngine.from_url("sqlite:///:memory:")
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            ip_hash_salt="test-salt-xyz",
            rate_limit_delete_per_min=3,
        )
        limiter = AbuseRateLimiter(cfg, db)
        now = datetime.datetime(
            2026, 11, 9, 14, 25, 10, tzinfo=datetime.timezone.utc
        )

        # First 3 requests in the 60s window are allowed; 4th is blocked
        for i in range(1, 4):
            dec = limiter.check_and_increment("198.51.100.42", "delete", now_dt=now)
            self.assertTrue(dec.allowed)
            self.assertEqual(dec.count, i)

        dec4 = limiter.check_and_increment("198.51.100.42", "delete", now_dt=now)
        self.assertFalse(dec4.allowed)
        self.assertEqual(dec4.retry_after, 50)

        # Verify raw IP is never in DB and expires_at is exactly +72h from window_start
        rows = db.fetchall("SELECT * FROM abuse_bucket")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("198.51.100.42", str(rows[0]))
        self.assertEqual(rows[0]["window_start"], "2026-11-09T14:25:00Z")
        self.assertEqual(rows[0]["expires_at"], "2026-11-12T14:25:00Z")

    def test_http_rate_limit_middleware_and_ws_concurrency_caps(self) -> None:
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            rate_limit_api_per_min=2,
            ws_max_concurrent_per_session=1,
            ws_max_concurrent_cluster=2,
        )
        app = create_app(cfg)
        client = TestClient(app)

        # Health endpoints are exempt from rate limiting
        for _ in range(5):
            self.assertEqual(client.get("/v1/health").status_code, 200)

        # API family capped at 2/min in this test config
        headers = {"X-Forwarded-For": "192.0.2.88"}
        r1 = client.get(
            "/v1/data/challenge",
            params={"device_pseudo_id": "11111111-1111-4111-8111-111111111111"},
            headers=headers,
        )
        r2 = client.get(
            "/v1/data/challenge",
            params={"device_pseudo_id": "11111111-1111-4111-8111-111111111111"},
            headers=headers,
        )
        r3 = client.get(
            "/v1/data/challenge",
            params={"device_pseudo_id": "11111111-1111-4111-8111-111111111111"},
            headers=headers,
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 429)
        self.assertEqual(r3.json()["code"], "E-RATE-LIMIT")

        # WebSocket concurrency slots: 1 per session, 2 cluster-wide
        limiter: AbuseRateLimiter = app.state.rate_limiter
        self.assertTrue(limiter.try_acquire_ws_slot("sess-1"))
        self.assertFalse(
            limiter.try_acquire_ws_slot("sess-1"),
            "Second concurrent WS for same session must be rejected",
        )
        self.assertTrue(limiter.try_acquire_ws_slot("sess-2"))
        self.assertFalse(
            limiter.try_acquire_ws_slot("sess-3"),
            "Cluster concurrent WS cap exceeded",
        )
        limiter.release_ws_slot("sess-1")
        self.assertTrue(limiter.try_acquire_ws_slot("sess-3"))


if __name__ == "__main__":
    unittest.main()
