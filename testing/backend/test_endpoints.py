"""Contract tests for student endpoints API-001..009 and admin surface API-A1..A10."""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from db.uuid7 import uuid7_str


class TestBackendEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self._tmp.name) / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.admin_token = "test-admin-secret-token-32-bytes-long!"
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="dev",
            release_tag="0.1.0",
            admin_token=self.admin_token,
            runs_dir=str(self.runs_dir),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_api_008_health_and_probes(self) -> None:
        r_live = self.client.get("/healthz")
        self.assertEqual(r_live.status_code, 200)
        self.assertTrue(r_live.json()["ok"])
        self.assertIn("X-Request-Id", r_live.headers)

        r_ready = self.client.get("/readyz")
        self.assertEqual(r_ready.status_code, 200)
        self.assertEqual(r_ready.json()["db"], "ok")

        r_v1 = self.client.get("/v1/health")
        self.assertEqual(r_v1.status_code, 200)
        body = r_v1.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["db"], "ok")
        self.assertEqual(body["schema_version"], "0002")
        self.assertEqual(body["release"], "0.1.0")
        self.assertEqual(body["guard_profile_mode"], "normal")

    def test_api_001_003_004_009_session_consent_coverage_and_resume(self) -> None:
        dev_id = str(uuid.uuid4())

        # Pre-consent bootstrap: server truth wins over client consent_state claim
        r1 = self.client.post(
            "/v1/session",
            json={
                "device_pseudo_id": dev_id,
                "lang": "hinglish",
                "consent_state": "granted",
                "page": {"course_id": "motion", "class": 9},
            },
        )
        self.assertEqual(r1.status_code, 200)
        b1 = r1.json()
        self.assertTrue(b1["consent_required"])
        self.assertEqual(b1["flags"], "voice_off")
        self.assertEqual(b1["guard_state"], "ok")

        # Coverage sync without consent -> 403 E-CONSENT-REQUIRED
        r_cov_blocked = self.client.put(
            f"/v1/session/{b1['session_id']}/coverage",
            json={"covered": [{"block_id": "b-01", "type": "text", "status": "read"}]},
            headers={"Authorization": f"ZivonSession {b1['session_token']}"},
        )
        self.assertEqual(r_cov_blocked.status_code, 403)
        self.assertEqual(r_cov_blocked.json()["code"], "E-CONSENT-REQUIRED")

        # API-004: Grant consent
        r_con = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        self.assertEqual(r_con.status_code, 200)
        consent_id = r_con.json()["consent_id"]
        self.assertTrue(consent_id)

        # Post-consent bootstrap -> voice_enabled
        r2 = self.client.post(
            "/v1/session",
            json={
                "device_pseudo_id": dev_id,
                "lang": "hi",
                "page": {"course_id": "motion", "class": 9},
            },
        )
        self.assertEqual(r2.status_code, 200)
        b2 = r2.json()
        self.assertFalse(b2["consent_required"])
        self.assertEqual(b2["flags"], "voice_enabled")
        sid = b2["session_id"]
        tok = b2["session_token"]

        # API-003: Coverage PUT succeeds with consent
        cov_items = [
            {"block_id": "b-01", "type": "text", "status": "read"},
            {"block_id": "b-04", "type": "simulation", "status": "interacted"},
        ]
        r_cov = self.client.put(
            f"/v1/session/{sid}/coverage",
            json={"covered": cov_items},
            headers={"Authorization": f"ZivonSession {tok}"},
        )
        self.assertEqual(r_cov.status_code, 200)
        self.assertTrue(r_cov.json()["coverage_synced"])
        self.assertEqual(r_cov.json()["rev"], 1)

        # API-009: Resume session
        r_res = self.client.get(
            f"/v1/session/{sid}",
            headers={"Authorization": f"ZivonSession {tok}"},
        )
        self.assertEqual(r_res.status_code, 200)
        b_res = r_res.json()
        self.assertEqual(b_res["session_id"], sid)
        self.assertEqual(b_res["flags"], "voice_enabled")
        self.assertEqual(len(b_res["coverage"]), 2)
        self.assertEqual(b_res["rev"], 1)

        # Invalid session token -> 401 E-SESSION-EXPIRED
        r_bad = self.client.get(
            f"/v1/session/{sid}",
            headers={"Authorization": "ZivonSession tampered.token"},
        )
        self.assertEqual(r_bad.status_code, 401)
        self.assertEqual(r_bad.json()["code"], "E-SESSION-EXPIRED")

    def test_api_005_events_batch_validation_consent_and_dedup(self) -> None:
        dev_no_consent = str(uuid.uuid4())
        s_no_con = self.client.post(
            "/v1/session",
            json={"device_pseudo_id": dev_no_consent, "lang": "en-IN"},
        ).json()["session_id"]

        # Pre-consent: EVT-001 (allowed), EVT-004 (blocked without consent), free-text (rejected)
        r_batch = self.client.post(
            "/v1/events",
            json={
                "events": [
                    {
                        "event_uuid": "evt-uuid-1",
                        "evt_id": "EVT-001",
                        "session_id": s_no_con,
                        "props": {"page_id": "motion", "lang": "en-IN"},
                    },
                    {
                        "evt_id": "EVT-004",
                        "session_id": s_no_con,
                        "props": {"block_id": "b-07", "correct": True},
                    },
                    {
                        "evt_id": "EVT-001",
                        "session_id": s_no_con,
                        "props": {"transcript": "raw child text forbidden"},
                    },
                    {
                        "evt_id": "EVT-999-UNKNOWN",
                        "session_id": s_no_con,
                        "props": {},
                    },
                ]
            },
        )
        self.assertEqual(r_batch.status_code, 200)
        data = r_batch.json()
        self.assertEqual(data["accepted"], 1)
        self.assertEqual(len(data["rejected"]), 3)
        codes = {item["i"]: item["code"] for item in data["rejected"]}
        self.assertEqual(codes[1], "E-CONSENT-REQUIRED")
        self.assertEqual(codes[2], "E-EVT-SCHEMA")
        self.assertEqual(codes[3], "E-EVT-SCHEMA")

        # Duplicate event_uuid is idempotently accepted without inserting a second row
        r_dup = self.client.post(
            "/v1/events",
            json={
                "events": [
                    {
                        "event_uuid": "evt-uuid-1",
                        "evt_id": "EVT-001",
                        "session_id": s_no_con,
                        "props": {"page_id": "motion", "lang": "en-IN"},
                    }
                ]
            },
        )
        self.assertEqual(r_dup.status_code, 200)
        self.assertEqual(r_dup.json()["accepted"], 1)
        rows = self.app.state.db.fetchall("SELECT * FROM telemetry_event")
        self.assertEqual(len(rows), 1)

    def test_api_006_problem_reports_pii_rejection_and_nonce_dedup(self) -> None:
        # Rejects any PII field in request payload
        r_pii = self.client.post(
            "/v1/reports",
            json={
                "course_id": "motion",
                "class": 9,
                "category": "wrong_physics",
                "name": "Aarav",
            },
        )
        self.assertEqual(r_pii.status_code, 422)
        self.assertEqual(r_pii.json()["code"], "E-VALIDATION")

        # Rejects text > 500 chars
        r_long = self.client.post(
            "/v1/reports",
            json={
                "course_id": "motion",
                "class": 9,
                "category": "wrong_physics",
                "text": "x" * 501,
            },
        )
        self.assertEqual(r_long.status_code, 422)

        # Valid report + idempotent nonce replay
        r_ok1 = self.client.post(
            "/v1/reports",
            json={
                "course_id": "motion",
                "class": 9,
                "block_id": "b-03",
                "category": "wrong_physics",
                "text": "Slope unit should be m/s^2",
                "report_nonce": "nonce-abc-123",
            },
        )
        self.assertEqual(r_ok1.status_code, 200)
        rep_id = r_ok1.json()["report_id"]

        r_ok2 = self.client.post(
            "/v1/reports",
            json={
                "course_id": "motion",
                "class": 9,
                "block_id": "b-03",
                "category": "wrong_physics",
                "text": "Slope unit should be m/s^2",
                "report_nonce": "nonce-abc-123",
            },
        )
        self.assertEqual(r_ok2.status_code, 200)
        self.assertEqual(r_ok2.json()["report_id"], rep_id)

    def test_admin_surface_auth_and_endpoints_a1_through_a10(self) -> None:
        # Unauthenticated -> 401
        r_unauth = self.client.get("/v1/admin/summary")
        self.assertEqual(r_unauth.status_code, 401)
        self.assertEqual(r_unauth.json()["code"], "E-UNAUTHORIZED")

        # Fail-closed 503 when ZIVON_ADMIN_TOKEN is not configured
        unconfigured_app = create_app(
            BackendConfig(db_url="sqlite:///:memory:", admin_token=None)
        )
        unconf_client = TestClient(unconfigured_app)
        r_503 = unconf_client.get(
            "/v1/admin/summary",
            headers={"Authorization": "Bearer any-token"},
        )
        self.assertEqual(r_503.status_code, 503)

        headers = {"Authorization": f"Bearer {self.admin_token}"}
        dev_id = str(uuid.uuid4())
        self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        s_resp = self.client.post(
            "/v1/session",
            json={
                "device_pseudo_id": dev_id,
                "lang": "en-IN",
                "page": {"course_id": "motion", "class": 9},
            },
        ).json()
        sid = s_resp["session_id"]

        # Seed a voice_turn with transcript to verify NFR-30 (never exposed on admin views)
        self.app.state.db.execute(
            """
            INSERT INTO voice_turn (turn_id, session_id, turn_seq, modality, transcript, tutor_text)
            VALUES (?, ?, 1, 'voice', 'PRIVATE_CHILD_TRANSCRIPT_SECRET', 'Tutor explanation')
            """,
            (uuid7_str(), sid),
        )

        # API-A1: summary
        ra1 = self.client.get("/v1/admin/summary", headers=headers)
        self.assertEqual(ra1.status_code, 200)
        self.assertEqual(ra1.json()["sessions_today"], 1)
        self.assertNotIn("PRIVATE_CHILD_TRANSCRIPT_SECRET", ra1.text)

        # API-A2: sessions (aggregate/pseudonymous only, no transcripts)
        ra2 = self.client.get("/v1/admin/sessions", headers=headers)
        self.assertEqual(ra2.status_code, 200)
        self.assertEqual(len(ra2.json()["sessions"]), 1)
        self.assertNotIn("PRIVATE_CHILD_TRANSCRIPT_SECRET", ra2.text)

        # API-A3: credits
        ra3 = self.client.get("/v1/admin/credits", headers=headers)
        self.assertEqual(ra3.status_code, 200)
        self.assertTrue(ra3.json()["drift_within_slo"])

        # API-A4: guard read + profile toggle
        ra4_get = self.client.get("/v1/admin/guard", headers=headers)
        self.assertEqual(ra4_get.status_code, 200)
        self.assertEqual(ra4_get.json()["mode"], "normal")

        ra4_post = self.client.post(
            "/v1/admin/guard/profile",
            json={"mode": "demo"},
            headers=headers,
        )
        self.assertEqual(ra4_post.status_code, 200)
        self.assertEqual(ra4_post.json()["mode"], "demo")

        # API-A6: reports list + patch status
        rep_id = self.client.post(
            "/v1/reports",
            json={"course_id": "motion", "class": 9, "category": "broken_sim"},
        ).json()["report_id"]
        ra6_list = self.client.get("/v1/admin/reports", headers=headers)
        self.assertEqual(ra6_list.status_code, 200)
        self.assertEqual(len(ra6_list.json()["reports"]), 1)

        ra6_patch = self.client.patch(
            f"/v1/admin/reports/{rep_id}",
            json={"status": "fixed"},
            headers=headers,
        )
        self.assertEqual(ra6_patch.status_code, 200)
        self.assertEqual(ra6_patch.json()["status"], "fixed")
        self.assertIsNotNone(ra6_patch.json()["resolved_at"])

        # API-A7: run-tests trigger button
        ra7 = self.client.post("/v1/admin/actions/run-tests", headers=headers)
        self.assertEqual(ra7.status_code, 202)
        self.assertEqual(ra7.json()["script"], "scripts/trigger-tests.sh")

        # API-A8: generate-topic trigger button + shell injection guard
        ra8_bad = self.client.post(
            "/v1/admin/actions/generate-topic",
            json={"chapter": "Motion; rm -rf /", "class": 9},
            headers=headers,
        )
        self.assertEqual(ra8_bad.status_code, 422)

        ra8 = self.client.post(
            "/v1/admin/actions/generate-topic",
            json={"chapter": "Motion", "class": 9, "fresh": True},
            headers=headers,
        )
        self.assertEqual(ra8.status_code, 202)
        self.assertEqual(
            ra8.json()["command"],
            ["scripts/trigger-factory-run.sh", "Motion", "9", "--fresh"],
        )
        run_id = ra8.json()["run_id"]

        # API-A5 & API-A9: runs list, run detail, watch-run logs
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "status.json").write_text(
            json.dumps(
                {
                    "chapter": "Motion",
                    "class_level": 9,
                    "current_stage": "02-generate",
                    "ok": True,
                }
            ),
            encoding="utf-8",
        )
        ra5_list = self.client.get("/v1/admin/runs", headers=headers)
        self.assertEqual(ra5_list.status_code, 200)
        self.assertGreaterEqual(len(ra5_list.json()["runs"]), 1)

        ra5_detail = self.client.get(f"/v1/admin/runs/{run_id}", headers=headers)
        self.assertEqual(ra5_detail.status_code, 200)
        self.assertEqual(ra5_detail.json()["verdict"], "pass")

        ra9 = self.client.get(
            f"/v1/admin/actions/watch-run/{run_id}/logs", headers=headers
        )
        self.assertEqual(ra9.status_code, 200)
        self.assertEqual(ra9.json()["label_selector"], "task=factory-run")
        self.assertEqual(len(ra9.json()["logs"]), 1)

        # API-A9 guard: run_id is a path component. Only the slug allowlist is
        # accepted, and an unknown (but well-formed) id reads nothing.
        for bad_run_id in (".hidden", "Upper", "a_b~c"):
            bad = self.client.get(
                f"/v1/admin/actions/watch-run/{bad_run_id}/logs", headers=headers
            )
            self.assertEqual(bad.status_code, 422, bad_run_id)
        # Second, independent barrier: a run directory that resolves outside
        # runs_dir (e.g. a planted symlink) is never read, even with a valid slug.
        outside = Path(self._tmp.name) / "outside-run"
        outside.mkdir()
        (outside / "status.json").write_text('{"leak": true}', encoding="utf-8")
        link = self.runs_dir / "escape-run"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:  # pragma: no cover - filesystem without symlink support
            self.skipTest("symlinks unsupported on this filesystem")
        escaped = self.client.get(
            "/v1/admin/actions/watch-run/escape-run/logs", headers=headers
        )
        self.assertEqual(escaped.status_code, 200)
        self.assertEqual(escaped.json()["logs"], [])
        self.assertNotIn("leak", escaped.text)
        unknown = self.client.get(
            "/v1/admin/actions/watch-run/does-not-exist/logs", headers=headers
        )
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.json()["logs"], [])

        # API-A10: audit log
        ra10 = self.client.get("/v1/admin/audit", headers=headers)
        self.assertEqual(ra10.status_code, 200)
        actions = [row["action"] for row in ra10.json()["audit"]]
        self.assertIn("guard_profile.flip", actions)
        self.assertIn("report.status", actions)
        self.assertIn("trigger.run-tests", actions)
        self.assertIn("trigger.generate-topic", actions)

    def test_voice_websocket_mount_stub(self) -> None:
        dev_id = str(uuid.uuid4())
        self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        tok = self.client.post(
            "/v1/session",
            json={"device_pseudo_id": dev_id, "lang": "en-IN"},
        ).json()["session_token"]

        with self.client.websocket_connect(f"/v1/voice?session_token={tok}") as ws:
            ws.send_json({"type": "ping"})
            reply = ws.receive_json()
            self.assertEqual(reply["type"], "pong")
            ws.send_json({"type": "session.start", "session_token": tok})
            state_msg = ws.receive_json()
            self.assertEqual(state_msg["type"], "state")
            self.assertEqual(state_msg["payload"]["state"], "voice_enabled")


if __name__ == "__main__":
    unittest.main()
