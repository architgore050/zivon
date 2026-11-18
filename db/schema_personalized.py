"""SQL DDL for revision 0005: personalized learning data foundation (W5.5 PL1).

The PL1 tables of `docs/specs/personalized-learning/data-and-api.md` §2: account
personal instructions (`C22`), saved teaching sessions + messages (`C23`), the
content-addressed artifact cache (`C24`), and the usage/quota ops counters
(`C25`). Kept in its own module (same pattern as `db/schema_assessment.py`) so
`db.schema` stays the 0001-0003 home and owns the single `ALL_TABLES` registry.

**No paywall tables.** There is no `plan`, `subscription`, `payment`,
`entitlement`, `price`, or `invoice` table here — free access is the product and
quotas are counters, not entitlements (data-and-api.md header).

Every table is SQLite-portable (the containerless empty->head test) and valid
PostgreSQL 16 (the CI Alembic job). IDs are UUIDv7 (`db/uuid7.py`); timestamps
are `timestamptz` (TEXT ISO on SQLite); JSON columns are JSONB/TEXT.

Two CHECK widenings ride in this revision because PL1 also extends
`backend/abuse.py` with the four personalized rate-limit families
(data-and-api.md §4.1) and emits `personalized_mastery` progress events
(workstreams.md §7). Both engines need a real change, not a comment:

- `progress_event.kind` gains `'personalized_mastery'`: PostgreSQL swaps the
  named CHECK constraint; SQLite cannot alter a CHECK, so the revision rebuilds
  the table (create `_new`, copy, drop, rename, recreate both indexes).
- `abuse_bucket.endpoint_family` gains the four personalized families: same
  constraint swap on PostgreSQL, same rebuild on SQLite.

The down migration reverses everything: it rebuilds both CHECK tables back to
their pre-0005 lists and drops the six new tables in reverse dependency order
(message, usage, session, quota, artifact, preferences). **Downgrade data plan
(expand/contract rule):** the downgrade is destructive by design — the six PL
tables and the `personalized_mastery` progress events are 0005-owned data with
no meaning on a 0004 schema, so they are deleted explicitly rather than
silently or by a CHECK failure; no other `progress_event` row is touched.
"""

from __future__ import annotations

from typing import Final

PERSONALIZED_TABLES_0005: Final[tuple[str, ...]] = (
    "user_preferences",
    "personalized_session",
    "personalized_message",
    "personalized_artifact",
    "personalized_usage",
    "personalized_quota",
)

# The pre-0005 and post-0005 vocabularies of the two widened CHECK columns.
_PROGRESS_KINDS_0004: Final[str] = (
    "('lesson_block_view', 'lesson_complete', 'practice_answer', "
    "'test_submit', 'speaking_attempt', 'bookmark_add', 'bookmark_remove')"
)
_PROGRESS_KINDS_0005: Final[str] = (
    "('lesson_block_view', 'lesson_complete', 'practice_answer', "
    "'test_submit', 'speaking_attempt', 'bookmark_add', 'bookmark_remove', "
    "'personalized_mastery')"
)
_ABUSE_FAMILIES_0004: Final[str] = (
    "('static', 'audio', 'api', 'ws', 'events', 'reports', 'delete')"
)
_ABUSE_FAMILIES_0005: Final[str] = (
    "('static', 'audio', 'api', 'ws', 'events', 'reports', 'delete', "
    "'personalized_turn', 'personalized_create', 'personalized_read', "
    "'personalized_ip')"
)

_STAGE_CHECK: Final[str] = (
    "('diagnose','teach','check','adapt','worked_example','advance',"
    "'harder','board','mastery','done')"
)


def _rebuild_progress_event_sqlite(kinds_check: str) -> list[str]:
    """SQLite rebuild of `progress_event` with the given `kind` vocabulary.

    SQLite cannot ALTER a CHECK, so the table is rebuilt: create `_new`,
    copy every row, drop the old table, rename, recreate both indexes.
    """
    return [
        f"""
        CREATE TABLE progress_event_new (
            event_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN {kinds_check}),
            chapter_id TEXT,
            concept_id TEXT,
            question_id TEXT,
            payload TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        INSERT INTO progress_event_new (
            event_id, user_id, kind, chapter_id, concept_id, question_id,
            payload, created_at
        ) SELECT event_id, user_id, kind, chapter_id, concept_id, question_id,
                 payload, created_at
        FROM progress_event
        """,
        "DROP TABLE progress_event",
        "ALTER TABLE progress_event_new RENAME TO progress_event",
        "CREATE INDEX IF NOT EXISTS idx_progress_event_user_created ON progress_event(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_progress_event_user_chapter ON progress_event(user_id, chapter_id)",
    ]


