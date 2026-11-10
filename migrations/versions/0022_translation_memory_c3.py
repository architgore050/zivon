"""Class C3 translation memory, block translations, and glossary tables.

Revision ID: 0022_translation_memory_c3
Revises: 0002 (EX0-BACKEND's Wave-E addenda head — this revision is welded onto
EX0's chain by EX6-CICD so the hot database has exactly ONE Alembic head; both
version directories are listed in alembic.ini's version_locations)
Create Date: 2026-11-09

Since EX0's `0002` already ships the same C3 tables (from `db/schema.py`) with
`CREATE TABLE IF NOT EXISTS` and `ON CONFLICT DO NOTHING` seeds, running this
revision after `0002` is a schema no-op on a fresh database — it stays as the
record of EX2's translation contract and keeps every reference to
`migrations/versions/0022_translation_memory_c3.py` valid. Order it AFTER
`0002` (never as a second root) and the chain is linear: 0001 -> 0002 -> 0022.

Traces to:
- ADR-0009 (11-locale model)
- ADR-0016 (Alembic migrations discipline)
- ADR-0022 (Two-tier Translation Memory and Class C3 PostgreSQL tables)
- docs/specs/translation/spec.md §3.2 (glossary_term, translation_memory_entry,
  block_translation, ui_string, locale_fallback)
- skills/zivon-backend-engineering-skills/README.md §1 (linear history,
  expand/contract, reversible downgrade)
"""

from __future__ import annotations

from typing import Any

revision: str = "0022_translation_memory_c3"
# Welded onto EX0-BACKEND's head (`0002`) by EX6-CICD: one linear chain, one
# head. The DB tables already exist from 0002, so the DDL below is defensive
# (`IF NOT EXISTS`) and the seed is idempotent (`ON CONFLICT DO NOTHING`).
down_revision: str | None = "0002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

LOCALE_FALLBACK_SEED_ROWS: list[dict[str, Any]] = [
    {
        "locale": "en",
        "autonym": "English",
        "script_code": "Latn",
        "fallback_locale": None,
        "baseline_nudge_px": 0.00,
        "launch_tier": "P0",
        "is_active": True,
    },
    {
        "locale": "hi",
        "autonym": "हिन्दी",
        "script_code": "Deva",
        "fallback_locale": "en",
        "baseline_nudge_px": -1.50,
        "launch_tier": "P0",
        "is_active": True,
    },
    {
        "locale": "hi-Latn",
        "autonym": "Hinglish",
        "script_code": "Latn",
        "fallback_locale": "hi",
        "baseline_nudge_px": 0.00,
        "launch_tier": "P0",
        "is_active": True,
    },
    {
        "locale": "ta",
        "autonym": "தமிழ்",
        "script_code": "Taml",
        "fallback_locale": "en",
        "baseline_nudge_px": -1.00,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "te",
        "autonym": "తెలుగు",
        "script_code": "Telu",
        "fallback_locale": "en",
        "baseline_nudge_px": -2.00,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "mr",
        "autonym": "मराठी",
        "script_code": "Deva",
        "fallback_locale": "en",
        "baseline_nudge_px": -1.50,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "bn",
        "autonym": "বাংলা",
        "script_code": "Beng",
        "fallback_locale": "en",
        "baseline_nudge_px": -1.00,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "gu",
        "autonym": "ગુજરાતી",
        "script_code": "Gujr",
        "fallback_locale": "en",
        "baseline_nudge_px": -1.00,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "kn",
        "autonym": "ಕನ್ನಡ",
        "script_code": "Knda",
        "fallback_locale": "en",
        "baseline_nudge_px": -2.00,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "ml",
        "autonym": "മലയാളം",
        "script_code": "Mlym",
        "fallback_locale": "en",
        "baseline_nudge_px": -2.00,
        "launch_tier": "P1",
        "is_active": False,
    },
    {
        "locale": "pa",
        "autonym": "ਪੰਜਾਬੀ",
        "script_code": "Guru",
        "fallback_locale": "en",
        "baseline_nudge_px": -1.00,
        "launch_tier": "P1",
        "is_active": False,
    },
]

