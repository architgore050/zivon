"""PL1 session-surface tests (API-PL-05…09, 12, 15 + the honest turn stub).

Owner scoping (DET-PL05-IDOR): every endpoint derives the owner from the
session cookie; another user's id is 404. CSRF (DET-PL05-CSRF): every write
without/with a bad token is 403 and changes nothing. Export (DET-PL05-EXPORT):
owner's data only, schema-versioned, never the answer key.
"""

from __future__ import annotations

import datetime
import json
import unittest
from typing import Any, ClassVar

from testing.backend.web_auth_support import PASSWORD, WebAuthSupport

_CHAPTER = "class-10-light-reflection-and-refraction"
_CHAPTER2 = "class-9-motion"


def _seed_chapters(db) -> None:  # type: ignore[no-untyped-def]
    """Two syllabus chapters + concepts, the minimum catalogue the picker needs."""
    db.execute(
        "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
        "VALUES (?, 10, 'physics', 10, 'light-reflection-and-refraction', "
        "'Light – Reflection and Refraction')",
        (_CHAPTER,),
    )
    db.execute(
        "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
        "VALUES (?, 9, 'physics', 8, 'motion', 'Motion')",
        (_CHAPTER2,),
    )
    db.execute(
        "INSERT INTO concept (concept_id, chapter_id, slug, title_en, order_index) "
        "VALUES (?, ?, 'spherical-mirrors', 'Spherical mirrors', 1)",
        ("class-10-spherical-mirrors", _CHAPTER),
    )
    db.execute(
        "INSERT INTO concept (concept_id, chapter_id, slug, title_en, order_index) "
        "VALUES (?, ?, 'reflection-of-light', 'Reflection of light', 0)",
        ("class-10-reflection-of-light", _CHAPTER),
    )


