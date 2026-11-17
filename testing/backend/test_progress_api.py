"""Progress API contract (`/v1/progress/*`, `/v1/bookmarks` — F3).

Hermetic: SQLite in memory, the dev email sink, no network, no keys. Covers
auth and CSRF reuse, per-item validation, the five state rules, weekly rhythm,
chapter detail, bookmark CRUD, tenant isolation, and the no-free-text promise.
"""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.progress import EventRow, build_summary, catalogue_snapshot

PASSWORD = "correct-horse-battery-staple"
CHAPTER = "class-9-describing-motion-around-us"
CONCEPT = "class-9-describing-motion-around-us-sec-01"
CHAPTER_B = "class-9-how-forces-affect-motion"
CHAPTER_C = "class-11-units-and-measurement"


def iso(days_ago: float = 0, *, hours_ago: float = 0) -> str:
    moment = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        days=days_ago, hours=hours_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def stamp(seconds_ago: float) -> str:
    """A readable, strictly increasing timestamp for order-sensitive events."""
    moment = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
        seconds=seconds_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


class ProgressApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=20,
            auth_register_per_min=20,
            rate_limit_api_per_min=200,
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.db = self.app.state.db
        self.register("kid@example.com")
        self.csrf = self._csrf()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def register(self, email: str) -> None:
        response = self.client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

    def _csrf(self) -> str:
        payload = self.client.get("/v1/auth/session").json()
        self.assertTrue(payload["authenticated"])
        return str(payload["csrf_token"])

    def post_events(self, events: list[dict[str, Any]], *, csrf: bool = True) -> Any:
        headers = {"X-CSRF-Token": self.csrf} if csrf else {}
        return self.client.post(
            "/v1/progress/events", json={"events": events}, headers=headers
        )

    def lesson_event(
        self,
        *,
        chapter_id: str = CHAPTER,
        concept_id: str | None = CONCEPT,
        section_id: str = "sec-01",
        **payload: Any,
    ) -> dict[str, Any]:
        return {
            "kind": "lesson_block_view",
            "chapter_id": chapter_id,
            "concept_id": concept_id,
            "payload": {
                "section_id": section_id,
                "source": "lesson_shell",
                **payload,
            },
        }

    def answer_event(
        self,
        *,
        correct: bool,
        chapter_id: str = CHAPTER,
        concept_id: str | None = CONCEPT,
    ) -> dict[str, Any]:
        return {
            "kind": "practice_answer",
            "chapter_id": chapter_id,
            "concept_id": concept_id,
            "payload": {"correct": correct, "source": "merge"},
        }

    def summary(self) -> dict[str, Any]:
        response = self.client.get("/v1/progress/summary")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def chapter_map(self, chapter_id: str = CHAPTER) -> dict[str, Any]:
        payload = self.summary()
        for group in payload["classes"]:
            for chapter in group["chapters"]:
                if chapter["chapter_id"] == chapter_id:
                    return chapter
        self.fail(f"{chapter_id} is not on the map")

    # -- auth ---------------------------------------------------------------

    def test_guest_cannot_read_or_write_progress(self) -> None:
        guest = TestClient(self.app, base_url="https://testserver")
        for method, path, body in (
            ("get", "/v1/progress/summary", None),
            ("get", f"/v1/progress/chapters/{CHAPTER}", None),
            ("get", "/v1/bookmarks", None),
            ("post", "/v1/progress/events", {"events": []}),
            (
                "post",
                "/v1/bookmarks",
                {"target_type": "chapter", "target_id": CHAPTER},
            ),
        ):
            if body is None:
                response = getattr(guest, method)(path)
            else:
                response = getattr(guest, method)(path, json=body)
            self.assertEqual(response.status_code, 401, (method, path, response.text))
            self.assertEqual(response.json()["code"], "E-AUTH-REQUIRED")

    def test_writes_require_the_account_csrf_header(self) -> None:
        self.assertEqual(
            self.post_events([self.lesson_event()], csrf=False).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                "/v1/bookmarks",
                json={"target_type": "chapter", "target_id": CHAPTER},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(
                "/v1/bookmarks",
                params={"target_type": "chapter", "target_id": CHAPTER},
            ).status_code,
            403,
        )

    # -- validation ---------------------------------------------------------

    def test_valid_and_invalid_items_are_resolved_per_item(self) -> None:
        response = self.post_events(
            [
                self.lesson_event(),
                {"kind": "made_up", "chapter_id": CHAPTER, "payload": {}},
                {
                    "kind": "lesson_block_view",
                    "chapter_id": CHAPTER,
                    "payload": {"note": "my teacher said so"},
                },
                {
                    "kind": "lesson_block_view",
                    "chapter_id": CHAPTER,
                    "payload": {"source": "because"},
                },
                {
                    "kind": "lesson_block_view",
                    "chapter_id": CHAPTER,
                    "payload": {"section_id": "Sec 1"},
                },
                {
                    "kind": "lesson_block_view",
                    "chapter_id": CHAPTER,
                    "payload": {"blocks_seen": {"n": 1}},
                },
                {
                    "kind": "practice_answer",
                    "chapter_id": "Class 9 Motion",
                    "payload": {"correct": True},
                },
                {
                    "kind": "practice_answer",
                    "chapter_id": CHAPTER,
                    "payload": {"correct": "yes"},
                },
                {
                    "kind": "practice_answer",
                    "chapter_id": CHAPTER,
                    "payload": {"correct": 1},
                },
            ]
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["accepted"], 1)
        self.assertEqual(
            [item["index"] for item in body["rejected"]], list(range(1, 9))
        )
        self.assertTrue(
            all(item["code"] == "E-EVT-SCHEMA" for item in body["rejected"])
        )
        self.assertEqual(self.chapter_map()["state"], "learning")

    def test_batch_envelope_is_bounded(self) -> None:
        too_many = [self.lesson_event(section_id=f"sec-{i:02d}") for i in range(41)]
        self.assertEqual(self.post_events(too_many).status_code, 422)
        self.assertEqual(
            self.client.post(
                "/v1/progress/events",
                json={"events": "not-a-list"},
                headers={"X-CSRF-Token": self.csrf},
            ).status_code,
            422,
        )
        extra = self.lesson_event()
        extra["unexpected"] = "field"
        self.assertEqual(self.post_events([extra]).status_code, 422)
        empty = self.post_events([])
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json(), {"accepted": 0, "rejected": []})

    def test_no_free_text_reaches_the_database(self) -> None:
        self.post_events(
            [
                {
                    "kind": "practice_answer",
                    "chapter_id": CHAPTER,
                    "payload": {"correct": True, "note": "my answer is 42"},
                }
            ]
        )
        row = self.db.fetchone("SELECT payload FROM progress_event")
        self.assertIsNone(row, "the rejected event must not be stored")
        self.post_events([self.answer_event(correct=True)])
        row = self.db.fetchone("SELECT payload FROM progress_event")
        assert row is not None
        self.assertEqual(set(json.loads(row["payload"])), {"correct", "source"})

    def test_future_client_time_is_clamped_to_the_server_receipt_time(self) -> None:
        event = self.lesson_event()
        event["occurred_at"] = "2099-01-01T00:00:00Z"
        self.assertEqual(self.post_events([event]).status_code, 200)
        summary = self.summary()
        recent = summary["recent"][0]
        year = int(recent["created_at"][:4])
        self.assertEqual(year, datetime.datetime.now(datetime.UTC).year)

    # -- summary and states -------------------------------------------------

    def test_new_user_summary_is_an_honest_empty_state(self) -> None:
        summary = self.summary()
        self.assertTrue(summary["is_new"])
        self.assertIsNone(summary["continue"])
        self.assertEqual(summary["recent"], [])
        self.assertEqual(summary["counts"]["chapters_started"], 0)
        self.assertEqual(summary["weekly"]["goal_days"], 4)
        self.assertEqual(len(summary["weekly"]["days"]), 7)
        self.assertFalse(any(day["active"] for day in summary["weekly"]["days"]))
        class_nine = next(
            group for group in summary["classes"] if group["class_level"] == 9
        )
        self.assertTrue(class_nine["chapters"])
        self.assertTrue(
            all(chapter["state"] == "not_started" for chapter in class_nine["chapters"])
        )
        self.assertNotIn("kid@example.com", str(summary))
        self.assertNotIn("user_id", str(summary))

    def test_lesson_activity_is_learning_and_continue_points_at_the_chapter(
        self,
    ) -> None:
        response = self.post_events(
            [
                self.lesson_event(
                    concept_id=CONCEPT,
                    section_id="sec-01",
                    blocks_seen=2,
                    blocks_total=9,
                )
            ]
        )
        self.assertEqual(response.status_code, 200, response.text)
        summary = self.summary()
        self.assertFalse(summary["is_new"])
        self.assertEqual(summary["counts"]["chapters_started"], 1)
        self.assertEqual(summary["continue"]["chapter_id"], CHAPTER)
        self.assertIn("Describing Motion", summary["continue"]["title"])
        self.assertEqual(summary["continue"]["sections_seen"], 2)
        self.assertEqual(summary["continue"]["sections_total"], 9)
        chapter = self.chapter_map()
        self.assertEqual(chapter["state"], "learning")
        self.assertEqual(chapter["state_label"], "Learning")
        self.assertEqual(chapter["evidence"]["sections_seen"], 2)

        detail = self.client.get(f"/v1/progress/chapters/{CHAPTER}")
        self.assertEqual(detail.status_code, 200, detail.text)
        body = detail.json()
        self.assertEqual(body["chapter"]["state"], "learning")
        self.assertTrue(body["concepts_available"])
        concept = next(
            item for item in body["concepts"] if item["concept_id"] == CONCEPT
        )
        self.assertEqual(concept["state"], "learning")

    def test_published_catalogue_supplies_title_link_number_and_slug(self) -> None:
        # The catalogue entry carries `href`, not `topic_slug`; the read model
        # derives the slug and the lesson link from it.
        chapter = self.chapter_map()
        self.assertEqual(chapter["title"], "Describing Motion Around Us")
        self.assertEqual(
            chapter["lesson_url"],
            "/courses/class-9-physics/describing-motion-around-us/",
        )
        self.assertEqual(chapter["slug"], "describing-motion-around-us")
        self.assertEqual(chapter["chapter_no"], 4)

    def test_continue_counts_sections_from_events_without_an_absolute_total(
        self,
    ) -> None:
        self.post_events(
            [
                self.lesson_event(concept_id=None, section_id="sec-01"),
                self.lesson_event(concept_id=None, section_id="sec-02"),
            ]
        )
        summary = self.summary()
        self.assertEqual(summary["continue"]["sections_seen"], 2)
        self.assertIsNone(summary["continue"]["sections_total"])

    def test_completed_chapter_is_not_the_continue_card(self) -> None:
        self.post_events(
            [
                self.lesson_event(concept_id=None),
                {
                    "kind": "lesson_complete",
                    "chapter_id": CHAPTER,
                    "payload": {"sections_seen": 9, "source": "merge"},
                },
            ]
        )
        summary = self.summary()
        self.assertEqual(summary["counts"]["chapters_completed"], 1)
        self.assertIsNone(summary["continue"])

    def test_lesson_complete_alone_records_sections_read(self) -> None:
        # F5/F7 may report completion without per-section views; the counter
        # must take `sections_seen`/`sections_total` from `lesson_complete`.
        response = self.post_events(
            [
                {
                    "kind": "lesson_complete",
                    "chapter_id": CHAPTER,
                    "payload": {
                        "sections_seen": 9,
                        "sections_total": 9,
                        "source": "lesson_shell",
                    },
                }
            ]
        )
        self.assertEqual(response.status_code, 200, response.text)
        chapter = self.chapter_map()
        self.assertEqual(chapter["blocks_seen"], 9)
        self.assertEqual(chapter["blocks_total"], 9)
        self.assertEqual(chapter["evidence"]["sections_seen"], 9)
        self.assertEqual(chapter["state"], "learning")

    def test_state_rules_confident_practising_and_revision(self) -> None:
        self.post_events(
            [self.answer_event(correct=True) for _ in range(5)]
            + [
                self.answer_event(correct=False, chapter_id=CHAPTER_B, concept_id=None)
                for _ in range(3)
            ]
            + [
                self.answer_event(correct=True, chapter_id=CHAPTER_C, concept_id=None),
                self.answer_event(correct=False, chapter_id=CHAPTER_C, concept_id=None),
            ]
        )
        summary = self.summary()
        states = {
            chapter["chapter_id"]: chapter["state"]
            for group in summary["classes"]
            for chapter in group["chapters"]
        }
        self.assertEqual(states[CHAPTER], "confident")
        self.assertEqual(states[CHAPTER_B], "needs_revision")
        self.assertEqual(states[CHAPTER_C], "practising")
        chapter = next(
            chapter
            for group in summary["classes"]
            for chapter in group["chapters"]
            if chapter["chapter_id"] == CHAPTER
        )
        self.assertEqual(chapter["evidence"]["practice_answers"], 5)
        self.assertEqual(chapter["evidence"]["accuracy_pct"], 100)
        missing = self.client.get("/v1/progress/chapters/does-not-exist")
        self.assertEqual(missing.status_code, 404)

    def test_confident_needs_recent_correctness_not_just_a_high_average(self) -> None:
        flags = [True] * 8 + [False] * 2
        self.post_events(
            [
                {**self.answer_event(correct=flag), "occurred_at": stamp(60 - i)}
                for i, flag in enumerate(flags)
            ]
        )
        chapter = self.chapter_map()
        self.assertEqual(chapter["evidence"]["accuracy_pct"], 80)
        self.assertEqual(chapter["state"], "practising")

    def test_unknown_chapter_with_events_is_shown_honestly(self) -> None:
        legacy = "class-9-physics/describing-motion-around-us"
        self.post_events([self.lesson_event(chapter_id=legacy, concept_id=None)])
        detail = self.client.get(f"/v1/progress/chapters/{legacy}")
        self.assertEqual(detail.status_code, 200, detail.text)
        body = detail.json()
        self.assertEqual(body["chapter"]["state"], "learning")
        self.assertEqual(body["chapter"]["status"], "unmatched")
        self.assertEqual(body["chapter"]["title"], "Describing motion around us")
        summary = self.summary()
        self.assertEqual(summary["classes"][-1]["class_level"], None)
        self.assertEqual(summary["classes"][-1]["chapters"][0]["chapter_id"], legacy)

    def test_weekly_rhythm_counts_distinct_days_and_keeps_the_goal(self) -> None:
        self.post_events(
            [
                {**self.answer_event(correct=True), "occurred_at": iso(0)},
                {**self.answer_event(correct=True), "occurred_at": iso(1)},
                {**self.answer_event(correct=True), "occurred_at": iso(2)},
                {**self.answer_event(correct=True), "occurred_at": iso(9)},
            ]
        )
        weekly = self.summary()["weekly"]
        self.assertEqual(weekly["days_active"], 3)
        self.assertEqual(weekly["goal_days"], 4)
        self.assertTrue(weekly["today_active"])
        counts = self.summary()["counts"]
        self.assertEqual(counts["active_days_7d"], 3)
        self.assertEqual(counts["practice_answers_7d"], 3)

    def test_weekly_rhythm_uses_ist_calendar_days(self) -> None:
        # 20:00Z on the 17th is 01:30 IST on the 18th: the day belongs to the
        # IST date, not the UTC one. 17:00Z on the 11th is 22:30 IST on the
        # 11th, one day outside the 12-18 window.
        now = datetime.datetime(2026, 11, 18, 12, 0, tzinfo=datetime.UTC)
        events = [
            EventRow(
                event_id="e1",
                kind="lesson_block_view",
                chapter_id=CHAPTER,
                concept_id=None,
                question_id=None,
                payload={},
                created_at=datetime.datetime(2026, 11, 17, 20, 0, tzinfo=datetime.UTC),
            ),
            EventRow(
                event_id="e2",
                kind="practice_answer",
                chapter_id=CHAPTER,
                concept_id=None,
                question_id=None,
                payload={"correct": True},
                created_at=datetime.datetime(2026, 11, 11, 17, 0, tzinfo=datetime.UTC),
            ),
        ]
        summary = build_summary(
            events=events,
            progress_rows=[],
            bookmark_count=0,
            snapshot=catalogue_snapshot(None, "frontend"),
            now=now,
        )
        days = {day["date"]: day for day in summary["weekly"]["days"]}
        self.assertTrue(days["2026-11-18"]["active"])
        self.assertFalse(days["2026-11-17"]["active"])
        self.assertEqual(summary["weekly"]["days_active"], 1)

    # -- bookmarks ----------------------------------------------------------

    def test_bookmark_crud_is_idempotent_and_decorated(self) -> None:
        created = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "chapter", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertTrue(created.json()["created"])
        repeat = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "chapter", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(repeat.status_code, 200)
        self.assertFalse(repeat.json()["created"])

        section = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "block", "target_id": f"{CHAPTER}:sec-03"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(section.status_code, 201, section.text)
        listed = self.client.get("/v1/bookmarks").json()
        self.assertEqual(listed["count"], 2)
        chapter_item = next(
            item for item in listed["items"] if item["target_type"] == "chapter"
        )
        self.assertIn("Describing Motion", chapter_item["chapter_title"])
        self.assertTrue(chapter_item["lesson_url"].endswith("/"))
        block_item = next(
            item for item in listed["items"] if item["target_type"] == "block"
        )
        self.assertTrue(block_item["lesson_url"].endswith("/#sec-03"))

        removed = self.client.delete(
            "/v1/bookmarks",
            params={"target_type": "chapter", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.json()["removed"])
        again = self.client.delete(
            "/v1/bookmarks",
            params={"target_type": "chapter", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertFalse(again.json()["removed"])
        self.assertEqual(self.client.get("/v1/bookmarks").json()["count"], 1)

    def test_bookmark_batch_is_one_idempotent_request(self) -> None:
        body = {
            "items": [
                {"target_type": "chapter", "target_id": CHAPTER},
                {"target_type": "block", "target_id": f"{CHAPTER}:sec-01"},
            ]
        }
        response = self.client.post(
            "/v1/bookmarks", json=body, headers={"X-CSRF-Token": self.csrf}
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["created"], 2)
        repeat = self.client.post(
            "/v1/bookmarks", json=body, headers={"X-CSRF-Token": self.csrf}
        )
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.json()["created"], 0)
        self.assertEqual(repeat.json()["existing"], 2)
        self.assertEqual(self.client.get("/v1/bookmarks").json()["count"], 2)

        mixed = {"target_id": CHAPTER, "items": body["items"]}
        self.assertEqual(
            self.client.post(
                "/v1/bookmarks", json=mixed, headers={"X-CSRF-Token": self.csrf}
            ).status_code,
            422,
        )
        invalid = {
            "items": [
                {"target_type": "chapter", "target_id": CHAPTER},
                {"target_type": "block", "target_id": f"{CHAPTER}:sec 2"},
            ]
        }
        self.assertEqual(
            self.client.post(
                "/v1/bookmarks", json=invalid, headers={"X-CSRF-Token": self.csrf}
            ).status_code,
            422,
        )
        self.assertEqual(self.client.get("/v1/bookmarks").json()["count"], 2)

    def test_a_bookmark_alone_is_not_a_continue_card(self) -> None:
        self.client.post(
            "/v1/bookmarks",
            json={"target_type": "chapter", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        summary = self.summary()
        self.assertIsNone(summary["continue"])
        self.assertEqual(self.chapter_map()["state"], "learning")
        self.assertEqual(summary["counts"]["bookmarks"], 1)

    def test_bookmark_validation_and_activity_feed(self) -> None:
        bad_type = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "profile", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(bad_type.status_code, 422)
        bad_target = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "block", "target_id": f"{CHAPTER}:sec 1"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(bad_target.status_code, 422)
        no_chapter = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "chapter", "target_id": "Class 9"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(no_chapter.status_code, 422)

        self.client.post(
            "/v1/bookmarks",
            json={"target_type": "chapter", "target_id": CHAPTER},
            headers={"X-CSRF-Token": self.csrf},
        )
        summary = self.summary()
        self.assertEqual(summary["counts"]["bookmarks"], 1)
        self.assertEqual(summary["recent"][0]["kind"], "bookmark_add")
        self.assertTrue(summary["weekly"]["today_active"])

    # -- isolation ----------------------------------------------------------

    def test_another_account_never_sees_this_accounts_activity(self) -> None:
        self.post_events([self.lesson_event()])
        self.client.post("/v1/auth/logout", headers={"X-CSRF-Token": self.csrf})
        self.register("other@example.com")
        other = self.summary()
        self.assertTrue(other["is_new"])
        self.assertEqual(other["counts"]["chapters_started"], 0)
        self.assertEqual(self.client.get("/v1/bookmarks").json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
