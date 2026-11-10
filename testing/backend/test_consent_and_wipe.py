"""Tests for consent gating, withdrawal, 8-step device-wipe cascade, and REDEL-01."""

from __future__ import annotations

import unittest
import uuid

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.logging_shim import log_event
from backend.sync import ColdStorageSync
from db.uuid7 import uuid7_str


class TestConsentAndWipeCascade(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            current_notice_version="zivon-voice-notice-v1",
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app)
        self.db = self.app.state.db

    def test_consent_dedup_withdrawal_and_stale_notice_gate(self) -> None:
        dev_id = str(uuid.uuid4())

        # Two rapid identical 'granted' calls within 60s deduplicate to the same consent_id
        r1 = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        r2 = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        self.assertEqual(r1.json()["consent_id"], r2.json()["consent_id"])

        # Bootstrap session while consent is granted
        s_boot = self.client.post(
            "/v1/session",
            json={"device_pseudo_id": dev_id, "lang": "en-IN"},
        ).json()
        sid = s_boot["session_id"]
        tok = s_boot["session_token"]
        self.assertEqual(s_boot["flags"], "voice_enabled")

        # Withdraw consent -> next coverage PUT is blocked with E-CONSENT-REQUIRED
        self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "withdrawn",
            },
        )
        r_cov = self.client.put(
            f"/v1/session/{sid}/coverage",
            json={"covered": [{"block_id": "b-01", "type": "text", "status": "read"}]},
            headers={"Authorization": f"ZivonSession {tok}"},
        )
        self.assertEqual(r_cov.status_code, 403)
        self.assertEqual(r_cov.json()["code"], "E-CONSENT-REQUIRED")

        # Grant with an older notice_version -> blocked with E-CONSENT-STALE
        self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "notice_version": "zivon-voice-notice-v0-old",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        r_stale = self.client.put(
            f"/v1/session/{sid}/coverage",
            json={"covered": [{"block_id": "b-01", "type": "text", "status": "read"}]},
            headers={"Authorization": f"ZivonSession {tok}"},
        )
        self.assertEqual(r_stale.status_code, 403)
        self.assertEqual(r_stale.json()["code"], "E-CONSENT-STALE")

    def test_device_wipe_cascade_and_redelete_on_restore(self) -> None:
        dev_id = str(uuid.uuid4())
        c_res = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        ).json()
        consent_id = c_res["consent_id"]

        s_res = self.client.post(
            "/v1/session",
            json={"device_pseudo_id": dev_id, "lang": "en-IN"},
        ).json()
        sid = s_res["session_id"]

        # Populate voice_turn, telemetry_event, problem_report, eval_kid_session, log_events, and credit_ledger
        self.db.execute(
            """
            INSERT INTO voice_turn (turn_id, session_id, turn_seq, modality, transcript, tutor_text)
            VALUES (?, ?, 1, 'voice', 'student question', 'tutor answer')
            """,
            (uuid7_str(), sid),
        )
        self.client.post(
            "/v1/events",
            json={
                "events": [
                    {
                        "evt_id": "EVT-004",
                        "session_id": sid,
                        "props": {"block_id": "b-02", "correct": True},
                    }
                ]
            },
        )
        self.client.post(
            "/v1/reports",
            json={
                "course_id": "motion",
                "class": 9,
                "category": "wrong_physics",
                "device_pseudo_id": dev_id,
            },
        )
        self.db.execute(
            """
            INSERT INTO eval_kid_session (id, session_code, consent_record_id, topic_slug, gate_b_pass)
            VALUES (?, 'kid-r1-01', ?, 'motion', 1)
            """,
            (uuid7_str(), consent_id),
        )
        log_event("voice.turn.started", {"page_topic": "motion"}, session_id=sid)
        self.app.state.guard.record_ledger_entry(
            device_pseudo_id=dev_id,
            model="prisma",
            units="seconds",
            amount=10.0,
            cost_credits=2.5,
            session_id=sid,
        )

        # Missing or wrong confirm_token -> 400 E-CONFIRM-REQUIRED
        r_bad = self.client.request(
            "DELETE",
            "/v1/data",
            json={
                "device_pseudo_id": dev_id,
                "confirm_token": "invalid.token",
                "scope": "device",
            },
        )
        self.assertEqual(r_bad.status_code, 400)
        self.assertEqual(r_bad.json()["code"], "E-CONFIRM-REQUIRED")

        # Obtain valid server confirm_token challenge and execute wipe
        chal = self.client.get(
            "/v1/data/challenge", params={"device_pseudo_id": dev_id}
        ).json()["confirm_token"]
        r_del = self.client.request(
            "DELETE",
            "/v1/data",
            json={
                "device_pseudo_id": dev_id,
                "confirm_token": chal,
                "scope": "device",
            },
        )
        self.assertEqual(r_del.status_code, 200)
        body = r_del.json()
        self.assertEqual(
            body["deleted"],
            {
                "sessions": 1,
                "consents": 1,
                "events": 1,
                "turns": 1,
                "reports": 1,
            },
        )

        # Verify all personal/pseudonymous child tables are empty for dev_id
        for tbl, col, val in [
            ("device", "device_pseudo_id", dev_id),
            ("session", "device_pseudo_id", dev_id),
            ("consent_record", "device_pseudo_id", dev_id),
            ("telemetry_event", "device_pseudo_id", dev_id),
            ("problem_report", "device_pseudo_id", dev_id),
            ("voice_turn", "session_id", sid),
            ("eval_kid_session", "consent_record_id", consent_id),
        ]:
            rem = self.db.fetchall(f"SELECT * FROM {tbl} WHERE {col} = ?", (val,))
            self.assertEqual(len(rem), 0, f"Expected 0 rows in {tbl}, found {len(rem)}")

        # Verify subject telemetry logs are purged and only the L3 privacy.subject_deleted audit event remains (ADR-0025 §4b)
        subj_logs = self.db.fetchall(
            "SELECT event FROM log_events WHERE session_id = ? AND event != 'privacy.subject_deleted'",
            (sid,),
        )
        self.assertEqual(len(subj_logs), 0)
        audit_logs = self.db.fetchall(
            "SELECT event FROM log_events WHERE session_id = ? AND event = 'privacy.subject_deleted'",
            (sid,),
        )
        self.assertEqual(len(audit_logs), 1)

        # Verify credit_ledger and deletion_request tombstone are preserved
        led = self.db.fetchall(
            "SELECT * FROM credit_ledger WHERE device_pseudo_id = ?", (dev_id,)
        )
        self.assertEqual(len(led), 1)
        tomb = self.db.fetchall(
            "SELECT * FROM deletion_request WHERE device_pseudo_id = ? AND status = 'completed'",
            (dev_id,),
        )
        self.assertEqual(len(tomb), 1)

        # Simulate a backup restore resurrecting the device row, then run REDEL-01
        self.db.upsert_device(dev_id)
        sync = ColdStorageSync(self.db, self.cfg)
        redel = sync.apply_redelete_on_restore()
        self.assertEqual(redel["tombstones_checked"], 1)
        self.assertIsNone(
            self.db.fetchone(
                "SELECT * FROM device WHERE device_pseudo_id = ?", (dev_id,)
            )
        )



        # Re-registering new data for dev_id and replaying the ALREADY-CONSUMED confirm_token must fail (one-time challenge)
        self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": dev_id,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        r_replay = self.client.request(
            "DELETE",
            "/v1/data",
            json={
                "device_pseudo_id": dev_id,
                "confirm_token": chal,
                "scope": "device",
            },
        )
        self.assertEqual(r_replay.status_code, 400)
        self.assertEqual(r_replay.json()["code"], "E-CONFIRM-REQUIRED")


if __name__ == "__main__":
    unittest.main()
