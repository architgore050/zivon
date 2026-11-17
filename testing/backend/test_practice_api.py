"""Practice API contract (`/v1/practice/*`, F5).

Hermetic SQLite in memory seeded from the tracked P2 packs through the real
importer. No network, no keys, no model call. Covers auth/CSRF reuse, mode and
count validation, question availability, answer-key withholding, server-side
grading for MCQ / numeric / assertion-reason, retries and first-attempt
progress, completion/summary/history, tenant isolation, language selection with
an honest fallback, and the promise that no answer text or PII enters a log or
a response it should not.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.assessment import (
    fetch_question,
    fetch_questions,
    list_missed_question_ids,
    select_question_ids,
)
from db.uuid7 import uuid7_str

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
LIGHT = "class-10-light-reflection-and-refraction"
PASSWORD = "correct-horse-battery-staple"


def _load_importer() -> ModuleType:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location("import_assessment_packs_api", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


class PracticeApiTests(unittest.TestCase):
    app: Any
    db: Any
    _tmp: tempfile.TemporaryDirectory
    client: TestClient
    csrf: str
    email: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(cls._tmp.name) / "runs"),
            cold_staging_dir=str(Path(cls._tmp.name) / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=100,
            auth_register_per_min=100,
            rate_limit_api_per_min=10_000,
        )
        cls.app = create_app(cfg)
        cls.db = cls.app.state.db
        importer.import_packs(cls.db, PACKS_DIR)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.client = TestClient(self.app, base_url="https://testserver")
        self.email = f"kid-{uuid7_str()}@example.com"
        self.register(self.client, self.email)
        self.csrf = self._csrf(self.client)

    # -- helpers ------------------------------------------------------------

    def register(
        self,
        client: TestClient,
        email: str,
        *,
        class_level: int | None = 9,
        language: str = "en-IN",
    ) -> None:
        response = client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": class_level,
                "language": language,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

    def _csrf(self, client: TestClient) -> str:
        payload = client.get("/v1/auth/session").json()
        self.assertTrue(payload["authenticated"])
        return str(payload["csrf_token"])

    def create(
        self,
        *,
        mode: str = "chapter",
        chapter_id: str | None = MOTION,
        count: int | None = None,
        csrf: bool = True,
        client: TestClient | None = None,
    ) -> Any:
        active = client or self.client
        headers = {"X-CSRF-Token": self.csrf if client is None else self._csrf(active)}
        if not csrf:
            headers = {}
        body: dict[str, Any] = {"mode": mode}
        if chapter_id is not None:
            body["chapter_id"] = chapter_id
        if count is not None:
            body["count"] = count
        return active.post("/v1/practice/sessions", json=body, headers=headers)

    def session(self, session_id: str, client: TestClient | None = None) -> Any:
        return (client or self.client).get(f"/v1/practice/sessions/{session_id}")

    def answer(
        self,
        session_id: str,
        question_id: str,
        answer: Any,
        *,
        csrf: bool = True,
        client: TestClient | None = None,
        hints_used: int = 0,
        time_ms: int = 1200,
    ) -> Any:
        active = client or self.client
        headers = {"X-CSRF-Token": self.csrf if client is None else self._csrf(active)}
        if not csrf:
            headers = {}
        return active.post(
            f"/v1/practice/sessions/{session_id}/answers",
            json={
                "question_id": question_id,
                "answer": answer,
                "time_ms": time_ms,
                "hints_used": hints_used,
            },
            headers=headers,
        )

    def complete(self, session_id: str, *, client: TestClient | None = None) -> Any:
        active = client or self.client
        headers = {"X-CSRF-Token": self.csrf if client is None else self._csrf(active)}
        return active.post(
            f"/v1/practice/sessions/{session_id}/complete", headers=headers
        )

    def correct_answer(self, question_id: str) -> dict[str, Any]:
        question = fetch_question(self.db, question_id)
        assert question is not None
        if question.type == "numeric":
            return {"value": float(question.answer["value"])}
        return {"index": int(question.answer["index"])}

    def wrong_answer(self, question_id: str) -> dict[str, Any]:
        question = fetch_question(self.db, question_id)
        assert question is not None
        if question.type == "numeric":
            return {"value": float(question.answer["value"]) + 1000.0}
        correct = int(question.answer["index"])
        return {"index": (correct + 1) % len(question.options)}

    def question_ids(self, session_id: str) -> list[str]:
        payload = self.session(session_id).json()
        return [str(item) for item in payload["session"]["question_ids"]]

    # -- auth, CSRF, validation --------------------------------------------

    def test_auth_and_csrf_are_required(self) -> None:
        guest = TestClient(self.app, base_url="https://testserver")
        self.assertEqual(
            guest.post("/v1/practice/sessions", json={"mode": "chapter"}).status_code,
            401,
        )
        self.assertEqual(guest.get("/v1/practice/history").status_code, 401)
        self.assertEqual(guest.get("/v1/practice/sessions/any").status_code, 401)
        self.assertEqual(self.create().status_code, 201)
        created = self.create(csrf=False)
        self.assertEqual(created.status_code, 403)
        self.assertEqual(
            guest.post(f"/v1/practice/sessions/{uuid7_str()}/complete").status_code,
            401,
        )

    def test_request_validation_is_bounded(self) -> None:
        self.assertEqual(self.create(mode="not-a-mode").status_code, 422)
        self.assertEqual(self.create(count=9).status_code, 422)
        self.assertEqual(self.create(count=21).status_code, 422)
        self.assertEqual(
            self.create(mode="daily", count=5).status_code,
            422,
            "Daily 5 is fixed at five questions",
        )
        self.assertEqual(
            self.client.post(
                "/v1/practice/sessions",
                json={"mode": "chapter", "chapter_id": MOTION, "extra": 1},
                headers={"X-CSRF-Token": self.csrf},
            ).status_code,
            422,
            "unknown fields are rejected",
        )
        self.assertEqual(
            self.create(chapter_id=None).status_code,
            422,
            "a chapter drill needs a chapter",
        )

    def test_a_chapter_without_a_bank_is_an_honest_content_error(self) -> None:
        response = self.create(chapter_id="class-9-no-such-chapter")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-CONTENT-UNAVAILABLE")
        self.assertEqual(
            self.create(chapter_id="").status_code,
            422,
            "an empty chapter id is a request defect, not missing content",
        )

    # -- creation and withholding ------------------------------------------

    def test_chapter_session_is_bounded_unique_and_servable(self) -> None:
        response = self.create(count=10)
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()["session"]
        self.assertEqual(session["mode"], "chapter")
        self.assertEqual(session["chapter_id"], MOTION)
        self.assertEqual(session["question_count"], 10)
        ids = session["question_ids"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(session["config"]["language"], "en")
        self.assertFalse(session["config"]["language_fallback"])
        questions = fetch_questions(self.db, ids)
        self.assertEqual(len(questions), 10)
        self.assertTrue(all(question.chapter_id == MOTION for question in questions))
        self.assertTrue(all(question.language == "en" for question in questions))
        # A wider request takes every available row rather than failing.
        wider = self.create(count=20).json()["session"]
        self.assertEqual(wider["question_count"], 15)

    def test_session_state_withholds_the_answer_key_until_commit(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        payload = self.session(session_id).json()
        self.assertEqual(payload["index"], 0)
        self.assertEqual(payload["answered_count"], 0)
        self.assertFalse(payload["completed"])
        self.assertIsNone(payload["question"]["feedback"])
        question = payload["question"]
        self.assertFalse(question["answered"])
        self.assertFalse(question["hint_available"])
        self.assertNotIn("answer", question)
        self.assertNotIn("explanation", question)
        self.assertNotIn("misconception", question)
        self.assertTrue(question["prompt"])
        self.assertIn(question["type"], {"mcq", "numeric", "assertion_reason"})

    # -- grading ------------------------------------------------------------

    def test_mcq_grading_reveals_feedback_after_the_commit(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        question = self.session(session_id).json()["question"]
        response = self.answer(
            session_id,
            question["question_id"],
            self.correct_answer(question["question_id"]),
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["feedback"]["correct"])
        self.assertTrue(payload["feedback"]["explanation"])
        self.assertEqual(
            payload["feedback"]["answer"],
            self.correct_answer(question["question_id"]),
        )
        self.assertEqual(payload["attempt"]["attempt_no"], 1)
        self.assertEqual(payload["next_index"], 1)
        self.assertFalse(payload["complete_available"])
        # The next state is the next question, not the answered one.
        advanced = self.session(session_id).json()
        self.assertEqual(advanced["index"], 1)
        self.assertNotEqual(
            advanced["question"]["question_id"], question["question_id"]
        )

    def test_retry_appends_attempts_but_progress_counts_the_first(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        question_id = self.session(session_id).json()["question"]["question_id"]
        wrong = self.answer(session_id, question_id, self.wrong_answer(question_id))
        self.assertEqual(wrong.status_code, 200)
        self.assertFalse(wrong.json()["feedback"]["correct"])
        retry = self.answer(session_id, question_id, self.correct_answer(question_id))
        self.assertEqual(retry.json()["attempt"]["attempt_no"], 2)
        self.assertTrue(retry.json()["feedback"]["correct"])
        rows = self.db.fetchall(
            "SELECT kind, payload FROM progress_event WHERE user_id = ?",
            (self._user_id(),),
        )
        self.assertEqual(len(rows), 1, "only the first attempt feeds progress")
        payload = json.loads(rows[0]["payload"])
        self.assertEqual(
            set(payload),
            {"correct", "hints_used", "time_ms"},
            "no answer text or key may enter the progress event",
        )
        self.assertFalse(payload["correct"])
        summary = self.complete(session_id).json()["summary"]
        self.assertEqual(summary["answered_count"], 1)
        self.assertEqual(summary["correct_count"], 1)
        self.assertEqual(summary["first_attempt_correct"], 0)

    def test_numeric_answers_are_parsed_and_tolerance_graded(self) -> None:
        session_id = self.create(count=20).json()["session"]["session_id"]
        numeric_id = self._question_of_type(session_id, "numeric")
        malformed = self.answer(session_id, numeric_id, {"value": "abc"})
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(malformed.json()["code"], "E-VALIDATION")
        self.assertEqual(
            self.answer(session_id, numeric_id, None).status_code,
            422,
            "a missing answer is a malformed answer, not a wrong one",
        )
        wrong = self.answer(session_id, numeric_id, {"value": 999_999})
        self.assertFalse(wrong.json()["feedback"]["correct"])
        # A second numeric item is graded inside its authored tolerance.
        other = self._other_numeric(session_id, numeric_id)
        question = fetch_question(self.db, other)
        assert question is not None
        expected = float(question.answer["value"])
        tolerance = float(question.answer.get("tolerance") or 0)
        inside = self.answer(session_id, other, {"value": expected + tolerance / 2})
        self.assertTrue(inside.json()["feedback"]["correct"])

    def test_assertion_reason_grades_by_option_index(self) -> None:
        session_id = self.create(count=20).json()["session"]["session_id"]
        question_id = self._question_of_type(session_id, "assertion_reason")
        correct = self.correct_answer(question_id)
        response = self.answer(session_id, question_id, correct)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["feedback"]["correct"])
        question = fetch_question(self.db, question_id)
        assert question is not None
        out_of_range = self.answer(
            session_id, question_id, {"index": len(question.options)}
        )
        self.assertEqual(out_of_range.status_code, 422)

    def test_a_question_outside_the_session_is_rejected(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        in_session = set(self.question_ids(session_id))
        outside = next(
            item
            for item in select_question_ids(self.db, MOTION, language="en")
            if item not in in_session
        )
        response = self.answer(session_id, outside, {"index": 0})
        self.assertEqual(response.status_code, 422)

    # -- completion, summary, history -------------------------------------

    def test_complete_is_idempotent_and_closes_the_set(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        first_id = self.session(session_id).json()["question"]["question_id"]
        self.answer(session_id, first_id, self.wrong_answer(first_id))
        closed = self.complete(session_id)
        self.assertEqual(closed.status_code, 200, closed.text)
        summary = closed.json()["summary"]
        self.assertEqual(summary["answered_count"], 1)
        self.assertEqual(summary["question_count"], 10)
        self.assertEqual(summary["unanswered_count"], 9)
        self.assertEqual(summary["score"], 0.0)
        self.assertEqual(summary["first_attempt_accuracy_pct"], 0.0)
        self.assertTrue(summary["concepts"])
        self.assertEqual(summary["concepts"][0]["answered"], 1)
        again = self.complete(session_id).json()["summary"]
        self.assertEqual(again["score"], 0.0, "a second complete is a no-op")
        self.assertEqual(again["answered_count"], 1)
        self.assertEqual(
            self.answer(
                session_id, first_id, self.correct_answer(first_id)
            ).status_code,
            409,
        )
        state = self.session(session_id).json()
        self.assertTrue(state["completed"])
        self.assertIsNone(state["question"])

    def test_history_is_newest_first_and_owner_scoped(self) -> None:
        first = self.create().json()["session"]["session_id"]
        second = self.create(mode="daily").json()["session"]["session_id"]
        history = self.client.get("/v1/practice/history").json()
        ids = [item["session_id"] for item in history["items"]]
        self.assertEqual(ids[0], second)
        self.assertEqual(ids[1], first)
        self.assertEqual(history["count"], 2)

        other = TestClient(self.app, base_url="https://testserver")
        other_email = f"other-{uuid7_str()}@example.com"
        self.register(other, other_email)
        other_csrf = self._csrf(other)
        self.assertEqual(other.get("/v1/practice/history").json()["items"], [])
        self.assertEqual(other.get(f"/v1/practice/sessions/{first}").status_code, 404)
        self.assertEqual(
            other.post(
                f"/v1/practice/sessions/{first}/answers",
                json={"question_id": "x", "answer": {"index": 0}},
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )
        self.assertEqual(
            other.post(
                f"/v1/practice/sessions/{first}/complete",
                headers={"X-CSRF-Token": other_csrf},
            ).status_code,
            404,
        )

    # -- modes --------------------------------------------------------------

    def test_daily_five_spreads_across_the_class_and_retry_reuses_misses(self) -> None:
        daily = self.create(mode="daily", chapter_id=None).json()["session"]
        self.assertEqual(daily["question_count"], 5)
        self.assertIsNone(daily["chapter_id"])
        questions = fetch_questions(self.db, daily["question_ids"])
        self.assertTrue(all(question.class_level == 9 for question in questions))

        chapter_session = self.create()
        session_id = chapter_session.json()["session"]["session_id"]
        missed_id = self.session(session_id).json()["question"]["question_id"]
        missed = fetch_question(self.db, missed_id)
        assert missed is not None
        self.answer(session_id, missed_id, self.wrong_answer(missed_id))

        retry = self.create(mode="retry_mistakes", chapter_id=None)
        self.assertEqual(retry.status_code, 201, retry.text)
        retry_session = retry.json()["session"]
        self.assertIn(missed_id, retry_session["question_ids"])

        weak = self.create(mode="weak_topic", chapter_id=MOTION)
        self.assertEqual(weak.status_code, 201, weak.text)
        weak_questions = fetch_questions(
            self.db, weak.json()["session"]["question_ids"]
        )
        self.assertIn(missed.concept_id, {item.concept_id for item in weak_questions})

        # "Missed" is the latest attempt ACROSS sessions, not per session: once
        # the retry session resolves it, neither drill offers it again.
        resolved = self.answer(
            retry_session["session_id"], missed_id, self.correct_answer(missed_id)
        )
        self.assertTrue(resolved.json()["feedback"]["correct"])
        self.assertEqual(
            self.create(mode="retry_mistakes", chapter_id=None).status_code, 409
        )
        self.assertEqual(
            self.create(mode="weak_topic", chapter_id=MOTION).status_code, 409
        )

    def test_missed_question_ids_filter_on_the_question_chapter(self) -> None:
        """A miss recorded inside a chapter-less retry set still belongs to its chapter."""
        session_id = self.create().json()["session"]["session_id"]
        question_id = self.session(session_id).json()["question"]["question_id"]
        self.answer(session_id, question_id, self.wrong_answer(question_id))
        retry = self.create(mode="retry_mistakes", chapter_id=None).json()["session"]
        self.assertIn(question_id, retry["question_ids"])
        # Re-miss it inside the retry set, whose own chapter_id is NULL: the
        # latest attempt now hangs off a session that carries no chapter.
        self.answer(retry["session_id"], question_id, self.wrong_answer(question_id))
        missed = list_missed_question_ids(
            self.db, self._user_id(), language="en", chapter_id=MOTION
        )
        self.assertIn(
            question_id,
            missed,
            "the filter is the question's chapter, not the attempt's session",
        )
        self.assertEqual(
            list_missed_question_ids(
                self.db, self._user_id(), language="en", chapter_id=LIGHT
            ),
            [],
            "another chapter's misses stay out of the drill",
        )

    def test_empty_retry_and_weak_states_are_coded_errors(self) -> None:
        response = self.create(mode="retry_mistakes", chapter_id=None)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-CONTENT-UNAVAILABLE")
        weak = self.create(mode="weak_topic", chapter_id=MOTION)
        self.assertEqual(weak.status_code, 409)
        self.assertEqual(weak.json()["code"], "E-CONTENT-UNAVAILABLE")

    def test_daily_requires_a_class(self) -> None:
        client = TestClient(self.app, base_url="https://testserver")
        self.register(client, f"noclass-{uuid7_str()}@example.com", class_level=None)
        response = self.create(mode="daily", chapter_id=None, client=client)
        self.assertEqual(response.status_code, 422)

    # -- language -----------------------------------------------------------

    def test_saved_language_is_served_and_the_fallback_is_stated(self) -> None:
        hindi = TestClient(self.app, base_url="https://testserver")
        self.register(hindi, f"hindi-{uuid7_str()}@example.com", language="hi-IN")
        response = self.create(client=hindi)
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()["session"]
        self.assertEqual(session["config"]["language"], "hi")
        questions = fetch_questions(self.db, session["question_ids"])
        self.assertTrue(all(question.language == "hi" for question in questions))

        # Remove the Class 10 Hindi rows, then a Hindi student gets English
        # with the fallback flag set rather than an empty set or silent pretend.
        self.db.execute(
            "UPDATE question_bank SET status = 'retired' "
            "WHERE chapter_id = ? AND language = 'hi'",
            (LIGHT,),
        )
        fallback = self.create(chapter_id=LIGHT, client=hindi)
        self.assertEqual(fallback.status_code, 201, fallback.text)
        fallback_session = fallback.json()["session"]
        self.assertEqual(fallback_session["config"]["language"], "en")
        self.assertTrue(fallback_session["config"]["language_fallback"])
        self.assertEqual(fallback_session["config"]["requested_language"], "hi")

    # -- privacy ------------------------------------------------------------

    def test_responses_carry_no_pii_or_session_secrets(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        bodies = [
            self.session(session_id).text,
            self.client.get("/v1/practice/history").text,
        ]
        for body in bodies:
            self.assertNotIn(self.email, body)
            self.assertNotIn("user_id", body)
            self.assertNotIn("password", body)
            self.assertNotIn("zivon_session", body)

    def test_first_answer_feeds_the_dashboard_progress_summary(self) -> None:
        session_id = self.create().json()["session"]["session_id"]
        question_id = self.session(session_id).json()["question"]["question_id"]
        self.answer(session_id, question_id, self.correct_answer(question_id))
        summary = self.client.get("/v1/progress/summary").json()
        self.assertGreaterEqual(summary["counts"]["practice_answers_7d"], 1)
        row = self.db.fetchone(
            "SELECT kind, concept_id FROM progress_event WHERE user_id = ?",
            (self._user_id(),),
        )
        assert row is not None
        self.assertEqual(row["kind"], "practice_answer")
        self.assertTrue(row["concept_id"])

    # -- fixtures -----------------------------------------------------------

    def _user_id(self) -> str:
        row = self.db.fetchone(
            "SELECT user_id FROM users WHERE email = ?", (self.email,)
        )
        assert row is not None
        return str(row["user_id"])

    def _question_of_type(self, session_id: str, kind: str) -> str:
        ids = self.session(session_id).json()["session"]["question_ids"]
        for question in fetch_questions(self.db, ids):
            if question.type == kind:
                return question.question_id
        self.fail(f"no {kind} question in the session")

    def _other_numeric(self, session_id: str, first: str) -> str:
        ids = self.session(session_id).json()["session"]["question_ids"]
        for question in fetch_questions(self.db, ids):
            if question.type == "numeric" and question.question_id != first:
                return question.question_id
        self.fail("the session has only one numeric question")


if __name__ == "__main__":
    unittest.main()
