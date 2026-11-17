"""Practice / speaking / test repository helpers (`backend/assessment/store.py`).

Hermetic SQLite in memory, seeded from the tracked P2 packs through the real
importer. Covers question lookup and answer-key withholding, the deterministic
answer grader (MCQ, assertion-reason, numeric tolerance), practice session and
attempt lifecycle, speaking attempt save/get/delete, and the test-attempt flow
(resume, autosave upsert, grading on submit, idempotent submit). Every learner
call is exercised for cross-account isolation.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType

from backend.assessment import (
    AssessmentError,
    check_answer,
    complete_practice_session,
    create_practice_session,
    create_test_attempt,
    delete_speaking_attempt,
    fetch_question,
    fetch_questions,
    fetch_speaking_prompt,
    get_practice_session,
    get_series,
    get_speaking_attempt,
    get_test,
    get_test_attempt,
    list_practice_attempts,
    list_practice_history,
    list_series,
    list_speaking_attempts,
    list_speaking_prompts,
    list_test_answers,
    list_test_attempts,
    list_test_questions,
    list_tests,
    record_practice_answer,
    save_speaking_attempt,
    save_test_answer,
    select_question_ids,
    submit_test_attempt,
)
from db import DatabaseEngine
from db.uuid7 import uuid7_str

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
MCQ = "q-c9-motion-001-en"  # options[0] is correct
NUMERIC = "q-c9-motion-003-en"  # 15.0 m/s, tolerance 0.1


def _load_importer() -> ModuleType:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location("import_assessment_packs_store", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 11, 17, 9, 0, tzinfo=datetime.UTC)


class StoreTestCase(unittest.TestCase):
    db: DatabaseEngine

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        importer.import_packs(cls.db, PACKS_DIR)

    def setUp(self) -> None:
        self.user_id = self._user(f"kid-{uuid7_str()}@example.com", "Asha")
        self.other_id = self._user(f"other-{uuid7_str()}@example.com", "Ravi")

    # -- fixtures -----------------------------------------------------------

    def _user(self, email: str, name: str) -> str:
        user_id = uuid7_str()
        self.db.execute(
            "INSERT INTO users (user_id, email, display_name, board, language, role) "
            "VALUES (?, ?, ?, 'CBSE', 'en-IN', 'student')",
            (user_id, email, name),
        )
        return user_id

    def _paper(self, question_ids: tuple[str, ...] = (MCQ, NUMERIC)) -> str:
        _series_id, test_id = self._paper_with_series(question_ids)
        return test_id

    def _paper_with_series(
        self, question_ids: tuple[str, ...] = (MCQ, NUMERIC)
    ) -> tuple[str, str]:
        series_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test_series (series_id, slug, class_level, kind, title, "
            "language_set, status) VALUES (?, ?, 9, 'ai_lesson', 'AI Lesson', "
            "'[\"en\",\"hi\"]', 'published')",
            (series_id, f"ai-lesson-9-{series_id[-6:]}"),
        )
        test_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test (test_id, series_id, title, language, duration_s, "
            "total_marks, status) VALUES (?, ?, 'Motion test', 'en', 900, ?, 'published')",
            (test_id, series_id, len(question_ids)),
        )
        for index, question_id in enumerate(question_ids, start=1):
            self.db.execute(
                "INSERT INTO test_question (test_id, question_id, order_index, section, marks) "
                "VALUES (?, ?, ?, 'A', 1)",
                (test_id, question_id, index),
            )
        return series_id, test_id

    # -- question bank ------------------------------------------------------

    def test_select_question_ids_is_chapter_language_and_concept_aware(self) -> None:
        english = select_question_ids(self.db, MOTION, language="en")
        self.assertEqual(len(english), 15)
        self.assertEqual(english, sorted(english), "the candidate set is stable")

        hindi = select_question_ids(self.db, MOTION, language="hi")
        self.assertEqual(len(hindi), 15)
        self.assertTrue(all(question_id.endswith("-hi") for question_id in hindi))

        concept = "class-9-describing-motion-around-us-acceleration"
        scoped = select_question_ids(
            self.db, MOTION, language="en", concept_ids=[concept]
        )
        self.assertEqual(len(scoped), 2)
        for question_id in scoped:
            question = fetch_question(self.db, question_id)
            assert question is not None
            self.assertEqual(question.concept_id, concept)

        hard = select_question_ids(
            self.db, MOTION, language="en", difficulties=["hard"]
        )
        self.assertTrue(hard)
        for question_id in hard:
            question = fetch_question(self.db, question_id)
            assert question is not None
            self.assertEqual(question.difficulty, "hard")

        self.assertEqual(select_question_ids(self.db, "no-such-chapter"), [])
        self.assertEqual(
            len(select_question_ids(self.db, MOTION, language="en", limit=5)), 5
        )
        with self.assertRaises(AssessmentError) as caught:
            select_question_ids(self.db, MOTION, language="ta")
        self.assertEqual(caught.exception.code, "E-LANGUAGE-INVALID")

    def test_retired_and_draft_questions_never_serve(self) -> None:
        try:
            self.db.execute(
                "UPDATE question_bank SET status = 'retired' WHERE question_id = ?",
                (MCQ,),
            )
            self.db.execute(
                "UPDATE question_bank SET status = 'draft' WHERE question_id = ?",
                (NUMERIC,),
            )
            servable = select_question_ids(self.db, MOTION, language="en")
            self.assertNotIn(MCQ, servable)
            self.assertNotIn(NUMERIC, servable)
            self.assertEqual(len(servable), 13)
        finally:
            self.db.execute(
                "UPDATE question_bank SET status = 'reviewed' WHERE question_id IN (?, ?)",
                (MCQ, NUMERIC),
            )

    def test_fetch_questions_preserves_request_order_and_skips_unknown(self) -> None:
        questions = fetch_questions(self.db, [NUMERIC, "missing-1", MCQ])
        self.assertEqual(
            [question.question_id for question in questions], [NUMERIC, MCQ]
        )
        self.assertEqual(fetch_questions(self.db, []), [])
        self.assertIsNone(fetch_question(self.db, "missing-1"))
        self.assertIsNone(fetch_question(self.db, ""))

    def test_player_shape_withholds_the_answer_key(self) -> None:
        question = fetch_question(self.db, MCQ)
        assert question is not None
        public = question.public()
        for hidden in ("answer", "explanation", "misconception", "source_ref"):
            self.assertNotIn(hidden, public)
        review = question.review()
        self.assertEqual(review["answer"], {"index": 0})
        self.assertTrue(review["explanation"])
        self.assertIn("options", review)

    # -- grading ------------------------------------------------------------

    def test_mcq_and_assertion_reason_grade_by_index(self) -> None:
        question = fetch_question(self.db, MCQ)
        assert question is not None
        correct = check_answer(question, 0)
        self.assertTrue(correct.correct)
        self.assertEqual(correct.stored, {"index": 0})
        wrong = check_answer(question, 2)
        self.assertFalse(wrong.correct)

        assertion_reason = fetch_question(self.db, "q-c9-motion-005-en")
        assert assertion_reason is not None
        self.assertEqual(assertion_reason.type, "assertion_reason")
        self.assertEqual(len(assertion_reason.options), 4)
        self.assertTrue(check_answer(assertion_reason, {"index": 0}).correct)

    def test_numeric_grades_within_the_authored_tolerance(self) -> None:
        question = fetch_question(self.db, NUMERIC)
        assert question is not None
        self.assertEqual(question.type, "numeric")
        self.assertTrue(check_answer(question, 15.0).correct)
        self.assertTrue(check_answer(question, 15.09).correct)
        self.assertTrue(check_answer(question, {"value": 14.91}).correct)
        self.assertFalse(check_answer(question, 15.2).correct)

    def test_a_malformed_answer_is_an_error_not_a_wrong_answer(self) -> None:
        question = fetch_question(self.db, MCQ)
        assert question is not None
        for bad in (True, "0", None, 4, -1, 1.5):
            with self.assertRaises(AssessmentError) as caught:
                check_answer(question, bad)
            self.assertEqual(caught.exception.code, "E-ANSWER-INVALID")
        numeric = fetch_question(self.db, NUMERIC)
        assert numeric is not None
        for bad in (float("nan"), float("inf"), "15", True):
            with self.assertRaises(AssessmentError):
                check_answer(numeric, bad)

    # -- practice -----------------------------------------------------------

    def _session(
        self, question_ids: tuple[str, ...] = (MCQ, NUMERIC)
    ) -> dict[str, object]:
        return create_practice_session(
            self.db,
            self.user_id,
            mode="chapter",
            chapter_id=MOTION,
            question_ids=list(question_ids),
            now=_now(),
        )

    def test_practice_session_lifecycle_and_score(self) -> None:
        session = self._session()
        self.assertEqual(session["question_count"], 2)
        self.assertEqual(session["question_ids"], [MCQ, NUMERIC])
        self.assertIsNone(session["completed_at"])
        session_id = str(session["session_id"])

        first = record_practice_answer(
            self.db,
            self.user_id,
            session_id,
            question_id=MCQ,
            answer={"index": 0},
            time_ms=12000,
            hints_used=1,
            now=_now(),
        )
        self.assertEqual(first["attempt_no"], 1)
        self.assertTrue(first["correct"])
        retry = record_practice_answer(
            self.db,
            self.user_id,
            session_id,
            question_id=MCQ,
            answer={"index": 0},
            now=_now(),
        )
        self.assertEqual(
            retry["attempt_no"], 2, "a retry is a new attempt, not an update"
        )
        wrong = record_practice_answer(
            self.db,
            self.user_id,
            session_id,
            question_id=NUMERIC,
            answer={"value": 15.2},  # outside the authored 0.1 tolerance
            now=_now(),
        )
        self.assertFalse(wrong["correct"], "the store grades, the caller cannot")

        attempts = list_practice_attempts(self.db, self.user_id, session_id)
        self.assertEqual(len(attempts), 3)

        completed = complete_practice_session(
            self.db, self.user_id, session_id, now=_now()
        )
        assert completed is not None
        # Two attempts on the MCQ (both correct) plus one wrong numeric answer: 2/3.
        self.assertAlmostEqual(float(completed["score"]), 66.67, places=2)
        self.assertIsNotNone(completed["completed_at"])

        again = complete_practice_session(self.db, self.user_id, session_id, now=_now())
        assert again is not None
        self.assertEqual(again["score"], completed["score"], "completion is idempotent")

        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.user_id,
                session_id,
                question_id=MCQ,
                answer={"index": 0},
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-CLOSED")

        history = list_practice_history(self.db, self.user_id)
        self.assertTrue(any(row["session_id"] == session_id for row in history))
        self.assertEqual(list_practice_history(self.db, self.other_id), [])

    def test_practice_session_validation(self) -> None:
        with self.assertRaises(AssessmentError) as caught:
            create_practice_session(
                self.db, self.user_id, mode="exam", question_ids=[MCQ]
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-MODE")
        with self.assertRaises(AssessmentError) as caught:
            create_practice_session(
                self.db, self.user_id, mode="chapter", question_ids=[]
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-QUESTIONS")
        with self.assertRaises(AssessmentError):
            create_practice_session(
                self.db,
                self.user_id,
                mode="daily",
                question_ids=[f"q-{index}" for index in range(201)],
            )

    def test_practice_rows_are_owner_scoped(self) -> None:
        session = self._session()
        session_id = str(session["session_id"])
        self.assertIsNone(get_practice_session(self.db, self.other_id, session_id))
        self.assertEqual(list_practice_attempts(self.db, self.other_id, session_id), [])
        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.other_id,
                session_id,
                question_id=MCQ,
                answer={"index": 0},
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-NOT-FOUND")
        self.assertIsNone(
            complete_practice_session(self.db, self.other_id, session_id, score=100.0)
        )

    def test_practice_answer_bounds(self) -> None:
        session = self._session()
        session_id = str(session["session_id"])
        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.user_id,
                session_id,
                question_id=MCQ,
                answer={"index": 0},
                hints_used=21,
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-HINTS")
        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.user_id,
                session_id,
                question_id=MCQ,
                answer={"index": 0},
                time_ms=4_000_000,
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-TIME")

    def test_a_question_outside_the_session_is_rejected(self) -> None:
        session = self._session((MCQ,))
        session_id = str(session["session_id"])
        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.user_id,
                session_id,
                question_id=NUMERIC,
                answer={"value": 15.0},
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-QUESTION-UNKNOWN")

    def test_an_unknown_question_or_bad_answer_is_rejected(self) -> None:
        session = self._session()
        session_id = str(session["session_id"])
        forged = create_practice_session(
            self.db,
            self.user_id,
            mode="daily",
            question_ids=["q-does-not-exist-en"],
        )
        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.user_id,
                str(forged["session_id"]),
                question_id="q-does-not-exist-en",
                answer={"index": 0},
            )
        self.assertEqual(caught.exception.code, "E-PRACTICE-QUESTION-UNKNOWN")
        with self.assertRaises(AssessmentError) as caught:
            record_practice_answer(
                self.db,
                self.user_id,
                session_id,
                question_id=MCQ,
                answer={"index": 99},
            )
        self.assertEqual(caught.exception.code, "E-ANSWER-INVALID")

    # -- speaking -----------------------------------------------------------

    def test_speaking_prompts_withhold_the_answer(self) -> None:
        prompts = list_speaking_prompts(self.db, chapter_id=MOTION, language="en")
        self.assertEqual(len(prompts), 3)
        for prompt in prompts:
            self.assertNotIn("model_answer", prompt)
            self.assertNotIn(
                "key_ideas", prompt, "the key ideas are the expected answer"
            )
            self.assertGreaterEqual(prompt["key_idea_count"], 3)
            self.assertTrue(prompt["rubric"])

        hindi = list_speaking_prompts(self.db, chapter_id=MOTION, language="hi")
        self.assertEqual(len(hindi), 3)
        self.assertTrue(all(prompt["language"] == "hi" for prompt in hindi))

        full = fetch_speaking_prompt(self.db, str(prompts[0]["prompt_id"]), "en")
        assert full is not None
        self.assertTrue(full["model_answer"])
        self.assertEqual(len(full["key_ideas"]), full["key_idea_count"])
        self.assertEqual(full["model_answer_source"]["book_id"], "ncert-science-9")
        self.assertIsNone(fetch_speaking_prompt(self.db, "spk-missing", "en"))

    def test_speaking_attempt_save_get_delete(self) -> None:
        attempt = save_speaking_attempt(
            self.db,
            self.user_id,
            prompt_id="spk-c9-motion-001",
            language="en",
            transcript="Distance is the path, displacement is the net change.",
            rubric_scores={"pass_ratio": 0.75, "ideas_present": 3},
            feedback={"band": "pass", "label": "AI feedback"},
            score=75.0,
            duration_ms=38000,
            now=_now(),
        )
        attempt_id = str(attempt["attempt_id"])
        self.assertEqual(attempt["score"], 75.0)
        self.assertEqual(attempt["feedback"]["band"], "pass")

        fetched = get_speaking_attempt(self.db, self.user_id, attempt_id)
        assert fetched is not None
        self.assertIn("displacement", str(fetched["transcript"]))
        self.assertIsNone(get_speaking_attempt(self.db, self.other_id, attempt_id))

        listed = list_speaking_attempts(
            self.db, self.user_id, prompt_id="spk-c9-motion-001"
        )
        self.assertEqual([row["attempt_id"] for row in listed], [attempt_id])
        self.assertEqual(list_speaking_attempts(self.db, self.other_id), [])

        self.assertFalse(delete_speaking_attempt(self.db, self.other_id, attempt_id))
        self.assertTrue(delete_speaking_attempt(self.db, self.user_id, attempt_id))
        self.assertIsNone(get_speaking_attempt(self.db, self.user_id, attempt_id))
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM speaking_attempt WHERE attempt_id = ?",
            (attempt_id,),
        )
        assert row is not None
        self.assertEqual(int(row["c"]), 0, "delete is a hard delete, not a tombstone")

    def test_speaking_attempt_validation(self) -> None:
        with self.assertRaises(AssessmentError) as caught:
            save_speaking_attempt(
                self.db,
                self.user_id,
                prompt_id="spk-missing",
                language="en",
                transcript="hello",
            )
        self.assertEqual(caught.exception.code, "E-SPEAKING-PROMPT-UNKNOWN")
        with self.assertRaises(AssessmentError) as caught:
            save_speaking_attempt(
                self.db,
                self.user_id,
                prompt_id="spk-c9-motion-001",
                language="en",
                transcript="x" * 4001,
            )
        self.assertEqual(caught.exception.code, "E-SPEAKING-TRANSCRIPT")
        with self.assertRaises(AssessmentError) as caught:
            save_speaking_attempt(
                self.db,
                self.user_id,
                prompt_id="spk-c9-motion-001",
                language="ta",
                transcript=None,
            )
        self.assertEqual(caught.exception.code, "E-LANGUAGE-INVALID")

    # -- tests and series ---------------------------------------------------

    def test_series_and_test_visibility(self) -> None:
        series_id, test_id = self._paper_with_series()
        series = list_series(self.db, class_level=9)
        self.assertTrue(series)
        self.assertIsNotNone(get_series(self.db, str(series[0]["slug"])))
        self.assertIsNone(get_series(self.db, "no-such-series"))
        self.assertEqual(list_series(self.db, class_level=12), [])

        self.assertTrue(
            any(row["test_id"] == test_id for row in list_tests(self.db, series_id))
        )
        self.assertIsNotNone(get_test(self.db, test_id, user_id=self.user_id))

        custom = uuid7_str()
        self.db.execute(
            "INSERT INTO test (test_id, user_id, title, duration_s, status) "
            "VALUES (?, ?, 'My test', 600, 'draft')",
            (custom, self.user_id),
        )
        self.assertIsNotNone(get_test(self.db, custom, user_id=self.user_id))
        self.assertIsNone(get_test(self.db, custom, user_id=self.other_id))

        draft = uuid7_str()
        self.db.execute(
            "INSERT INTO test (test_id, series_id, title, duration_s, status) "
            "VALUES (?, ?, 'Unpublished', 600, 'draft')",
            (draft, series_id),
        )
        self.assertIsNone(get_test(self.db, draft, user_id=self.user_id))
        self.assertEqual(
            [
                row["test_id"]
                for row in list_tests(self.db, series_id, include_unpublished=True)
                if row["test_id"] == draft
            ],
            [draft],
        )

    def test_paper_questions_use_paper_marks_and_hide_the_key(self) -> None:
        test_id = self._paper()
        player = list_test_questions(self.db, test_id)
        self.assertEqual([row["question_id"] for row in player], [MCQ, NUMERIC])
        self.assertEqual([row["order_index"] for row in player], [1, 2])
        self.assertEqual([row["marks"] for row in player], [1.0, 1.0])
        self.assertEqual([row["section"] for row in player], ["A", "A"])
        self.assertNotIn("answer", player[0])

        review = list_test_questions(self.db, test_id, include_answers=True)
        self.assertEqual(review[0]["answer"], {"index": 0})
        self.assertTrue(review[1]["explanation"])

    def test_test_attempt_resumes_autosaves_and_submits(self) -> None:
        test_id = self._paper()
        attempt = create_test_attempt(self.db, self.user_id, test_id, now=_now())
        attempt_id = str(attempt["attempt_id"])
        self.assertEqual(attempt["status"], "in_progress")

        resumed = create_test_attempt(self.db, self.user_id, test_id, now=_now())
        self.assertEqual(
            resumed["attempt_id"], attempt_id, "starting twice resumes the live attempt"
        )

        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=MCQ,
            answer={"index": 0},
            time_ms=9000,
            now=_now(),
        )
        # Autosave is an upsert, and a flag-only save keeps the answer.
        save_test_answer(
            self.db, self.user_id, attempt_id, question_id=MCQ, flagged=True
        )
        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=NUMERIC,
            answer={"value": 15.2},
            now=_now(),
        )
        answers = {
            row["question_id"]: row
            for row in list_test_answers(self.db, self.user_id, attempt_id)
        }
        self.assertEqual(answers[MCQ]["answer"], {"index": 0})
        self.assertTrue(answers[MCQ]["flagged"])
        self.assertEqual(answers[MCQ]["time_ms"], 9000)

        result = submit_test_attempt(self.db, self.user_id, attempt_id, now=_now())
        assert result is not None
        self.assertEqual(result["status"], "submitted")
        self.assertAlmostEqual(float(result["score"]), 50.0, places=2)
        self.assertIsNotNone(result["submitted_at"])

        graded = {
            row["question_id"]: row
            for row in list_test_answers(self.db, self.user_id, attempt_id)
        }
        self.assertTrue(graded[MCQ]["correct"])
        self.assertEqual(float(graded[MCQ]["marks_awarded"]), 1.0)
        self.assertFalse(graded[NUMERIC]["correct"])
        self.assertEqual(float(graded[NUMERIC]["marks_awarded"]), 0.0)

        again = submit_test_attempt(self.db, self.user_id, attempt_id, now=_now())
        assert again is not None
        self.assertEqual(again["score"], result["score"], "submit is idempotent")

        fresh = create_test_attempt(self.db, self.user_id, test_id, now=_now())
        self.assertNotEqual(
            fresh["attempt_id"], attempt_id, "a submitted test can restart"
        )
        self.assertEqual(len(list_test_attempts(self.db, self.user_id)), 2)
        self.assertEqual(list_test_attempts(self.db, self.other_id), [])

    def test_test_attempt_guards(self) -> None:
        test_id = self._paper()
        with self.assertRaises(AssessmentError) as caught:
            create_test_attempt(self.db, self.user_id, "no-such-test")
        self.assertEqual(caught.exception.code, "E-TEST-NOT-FOUND")

        attempt_id = str(
            create_test_attempt(self.db, self.user_id, test_id)["attempt_id"]
        )
        self.assertIsNone(get_test_attempt(self.db, self.other_id, attempt_id))
        with self.assertRaises(AssessmentError) as caught:
            save_test_answer(
                self.db,
                self.other_id,
                attempt_id,
                question_id=MCQ,
                answer={"index": 0},
            )
        self.assertEqual(caught.exception.code, "E-TEST-ATTEMPT-NOT-FOUND")
        with self.assertRaises(AssessmentError) as caught:
            save_test_answer(
                self.db,
                self.user_id,
                attempt_id,
                question_id="q-not-on-paper",
                answer={"index": 0},
            )
        self.assertEqual(caught.exception.code, "E-TEST-QUESTION-UNKNOWN")
        self.assertIsNone(submit_test_attempt(self.db, self.other_id, attempt_id))

        submit_test_attempt(self.db, self.user_id, attempt_id)
        with self.assertRaises(AssessmentError) as caught:
            save_test_answer(
                self.db,
                self.user_id,
                attempt_id,
                question_id=MCQ,
                answer={"index": 1},
            )
        self.assertEqual(caught.exception.code, "E-TEST-ATTEMPT-CLOSED")

    def test_a_malformed_saved_answer_scores_zero_instead_of_blocking_submit(
        self,
    ) -> None:
        test_id = self._paper()
        attempt_id = str(
            create_test_attempt(self.db, self.user_id, test_id)["attempt_id"]
        )
        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=MCQ,
            answer={"index": 99},  # out of range: a stale/forged row
        )
        result = submit_test_attempt(self.db, self.user_id, attempt_id)
        assert result is not None
        self.assertEqual(result["status"], "submitted")
        self.assertAlmostEqual(float(result["score"]), 0.0, places=2)
        graded = {
            row["question_id"]: row
            for row in list_test_answers(self.db, self.user_id, attempt_id)
        }
        self.assertFalse(graded[MCQ]["correct"])
        self.assertEqual(float(graded[MCQ]["marks_awarded"]), 0.0)

    def test_unanswered_questions_count_against_the_score(self) -> None:
        test_id = self._paper()
        attempt_id = str(
            create_test_attempt(self.db, self.user_id, test_id)["attempt_id"]
        )
        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=MCQ,
            answer={"index": 0},
        )
        result = submit_test_attempt(self.db, self.user_id, attempt_id)
        assert result is not None
        self.assertAlmostEqual(float(result["score"]), 50.0, places=2)


if __name__ == "__main__":
    unittest.main()