class PersonalizedSessionsTest(WebAuthSupport):
    # Lift the hourly create family above the daily session cap so the
    # E-QUOTA-EXHAUSTED path (not the IP rate limiter) is what the day-quota
    # test observes; the family limiter itself is covered by the 429 test.
    config_overrides: ClassVar[dict[str, Any]] = {
        "rate_limit_personalized_create_per_hour": 50
    }

    def setUp(self) -> None:
        super().setUp()
        _seed_chapters(self.db)
        self.register_via_api()
        self.csrf = self.session_csrf()

    def _create(self, **overrides: object) -> dict:  # type: ignore[type-arg]
        body: dict[str, object] = {
            "chapter_id": _CHAPTER,
            "concept_ids": ["class-10-spherical-mirrors"],
            "weakness_text": "I don't get why the image flips",
        }
        body.update(overrides)
        response = self.client.post(
            "/v1/personalized/sessions",
            json=body,
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()  # type: ignore[no-any-return]

    # -- create ------------------------------------------------------------------

    def test_create_returns_server_generated_title_and_quota(self) -> None:
        payload = self._create()
        self.assertTrue(payload["session_id"])
        # The title comes from the chapter/concept, never from the free text.
        self.assertEqual(
            payload["title"],
            "Light – Reflection and Refraction · class-10-spherical-mirrors",
        )
        self.assertNotIn("image flips", payload["title"])
        self.assertEqual(payload["stage"], "diagnose")
        self.assertEqual(payload["class_level"], 10)
        self.assertEqual(payload["diagnostic"]["remaining"], 0)
        self.assertIsNone(payload["diagnostic"]["first_question"])
        self.assertIn("turns_remaining", payload["quota"])
        self.assertIn("reset_at", payload["quota"])

    def test_create_with_weakness_only_resolves_one_chapter_lexically(self) -> None:
        response = self.client.post(
            "/v1/personalized/sessions",
            json={"weakness_text": "spherical mirrors confuse me"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["title"].startswith("Light"), True)

    def test_create_ambiguous_weakness_is_422_never_a_guess(self) -> None:
        response = self.client.post(
            "/v1/personalized/sessions",
            json={"weakness_text": "I am confused about everything today"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["reason"], "chapter_required")

    def test_create_validates_concepts_and_parent(self) -> None:
        bad_concept = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": _CHAPTER, "concept_ids": ["class-9-motion-is-fine"]},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(bad_concept.status_code, 422)
        self.assertEqual(bad_concept.json()["reason"], "concept_not_in_chapter")
        bad_parent = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": _CHAPTER, "parent_session_id": "missing"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(bad_parent.status_code, 422)
        self.assertEqual(bad_parent.json()["reason"], "invalid_parent")

    def test_create_guest_401_and_write_csrf_403(self) -> None:
        guest = type(self.client)(app=self.app, base_url="https://testserver")
        self.assertEqual(
            guest.post(
                "/v1/personalized/sessions", json={"chapter_id": _CHAPTER}
            ).status_code,
            401,
        )
        missing_csrf = self.client.post(
            "/v1/personalized/sessions", json={"chapter_id": _CHAPTER}
        )
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(missing_csrf.json()["code"], "E-AUTH-CSRF")
        self.assertEqual(
            int(
                self.db.fetchone("SELECT COUNT(*) AS c FROM personalized_session")["c"]
            ),
            0,
        )

    def test_session_day_quota_403_after_five_creates(self) -> None:
        for _ in range(5):
            self._create()
        sixth = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": _CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(sixth.status_code, 403)
        self.assertEqual(sixth.json()["code"], "E-QUOTA-EXHAUSTED")

    def test_skip_diagnostic_starts_at_teach(self) -> None:
        payload = self._create(skip_diagnostic=True)
        self.assertEqual(payload["stage"], "teach")

    # -- list / detail / messages ---------------------------------------------------

    def test_list_orders_and_hides_weakness_text(self) -> None:
        first = self._create()
        second = self._create()
        items = self.client.get("/v1/personalized/sessions").json()["items"]
        self.assertEqual(len(items), 2)
        ids = [i["session_id"] for i in items]
        self.assertIn(first["session_id"], ids)
        self.assertIn(second["session_id"], ids)
        for item in items:
            self.assertNotIn("weakness_text", item)
            self.assertNotIn("state", item)

    def test_list_cursor_pages_through(self) -> None:
        for _ in range(3):
            self._create()
        page1 = self.client.get("/v1/personalized/sessions?limit=2").json()
        self.assertEqual(len(page1["items"]), 2)
        self.assertIsNotNone(page1["next"])
        page2 = self.client.get(
            f"/v1/personalized/sessions?limit=2&cursor={page1['next']}"
        ).json()
        self.assertEqual(len(page2["items"]), 1)
        self.assertIsNone(page2["next"])
        all_ids = {i["session_id"] for i in page1["items"] + page2["items"]}
        self.assertEqual(len(all_ids), 3)

    def test_detail_returns_state_and_last_messages(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text) "
            "VALUES ('m-0', ?, 0, 'tutor', 'text', 'Let us start with mirrors.')",
            (session_id,),
        )
        detail = self.client.get(f"/v1/personalized/sessions/{session_id}")
        self.assertEqual(detail.status_code, 200)
        body = detail.json()
        self.assertEqual(body["session"]["session_id"], session_id)
        self.assertEqual(
            body["session"]["weakness_text"], "I don't get why the image flips"
        )
        self.assertEqual(body["messages"][0]["text"], "Let us start with mirrors.")
        self.assertIn("quota", body)

    def test_messages_endpoint_pages_earlier_turns(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        for idx in range(7):
            self.db.execute(
                "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text) "
                f"VALUES ('m-{idx}', ?, {idx}, 'tutor', 'text', 'msg {idx}')",
                (session_id,),
            )
        page = self.client.get(
            f"/v1/personalized/sessions/{session_id}/messages?before=5&limit=3"
        )
        self.assertEqual(page.status_code, 200)
        indexes = [m["turn_index"] for m in page.json()["items"]]
        self.assertEqual(indexes, [2, 3, 4])

    # -- IDOR: another user's id is 404 everywhere ----------------------------------

    def test_other_users_session_is_404_on_every_endpoint(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        guest = type(self.client)(app=self.app, base_url="https://testserver")
        guest.post(
            "/v1/auth/register",
            json={"email": "other@example.com", "password": PASSWORD},
        )
        other_csrf = guest.get("/v1/auth/session").json()["csrf_token"]
        paths = [
            f"/v1/personalized/sessions/{session_id}",
            f"/v1/personalized/sessions/{session_id}/export",
            f"/v1/personalized/sessions/{session_id}/messages",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(guest.get(path).status_code, 404)
        self.assertEqual(
            guest.post(
                f"/v1/personalized/sessions/{session_id}/turns",
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )
        self.assertEqual(
            guest.post(
                f"/v1/personalized/sessions/{session_id}/end",
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )
        self.assertEqual(
            guest.delete(
                f"/v1/personalized/sessions/{session_id}",
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )
        # The create response never leaks another user's parent either.
        bad_parent = guest.post(
            "/v1/personalized/sessions",
            json={"chapter_id": _CHAPTER, "parent_session_id": session_id},
            headers={"X-CSRF-Token": other_csrf},
        )
        self.assertEqual(bad_parent.status_code, 422)

    # -- end / export / delete ---------------------------------------------------------

    def test_end_is_idempotent_with_summary(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        first = self.client.post(
            f"/v1/personalized/sessions/{session_id}/end",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "completed")
        summary = first.json()["summary"]
        self.assertEqual(summary["concept_total"], 1)
        second = self.client.post(
            f"/v1/personalized/sessions/{session_id}/end",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())

    def test_export_is_owner_scoped_schema_versioned_and_keyless(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        # A scored check (answer_key already NULL) and an unsubmitted one.
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text, payload) "
            "VALUES ('m-0', ?, 0, 'tutor', 'check', 'What is the focal length?', "
            '\'{"check_id": "chk-1", "expected": "-18 cm"}\')',
            (session_id,),
        )
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text, payload, answer_key) "
            "VALUES ('m-1', ?, 1, 'tutor', 'check', 'Which mirror always diverges?', "
            "'{\"check_id\": \"chk-2\"}', 'convex mirror')",
            (session_id,),
        )
        response = self.client.get(f"/v1/personalized/sessions/{session_id}/export")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.headers["Content-Disposition"].startswith("attachment;")
        )
        body = json.loads(response.text)
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["session"]["session_id"], session_id)
        self.assertEqual(len(body["messages"]), 2)
        self.assertNotIn("answer_key", body["messages"][1])
        # The submitted check carries the expected value the student saw; the
        # unsubmitted one carries no key at all.
        self.assertEqual(body["messages"][0]["payload"]["expected"], "-18 cm")
        self.assertNotIn("expected", body["messages"][1]["payload"])
        self.assertIn("preferences", body)
        self.assertIn("mastery", body)
        self.assertIn("artifacts", body)

    def test_delete_removes_messages_and_detaches_usage(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        self.db.execute(
            "INSERT INTO personalized_message (message_id, session_id, turn_index, role, kind, text) "
            "VALUES ('m-0', ?, 0, 'student', 'text', 'why?')",
            (session_id,),
        )
        self.db.execute(
            "INSERT INTO personalized_usage (usage_id, user_id, session_id) "
            "VALUES ('u-0', (SELECT user_id FROM users LIMIT 1), ?)",
            (session_id,),
        )
        response = self.client.delete(
            f"/v1/personalized/sessions/{session_id}",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(
            self.db.fetchone(
                "SELECT 1 AS x FROM personalized_session WHERE session_id = ?",
                (session_id,),
            )
        )
        self.assertEqual(
            int(
                self.db.fetchone("SELECT COUNT(*) AS c FROM personalized_message")["c"]
            ),
            0,
        )
        usage = self.db.fetchone(
            "SELECT session_id FROM personalized_usage WHERE usage_id = 'u-0'"
        )
        assert usage is not None
        self.assertIsNone(usage["session_id"])
        second = self.client.delete(
            f"/v1/personalized/sessions/{session_id}",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(second.status_code, 404)

    def test_last_turn_at_advances_on_every_appended_message(self) -> None:
        """The 90-day TTL clock (data-and-api.md §2.2) tracks the LAST turn.

        `last_turn_at` drives retention (D-PL-05: 90 days from last activity);
        an appended message must advance it even when it already held an older
        value — a clock stuck on the session's first turn would delete a live
        session mid-use.
        """
        from backend.personalized.store import PersonalizedStore

        payload = self._create()
        session_id = payload["session_id"]
        stale = "2026-05-01T00:00:00.000Z"
        self.db.execute(
            "UPDATE personalized_session SET last_turn_at = ? WHERE session_id = ?",
            (stale, session_id),
        )
        store = PersonalizedStore(self.db)
        store.append_message(
            session_id=session_id, role="tutor", kind="text", text="hello"
        )
        row = self.db.fetchone(
            "SELECT last_turn_at FROM personalized_session WHERE session_id = ?",
            (session_id,),
        )
        assert row is not None
        advanced = str(row["last_turn_at"])
        self.assertGreater(
            advanced,
            stale,
            "appending a message must advance last_turn_at (the retention clock)",
        )
        # The list summary's deletes_at moves with the advanced clock too:
        # advanced last_turn_at + the 90-day retention window.
        last_dt = datetime.datetime.fromisoformat(advanced)
        expected_day = (last_dt + datetime.timedelta(days=90)).date().isoformat()
        listing = self.client.get("/v1/personalized/sessions").json()
        summary = next(
            item for item in listing["items"] if item["session_id"] == session_id
        )
        self.assertIsNotNone(summary["deletes_at"])
        self.assertTrue(
            str(summary["deletes_at"]).startswith(expected_day),
            "deletes_at must track the last turn, not the first one",
        )

    # -- the honest turn stub + usage ---------------------------------------------------

    def test_turn_stub_is_503_model_down_without_quota_side_effects(self) -> None:
        payload = self._create()
        session_id = payload["session_id"]
        response = self.client.post(
            f"/v1/personalized/sessions/{session_id}/turns",
            json={"action": "answer", "text": "convex"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "E-PL-MODEL-DOWN")
        self.assertEqual(
            int(self.db.fetchone("SELECT COUNT(*) AS c FROM personalized_usage")["c"]),
            0,
        )
        quota = self.db.fetchone("SELECT turns_reserved FROM personalized_quota")
        self.assertIsNone(quota)

    def test_usage_endpoint_reports_caps_and_reset(self) -> None:
        usage = self.client.get("/v1/personalized/usage").json()
        self.assertEqual(usage["turns"]["cap"], 40)
        self.assertEqual(usage["turns"]["remaining"], 40)
        self.assertEqual(usage["artifacts"]["cap"], 12)
        self.assertTrue(usage["enabled"])
        self.assertIn("reset_at", usage)
        self.assertIn("global", usage)

    def test_catalog_is_honest_503_without_the_index(self) -> None:
        response = self.client.get("/v1/personalized/catalog")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "E-CONTENT-UNAVAILABLE")

    # -- rate-limit family (DET-PL05-RATE) ----------------------------------------------

    def test_read_family_429_with_retry_after(self) -> None:
        cfg_limit = self.cfg.rate_limit_personalized_read_per_min
        seen_429 = None
        for i in range(cfg_limit + 2):
            response = self.client.get("/v1/personalized/usage")
            if response.status_code == 429:
                seen_429 = response
                break
        self.assertIsNotNone(seen_429)
        assert seen_429 is not None
        self.assertEqual(seen_429.json()["code"], "E-RATE-LIMIT")
        self.assertIn("Retry-After", seen_429.headers)


if __name__ == "__main__":
    unittest.main()
