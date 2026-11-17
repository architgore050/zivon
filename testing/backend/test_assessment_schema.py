"""Schema contracts for revision `0004_practice_speaking_tests` (W4 foundation).

Hermetic SQLite in memory. These are the guarantees the feature routes rely on
and that SQL (not application code) must enforce: learner rows are scoped to a
user and die with the account, one live test attempt exists per (test, student),
a question in a published paper cannot be deleted out from under it, and no
table in the assessment foundation has an audio column (REQUIREMENTS §9.5, T11).
"""

from __future__ import annotations

import unittest

from backend.assessment.store import PACK_LANGUAGES, PRACTICE_MODES
from db import DatabaseEngine
from db.schema_assessment import PACK_LANGUAGES_0004, PRACTICE_TEST_TABLES_0004
from db.uuid7 import uuid7_str

AUDIO_COLUMN_MARKERS = ("audio", "wav", "opus", "pcm", "mp3", "blob")


class AssessmentSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        self.user_id = self._user("kid@example.com")
        self.question_id = self._question()

    # -- fixtures -----------------------------------------------------------

    def _user(self, email: str) -> str:
        user_id = uuid7_str()
        self.db.execute(
            "INSERT INTO users (user_id, email, board, language, role) "
            "VALUES (?, ?, 'CBSE', 'en-IN', 'student')",
            (user_id, email),
        )
        return user_id

    def _question(self, question_id: str = "q-test-001-en") -> str:
        self.db.execute(
            """
            INSERT INTO question_bank (
                question_id, base_item_id, class_level, chapter_id, concept_id,
                type, difficulty, marks, language, source_type, prompt, options,
                answer, explanation, expected_time_ms
            ) VALUES (?, ?, 9, 'class-9-x', 'class-9-x-concept', 'mcq', 'easy', 1,
                      'en', 'generated', 'Pick one', '["a","b"]',
                      '{"index": 0}', 'Because.', 30000)
            """,
            (question_id, question_id.rsplit("-", 1)[0]),
        )
        return question_id

    def _series(self) -> str:
        series_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test_series (series_id, slug, class_level, kind, title, status) "
            "VALUES (?, 'ai-lesson-10', 10, 'ai_lesson', 'AI Lesson', 'published')",
            (series_id,),
        )
        return series_id

    def _test(self) -> str:
        test_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test (test_id, series_id, title, duration_s, total_marks, status) "
            "VALUES (?, ?, 'Chapter test', 900, 1, 'published')",
            (test_id, self._series()),
        )
        self.db.execute(
            "INSERT INTO test_question (test_id, question_id, order_index, marks) "
            "VALUES (?, ?, 1, 1)",
            (test_id, self.question_id),
        )
        return test_id

    def test_schema_vocabulary_matches_the_runtime_constants(self) -> None:
        """The CHECK lists and the Python vocabularies cannot drift apart."""
        self.assertEqual(set(PACK_LANGUAGES_0004), set(PACK_LANGUAGES))
        for mode in PRACTICE_MODES:
            self.db.execute(
                "INSERT INTO practice_session (session_id, user_id, mode, question_ids) "
                "VALUES (?, ?, ?, '[]')",
                (uuid7_str(), self.user_id, mode),
            )
        self.assertEqual(
            len(self.db.fetchall("SELECT session_id FROM practice_session")),
            len(PRACTICE_MODES),
        )

    # -- no raw audio -------------------------------------------------------

    def test_assessment_tables_have_no_audio_column(self) -> None:
        for table in PRACTICE_TEST_TABLES_0004:
            columns = {
                str(row["name"]).lower()
                for row in self.db.fetchall(f"PRAGMA table_info({table})")
            }
            offenders = sorted(
                column
                for column in columns
                if any(marker in column for marker in AUDIO_COLUMN_MARKERS)
            )
            self.assertEqual(
                offenders,
                [],
                f"{table} has an audio-shaped column; raw audio is never stored",
            )

    # -- referential integrity and user scoping -----------------------------

    def test_deleting_the_account_removes_learner_rows(self) -> None:
        session_id = uuid7_str()
        self.db.execute(
            "INSERT INTO practice_session (session_id, user_id, mode, chapter_id, "
            "question_ids, question_count) VALUES (?, ?, 'chapter', 'class-9-x', ?, 1)",
            (session_id, self.user_id, f'["{self.question_id}"]'),
        )
        self.db.execute(
            "INSERT INTO practice_attempt (attempt_id, session_id, question_id, "
            "answer, correct) VALUES (?, ?, ?, '{}', 1)",
            (uuid7_str(), session_id, self.question_id),
        )
        self.db.execute(
            "INSERT INTO speaking_attempt (attempt_id, user_id, prompt_id, language) "
            "VALUES (?, ?, 'spk-1', 'en')",
            (uuid7_str(), self.user_id),
        )
        self.db.execute(
            "INSERT INTO test (test_id, user_id, title, duration_s) "
            "VALUES ('custom-1', ?, 'Custom', 600)",
            (self.user_id,),
        )
        self.db.execute(
            "INSERT INTO test_attempt (attempt_id, test_id, user_id) "
            "VALUES (?, 'custom-1', ?)",
            (uuid7_str(), self.user_id),
        )
        self.db.execute("DELETE FROM users WHERE user_id = ?", (self.user_id,))
        for table in (
            "practice_session",
            "practice_attempt",
            "speaking_attempt",
            "test_attempt",
        ):
            row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
            assert row is not None
            self.assertEqual(int(row["c"]), 0, f"{table} survived account deletion")
        custom = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM test WHERE test_id = 'custom-1'"
        )
        assert custom is not None
        self.assertEqual(int(custom["c"]), 0)

    def test_practice_attempt_cascades_with_its_session(self) -> None:
        session_id = uuid7_str()
        self.db.execute(
            "INSERT INTO practice_session (session_id, user_id, mode, question_ids, "
            "question_count) VALUES (?, ?, 'daily', ?, 1)",
            (session_id, self.user_id, f'["{self.question_id}"]'),
        )
        self.db.execute(
            "INSERT INTO practice_attempt (attempt_id, session_id, question_id, "
            "answer, correct) VALUES (?, ?, ?, '{}', 1)",
            (uuid7_str(), session_id, self.question_id),
        )
        self.db.execute(
            "DELETE FROM practice_session WHERE session_id = ?", (session_id,)
        )
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM practice_attempt")
        assert row is not None
        self.assertEqual(int(row["c"]), 0)

    def test_a_question_used_in_a_paper_cannot_be_deleted(self) -> None:
        test_id = self._test()
        self.assertTrue(test_id)
        with self.assertRaises(Exception):  # noqa: B017 — FK RESTRICT is the contract
            self.db.execute(
                "DELETE FROM question_bank WHERE question_id = ?", (self.question_id,)
            )

    def test_one_live_attempt_per_student_and_test(self) -> None:
        test_id = self._test()
        attempt_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test_attempt (attempt_id, test_id, user_id) VALUES (?, ?, ?)",
            (attempt_id, test_id, self.user_id),
        )
        with self.assertRaises(Exception):  # noqa: B017 — partial unique index
            self.db.execute(
                "INSERT INTO test_attempt (attempt_id, test_id, user_id) VALUES (?, ?, ?)",
                (uuid7_str(), test_id, self.user_id),
            )
        # Once submitted, the student may start a fresh attempt.
        self.db.execute(
            "UPDATE test_attempt SET status = 'submitted', submitted_at = "
            "CURRENT_TIMESTAMP WHERE attempt_id = ?",
            (attempt_id,),
        )
        self.db.execute(
            "INSERT INTO test_attempt (attempt_id, test_id, user_id) VALUES (?, ?, ?)",
            (uuid7_str(), test_id, self.user_id),
        )
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM test_attempt WHERE test_id = ?", (test_id,)
        )
        assert row is not None
        self.assertEqual(int(row["c"]), 2)

    # -- value checks -------------------------------------------------------

    def test_question_identity_and_vocabulary_checks(self) -> None:
        with self.assertRaises(Exception):  # noqa: B017 — one row per (item, language)
            self._question(question_id="q-test-001-hi")
        self.db.execute(
            "UPDATE question_bank SET language = 'hi' WHERE question_id = ?",
            (self.question_id,),
        )
        with self.assertRaises(Exception):  # noqa: B017 — language vocabulary
            self.db.execute(
                "UPDATE question_bank SET language = 'ta' WHERE question_id = ?",
                (self.question_id,),
            )
        with self.assertRaises(Exception):  # noqa: B017 — type vocabulary
            self.db.execute(
                "UPDATE question_bank SET type = 'essay' WHERE question_id = ?",
                (self.question_id,),
            )
        with self.assertRaises(Exception):  # noqa: B017 — a question needs marks
            self.db.execute(
                "UPDATE question_bank SET marks = 0 WHERE question_id = ?",
                (self.question_id,),
            )

    def test_learner_ranges_are_schema_enforced(self) -> None:
        session_id = uuid7_str()
        self.db.execute(
            "INSERT INTO practice_session (session_id, user_id, mode, question_ids, "
            "question_count) VALUES (?, ?, 'chapter', '[]', 0)",
            (session_id, self.user_id),
        )
        with self.assertRaises(Exception):  # noqa: B017 — unknown practice mode
            self.db.execute(
                "INSERT INTO practice_session (session_id, user_id, mode, question_ids) "
                "VALUES (?, ?, 'exam', '[]')",
                (uuid7_str(), self.user_id),
            )
        with self.assertRaises(Exception):  # noqa: B017 — score is a percentage
            self.db.execute(
                "UPDATE practice_session SET score = 140 WHERE session_id = ?",
                (session_id,),
            )
        with self.assertRaises(Exception):  # noqa: B017 — hints are bounded
            self.db.execute(
                "INSERT INTO practice_attempt (attempt_id, session_id, question_id, "
                "answer, correct, hints_used) VALUES (?, ?, 'q', '{}', 1, 99)",
                (uuid7_str(), session_id),
            )

    def test_a_test_belongs_to_a_series_or_a_student(self) -> None:
        with self.assertRaises(Exception):  # noqa: B017 — no orphan papers
            self.db.execute(
                "INSERT INTO test (test_id, title, duration_s) VALUES ('orphan', 'X', 60)"
            )


if __name__ == "__main__":
    unittest.main()
