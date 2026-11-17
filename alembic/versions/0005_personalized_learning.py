"""Personalized learning data foundation (W5.5 PL1).

Revision ID: 0005_personalized_learning
Revises: 0004_practice_speaking_tests
Create Date: 2026-11-17

Six new tables per `docs/specs/personalized-learning/data-and-api.md` §2 —
`user_preferences` (C22), `personalized_session` / `personalized_message` (C23),
`personalized_artifact` (C24), `personalized_usage` / `personalized_quota` (C25)
— plus two CHECK widenings that need a real change on both engines:

- `progress_event.kind` gains `'personalized_mastery'`: PostgreSQL swaps the
  named CHECK constraint; SQLite rebuilds the table (create `_new`, copy,
  drop, rename, recreate the indexes).
- `abuse_bucket.endpoint_family` gains the four personalized rate-limit
  families (`personalized_turn`, `personalized_create`, `personalized_read`,
  `personalized_ip` of data-and-api.md §4.1): same swap/rebuild pattern.

No existing table is otherwise altered and no paywall/plan/entitlement table
exists here. The down migration reverses the CHECK widenings and drops the six
tables in reverse dependency order. SQLite-portable (the containerless
empty->head test) and valid PostgreSQL 16 (the CI Alembic job).
"""

from __future__ import annotations

from db.schema_personalized import (
    get_revision_0005_down_sql,
    get_revision_0005_up_sql,
)

revision: str = "0005_personalized_learning"
down_revision: str | None = "0004_practice_speaking_tests"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _dialect_name() -> str:
    try:
        from alembic import op  # type: ignore[import-not-found]

        bind = op.get_bind()
        return str(bind.dialect.name)
    except Exception:  # noqa: BLE001
        return "postgresql"


def upgrade() -> None:
    """Apply revision 0005 (six PL tables + the two CHECK widenings)."""
    from alembic import op  # type: ignore[import-not-found]

    dialect = _dialect_name()
    for stmt in get_revision_0005_up_sql(dialect):
        op.execute(stmt)


def downgrade() -> None:
    """Revert revision 0005 (CHECK widenings back; six tables dropped)."""
    from alembic import op  # type: ignore[import-not-found]

    for stmt in get_revision_0005_down_sql(_dialect_name()):
        op.execute(stmt)
