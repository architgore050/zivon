"""PL1 logging canary (DET-PL05-LOGS) and account-deletion cascade tests.

The canary: seed `PII_CANARY_7f3a` and student sentences into a session, drive
the API, and assert NO structured-log payload contains the canary, the message
text, or the weakness — plus that every emitted key stays in the allow-list
(security-privacy.md §4.6). The cascade: `AuthService.delete_account` removes
every personalized row (C22-C25) and only the users tombstone remains.
"""

from __future__ import annotations

import json
import unittest

from evals.checkers.personalized_checks import PL_EVENT_ALLOWED_KEYS
from testing.backend.web_auth_support import PASSWORD, WebAuthSupport

_CANARY = "PII_CANARY_7f3a"
_WEAKNESS = f"I hide {_CANARY} inside my weakness about mirrors"
_MESSAGE_TEXT = "my secret sentence about the focal length and the mirror"

# Fields allowed in personalized/privacy event payloads (§4.6: ids, enums,
# counts; never text). ONE contract: imported from the PL5 checker so this
# suite and `testing/backend/test_personalized_security.py` (which pins the
# equality) can never drift from it — the turn/usage/retention keys are part
# of the same §4.6 allow-list.
_ALLOWED_KEYS = set(PL_EVENT_ALLOWED_KEYS)


