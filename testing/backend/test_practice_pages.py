"""Practice pages (`/app/practice/*`, F5): SSR contract and honest states.

Hermetic SQLite in memory with the tracked packs imported, no network, no keys.
Covers the guest redirect, the nav entry, hub modes and empty states, the
one-question player, no answer key before a commit, the JavaScript-off Check
path, numeric parse errors, summary/history, a branded 404, CSRF on the form
posts, and the no-PII/no-§10-device rules the shell shares.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.assessment import (
    complete_practice_session,
    create_practice_session,
    fetch_question,
    select_question_ids,
)
from db.uuid7 import uuid7_str

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
PASSWORD = "correct-horse-battery-staple"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _load_importer() -> ModuleType:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location("import_assessment_packs_pages", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


class PracticePageTests(unittest.TestCase):
    app: Any
    empty_app: Any
    db: Any
    empty_db: Any
    _tmp: tempfile.TemporaryDirectory
    client: TestClient
    csrf: str
    email: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.app = create_app(cls._config("practice-pages"))
        cls.db = cls.app.state.db
        importer.import_packs(cls.db, PACKS_DIR)
        cls.empty_app = create_app(cls._config("practice-empty"))
        cls.empty_db = cls.empty_app.state.db

    @classmethod
    def _config(cls, name: str) -> BackendConfig:
        assert cls._tmp is not None
        return BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(cls._tmp.name) / name / "runs"),
            cold_staging_dir=str(Path(cls._tmp.name) / name / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=100,
            auth_register_per_min=100,
            rate_limit_api_per_min=10_000,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self.client = TestClient(self.app, base_url="https://testserver")
        self.email = f"kid-{uuid7_str()}@example.com"
        self._register(self.client, self.email)
        self.csrf = self._csrf(self.client)

    # -- helpers ------------------------------------------------------------

    def _register(
        self, client: TestClient, email: str, *, class_level: int | None = 9
    ) -> None:
        response = client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": class_level,
                "language": "en-IN",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

    def _csrf(self, client: TestClient) -> str:
        return str(client.get("/v1/auth/session").json()["csrf_token"])

    def _create_session(self, *, count: int | None = None) -> str:
        body: dict[str, Any] = {"mode": "chapter", "chapter_id": MOTION}
        if count is not None:
            body["count"] = count
        response = self.client.post(
            "/v1/practice/sessions",
            json=body,
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["session"]["session_id"])

    def _answer(self, session_id: str, question_id: str, answer: dict[str, Any]) -> Any:
        return self.client.post(
            f"/v1/practice/sessions/{session_id}/answers",
            json={"question_id": question_id, "answer": answer, "time_ms": 1000},
            headers={"X-CSRF-Token": self.csrf},
        )

    def _correct(self, question_id: str) -> dict[str, Any]:
        question = fetch_question(self.db, question_id)
        assert question is not None
        if question.type == "numeric":
            return {"value": float(question.answer["value"])}
        return {"index": int(question.answer["index"])}

    def _user_id(self) -> str:
        row = self.db.fetchone(
            "SELECT user_id FROM users WHERE email = ?", (self.email,)
        )
        assert row is not None
        return str(row["user_id"])

    def _form_token(self, html: str) -> str:
        match = CSRF_RE.search(html)
        self.assertIsNotNone(match, "no CSRF field on the form")
        assert match is not None
        return match.group(1)

    def _assert_clean_shell(self, html: str) -> None:
        self.assertNotIn(self.email, html)
        self.assertNotIn("zn-", html)
        self.assertNotIn("zivon.css", html)
        self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(html, r"<style")
        self.assertNotRegex(html, r"\sstyle=")
        self.assertNotRegex(html, r"\son[a-z]+=")
        self.assertIn('name="viewport"', html)
        self.assertIn("noindex", html)

    # -- guard --------------------------------------------------------------

    def test_guest_is_redirected_to_login(self) -> None:
        guest = TestClient(self.app, base_url="https://testserver")
        for path in (
            "/app/practice",
            "/app/practice/history",
            "/app/practice/does-not-exist",
            "/app/practice/does-not-exist/summary",
        ):
            response = guest.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303, path)
            self.assertEqual(
                response.headers["location"],
                f"/login?next={path}",
            )

    def test_practice_nav_entry_is_active(self) -> None:
        response = self.client.get("/app/practice")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/app/practice" aria-current="page"', response.text)
        self.assertIn(">Practice</a>", response.text)

    # -- hub ----------------------------------------------------------------

    def test_hub_offers_the_modes_and_honest_empty_states(self) -> None:
        response = self.client.get("/app/practice")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Start the Daily 5", html)
        self.assertIn("Describing Motion Around Us", html)
        self.assertIn("Start", html)
        self.assertIn("No unresolved mistakes yet", html)
        self.assertIn("Nothing is marked weak yet", html)
        self.assertIn("No practice sets yet", html)
        self.assertIn("Hints are not authored yet", html)
        self._assert_clean_shell(html)

    def test_hub_without_a_bank_is_an_honest_empty_state(self) -> None:
        client = TestClient(self.empty_app, base_url="https://testserver")
        self._register(client, f"empty-{uuid7_str()}@example.com")
        response = client.get("/app/practice")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("No chapter has an imported practice bank yet", html)
        self.assertNotIn('action="/app/practice/start"', html)
        self.assertIn("No Class 9 practice set is imported yet", html)

    def test_hub_focus_card_comes_from_the_lesson_link(self) -> None:
        response = self.client.get(f"/app/practice?chapter={MOTION}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("From the lesson", response.text)
        self.assertIn(
            f'<input type="hidden" name="chapter_id" value="{MOTION}">',
            response.text,
        )

    # -- player -------------------------------------------------------------

    def test_player_shows_one_question_and_withholds_the_key(self) -> None:
        session_id = self._create_session()
        response = self.client.get(f"/app/practice/{session_id}")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Question 1 of 10", html)
        self.assertIn('<legend class="practice-prompt">', html)
        self.assertIn("Check answer", html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('name="answer_kind" value="index"', html)
        self.assertNotIn("The answer is", html)
        self.assertNotIn("Common mix-up", html)
        self.assertIn("No authored hint for this question yet", html)
        self._assert_clean_shell(html)

    def test_check_posts_without_javascript_and_renders_feedback(self) -> None:
        session_id = self._create_session()
        page = self.client.get(f"/app/practice/{session_id}")
        token = self._form_token(page.text)
        question_id = self.client.get(f"/v1/practice/sessions/{session_id}").json()[
            "question"
        ]["question_id"]
        answer = self._correct(question_id)
        payload = {
            "csrf_token": token,
            "question_id": question_id,
            "answer_kind": "index",
            "answer_index": str(answer["index"]),
            "hints_used": "1",
            "time_ms": "4000",
        }
        response = self.client.post(
            f"/app/practice/{session_id}/answer",
            data=payload,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertIn(f"answered={question_id}", response.headers["location"])
        feedback = self.client.get(response.headers["location"])
        self.assertEqual(feedback.status_code, 200)
        self.assertIn("Correct.", feedback.text)
        self.assertIn("The answer is", feedback.text)
        self.assertIn("Next question", feedback.text)
        self.assertIn("Ask the tutor on this chapter", feedback.text)
        # Retry is still available on the reviewed question, with the chosen
        # option preselected; it appends another attempt rather than erasing.
        self.assertIn("Check again", feedback.text)
        self.assertIn(f'value="{answer["index"]}" checked', feedback.text)
        row = self.db.fetchone(
            "SELECT hints_used, time_ms FROM practice_attempt "
            "WHERE session_id = ? AND question_id = ?",
            (session_id, question_id),
        )
        assert row is not None
        self.assertEqual(int(row["hints_used"]), 1)
        self.assertEqual(int(row["time_ms"]), 4000)

    def test_numeric_parse_error_keeps_the_entered_value(self) -> None:
        numeric_id = ""
        for candidate in select_question_ids(self.db, MOTION, language="en"):
            question = fetch_question(self.db, candidate)
            if question is not None and question.type == "numeric":
                numeric_id = candidate
                break
        self.assertTrue(numeric_id, "the pack has numeric questions")
        session = create_practice_session(
            self.db,
            self._user_id(),
            mode="chapter",
            question_ids=[numeric_id],
            chapter_id=MOTION,
        )
        page = self.client.get(f"/app/practice/{session['session_id']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn('name="answer_value"', page.text)
        token = self._form_token(page.text)
        response = self.client.post(
            f"/app/practice/{session['session_id']}/answer",
            data={
                "csrf_token": token,
                "question_id": numeric_id,
                "answer_kind": "value",
                "answer_value": "abc",
                "hints_used": "0",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Enter a number like 15", response.text)
        self.assertIn('value="abc"', response.text)
        self.assertNotIn("practice-feedback--correct", response.text)

    def test_a_form_post_without_csrf_is_rejected(self) -> None:
        session_id = self._create_session()
        response = self.client.post(
            "/app/practice/start",
            data={"mode": "chapter", "chapter_id": MOTION},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)
        answer = self.client.post(
            f"/app/practice/{session_id}/answer",
            data={"question_id": "x", "answer_kind": "index", "answer_index": "0"},
            follow_redirects=False,
        )
        self.assertEqual(answer.status_code, 403)

    def test_completed_player_redirects_to_the_summary(self) -> None:
        session_id = self._create_session()
        question_id = self.client.get(f"/v1/practice/sessions/{session_id}").json()[
            "question"
        ]["question_id"]
        self._answer(session_id, question_id, self._correct(question_id))
        complete_practice_session(self.db, self._user_id(), session_id, score=100.0)
        response = self.client.get(
            f"/app/practice/{session_id}", follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"], f"/app/practice/{session_id}/summary"
        )

    # -- summary and history ------------------------------------------------

    def test_summary_reports_score_concepts_and_next_actions(self) -> None:
        session_id = self._create_session()
        question_id = self.client.get(f"/v1/practice/sessions/{session_id}").json()[
            "question"
        ]["question_id"]
        self._answer(session_id, question_id, self._correct(question_id))
        complete = self.client.post(
            f"/v1/practice/sessions/{session_id}/complete",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(complete.status_code, 200)
        page = self.client.get(f"/app/practice/{session_id}/summary")
        self.assertEqual(page.status_code, 200)
        html = page.text
        self.assertIn("You answered 1 of 1 correctly", html)
        self.assertIn("Where the marks came from", html)
        self.assertIn("First attempts", html)
        self.assertIn("questions left unanswered", html)
        self.assertIn("Tests open with their own release", html)
        self.assertNotIn("leaderboard", html.lower())
        self._assert_clean_shell(html)

        history = self.client.get("/app/practice/history")
        self.assertEqual(history.status_code, 200)
        self.assertIn("Saved sessions", history.text)
        self.assertIn("Open summary", history.text)

    def test_open_summary_says_the_set_is_still_open(self) -> None:
        session_id = self._create_session()
        response = self.client.get(f"/app/practice/{session_id}/summary")
        self.assertEqual(response.status_code, 200)
        self.assertIn("This set is still open", response.text)
        self.assertIn("Continue this set", response.text)

    def test_finished_set_with_no_answers_shows_no_score(self) -> None:
        """A completed set nobody answered must not claim a 0% score."""
        session_id = self._create_session()
        complete_practice_session(self.db, self._user_id(), session_id, score=0.0)
        response = self.client.get(f"/app/practice/{session_id}/summary")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nothing was answered in this set", response.text)
        self.assertNotIn("Set score", response.text)
        self.assertIn("left unanswered", response.text)

    def test_history_empty_state(self) -> None:
        response = self.client.get("/app/practice/history")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No practice sets yet", response.text)

    # -- isolation and missing ---------------------------------------------

    def test_unknown_or_foreign_session_is_a_branded_404(self) -> None:
        missing = self.client.get("/app/practice/not-a-session")
        self.assertEqual(missing.status_code, 404)
        self.assertIn("Practice set not found", missing.text)
        self.assertNotIn('"code": "E-NOT-FOUND"', missing.text)
        session_id = self._create_session()
        other = TestClient(self.app, base_url="https://testserver")
        self._register(other, f"other-{uuid7_str()}@example.com")
        self.assertEqual(other.get(f"/app/practice/{session_id}").status_code, 404)
        self.assertEqual(
            other.get(f"/app/practice/{session_id}/summary").status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