def _rebuild_abuse_bucket_sqlite(families_check: str) -> list[str]:
    """SQLite rebuild of `abuse_bucket` with the given family vocabulary.

    `bucket_id` is INTEGER PRIMARY KEY AUTOINCREMENT: inserting the copied
    rows by explicit id keeps `sqlite_sequence` at the copied max, so the
    rename leaves the next auto id above every existing bucket.
    """
    return [
        f"""
        CREATE TABLE abuse_bucket_new (
            bucket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bucket_key TEXT NOT NULL,
            endpoint_family TEXT NOT NULL CHECK (endpoint_family IN {families_check}),
            window_start TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL,
            UNIQUE (bucket_key, endpoint_family, window_start)
        )
        """,
        """
        INSERT INTO abuse_bucket_new (
            bucket_id, bucket_key, endpoint_family, window_start, count, expires_at
        ) SELECT bucket_id, bucket_key, endpoint_family, window_start, count, expires_at
        FROM abuse_bucket
        """,
        "DROP TABLE abuse_bucket",
        "ALTER TABLE abuse_bucket_new RENAME TO abuse_bucket",
        "CREATE INDEX IF NOT EXISTS idx_abuse_bucket_expires ON abuse_bucket(expires_at)",
    ]


def get_revision_0005_up_sql(dialect: str = "postgresql") -> list[str]:
    """Return DDL statements for revision 0005 (six PL tables + CHECK widenings)."""
    ts_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    now_default = "NOW()" if dialect == "postgresql" else "CURRENT_TIMESTAMP"
    bool_false = "FALSE" if dialect == "postgresql" else "0"

    stmts: list[str] = [
        # --- C22: account personal instructions (§2.1) --------------------
        f"""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            personal_instructions TEXT
                CHECK (personal_instructions IS NULL OR length(personal_instructions) <= 500),
            instructions_version INTEGER NOT NULL DEFAULT 0 CHECK (instructions_version >= 0),
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        # --- C23: saved sessions (§2.2) ------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS personalized_session (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            parent_session_id TEXT REFERENCES personalized_session(session_id) ON DELETE SET NULL,
            title TEXT NOT NULL CHECK (length(title) <= 120),
            mode TEXT NOT NULL DEFAULT 'learning' CHECK (mode IN ('learning', 'chat')),
            class_level INTEGER NOT NULL CHECK (class_level >= 6 AND class_level <= 12),
            chapter_id TEXT NOT NULL,
            concept_ids {json_type} NOT NULL DEFAULT '[]',
            weakness_text TEXT
                CHECK (weakness_text IS NULL OR length(weakness_text) <= 500),
            stage TEXT NOT NULL DEFAULT 'diagnose' CHECK (stage IN {_STAGE_CHECK}),
            difficulty_level INTEGER NOT NULL DEFAULT 1
                CHECK (difficulty_level >= 1 AND difficulty_level <= 4),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'completed', 'abandoned')),
            state {json_type} NOT NULL DEFAULT '{{}}',
            turn_count INTEGER NOT NULL DEFAULT 0
                CHECK (turn_count >= 0 AND turn_count <= 60),
            rag_index_version TEXT,
            prompt_version TEXT NOT NULL DEFAULT 'pl-1',
            model TEXT,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            last_turn_at {ts_type},
            completed_at {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pl_session_user_updated ON personalized_session(user_id, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pl_session_user_status ON personalized_session(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_pl_session_user_chapter ON personalized_session(user_id, chapter_id)",
        "CREATE INDEX IF NOT EXISTS idx_pl_session_last_turn ON personalized_session(last_turn_at)",
        # --- C23: append-only messages (§2.3) -------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS personalized_message (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES personalized_session(session_id) ON DELETE CASCADE,
            turn_index INTEGER NOT NULL,
            client_turn_id TEXT,
            role TEXT NOT NULL CHECK (role IN ('student', 'tutor', 'system_event')),
            kind TEXT NOT NULL CHECK (
                kind IN ('text', 'check', 'check_result', 'artifact_ref',
                         'stage_change', 'diagnostic', 'summary')
            ),
            text TEXT CHECK (text IS NULL OR length(text) <= 8000),
            payload {json_type} NOT NULL DEFAULT '{{}}',
            answer_key TEXT,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (session_id, turn_index)
        )
        """,
        # Partial idempotency key: NULL client ids never collide. Both engines
        # support partial unique indexes; the store looks the row up first and
        # treats a unique violation as the replay case, never an upsert.
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pl_message_session_client_turn
            ON personalized_message(session_id, client_turn_id)
            WHERE client_turn_id IS NOT NULL
        """,
        # --- C24: content-addressed artifact cache (§2.4) -------------------
        f"""
        CREATE TABLE IF NOT EXISTS personalized_artifact (
            artifact_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('simulation', 'diagram')),
            title TEXT NOT NULL CHECK (length(title) <= 120),
            spec {json_type} NOT NULL,
            html TEXT,
            fallback {json_type},
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
            failure_reason TEXT CHECK (
                failure_reason IS NULL OR
                failure_reason IN ('lint', 'render', 'timeout', 'budget', 'route', 'spec')
            ),
            model TEXT,
            prompt_version TEXT NOT NULL,
            doctrine_hash TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            lint_version TEXT NOT NULL DEFAULT 'pl-artifact-1',
            lint_hits INTEGER NOT NULL DEFAULT 0 CHECK (lint_hits >= 0),
            render_ms INTEGER,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            ready_at {ts_type},
            last_used_at {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pl_artifact_status_last_used ON personalized_artifact(status, last_used_at)",
        # --- C25: usage ledger (§2.5) ----------------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS personalized_usage (
            usage_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            session_id TEXT REFERENCES personalized_session(session_id) ON DELETE SET NULL,
            turn_index INTEGER,
            stage TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cached_tokens INTEGER,
            first_token_ms INTEGER,
            latency_ms INTEGER,
            artifact_build BOOLEAN NOT NULL DEFAULT {bool_false},
            cache_hit BOOLEAN NOT NULL DEFAULT {bool_false},
            outcome TEXT NOT NULL DEFAULT 'ok' CHECK (
                outcome IN ('ok', 'model_error', 'quota_blocked', 'rate_limited',
                            'artifact_failed', 'cancelled', 'rejected')
            ),
            created_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_pl_usage_user_created ON personalized_usage(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pl_usage_created ON personalized_usage(created_at)",
        # --- C25: hot quota counters (§2.6) ----------------------------------
        f"""
        CREATE TABLE IF NOT EXISTS personalized_quota (
            period TEXT NOT NULL,
            scope TEXT NOT NULL CHECK (scope IN ('user', 'global')),
            scope_key TEXT NOT NULL,
            turns_used INTEGER NOT NULL DEFAULT 0 CHECK (turns_used >= 0),
            turns_reserved INTEGER NOT NULL DEFAULT 0 CHECK (turns_reserved >= 0),
            artifact_used INTEGER NOT NULL DEFAULT 0 CHECK (artifact_used >= 0),
            artifact_reserved INTEGER NOT NULL DEFAULT 0 CHECK (artifact_reserved >= 0),
            state TEXT NOT NULL DEFAULT 'ok' CHECK (state IN ('ok', 'warn', 'exhausted')),
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (period, scope, scope_key)
        )
        """,
    ]

    if dialect == "postgresql":
        # PostgreSQL can swap a CHECK constraint in place (named constraints):
        # the auto-generated names follow `<table>_<column>_check` for the
        # single-column checks created by revisions 0001/0003.
        stmts.extend(
            [
                """
                ALTER TABLE progress_event DROP CONSTRAINT IF EXISTS progress_event_kind_check
                """,
                f"""
                ALTER TABLE progress_event ADD CONSTRAINT progress_event_kind_check
                    CHECK (kind IN {_PROGRESS_KINDS_0005})
                """,
                """
                ALTER TABLE abuse_bucket DROP CONSTRAINT IF EXISTS abuse_bucket_endpoint_family_check
                """,
                f"""
                ALTER TABLE abuse_bucket ADD CONSTRAINT abuse_bucket_endpoint_family_check
                    CHECK (endpoint_family IN {_ABUSE_FAMILIES_0005})
                """,
            ]
        )
    else:
        stmts.extend(_rebuild_progress_event_sqlite(_PROGRESS_KINDS_0005))
        stmts.extend(_rebuild_abuse_bucket_sqlite(_ABUSE_FAMILIES_0005))
    return [s.strip() for s in stmts]


def get_revision_0005_down_sql(dialect: str = "postgresql") -> list[str]:
    """Revert revision 0005: widen-checks back, drop the six tables (reverse order).

    The CHECK reversal is dialect-specific like the up path: PostgreSQL swaps
    the named constraints back; SQLite rebuilds both tables with the pre-0005
    vocabularies. The six new tables then drop in reverse dependency order.
    """
    if dialect == "postgresql":
        down: list[str] = [
            # Explicit data-migration step (expand/contract rule): the mastery
            # events are 0005-owned rows with no meaning on a 0004 schema, so
            # the downgrade deletes them instead of failing the CHECK swap.
            "DELETE FROM progress_event WHERE kind = 'personalized_mastery'",
            "ALTER TABLE progress_event DROP CONSTRAINT IF EXISTS progress_event_kind_check",
            f"""
            ALTER TABLE progress_event ADD CONSTRAINT progress_event_kind_check
                CHECK (kind IN {_PROGRESS_KINDS_0004})
            """,
            "ALTER TABLE abuse_bucket DROP CONSTRAINT IF EXISTS abuse_bucket_endpoint_family_check",
            f"""
            ALTER TABLE abuse_bucket ADD CONSTRAINT abuse_bucket_endpoint_family_check
                CHECK (endpoint_family IN {_ABUSE_FAMILIES_0004})
            """,
        ]
    else:
        down = ["DELETE FROM progress_event WHERE kind = 'personalized_mastery'"]
        down.extend(_rebuild_progress_event_sqlite(_PROGRESS_KINDS_0004))
        down.extend(_rebuild_abuse_bucket_sqlite(_ABUSE_FAMILIES_0004))
    ordered = [
        "personalized_message",
        "personalized_usage",
        "personalized_session",
        "personalized_quota",
        "personalized_artifact",
        "user_preferences",
    ]
    down.extend(f"DROP TABLE IF EXISTS {tbl}" for tbl in ordered)
    return [s.strip() for s in down]