UPGRADE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS locale_fallback (
        locale VARCHAR(16) PRIMARY KEY,
        autonym VARCHAR(64) NOT NULL,
        script_code CHAR(4) NOT NULL,
        fallback_locale VARCHAR(16) NULL REFERENCES locale_fallback(locale),
        baseline_nudge_px NUMERIC(4,2) NOT NULL DEFAULT 0.00,
        launch_tier VARCHAR(16) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT false,
        CONSTRAINT ck_locale_fallback_tier CHECK (launch_tier IN ('P0', 'P1', 'disabled'))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS glossary_term (
        id UUID PRIMARY KEY,
        term_slug VARCHAR(64) NOT NULL,
        locale VARCHAR(16) NOT NULL REFERENCES locale_fallback(locale),
        english_term VARCHAR(128) NOT NULL,
        native_term VARCHAR(128) NOT NULL,
        first_mention_gloss VARCHAR(256) NOT NULL,
        short_label VARCHAR(64) NOT NULL,
        do_not_translate BOOLEAN NOT NULL DEFAULT false,
        pronunciation_hint VARCHAR(256) NULL,
        glossary_version VARCHAR(16) NOT NULL DEFAULT '1.0.0',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_glossary_term_slug_locale_ver UNIQUE (term_slug, locale, glossary_version),
        CONSTRAINT ck_glossary_term_locale_bcp47 CHECK (locale ~ '^[a-z]{2,3}(-[A-Za-z]{2,4})?$')
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_glossary_term_locale_ver
        ON glossary_term (locale, glossary_version);
    """,
    """
    CREATE TABLE IF NOT EXISTS translation_memory_entry (
        tm_key CHAR(64) PRIMARY KEY,
        source_content_sha256 CHAR(64) NOT NULL,
        unit_type VARCHAR(24) NOT NULL,
        locale VARCHAR(16) NOT NULL REFERENCES locale_fallback(locale),
        glossary_version VARCHAR(16) NOT NULL,
        prompt_version VARCHAR(16) NOT NULL,
        source_payload JSONB NOT NULL,
        translated_payload JSONB NOT NULL,
        translation_source VARCHAR(16) NOT NULL DEFAULT 'machine',
        model_id VARCHAR(64) NOT NULL DEFAULT 'evon-v3.3',
        review_status VARCHAR(24) NOT NULL DEFAULT 'machine_verified',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_tm_source_locale_ver_prompt UNIQUE (
            source_content_sha256, locale, glossary_version, prompt_version
        ),
        CONSTRAINT ck_tm_translation_source CHECK (
            translation_source IN ('machine', 'human')
        ),
        CONSTRAINT ck_tm_review_status CHECK (
            review_status IN ('machine_verified', 'human_approved')
        )
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tm_source_sha_locale
        ON translation_memory_entry (source_content_sha256, locale);
    """,
    """
    CREATE TABLE IF NOT EXISTS block_translation (
        id UUID PRIMARY KEY,
        lesson_version_id UUID NOT NULL,
        content_block_id UUID NULL,
        block_id_str VARCHAR(16) NOT NULL,
        locale VARCHAR(16) NOT NULL REFERENCES locale_fallback(locale),
        source_content_sha256 CHAR(64) NOT NULL,
        tm_key CHAR(64) NULL REFERENCES translation_memory_entry(tm_key) ON DELETE SET NULL,
        translated_spec JSONB NOT NULL,
        translation_source VARCHAR(16) NOT NULL DEFAULT 'machine',
        status VARCHAR(24) NOT NULL DEFAULT 'draft',
        reviewer_report JSONB NULL,
        reviewed_by VARCHAR(64) NULL,
        reviewed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_block_trans_ver_block_locale UNIQUE (
            lesson_version_id, block_id_str, locale
        ),
        CONSTRAINT ck_block_trans_status CHECK (
            status IN ('draft', 'verified', 'human_approved', 'rejected', 'fallback_en')
        ),
        CONSTRAINT ck_block_trans_source CHECK (
            translation_source IN ('machine', 'human')
        )
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_block_trans_version_locale
        ON block_translation (lesson_version_id, locale, status);
    """,
    """
    CREATE TABLE IF NOT EXISTS ui_string (
        copy_key VARCHAR(128) NOT NULL,
        locale VARCHAR(16) NOT NULL REFERENCES locale_fallback(locale),
        text_value TEXT NOT NULL,
        source VARCHAR(16) NOT NULL DEFAULT 'human',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (copy_key, locale),
        CONSTRAINT ck_ui_string_source CHECK (source IN ('human', 'machine'))
    );
    """,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS ui_string;",
    "DROP INDEX IF EXISTS idx_block_trans_version_locale;",
    "DROP TABLE IF EXISTS block_translation;",
    "DROP INDEX IF EXISTS idx_tm_source_sha_locale;",
    "DROP TABLE IF EXISTS translation_memory_entry;",
    "DROP INDEX IF EXISTS idx_glossary_term_locale_ver;",
    "DROP TABLE IF EXISTS glossary_term;",
    "DROP TABLE IF EXISTS locale_fallback;",
)


def _seed_locale_fallback_sql() -> list[str]:
    stmts: list[str] = []
    for row in LOCALE_FALLBACK_SEED_ROWS:
        fb = f"'{row['fallback_locale']}'" if row["fallback_locale"] else "NULL"
        active = "true" if row["is_active"] else "false"
        stmts.append(
            "INSERT INTO locale_fallback "
            "(locale, autonym, script_code, fallback_locale, baseline_nudge_px, launch_tier, is_active) "
            f"VALUES ('{row['locale']}', '{row['autonym']}', '{row['script_code']}', "
            f"{fb}, {row['baseline_nudge_px']:.2f}, '{row['launch_tier']}', {active}) "
            "ON CONFLICT (locale) DO NOTHING;"
        )
    return stmts


def get_up_sql_statements() -> list[str]:
    return [s.strip() for s in UPGRADE_DDL] + _seed_locale_fallback_sql()


def get_down_sql_statements() -> list[str]:
    return [s.strip() for s in DOWNGRADE_DDL]


def _resolve_op(op_override: Any | None = None) -> Any:
    if op_override is not None:
        return op_override
    from alembic import op  # type: ignore[import-not-found]

    return op


def upgrade(op_override: Any | None = None) -> None:
    """Apply Class C3 translation tables and seed ADR-0009 locale_fallback rows."""
    op_mod = _resolve_op(op_override)
    for stmt in get_up_sql_statements():
        op_mod.execute(stmt)


def downgrade(op_override: Any | None = None) -> None:
    """Reversibly drop Class C3 translation tables in dependency order."""
    op_mod = _resolve_op(op_override)
    for stmt in get_down_sql_statements():
        op_mod.execute(stmt)
