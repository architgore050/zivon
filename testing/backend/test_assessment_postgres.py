"""PostgreSQL parity for the W4 foundation (db-spec §4.19, ADR-0001/0016).

SQLite and PostgreSQL differ exactly where hand-written SQL is easy to get
wrong: boolean columns reject `1`/`0` on PostgreSQL, `SUM(<boolean>)` does not
exist there, and JSON columns round-trip through a driver that may hand back a
decoded object rather than text. The SQLite suites cannot see any of that, so
this module runs the real import + store flow against PostgreSQL 16 when the
environment provides one.

In CI the `tests` job sets `ZIVON_DB_URL` to a throwaway PostgreSQL 16 service,
so this runs there. Locally, without a PostgreSQL URL (or without psycopg), it
**skips with a reason** - a skip is never converted into a pass.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.assessment import (
    complete_practice_session,
    create_practice_session,
    create_test_attempt,
    list_practice_attempts,
    list_speaking_prompts,
    list_test_answers,
    record_practice_answer,
    save_speaking_attempt,
    save_test_answer,
    select_question_ids,
    submit_test_attempt,
)
from db.engine import DatabaseEngine
from db.uuid7 import uuid7_str

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
MCQ = "q-c9-motion-001-en"
NUMERIC = "q-c9-motion-003-en"
PG_URL = os.environ.get("ZIVON_DB_URL", "").strip()
PARITY_DB = "zivon_w4_parity"


def _load_importer() -> ModuleType:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location("import_assessment_packs_pg", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _skip_reason() -> str | None:
    if not PG_URL.startswith("postgresql"):
        return "ZIVON_DB_URL is not a PostgreSQL URL (SQLite-only environment)"
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return "psycopg is not installed"
    return None


SKIP_REASON = _skip_reason()


def _db_url(database: str) -> str:
    """Point the configured DSN at another database on the same server."""
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", "", ""))


def _admin_connection() -> Any:
    """Connect to the maintenance database to create/drop the parity database."""
    import psycopg

    return psycopg.connect(_db_url("postgres"), autocommit=True)


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class PostgresParityTests(unittest.TestCase):
    db: DatabaseEngine
    user_id: str

    @classmethod
    def setUpClass(cls) -> None:
        admin = _admin_connection()
        try:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{PARITY_DB}"')
                cur.execute(f'CREATE DATABASE "{PARITY_DB}"')
        except Exception as exc:  # no privilege means no parity run
            if "permission denied" in str(exc).lower():
                raise unittest.SkipTest(
                    "the PostgreSQL role cannot CREATE DATABASE for the parity test"
                ) from exc
            raise
        finally:
            admin.close()

        cls.db = DatabaseEngine.from_url(_db_url(PARITY_DB), auto_migrate=True)
        _load_importer().import_packs(cls.db, PACKS_DIR)
        cls.user_id = uuid7_str()
        cls.db.execute(
            "INSERT INTO users (user_id, email, board, language, role) "
            "VALUES (?, ?, 'CBSE', 'en-IN', 'student')",
            (cls.user_id, f"parity-{cls.user_id[:8]}@example.com"),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        admin = _admin_connection()
        try:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{PARITY_DB}"')
        finally:
            admin.close()

    def _paper(self) -> str:
        series_id = uuid7_str()
        test_id = uuid7_str()
        self.db.execute(
            "INSERT INTO test_series (series_id, slug, class_level, kind, title, "
            "language_set, status) VALUES (?, ?, 9, 'ai_lesson', 'AI Lesson', "
            "'[\"en\"]', 'published')",
            (series_id, f"parity-series-{series_id[-8:]}"),
        )
        self.db.execute(
            "INSERT INTO test (test_id, series_id, title, language, duration_s, "
            "total_marks, status) VALUES (?, ?, 'Parity test', 'en', 900, 2, 'published')",
            (test_id, series_id),
        )
        for index, question_id in enumerate((MCQ, NUMERIC), start=1):
            self.db.execute(
                "INSERT INTO test_question (test_id, question_id, order_index, marks) "
                "VALUES (?, ?, ?, 1)",
                (test_id, question_id, index),
            )
        return test_id

    def test_imported_rows_read_back_with_the_same_shape(self) -> None:
        self.assertEqual(len(select_question_ids(self.db, MOTION, language="en")), 15)
        prompts = list_speaking_prompts(self.db, chapter_id=MOTION, language="en")
        self.assertEqual(len(prompts), 3)
        self.assertNotIn("key_ideas", prompts[0])
        self.assertIsInstance(prompts[0]["concept_ids"], list)
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM question_bank WHERE chapter_id = ?", (MOTION,)
        )
        assert row is not None
        self.assertEqual(int(row["c"]), 45)

    def test_practice_flow_writes_and_grades_on_postgres(self) -> None:
        session = create_practice_session(
            self.db,
            self.user_id,
            mode="chapter",
            chapter_id=MOTION,
            question_ids=[MCQ, NUMERIC],
        )
        session_id = str(session["session_id"])
        attempt = record_practice_answer(
            self.db,
            self.user_id,
            session_id,
            question_id=MCQ,
            answer={"index": 0},
            time_ms=5000,
            hints_used=1,
        )
        self.assertTrue(attempt["correct"])
        wrong = record_practice_answer(
            self.db,
            self.user_id,
            session_id,
            question_id=NUMERIC,
            answer={"value": 15.2},
        )
        self.assertFalse(wrong["correct"])
        self.assertEqual(
            len(list_practice_attempts(self.db, self.user_id, session_id)), 2
        )
        completed = complete_practice_session(self.db, self.user_id, session_id)
        assert completed is not None
        self.assertAlmostEqual(float(completed["score"]), 50.0, places=2)

    def test_speaking_and_test_flows_write_on_postgres(self) -> None:
        speaking = save_speaking_attempt(
            self.db,
            self.user_id,
            prompt_id="spk-c9-motion-001",
            language="en",
            transcript="Distance is path, displacement is net change.",
            rubric_scores={"ideas_present": 3},
            feedback={"band": "pass"},
            score=70.0,
            duration_ms=40000,
        )
        self.assertEqual(speaking["score"], 70.0)

        test_id = self._paper()
        attempt_id = str(
            create_test_attempt(self.db, self.user_id, test_id)["attempt_id"]
        )
        saved = save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=MCQ,
            answer={"index": 0},
            flagged=True,
        )
        self.assertTrue(saved["flagged"])
        save_test_answer(
            self.db,
            self.user_id,
            attempt_id,
            question_id=NUMERIC,
            answer={"value": 15.2},
        )
        result = submit_test_attempt(self.db, self.user_id, attempt_id)
        assert result is not None
        self.assertEqual(result["status"], "submitted")
        self.assertAlmostEqual(float(result["score"]), 50.0, places=2)
        graded: dict[str, Any] = {
            row["question_id"]: row
            for row in list_test_answers(self.db, self.user_id, attempt_id)
        }
        self.assertTrue(graded[MCQ]["correct"])
        self.assertFalse(graded[NUMERIC]["correct"])

    def test_a_malformed_saved_answer_scores_zero_on_postgres(self) -> None:
        """The PostgreSQL boolean column rejects the integer `0` SQLite accepts."""
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


if __name__ == "__main__":
    unittest.main()
