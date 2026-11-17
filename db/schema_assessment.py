"""SQL DDL for revision 0004: practice, speaking, tests, and assessment import.

The W4 data foundation (F5 practice, F6 speaking, F7 tests/series). Kept in its
own module rather than appended to `db.schema` so the migration for one wave is
reviewable on its own and `db.schema` stays the 0001-0003 home; `db.schema`
still owns the single `ALL_TABLES` registry.

Every table is SQLite-portable (the empty->head migration test runs
containerless) and valid on PostgreSQL 16 (the CI Alembic job). Traceability:
`docs/backend/db-spec.md` §4.19 and REQUIREMENTS §8.3/§8.2/§7.3.

Two deliberate shapes:

- `question_bank` stores one row per (item, language), because the pack exports
  one row per language and the practice player serves one language at a time.
- learner rows (`practice_attempt`, `speaking_attempt`, `test_attempt_answer`)
  keep `question_id`/`prompt_id` as plain text, not foreign keys: learner
  evidence must survive a retired question or prompt. `test_question` is the
  authoring side and does hold the FK.

`speaking_attempt` has no audio column at all (REQUIREMENTS §9.5, T11: audio is
transient, never stored). There is no schema shape that could persist raw audio.
"""

from __future__ import annotations

from typing import Final

PRACTICE_TEST_TABLES_0004: Final[tuple[str, ...]] = (
    "assessment_pack",
    "question_bank",
    "practice_session",
    "practice_attempt",
    "speaking_prompt",
    "speaking_attempt",
    "test_series",
    "test",
    "test_question",
    "test_attempt",
    "test_attempt_answer",
    "topic_time_prior",
)

# Practice and speaking carry EN + HI + Hinglish (FEATURE-MAP #3). This is the
# pack's language vocabulary (`en`, `hi`, `hi-Latn`), not the full 11-value
# locale enum used by device/account rows: a question is authored per language
# variant, not per locale code. Documented in db-spec §10 Q10.
PACK_LANGUAGES_0004: Final[tuple[str, ...]] = ("en", "hi", "hi-Latn")

_PACK_LANGUAGE_CHECK: Final[str] = (
    "(" + ",".join(f"'{language}'" for language in PACK_LANGUAGES_0004) + ")"
)
_REVIEW_STATUS_CHECK: Final[str] = "('draft','reviewed','published','retired')"
_SERIES_KIND_CHECK: Final[str] = (
    "('ai_lesson','pyq_pattern','exact_pyq','board_practice','challenge','loop')"
)


