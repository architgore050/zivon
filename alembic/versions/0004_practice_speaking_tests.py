"""Practice, speaking, tests, and assessment-pack import (W4 data foundation).

Revision ID: 0004_practice_speaking_tests
Revises: 0003_full_frontend
Create Date: 2026-11-17

Additive only (ADR-0016 expand/contract): twelve new tables that F5 (practice),
F6 (speaking), and F7 (tests/series) read and write through
`backend/assessment/store.py`. No existing table is altered, so the voice,
consent, device, admin, account, and progress contracts are untouched.

Every table is SQLite-portable (the containerless empty->head test) and valid
PostgreSQL 16 (the CI Alembic job). Traces to `docs/backend/db-spec.md` §4.19
and REQUIREMENTS §7.3/§8.2/§8.3.
"""

from __future__ import annotations

from db.schema_assessment import (
    get_revision_0004_down_sql,
    get_revision_0004_up_sql,
)

revision: str = "0004_practice_speaking_tests"
down_revision: str | None = "0003_full_frontend"
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
    """Apply revision 0004 (12 practice/speaking/test tables)."""
    from alembic import op  # type: ignore[import-not-found]

    dialect = _dialect_name()
    for stmt in get_revision_0004_up_sql(dialect):
        op.execute(stmt)


def downgrade() -> None:
    """Revert revision 0004 in reverse foreign-key dependency order."""
    from alembic import op  # type: ignore[import-not-found]

    for stmt in get_revision_0004_down_sql():
        op.execute(stmt)