class PersonalizedLoggingCanaryTest(WebAuthSupport):
    def setUp(self) -> None:
        super().setUp()
        self.db.execute(
            "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
            "VALUES ('class-10-light', 10, 'physics', 10, 'light', 'Light')"
        )
        self.register_via_api()
        self.csrf = self.session_csrf()

    def _log_rows(self) -> list[dict]:  # type: ignore[type-arg]
        rows = self.db.fetchall("SELECT event, fields FROM log_events")
        return [
            {"event": str(r["event"]), "fields": json.loads(str(r["fields"]) or "{}")}
            for r in rows
        ]

    def test_no_log_payload_carries_canary_or_free_text(self) -> None:
        created = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": "class-10-light", "weakness_text": _WEAKNESS},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        session_id = created.json()["session_id"]
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text) "
            "VALUES ('m-0', ?, 0, 'student', 'text', ?)",
            (session_id, _MESSAGE_TEXT),
        )
        self.client.get(f"/v1/personalized/sessions/{session_id}/export")
        self.client.post(
            f"/v1/personalized/sessions/{session_id}/end",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.client.post(
            f"/v1/personalized/sessions/{session_id}/resume",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.client.delete(
            f"/v1/personalized/sessions/{session_id}",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.client.put(
            "/v1/me/preferences",
            json={"personal_instructions": f"prefer {_CANARY} hints"},
            headers={"X-CSRF-Token": self.csrf},
        )
        rows = self._log_rows()
        self.assertTrue(rows, "no structured events captured at all")
        for row in rows:
            blob = json.dumps(row, ensure_ascii=False)
            with self.subTest(event=row["event"]):
                self.assertNotIn(_CANARY, blob)
                self.assertNotIn(_MESSAGE_TEXT, blob)
                self.assertNotIn("my weakness about mirrors", blob)
        # The event-key allow-list: no payload carries free-text-shaped keys.
        for row in rows:
            for key in row["fields"]:
                with self.subTest(event=row["event"], key=key):
                    self.assertIn(key, _ALLOWED_KEYS, f"unexpected log key {key!r}")

    def test_emitted_events_resolve_to_map_rows(self) -> None:
        from logging_manager import events as ev

        self.client.put(
            "/v1/me/preferences",
            json={"personal_instructions": "explain slowly"},
            headers={"X-CSRF-Token": self.csrf},
        )
        created = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": "class-10-light"},
            headers={"X-CSRF-Token": self.csrf},
        )
        session_id = created.json()["session_id"]
        self.client.post(
            f"/v1/personalized/sessions/{session_id}/end",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.client.post(
            f"/v1/personalized/sessions/{session_id}/resume",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.client.delete(
            f"/v1/personalized/sessions/{session_id}",
            headers={"X-CSRF-Token": self.csrf},
        )
        events = {row["event"] for row in self._log_rows()}
        self.assertIn("personalized.session.resumed", events)
        for row in self._log_rows():
            if row["event"] == "log.store_fallback":
                continue
            with self.subTest(event=row["event"]):
                self.assertIsNotNone(
                    ev.known_event(row["event"]),
                    f"event {row['event']} has no instrumentation-map row",
                )

    def _resumed_event_count(self) -> int:
        return len(
            [
                row
                for row in self._log_rows()
                if row["event"] == "personalized.session.resumed"
            ]
        )

    def test_a_page_reload_of_an_active_session_is_not_a_resume(self) -> None:
        """§4.7 / the map row: the resumed event belongs to the resume POST —
        a detail GET (a page reload) of an already-active session emits
        nothing. The session has turns taken, the shape the old
        emit-on-read behaviour keyed on."""
        created = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": "class-10-light"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        session_id = created.json()["session_id"]
        self.client.post(
            f"/v1/personalized/sessions/{session_id}/end",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.client.post(
            f"/v1/personalized/sessions/{session_id}/resume",
            headers={"X-CSRF-Token": self.csrf},
        )
        # A session the machine has advanced (turn_count > 0 lives in state).
        self.db.execute(
            "UPDATE personalized_session SET state = ? WHERE session_id = ?",
            ('{"schema_version": 1, "turn_count": 5}', session_id),
        )
        self.assertEqual(
            self._resumed_event_count(),
            1,
            "one resume POST emits exactly one resumed event",
        )
        for _ in range(2):
            detail = self.client.get(f"/v1/personalized/sessions/{session_id}")
            self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            self._resumed_event_count(),
            1,
            "a detail read of an active session must not emit the resumed event",
        )


class AccountDeletionCascadeTest(WebAuthSupport):
    def setUp(self) -> None:
        super().setUp()
        self.register_via_api()
        self.csrf = self.session_csrf()
        self.db.execute(
            "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
            "VALUES ('class-9-motion', 9, 'physics', 8, 'motion', 'Motion')"
        )

    def test_account_delete_removes_every_personalized_row(self) -> None:
        self.client.put(
            "/v1/me/preferences",
            json={"personal_instructions": "explain slowly"},
            headers={"X-CSRF-Token": self.csrf},
        )
        created = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": "class-9-motion", "weakness_text": "confused"},
            headers={"X-CSRF-Token": self.csrf},
        )
        session_id = created.json()["session_id"]
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text) "
            "VALUES ('m-0', ?, 0, 'student', 'text', 'why?')",
            (session_id,),
        )
        user_id = self.client.get("/v1/auth/session").json()["user"]["user_id"]
        quota_svc_quota_row = (
            "INSERT INTO personalized_quota (period, scope, scope_key) "
            "VALUES ('2026-11-16', 'user', ?)"
        )
        self.db.execute(quota_svc_quota_row, (user_id,))
        self.db.execute(
            "INSERT INTO personalized_usage (usage_id, user_id, session_id) "
            "VALUES ('u-1', ?, ?)",
            (user_id, session_id),
        )

        response = self.client.post(
            "/v1/me/delete",
            json={"confirm": "DELETE", "password": PASSWORD},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        deleted = response.json()["deleted"]
        self.assertEqual(deleted["preferences"], 1)
        self.assertEqual(deleted["personalized_sessions"], 1)
        self.assertEqual(deleted["personalized_usage"], 1)
        self.assertEqual(deleted["personalized_quota"], 1)
        for table, where in (
            ("user_preferences", f"user_id = '{user_id}'"),
            ("personalized_session", f"user_id = '{user_id}'"),
            ("personalized_message", f"session_id = '{session_id}'"),
            ("personalized_usage", f"user_id = '{user_id}'"),
            ("personalized_quota", f"scope_key = '{user_id}'"),
        ):
            row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}")
            assert row is not None
            self.assertEqual(int(row["c"]), 0, table)
        # Only the tombstone remains (ADR-0029).
        tomb = self.db.fetchone(
            "SELECT email, deleted_at FROM users WHERE user_id = ?", (user_id,)
        )
        assert tomb is not None
        self.assertTrue(str(tomb["email"]).startswith("deleted+"))
        self.assertIsNotNone(tomb["deleted_at"])

    def test_export_includes_preferences_and_session_summary_without_text(self) -> None:
        self.client.put(
            "/v1/me/preferences",
            json={"personal_instructions": "explain slowly"},
            headers={"X-CSRF-Token": self.csrf},
        )
        created = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": "class-9-motion", "weakness_text": "confused"},
            headers={"X-CSRF-Token": self.csrf},
        )
        session_id = created.json()["session_id"]
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text) "
            "VALUES ('m-0', ?, 0, 'student', 'text', 'a private sentence')",
            (session_id,),
        )
        payload = self.client.get("/v1/me/export").json()
        self.assertEqual(
            payload["preferences"]["personal_instructions"], "explain slowly"
        )
        self.assertEqual(payload["personalized_sessions_total"], 1)
        summary = payload["personalized_sessions"][0]
        self.assertEqual(summary["session_id"], session_id)
        self.assertNotIn("state", summary)
        # The account export carries no message text (per-session export does).
        self.assertNotIn("messages", summary)


if __name__ == "__main__":
    unittest.main()