def get_revision_0004_up_sql(dialect: str = "postgresql") -> list[str]:
    """Return DDL statements for revision 0004 (12 practice/speaking/test tables)."""
    ts_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    now_default = "NOW()" if dialect == "postgresql" else "CURRENT_TIMESTAMP"
    bool_false = "FALSE" if dialect == "postgresql" else "0"
    class_check = "class_level IS NULL OR (class_level >= 6 AND class_level <= 12)"

    stmts = [
        # --- import provenance -------------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS assessment_pack (
            pack_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('assessment', 'exam', 'series')),
            chapter_id TEXT NOT NULL,
            class_level INTEGER CHECK ({class_check}),
            subject TEXT NOT NULL DEFAULT 'physics',
            pack_version INTEGER NOT NULL CHECK (pack_version >= 1),
            content_hash TEXT NOT NULL,
            source_path TEXT,
            run_id TEXT,
            generator TEXT,
            gate_verdict TEXT NOT NULL DEFAULT 'pass'
                CHECK (gate_verdict IN ('pass', 'fail')),
            counts {json_type} NOT NULL DEFAULT '{{}}',
            generated_at {ts_type},
            imported_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (kind, chapter_id, content_hash)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_assessment_pack_chapter "
            "ON assessment_pack(chapter_id, kind, imported_at DESC)"
        ),
        # --- question bank (REQUIREMENTS §7.3) ---------------------------
        f"""
        CREATE TABLE IF NOT EXISTS question_bank (
            question_id TEXT PRIMARY KEY,
            base_item_id TEXT NOT NULL,
            class_level INTEGER NOT NULL
                CHECK (class_level >= 6 AND class_level <= 12),
            chapter_id TEXT NOT NULL,
            concept_id TEXT NOT NULL,
            type TEXT NOT NULL
                CHECK (type IN ('mcq', 'numeric', 'assertion_reason')),
            difficulty TEXT NOT NULL
                CHECK (difficulty IN ('easy', 'medium', 'hard')),
            marks NUMERIC NOT NULL CHECK (marks > 0),
            language TEXT NOT NULL CHECK (language IN {_PACK_LANGUAGE_CHECK}),
            source_type TEXT NOT NULL CHECK (
                source_type IN ('generated', 'past_paper', 'sample_paper', 'curated_pyq')
            ),
            source_ref {json_type} NOT NULL DEFAULT '{{}}',
            prompt TEXT NOT NULL,
            options {json_type} NOT NULL DEFAULT '[]',
            answer {json_type} NOT NULL,
            explanation TEXT NOT NULL,
            misconception TEXT,
            expected_time_ms INTEGER NOT NULL CHECK (expected_time_ms > 0),
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN {_REVIEW_STATUS_CHECK}),
            review_mode TEXT NOT NULL DEFAULT 'deterministic'
                CHECK (review_mode IN ('deterministic', 'judged', 'human')),
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            generator TEXT,
            pack_id TEXT REFERENCES assessment_pack(pack_id) ON DELETE SET NULL,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (base_item_id, language)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_question_bank_chapter "
            "ON question_bank(chapter_id, status)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_question_bank_concept "
            "ON question_bank(concept_id)"
        ),
        # --- practice (F5) -----------------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS practice_session (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            mode TEXT NOT NULL
                CHECK (mode IN ('chapter', 'daily', 'weak_topic', 'retry_mistakes')),
            chapter_id TEXT,
            question_ids {json_type} NOT NULL DEFAULT '[]',
            question_count INTEGER NOT NULL DEFAULT 0 CHECK (question_count >= 0),
            config {json_type} NOT NULL DEFAULT '{{}}',
            score NUMERIC CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
            started_at {ts_type} NOT NULL DEFAULT {now_default},
            completed_at {ts_type}
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_practice_session_user "
            "ON practice_session(user_id, started_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_practice_session_chapter "
            "ON practice_session(chapter_id)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS practice_attempt (
            attempt_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL
                REFERENCES practice_session(session_id) ON DELETE CASCADE,
            question_id TEXT NOT NULL,
            answer {json_type} NOT NULL DEFAULT '{{}}',
            correct BOOLEAN NOT NULL,
            time_ms INTEGER NOT NULL DEFAULT 0 CHECK (time_ms >= 0),
            hints_used INTEGER NOT NULL DEFAULT 0
                CHECK (hints_used >= 0 AND hints_used <= 20),
            attempt_no INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (session_id, question_id, attempt_no)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_practice_attempt_session "
            "ON practice_attempt(session_id, created_at)"
        ),
        # --- speaking (F6) -----------------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS speaking_prompt (
            prompt_id TEXT NOT NULL,
            language TEXT NOT NULL CHECK (language IN {_PACK_LANGUAGE_CHECK}),
            class_level INTEGER CHECK ({class_check}),
            chapter_id TEXT NOT NULL,
            concept_ids {json_type} NOT NULL DEFAULT '[]',
            prompt TEXT NOT NULL,
            key_ideas {json_type} NOT NULL DEFAULT '[]',
            model_answer TEXT NOT NULL,
            model_answer_source {json_type} NOT NULL DEFAULT '{{}}',
            rubric {json_type} NOT NULL DEFAULT '{{}}',
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN {_REVIEW_STATUS_CHECK}),
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            pack_id TEXT REFERENCES assessment_pack(pack_id) ON DELETE SET NULL,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (prompt_id, language)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_speaking_prompt_chapter "
            "ON speaking_prompt(chapter_id, language, status)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS speaking_attempt (
            attempt_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            prompt_id TEXT NOT NULL,
            language TEXT NOT NULL CHECK (language IN {_PACK_LANGUAGE_CHECK}),
            transcript TEXT,
            rubric_scores {json_type} NOT NULL DEFAULT '{{}}',
            feedback {json_type} NOT NULL DEFAULT '{{}}',
            self_check {json_type} NOT NULL DEFAULT '{{}}',
            score NUMERIC CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
            duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
            created_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_speaking_attempt_user "
            "ON speaking_attempt(user_id, created_at DESC)"
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_speaking_attempt_prompt "
            "ON speaking_attempt(prompt_id, language)"
        ),
        # --- tests and series (F7) ---------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS test_series (
            series_id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            class_level INTEGER NOT NULL
                CHECK (class_level >= 6 AND class_level <= 12),
            kind TEXT NOT NULL CHECK (kind IN {_SERIES_KIND_CHECK}),
            title TEXT NOT NULL,
            description TEXT,
            language_set {json_type} NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published', 'retired')),
            metadata {json_type} NOT NULL DEFAULT '{{}}',
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_test_series_class "
            "ON test_series(class_level, kind, status)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS test (
            test_id TEXT PRIMARY KEY,
            series_id TEXT REFERENCES test_series(series_id) ON DELETE CASCADE,
            user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
            chapter_ids {json_type} NOT NULL DEFAULT '[]',
            title TEXT NOT NULL,
            language TEXT CHECK (
                language IS NULL OR language IN {_PACK_LANGUAGE_CHECK}
            ),
            duration_s INTEGER NOT NULL CHECK (duration_s > 0),
            total_marks NUMERIC NOT NULL DEFAULT 0 CHECK (total_marks >= 0),
            structure {json_type} NOT NULL DEFAULT '{{}}',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published', 'retired')),
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            CHECK (series_id IS NOT NULL OR user_id IS NOT NULL)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_test_series_ref ON test(series_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_test_owner ON test(user_id, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS test_question (
            test_id TEXT NOT NULL REFERENCES test(test_id) ON DELETE CASCADE,
            question_id TEXT NOT NULL
                REFERENCES question_bank(question_id) ON DELETE RESTRICT,
            order_index INTEGER NOT NULL CHECK (order_index >= 1),
            section TEXT,
            marks NUMERIC NOT NULL CHECK (marks > 0),
            PRIMARY KEY (test_id, question_id),
            UNIQUE (test_id, order_index)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_test_question_bank "
            "ON test_question(question_id)"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS test_attempt (
            attempt_id TEXT PRIMARY KEY,
            test_id TEXT NOT NULL REFERENCES test(test_id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'in_progress'
                CHECK (status IN ('in_progress', 'submitted', 'expired', 'abandoned')),
            score NUMERIC CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
            time_spent_s INTEGER CHECK (time_spent_s IS NULL OR time_spent_s >= 0),
            started_at {ts_type} NOT NULL DEFAULT {now_default},
            submitted_at {ts_type}
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_test_attempt_user "
            "ON test_attempt(user_id, started_at DESC)"
        ),
        "CREATE INDEX IF NOT EXISTS idx_test_attempt_test ON test_attempt(test_id)",
        # One live attempt per (test, student): a double "start" resumes rather
        # than duplicating, and the DB - not the route - owns the guarantee.
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_test_attempt_one_live "
            "ON test_attempt(test_id, user_id) WHERE status = 'in_progress'"
        ),
        f"""
        CREATE TABLE IF NOT EXISTS test_attempt_answer (
            attempt_id TEXT NOT NULL
                REFERENCES test_attempt(attempt_id) ON DELETE CASCADE,
            question_id TEXT NOT NULL,
            answer {json_type} NOT NULL DEFAULT '{{}}',
            correct BOOLEAN,
            marks_awarded NUMERIC
                CHECK (marks_awarded IS NULL OR marks_awarded >= 0),
            time_ms INTEGER CHECK (time_ms IS NULL OR time_ms >= 0),
            flagged BOOLEAN NOT NULL DEFAULT {bool_false},
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (attempt_id, question_id)
        )
        """,
        # --- time priors (A5 topic priors; question priors live on the row) --
        f"""
        CREATE TABLE IF NOT EXISTS topic_time_prior (
            chapter_id TEXT NOT NULL,
            scope TEXT NOT NULL CHECK (scope IN ('chapter', 'concept')),
            scope_id TEXT NOT NULL,
            class_level INTEGER CHECK ({class_check}),
            expected_time_ms INTEGER NOT NULL CHECK (expected_time_ms > 0),
            question_count INTEGER NOT NULL DEFAULT 0 CHECK (question_count >= 0),
            formula_version TEXT NOT NULL,
            pack_id TEXT REFERENCES assessment_pack(pack_id) ON DELETE SET NULL,
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (chapter_id, scope, scope_id)
        )
        """,
        (
            "CREATE INDEX IF NOT EXISTS idx_topic_time_prior_chapter "
            "ON topic_time_prior(chapter_id)"
        ),
    ]
    return [s.strip() for s in stmts]


def get_revision_0004_down_sql() -> list[str]:
    """Revert revision 0004 in reverse foreign-key dependency order."""
    return [
        f"DROP TABLE IF EXISTS {tbl}" for tbl in reversed(PRACTICE_TEST_TABLES_0004)
    ]
