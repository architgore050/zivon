"""Alembic migration 0001: Create Eval Result Store tables (`ADR-0027`, `db-spec.md` §3.16–3.20).

Revision ID: 0001_eval_result_store
Revises: None
Create Date: 2026-04-20
"""

from __future__ import annotations

from typing import Any

revision: str = "0001_eval_result_store"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

UPGRADE_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS eval_run (
        id              UUID PRIMARY KEY,
        run_id          TEXT NOT NULL UNIQUE,
        suite           TEXT NOT NULL CHECK (suite IN ('smoke', 'full', 'calibrate', 'single_card')),
        git_sha         TEXT NOT NULL,
        git_branch      TEXT NOT NULL,
        trigger         TEXT NOT NULL CHECK (trigger IN ('ci_pr', 'ci_nightly', 'k8s_cron', 'manual_cli')),
        code_model      TEXT NOT NULL,
        judge_model     TEXT NOT NULL,
        overall_verdict TEXT NOT NULL CHECK (overall_verdict IN ('pass', 'fail')),
        total_cards     INTEGER NOT NULL CHECK (total_cards >= 0),
        passed_cards    INTEGER NOT NULL CHECK (passed_cards >= 0),
        failed_cards    INTEGER NOT NULL CHECK (failed_cards >= 0),
        skipped_cards   INTEGER NOT NULL CHECK (skipped_cards >= 0),
        started_at      TIMESTAMPTZ NOT NULL,
        finished_at     TIMESTAMPTZ NOT NULL,
        duration_ms     INTEGER NOT NULL CHECK (duration_ms >= 0),
        summary         JSONB NOT NULL DEFAULT '{}'::jsonb
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_run_git_sha ON eval_run (git_sha);",
    "CREATE INDEX IF NOT EXISTS idx_eval_run_started_at ON eval_run (started_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS eval_card_result (
        id                     UUID PRIMARY KEY,
        run_id                 UUID NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
        card_id                TEXT NOT NULL,
        stage                  TEXT NOT NULL,
        tier                   TEXT NOT NULL CHECK (tier IN ('tier1_Intrinsic', 'tier2_ReviewerCalibration', 'tier3_OperationalAndOutcome')),
        verdict                TEXT NOT NULL CHECK (verdict IN ('pass', 'fail', 'skipped')),
        deterministic_score    NUMERIC(5,4) NOT NULL CHECK (deterministic_score BETWEEN 0 AND 1),
        llm_judge_score        NUMERIC(5,4) CHECK (llm_judge_score IS NULL OR llm_judge_score BETWEEN 0 AND 1),
        metrics                JSONB NOT NULL DEFAULT '{}'::jsonb,
        thresholds_checked     JSONB NOT NULL DEFAULT '{}'::jsonb,
        issues                 JSONB NOT NULL DEFAULT '[]'::jsonb,
        judge_calls            INTEGER NOT NULL DEFAULT 0 CHECK (judge_calls >= 0),
        judge_thinking_s       NUMERIC(8,2) NOT NULL DEFAULT 0 CHECK (judge_thinking_s >= 0),
        max_completion_tokens  INTEGER NOT NULL DEFAULT 0 CHECK (max_completion_tokens >= 0),
        length_cuts            INTEGER NOT NULL DEFAULT 0 CHECK (length_cuts >= 0),
        duration_ms            INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
        created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (run_id, card_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_card_result_card_created ON eval_card_result (card_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_eval_card_result_run ON eval_card_result (run_id);",
    "CREATE INDEX IF NOT EXISTS idx_eval_card_result_metrics_gin ON eval_card_result USING GIN (metrics);",
    """
    CREATE TABLE IF NOT EXISTS eval_defect_sample_result (
        id                    UUID PRIMARY KEY,
        card_result_id        UUID NOT NULL REFERENCES eval_card_result(id) ON DELETE CASCADE,
        card_id               TEXT NOT NULL,
        sample_id             TEXT NOT NULL,
        defect_class          TEXT NOT NULL,
        expected_verdict      TEXT NOT NULL CHECK (expected_verdict IN ('pass', 'fail')),
        actual_verdict        TEXT NOT NULL CHECK (actual_verdict IN ('pass', 'fail')),
        expected_severity     TEXT,
        actual_max_severity   TEXT,
        matched               BOOLEAN NOT NULL,
        target_block_matched  BOOLEAN NOT NULL,
        source_quoted         BOOLEAN NOT NULL,
        latency_ms            INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
        raw_response          JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (card_result_id, sample_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_defect_sample_card_sample ON eval_defect_sample_result (card_id, sample_id, created_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS eval_human_edit (
        id                 UUID PRIMARY KEY,
        course_slug        TEXT NOT NULL,
        topic_slug         TEXT NOT NULL,
        baseline_git_sha   TEXT NOT NULL,
        published_git_sha  TEXT NOT NULL,
        files_changed      INTEGER NOT NULL CHECK (files_changed >= 0),
        lines_added        INTEGER NOT NULL CHECK (lines_added >= 0),
        lines_deleted      INTEGER NOT NULL CHECK (lines_deleted >= 0),
        total_lines        INTEGER NOT NULL CHECK (total_lines > 0),
        edit_ratio         NUMERIC(6,4) NOT NULL CHECK (edit_ratio >= 0),
        zero_edit_publish  BOOLEAN NOT NULL,
        per_file_diff      JSONB NOT NULL DEFAULT '{}'::jsonb,
        recorded_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_human_edit_course_topic ON eval_human_edit (course_slug, topic_slug, recorded_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_eval_human_edit_recorded_at ON eval_human_edit (recorded_at DESC);",
    """
    CREATE TABLE IF NOT EXISTS eval_kid_session (
        id                             UUID PRIMARY KEY,
        session_id                     TEXT NOT NULL UNIQUE,
        course_slug                    TEXT NOT NULL,
        topic_slug                     TEXT NOT NULL,
        cohort_tag                     TEXT NOT NULL,
        device_profile                 TEXT NOT NULL CHECK (device_profile IN ('weak-android', 'mid-laptop', 'other')),
        sections_viewed                INTEGER NOT NULL CHECK (sections_viewed >= 0),
        sections_total                 INTEGER NOT NULL CHECK (sections_total > 0),
        completed_lesson               BOOLEAN NOT NULL,
        time_to_first_interaction_ms   INTEGER NOT NULL CHECK (time_to_first_interaction_ms >= 0),
        total_dwell_ms                 INTEGER NOT NULL CHECK (total_dwell_ms >= 0),
        check_attempts                 INTEGER NOT NULL CHECK (check_attempts >= 0),
        check_passes_first_try         INTEGER NOT NULL CHECK (check_passes_first_try >= 0),
        sim_interactions               INTEGER NOT NULL DEFAULT 0 CHECK (sim_interactions >= 0),
        abandoned_at_section           TEXT,
        recorded_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_eval_kid_session_course_topic ON eval_kid_session (course_slug, topic_slug, recorded_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_eval_kid_session_recorded_at ON eval_kid_session (recorded_at DESC);",
)

DOWNGRADE_SQL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS eval_kid_session CASCADE;",
    "DROP TABLE IF EXISTS eval_human_edit CASCADE;",
    "DROP TABLE IF EXISTS eval_defect_sample_result CASCADE;",
    "DROP TABLE IF EXISTS eval_card_result CASCADE;",
    "DROP TABLE IF EXISTS eval_run CASCADE;",
)


def upgrade(op: Any | None = None) -> None:
    """Execute DDL statements for the 5 Eval Result Store tables."""
    if op is None:
        from alembic import op as alembic_op  # type: ignore[import-not-found]

        op = alembic_op
    for stmt in UPGRADE_SQL:
        op.execute(stmt)


def downgrade(op: Any | None = None) -> None:
    """Drop the 5 Eval Result Store tables in reverse dependency order."""
    if op is None:
        from alembic import op as alembic_op  # type: ignore[import-not-found]

        op = alembic_op
    for stmt in DOWNGRADE_SQL:
        op.execute(stmt)
