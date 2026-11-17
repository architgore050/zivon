"""Test engine, player, review, history, and series pages (F7, REQUIREMENTS §9.6/§10.11–§10.16).

Hermetic: one SQLite in-memory database seeded through the real assessment-pack
importer, one FastAPI app per test over that store, the dev email sink, no
browser, no network, no keys. Covers the account guard, CSRF on every write,
the builder, answer-key withholding, autosave/resume, the server clock,
server-side grading with no negative marking, the review, history filters,
retry mistakes, the six-series catalogue and its pending/disabled states, the
compliance notice, and the no-inline/no-lesson-device template contract.
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
    AssessmentError,
    create_test_with_questions,
    fetch_question,
    list_missed_test_question_ids,
    list_test_answers,
    select_question_ids,
)
from backend.test_engine import (
    SERIES_ORDER,
    n01_notice,
    series_by_slug,
    series_copy,
)
from backend.test_engine.series import SERIES_DEFINITIONS, subject_label
from db import DatabaseEngine
from db.uuid7 import uuid7_str

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
LIGHT = "class-10-light-reflection-and-refraction"
PASSWORD = "correct-horse-battery-staple"


def _load_importer() -> ModuleType:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location(
        "import_assessment_packs_webtests", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


def _config(root: Path) -> BackendConfig:
    return BackendConfig(
        db_url="sqlite:///:memory:",
        env="test",
        runs_dir=str(root / "runs"),
        cold_staging_dir=str(root / "cold"),
        auth_cookie_secure=True,
        auth_login_per_min=100,
        auth_register_per_min=100,
        rate_limit_api_per_min=10_000,
    )


class TestPagesTests(unittest.TestCase):
    """The signed-in test surfaces over the imported P2 banks."""

    db: DatabaseEngine
    series_id: str
    paper_id: str
    paper_questions: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        importer.import_packs(cls.db, PACKS_DIR)
        cls.series_id = uuid7_str()
        cls.paper_id = uuid7_str()
        cls.db.execute(
            "INSERT INTO test_series (series_id, slug, class_level, kind, title, "
            "description, language_set, status) VALUES (?, 'ai-lesson-tests', 10, "
            "'ai_lesson', 'AI lesson tests', 'Chapter tests from lesson concepts.', "
            '\'["en","hi","hi-Latn"]\', \'published\')',
            (cls.series_id,),
        )
        cls.paper_questions = select_question_ids(cls.db, LIGHT, language="en")[:3]
        cls.db.execute(
            "INSERT INTO test (test_id, series_id, chapter_ids, title, language, "
            "duration_s, total_marks, structure, status) VALUES (?, ?, ?, "
            "'Light chapter test', 'en', 600, 3, '{\"sections\": [\"A\"]}', 'published')",
            (cls.paper_id, cls.series_id, f'["{LIGHT}"]'),
        )
        for index, question_id in enumerate(cls.paper_questions, start=1):
            cls.db.execute(
                "INSERT INTO test_question (test_id, question_id, order_index, "
                "section, marks) VALUES (?, ?, ?, 'A', 1)",
                (cls.paper_id, question_id, index),
            )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = create_app(_config(self.root), db_engine=self.db)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.email = f"kid-{uuid7_str()}@example.com"
        self.session = self.register(self.email)
        self.csrf = str(self.session["csrf_token"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def register(
        self,
        email: str,
        *,
        class_level: int | None = 9,
        language: str = "en-IN",
    ) -> dict[str, Any]:
        response = self.client.post(
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
        return self.client.get("/v1/auth/session").json()

    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def create_custom(
        self,
        *,
        chapters: list[str] | None = None,
        count: int = 5,
        difficulty: str = "mixed",
        duration_s: int = 600,
        expect: int = 201,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/v1/tests/custom",
            json={
                "chapter_ids": chapters or [MOTION],
                "count": count,
                "difficulty": difficulty,
                "duration_s": duration_s,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def start(self, test_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"/v1/tests/{test_id}/attempts", headers=self.headers()
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def state(self, attempt_id: str) -> dict[str, Any]:
        response = self.client.get(f"/v1/tests/attempts/{attempt_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

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
            return {"value": float(question.answer["value"]) + 1000}
        index = int(question.answer["index"])
        return {"index": (index + 1) % max(1, len(question.options))}

    def answer(self, attempt_id: str, question_id: str, *, correct: bool) -> None:
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={
                "question_id": question_id,
                "answer": self.correct_answer(question_id)
                if correct
                else self.wrong_answer(question_id),
                "time_ms": 1200,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def submit(self, attempt_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"/v1/tests/attempts/{attempt_id}/submit", headers=self.headers()
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["review"]

    def page(self, path: str, *, status: int = 200) -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, response.text)
        return response.text

    # -- guard and CSRF -----------------------------------------------------

    def test_guest_is_redirected_from_every_test_page(self) -> None:
        guest = TestClient(self.app, base_url="https://testserver")
        for path in (
            "/app/tests",
            "/app/tests/new",
            "/app/tests/history",
            "/app/series",
            "/app/series/ai-lesson",
            f"/app/tests/{uuid7_str()}",
        ):
            response = guest.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303, path)
            self.assertEqual(response.headers["location"], f"/login?next={path}")

    def test_custom_test_form_requires_csrf(self) -> None:
        response = self.client.post(
            "/app/tests/start",
            data={"kind": "chapter", "chapter_id": MOTION},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)

    def test_json_writes_require_csrf(self) -> None:
        created = self.create_custom()
        started = self.start(created["test"]["test_id"])
        attempt_id = started["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={"question_id": question_id, "answer": {"index": 0}},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "E-AUTH-CSRF")
        response = self.client.post(f"/v1/tests/attempts/{attempt_id}/submit")
        self.assertEqual(response.status_code, 403)

    # -- builder ------------------------------------------------------------

    def test_custom_test_creation_builds_a_paper_from_the_bank(self) -> None:
        created = self.create_custom(count=5, difficulty="mixed", duration_s=600)
        test = created["test"]
        self.assertEqual(test["title"], "Custom test")
        self.assertEqual(test["duration_s"], 600)
        self.assertEqual(test["structure"]["question_count"], 5)
        self.assertEqual(test["structure"]["source"], "custom")
        self.assertEqual(test["status"], "draft")
        self.assertEqual(test["total_marks"], 5.0)
        started = self.start(test["test_id"])
        self.assertEqual(started["attempt"]["status"], "in_progress")
        self.assertEqual(started["resumed"], False)
        state = self.state(started["attempt"]["attempt_id"])
        self.assertEqual(state["counts"]["question_count"], 5)
        self.assertTrue(all(q["chapter_id"] == MOTION for q in state["questions"]))

    def test_builder_form_creation_and_chapter_test_derivation(self) -> None:
        response = self.client.post(
            "/app/tests/start",
            data={
                "kind": "custom",
                "chapter_class-9-describing-motion-around-us": "1",
                "count": "5",
                "difficulty": "easy",
                "duration_min": "10",
                "csrf_token": self.csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        location = response.headers["location"]
        self.assertTrue(location.startswith("/app/tests/"))
        self.assertEqual(self.client.get(location).status_code, 200)

        chapter = self.client.post(
            "/app/tests/start",
            data={
                "kind": "chapter",
                "chapter_id": MOTION,
                "csrf_token": self.csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(chapter.status_code, 303, chapter.text)
        attempt_id = chapter.headers["location"].rsplit("/", 1)[-1]
        state = self.state(attempt_id)
        self.assertEqual(state["test"]["structure"]["source"], "chapter")
        self.assertEqual(state["counts"]["question_count"], 10)
        self.assertGreaterEqual(state["test"]["duration_s"], 300)

    def test_builder_rejects_unknown_chapters_and_short_counts(self) -> None:
        self.create_custom(chapters=["no-such-chapter"], expect=409)
        self.create_custom(count=2, expect=422)
        self.create_custom(count=5, duration_s=60, expect=422)
        response = self.client.post(
            "/app/tests/start",
            data={
                "kind": "custom",
                "chapter_no-such-chapter": "1",
                "count": "5",
                "difficulty": "mixed",
                "duration_min": "10",
                "csrf_token": self.csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("do not have enough imported questions", response.text)

    def test_preset_uses_the_available_chapters(self) -> None:
        response = self.client.post(
            "/app/tests/start",
            data={
                "kind": "custom",
                "preset": "1",
                "count": "5",
                "difficulty": "mixed",
                "duration_min": "10",
                "csrf_token": self.csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        state = self.state(response.headers["location"].rsplit("/", 1)[-1])
        self.assertEqual(state["test"]["structure"]["chapters"], 1)

    def test_language_falls_back_to_english_and_says_so(self) -> None:
        session = self.register(f"hi-{uuid7_str()}@example.com", language="hinglish")
        csrf = str(session["csrf_token"])
        self.db.execute(
            "UPDATE question_bank SET status = 'draft' WHERE language = 'hi-Latn'"
        )
        try:
            response = self.client.post(
                "/v1/tests/custom",
                json={"chapter_ids": [MOTION], "count": 5},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(response.status_code, 201, response.text)
            test = response.json()["test"]
            self.assertEqual(test["language"], "en")
            self.assertTrue(test["structure"]["language_fallback"])
            self.assertEqual(test["structure"]["requested_language"], "hi-Latn")
        finally:
            self.db.execute(
                "UPDATE question_bank SET status = 'reviewed' "
                "WHERE language = 'hi-Latn'"
            )

    # -- answer-key withholding --------------------------------------------

    def test_start_payload_withholds_the_answer_key(self) -> None:
        created = self.create_custom()
        state = self.state(
            self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        )
        question = state["question"]
        for hidden in ("answer", "explanation", "misconception", "source_ref"):
            self.assertNotIn(hidden, question)
        stored = fetch_question(self.db, question["question_id"])
        assert stored is not None
        html = self.page(f"/app/tests/{state['attempt']['attempt_id']}")
        self.assertNotIn(stored.explanation, html)
        self.assertNotIn("Why", html)
        self.assertNotIn("data-answer", html)

    def test_verbatim_source_never_reaches_the_player(self) -> None:
        source = fetch_question(
            self.db, select_question_ids(self.db, MOTION, language="en")[0]
        )
        assert source is not None
        verbatim_id = f"verbatim-{uuid7_str()}-en"
        test_id = uuid7_str()
        self.db.execute(
            "INSERT INTO question_bank (question_id, base_item_id, class_level, "
            "chapter_id, concept_id, type, difficulty, marks, language, "
            "source_type, source_ref, prompt, options, answer, explanation, "
            "misconception, expected_time_ms, status, review_mode, version, "
            "generator, pack_id, created_at, updated_at) "
            "SELECT ?, ?, class_level, chapter_id, concept_id, type, difficulty, "
            "marks, language, 'past_paper', source_ref, prompt, options, answer, "
            "explanation, misconception, expected_time_ms, status, review_mode, "
            "version, generator, pack_id, created_at, updated_at "
            "FROM question_bank WHERE question_id = ?",
            (verbatim_id, f"verbatim-{uuid7_str()}", source.question_id),
        )
        self.db.execute(
            "INSERT INTO test (test_id, series_id, user_id, chapter_ids, title, "
            "language, duration_s, total_marks, structure, status) VALUES "
            "(?, NULL, ?, ?, 'Verbatim guard', 'en', 600, 1, '{}', 'published')",
            (test_id, self.session["user"]["user_id"], f'["{MOTION}"]'),
        )
        self.db.execute(
            "INSERT INTO test_question (test_id, question_id, order_index, marks) "
            "VALUES (?, ?, 1, 1)",
            (test_id, verbatim_id),
        )
        started = self.client.post(
            f"/v1/tests/{test_id}/attempts", headers=self.headers()
        )
        self.assertEqual(started.status_code, 201, started.text)
        attempt_id = started.json()["attempt"]["attempt_id"]
        response = self.client.get(f"/v1/tests/attempts/{attempt_id}")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "E-CONTENT-UNAVAILABLE")
        page = self.client.get(f"/app/tests/{attempt_id}")
        self.assertEqual(page.status_code, 409)
        self.assertIn("not cleared for practice yet", page.text)
        self.assertNotIn(source.prompt, page.text)
        self.assertNotIn(verbatim_id, page.text)

    def test_review_is_withheld_until_submit(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        response = self.client.get(f"/v1/tests/attempts/{attempt_id}/review")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-CONFLICT")
        response = self.client.get(
            f"/app/tests/{attempt_id}/review", follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"/app/tests/{attempt_id}")

    # -- autosave and resume ------------------------------------------------

    def test_autosave_and_resume_keep_the_same_attempt(self) -> None:
        created = self.create_custom()
        started = self.start(created["test"]["test_id"])
        attempt_id = started["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        self.answer(attempt_id, question_id, correct=True)
        state = self.state(attempt_id)
        saved = state["answers"][question_id]
        self.assertEqual(saved["answer"], self.correct_answer(question_id))
        self.assertIsNone(saved["correct"], "autosave must not grade")
        resumed = self.start(created["test"]["test_id"])
        self.assertEqual(resumed["attempt"]["attempt_id"], attempt_id)
        self.assertTrue(resumed["resumed"])

    def test_autosave_with_no_answer_and_no_flag_is_rejected(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={"question_id": question_id},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["code"], "E-VALIDATION")

    def test_flag_only_save_keeps_the_answer(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        self.answer(attempt_id, question_id, correct=True)
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={"question_id": question_id, "flagged": True},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.state(attempt_id)["answers"][question_id]
        self.assertTrue(saved["flagged"])
        self.assertEqual(saved["answer"], self.correct_answer(question_id))
        self.assertEqual(self.state(attempt_id)["counts"]["flagged"], 1)

    def test_html_player_saves_and_marks_without_javascript(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        answer = self.correct_answer(question_id)
        data: dict[str, str] = {
            "csrf_token": self.csrf,
            "question_id": question_id,
            "flagged": "1",
            "action": "save",
            "time_ms": "0",
        }
        if "index" in answer:
            data["answer_kind"] = "index"
            data["answer_index"] = str(answer["index"])
        else:
            data["answer_kind"] = "value"
            data["answer_value"] = str(answer["value"])
        response = self.client.post(
            f"/app/tests/{attempt_id}/answer", data=data, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303, response.text)
        saved = self.state(attempt_id)["answers"][question_id]
        self.assertEqual(saved["answer"], answer)
        self.assertTrue(saved["flagged"])

    # -- deadline -----------------------------------------------------------

    def test_expired_attempt_refuses_autosave_and_offers_submit(self) -> None:
        created = self.create_custom(duration_s=300)
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        self.db.execute(
            "UPDATE test_attempt SET started_at = '2020-01-01T00:00:00+00:00' "
            "WHERE attempt_id = ?",
            (attempt_id,),
        )
        state = self.state(attempt_id)
        self.assertTrue(state["expired"])
        self.assertEqual(state["remaining_s"], 0)
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={"question_id": question_id, "answer": {"index": 0}},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-CONFLICT")
        html = self.page(f"/app/tests/{attempt_id}")
        self.assertIn("Time is up", html)
        self.assertNotIn("Save answer", html)
        self.submit(attempt_id)
        self.assertEqual(self.state(attempt_id)["submitted"], True)

    # -- grading and review -------------------------------------------------

    def test_submit_grades_server_side_without_negative_marking(self) -> None:
        created = self.create_custom(count=5)
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        questions = self.state(attempt_id)["questions"]
        self.answer(attempt_id, questions[0]["question_id"], correct=True)
        self.answer(attempt_id, questions[1]["question_id"], correct=True)
        self.answer(attempt_id, questions[2]["question_id"], correct=False)
        review = self.submit(attempt_id)
        self.assertEqual(review["summary"]["earned"], 2.0)
        self.assertEqual(review["summary"]["possible"], 5.0)
        self.assertEqual(review["summary"]["score"], 40.0)
        self.assertEqual(review["summary"]["correct"], 2)
        self.assertEqual(review["summary"]["answered"], 3)
        self.assertEqual(review["summary"]["unanswered"], 2)
        self.assertEqual(review["summary"]["accuracy_pct"], 66.7)
        self.assertGreaterEqual(review["summary"]["earned"], 0.0)
        assert review["summary"]["earned"] == 2.0, "a wrong answer adds nothing"

    def test_submit_is_idempotent_and_locks_autosave(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        first = self.submit(attempt_id)
        second = self.submit(attempt_id)
        self.assertEqual(first["summary"]["score"], second["summary"]["score"])
        self.assertEqual(
            first["attempt"]["submitted_at"], second["attempt"]["submitted_at"]
        )
        question_id = first["questions"][0]["question_id"]
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={"question_id": question_id, "answer": {"index": 0}},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 409)

    def test_flag_only_question_is_unanswered_not_wrong(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        question_id = self.state(attempt_id)["question"]["question_id"]
        response = self.client.patch(
            f"/v1/tests/attempts/{attempt_id}/answers",
            json={"question_id": question_id, "flagged": True},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        review = self.submit(attempt_id)
        saved = next(
            item for item in review["questions"] if item["question_id"] == question_id
        )
        self.assertFalse(saved["answered"])
        self.assertIsNone(saved["correct"])
        stored = next(
            row
            for row in list_test_answers(
                self.db, self.session["user"]["user_id"], attempt_id
            )
            if row["question_id"] == question_id
        )
        self.assertIsNone(stored["correct"])
        self.assertEqual(review["summary"]["unanswered"], 5)

    def test_review_shows_every_question_key_and_explanation(self) -> None:
        created = self.create_custom(count=5)
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        questions = self.state(attempt_id)["questions"]
        self.answer(attempt_id, questions[0]["question_id"], correct=True)
        self.answer(attempt_id, questions[1]["question_id"], correct=False)
        review = self.submit(attempt_id)
        self.assertEqual(len(review["questions"]), 5)
        for entry in review["questions"]:
            self.assertIn("answer", entry)
            self.assertIn("explanation", entry)
            self.assertIn("answered", entry)
        first = review["questions"][0]
        self.assertEqual(first["correct"], True)
        self.assertEqual(first["chosen"], self.correct_answer(first["question_id"]))
        second = review["questions"][1]
        self.assertEqual(second["correct"], False)
        self.assertTrue(second["answer_text"])
        self.assertGreaterEqual(len(review["concepts"]), 1)
        self.assertGreaterEqual(len(review["chapters"]), 1)
        html = self.page(f"/app/tests/{attempt_id}/review")
        self.assertIn("Every question, with the working", html)
        self.assertIn("Why", html)
        self.assertIn("Ask the tutor on this chapter", html)

    # -- history and retry --------------------------------------------------

    def test_history_lists_attempts_and_filters(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        response = self.client.get("/v1/tests/history")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["status"], "in_progress")
        self.assertEqual(payload["items"][0]["kind"], "custom")
        self.assertTrue(
            self.client.get("/v1/tests/history?status=submitted").json()["count"] == 0
        )
        self.submit(attempt_id)
        self.assertEqual(
            self.client.get("/v1/tests/history?status=submitted").json()["count"], 1
        )
        self.assertEqual(
            self.client.get("/v1/tests/history?kind=series").json()["count"], 0
        )
        html = self.page("/app/tests/history?kind=custom")
        self.assertIn("Custom test", html)

    def test_retry_mistakes_builds_a_new_paper(self) -> None:
        created = self.create_custom(count=5)
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        questions = self.state(attempt_id)["questions"]
        self.answer(attempt_id, questions[0]["question_id"], correct=True)
        self.answer(attempt_id, questions[1]["question_id"], correct=False)
        self.submit(attempt_id)
        missed = list_missed_test_question_ids(
            self.db, self.session["user"]["user_id"], language="en"
        )
        self.assertEqual(missed, [questions[1]["question_id"]])
        response = self.client.post("/v1/tests/retry", headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        test = response.json()["test"]
        self.assertEqual(test["structure"]["source"], "retry")
        self.assertEqual(test["structure"]["question_count"], 1)
        self.assertEqual(test["total_marks"], questions[1]["marks"])
        response = self.client.post("/v1/tests/retry", headers=self.headers())
        self.assertEqual(response.status_code, 201)

    def test_retry_without_mistakes_is_honest(self) -> None:
        response = self.client.post("/v1/tests/retry", headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-CONTENT-UNAVAILABLE")
        html = self.page("/app/tests/history")
        self.assertIn("No unresolved test mistake yet", html)

    # -- isolation ----------------------------------------------------------

    def test_another_account_cannot_read_an_attempt(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        other = TestClient(self.app, base_url="https://testserver")
        other.post(
            "/v1/auth/register",
            json={
                "email": f"other-{uuid7_str()}@example.com",
                "password": PASSWORD,
                "display_name": "Ravi",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        self.assertEqual(other.get(f"/v1/tests/attempts/{attempt_id}").status_code, 404)
        self.assertEqual(other.get(f"/app/tests/{attempt_id}").status_code, 404)
        self.assertEqual(
            other.get(f"/v1/tests/attempts/{attempt_id}/review").status_code, 404
        )

    # -- series -------------------------------------------------------------

    def test_series_catalogue_is_honest_about_pending_and_dark(self) -> None:
        response = self.client.get("/v1/series")
        self.assertEqual(response.status_code, 200)
        cards = {card["kind"]: card for card in response.json()["cards"]}
        self.assertEqual(list(cards), list(SERIES_ORDER))
        self.assertEqual(cards["ai_lesson"]["status"], "not_open")
        html = self.page("/app/series")
        self.assertIn("Opens for Class 10 and 12", html)
        self.assertIn("The six series", html)

    def test_class_ten_series_shows_live_paper_and_pending_siblings(self) -> None:
        self.register(f"ten-{uuid7_str()}@example.com", class_level=10)
        response = self.client.get("/v1/series")
        cards = {card["kind"]: card for card in response.json()["cards"]}
        self.assertEqual(cards["ai_lesson"]["status"], "live")
        self.assertEqual(cards["ai_lesson"]["paper_count"], 1)
        self.assertEqual(cards["exact_pyq"]["status"], "disabled")
        self.assertEqual(cards["pyq_pattern"]["status"], "pending")
        html = self.page("/app/series/ai-lesson")
        self.assertIn("Light chapter test", html)
        self.assertIn("Start paper", html)
        self.assertIn(n01_notice(10), html)
        pending = self.page("/app/series/pyq-pattern")
        self.assertIn("Content pending", pending)
        self.assertIn("Approved minimum for Class 10", pending)
        self.assertNotIn("Start paper", pending)
        dark = self.page("/app/series/exact-pyq")
        self.assertIn("dark until the source clearance", dark)
        self.assertNotIn("Start paper", dark)
        self.assertIn(
            "not an official CBSE paper", self.page("/app/series/board-practice")
        )

    def test_series_start_only_accepts_its_own_paper(self) -> None:
        session = self.register(f"series-{uuid7_str()}@example.com", class_level=10)
        csrf = str(session["csrf_token"])
        created = self.client.post(
            "/v1/tests/custom",
            json={"chapter_ids": [LIGHT], "count": 5},
            headers={"X-CSRF-Token": csrf},
        ).json()
        response = self.client.post(
            "/app/series/ai-lesson/start",
            data={"test_id": created["test"]["test_id"], "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("That paper is not here", response.text)
        response = self.client.post(
            "/app/series/ai-lesson/start",
            data={"test_id": self.paper_id, "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        attempt = response.headers["location"].rsplit("/", 1)[-1]
        player = self.page(f"/app/tests/{attempt}")
        self.assertIn(n01_notice(10), player)
        self.assertIn("AI lesson tests", player)

    def test_paper_under_a_draft_series_is_not_startable(self) -> None:
        series_id = uuid7_str()
        test_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test_series (series_id, slug, class_level, kind, title, "
            "language_set, status) VALUES (?, ?, 10, 'challenge', 'Draft challenge', "
            "'[\"en\"]', 'draft')",
            (series_id, f"draft-{series_id}"),
        )
        self.db.execute(
            "INSERT INTO test (test_id, series_id, title, language, duration_s, "
            "total_marks, structure, status) VALUES (?, ?, 'Hidden paper', 'en', "
            "600, 1, '{}', 'published')",
            (test_id, series_id),
        )
        self.db.execute(
            "INSERT INTO test_question (test_id, question_id, order_index, marks) "
            "VALUES (?, ?, 1, 1)",
            (test_id, self.paper_questions[0]),
        )
        response = self.client.post(
            f"/v1/tests/{test_id}/attempts", headers=self.headers()
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_seeded_series_paper_grades_and_reviews_with_copy(self) -> None:
        session = self.register(f"paper-{uuid7_str()}@example.com", class_level=10)
        csrf = str(session["csrf_token"])
        response = self.client.post(
            f"/v1/tests/{self.paper_id}/attempts",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 201, response.text)
        attempt_id = response.json()["attempt"]["attempt_id"]
        state = self.client.get(f"/v1/tests/attempts/{attempt_id}").json()
        self.assertEqual(state["series"]["kind"], "ai_lesson")
        self.assertEqual(
            state["series"]["blurb"],
            series_copy(
                series_by_slug("ai-lesson") or SERIES_DEFINITIONS["ai_lesson"],
                class_num=10,
                subject=subject_label(10),
            ),
        )
        self.client.post(
            f"/v1/tests/attempts/{attempt_id}/submit",
            headers={"X-CSRF-Token": csrf},
        )
        review = self.client.get(f"/app/tests/{attempt_id}/review")
        self.assertEqual(review.status_code, 200)
        self.assertIn("Chapter tests and mixed practice", review.text)
        self.assertIn(n01_notice(10), review.text)

    def test_series_catalogue_matches_the_pipeline_definitions(self) -> None:
        from factory.series import (
            MINIMUM_VOLUME,
            SERIES_SPECS,
            minimum_volume,
        )
        from factory.series import (
            SERIES_ORDER as PIPELINE_ORDER,
        )
        from factory.series import series_copy as pipeline_copy

        self.assertEqual(SERIES_ORDER, PIPELINE_ORDER)
        for kind in PIPELINE_ORDER:
            spec = SERIES_SPECS[kind]
            definition = SERIES_DEFINITIONS[kind]
            self.assertEqual(definition.label, spec.label)
            self.assertEqual(definition.purpose, spec.purpose)
            self.assertEqual(definition.languages, spec.language_policy)
            self.assertEqual(definition.notice_id, spec.notice_id)
            if definition.notice_id == "N-01":
                self.assertEqual(
                    series_copy(definition, class_num=10, subject=subject_label(10)),
                    pipeline_copy(spec, class_num=10, subject_en=subject_label(10)),
                )
            self.assertEqual(MINIMUM_VOLUME[10][kind], minimum_volume(10, kind))
            self.assertEqual(MINIMUM_VOLUME[12][kind], minimum_volume(12, kind))

    def test_n01_notice_matches_the_compliance_copy(self) -> None:
        text = (REPO_ROOT / "docs" / "compliance" / "notices.md").read_text(
            encoding="utf-8"
        )
        block = re.search(
            r"## N-01 — generated exam-pattern notice.*?\*\*EN\*\*\s*```text\n(.*?)\n```",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(block)
        assert block is not None
        expected = block.group(1)
        expected = expected.replace("{{class_num}}", "10").replace(
            "{{subject}}", "Science (Physics section)"
        )
        self.assertEqual(n01_notice(10), expected)

    # -- empty and partial states ------------------------------------------

    def test_empty_bank_states_are_honest(self) -> None:
        empty_db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        app = create_app(_config(self.root / "empty"), db_engine=empty_db)
        client = TestClient(app, base_url="https://testserver")
        client.post(
            "/v1/auth/register",
            json={
                "email": f"empty-{uuid7_str()}@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 10,
                "language": "en-IN",
            },
        )
        hub = client.get("/app/tests")
        self.assertEqual(hub.status_code, 200)
        self.assertIn("No chapter has an imported question bank yet", hub.text)
        builder = client.get("/app/tests/new")
        self.assertIn("No chapter has an imported question bank yet", builder.text)
        history = client.get("/app/tests/history")
        self.assertIn("No attempts for this filter", history.text)
        series = client.get("/app/series")
        self.assertIn("Content pending", series.text)
        self.assertIn("Not available yet", series.text)
        self.assertNotIn("Start paper", series.text)

    # -- template and a11y contracts ---------------------------------------

    def test_pages_are_base_field_notes_and_carry_private_headers(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        self.answer(
            attempt_id, self.state(attempt_id)["question"]["question_id"], correct=True
        )
        self.submit(attempt_id)
        pages = {
            "/app/tests": self.page("/app/tests"),
            "/app/tests/new": self.page("/app/tests/new"),
            "/app/tests/history": self.page("/app/tests/history"),
            "/app/series": self.page("/app/series"),
            "/app/series/ai-lesson": self.page("/app/series/ai-lesson"),
            f"/app/tests/{attempt_id}/review": self.page(
                f"/app/tests/{attempt_id}/review"
            ),
        }
        for path, html in pages.items():
            self.assertNotIn("zivon.css", html, path)
            self.assertIsNone(re.search(r'class="[^"]*\bzn-', html), path)
            self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), path)
            self.assertIsNone(re.search(r"<style\b", html), path)
            self.assertIsNone(re.search(r"\son[a-z]+\s*=", html), path)
            self.assertIn('class="skip"', html, path)
            self.assertIn(">Tests</a>", html, path)
            response = self.client.get(path)
            self.assertEqual(response.headers["cache-control"], "no-store", path)
            self.assertEqual(
                response.headers["x-robots-tag"], "noindex, nofollow", path
            )
            self.assertIn(
                "default-src 'self'", response.headers["content-security-policy"]
            )

    def test_player_and_review_are_keyboard_and_screen_reader_ready(self) -> None:
        created = self.create_custom()
        attempt_id = self.start(created["test"]["test_id"])["attempt"]["attempt_id"]
        html = self.page(f"/app/tests/{attempt_id}")
        self.assertIn('role="timer"', html)
        self.assertIn('aria-live="off"', html)
        self.assertIn('data-tests-clock-announce aria-live="polite"', html)
        self.assertIn("<fieldset", html)
        self.assertIn("<legend", html)
        self.assertIn('aria-current="true"', html)
        self.assertIn("Mark this question for review", html)
        self.assertIn("Not answered", html)
        self.assertIn("Marked for review", html)
        questions = self.state(attempt_id)["questions"]
        self.answer(attempt_id, questions[0]["question_id"], correct=True)
        self.answer(attempt_id, questions[1]["question_id"], correct=False)
        self.submit(attempt_id)
        review = self.page(f"/app/tests/{attempt_id}/review")
        self.assertIn('class="tests-sr"', review)
        self.assertIn("<caption", review)
        self.assertIn("Correct", review)
        self.assertIn("Not answered", review)
        self.assertIn("Incorrect", review)

    def test_no_secrets_in_the_new_test_surface(self) -> None:
        files = [
            REPO_ROOT / "backend" / "test_engine" / "service.py",
            REPO_ROOT / "backend" / "test_engine" / "series.py",
            REPO_ROOT / "backend" / "routes" / "tests.py",
            REPO_ROOT / "web" / "test_views.py",
            REPO_ROOT / "web" / "routes" / "tests.py",
            REPO_ROOT / "web" / "templates" / "app" / "tests" / "player.html",
            REPO_ROOT / "frontend" / "assets" / "tests.js",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\bsk-[A-Za-z0-9]{8,}", text), path)
            self.assertIsNone(re.search(r"api[_-]?key\s*[=:]\s*['\"]", text), path)
            self.assertNotIn("ZIVON_SESSION_TOKEN_KEY", text, path)
            self.assertNotIn("postgresql://", text, path)


class TestStoreTests(unittest.TestCase):
    """The F7 store additions: atomic paper creation and miss selection."""

    db: DatabaseEngine

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        importer.import_packs(cls.db, PACKS_DIR)

    def setUp(self) -> None:
        self.user_id = uuid7_str()
        self.db.execute(
            "INSERT INTO users (user_id, email, display_name, board, language, role) "
            "VALUES (?, ?, 'Asha', 'CBSE', 'en-IN', 'student')",
            (self.user_id, f"store-{self.user_id}@example.com"),
        )

    def test_create_test_with_questions_is_atomic_and_bounded(self) -> None:
        ids = select_question_ids(self.db, MOTION, language="en")[:3]
        test = create_test_with_questions(
            self.db,
            self.user_id,
            title="Store paper",
            chapter_ids=[MOTION],
            language="en",
            duration_s=600,
            questions=[{"question_id": qid, "marks": 1} for qid in ids],
            structure={"source": "custom"},
        )
        self.assertEqual(test["total_marks"], 3.0)
        with self.assertRaises(AssessmentError) as caught:
            create_test_with_questions(
                self.db,
                self.user_id,
                title="Bad paper",
                chapter_ids=[MOTION],
                language="en",
                duration_s=600,
                questions=[{"question_id": "no-such-question", "marks": 1}],
            )
        self.assertEqual(caught.exception.code, "E-TEST-QUESTIONS")

    def test_missed_ids_use_the_latest_submitted_answer_only(self) -> None:
        ids = select_question_ids(self.db, MOTION, language="en")[:2]
        test = create_test_with_questions(
            self.db,
            self.user_id,
            title="Miss paper",
            chapter_ids=[MOTION],
            language="en",
            duration_s=600,
            questions=[{"question_id": qid, "marks": 1} for qid in ids],
        )
        attempt = self.db.fetchone(
            "SELECT attempt_id FROM test_attempt WHERE user_id = ?", (self.user_id,)
        )
        self.assertIsNone(attempt)
        from backend.assessment import (
            create_test_attempt,
            save_test_answer,
            submit_test_attempt,
        )

        started = create_test_attempt(self.db, self.user_id, test["test_id"])
        attempt_id = str(started["attempt_id"])
        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=ids[0],
            answer={"index": 0},
        )
        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=ids[1],
            answer={"index": 0},
        )
        submit_test_attempt(self.db, self.user_id, attempt_id)
        missed = list_missed_test_question_ids(self.db, self.user_id, language="en")
        stored = [
            row
            for row in list_test_answers(self.db, self.user_id, attempt_id)
            if row["question_id"] in ids
        ]
        expected = [row["question_id"] for row in stored if row["correct"] is False]
        self.assertEqual(set(missed), set(expected))


class EmptySeriesTests(unittest.TestCase):
    """A class-10 catalogue with no imported series has no fake papers."""

    def test_class_ten_without_series_rows_is_all_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
            app = create_app(_config(root), db_engine=db)
            client = TestClient(app, base_url="https://testserver")
            client.post(
                "/v1/auth/register",
                json={
                    "email": f"empty10-{uuid7_str()}@example.com",
                    "password": PASSWORD,
                    "display_name": "Ravi",
                    "class_level": 10,
                    "language": "en-IN",
                },
            )
            response = client.get("/v1/series")
            self.assertEqual(response.status_code, 200)
            cards = {card["kind"]: card for card in response.json()["cards"]}
            self.assertEqual(cards["exact_pyq"]["status"], "disabled")
            for kind in (
                "ai_lesson",
                "pyq_pattern",
                "board_practice",
                "challenge",
                "loop",
            ):
                self.assertEqual(cards[kind]["status"], "pending", kind)
                self.assertEqual(cards[kind]["paper_count"], 0)
            html = client.get("/app/series").text
            self.assertIn("Content pending", html)
            self.assertNotIn("Start paper", html)
            self.assertIn(n01_notice(10), html)


if __name__ == "__main__":
    unittest.main()
