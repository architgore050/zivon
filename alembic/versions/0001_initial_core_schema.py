"""Initial 20 core backend tables (db-spec.md, ADR-0001, ADR-0016).

Revision ID: 0001
Revises: None
Create Date: 2026-11-09
"""

from __future__ import annotations

from db.schema import get_revision_0001_down_sql, get_revision_0001_up_sql

revision: str = "0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _dialect_name() -> str:
    try:
        from alembic import op  # type: ignore[import-not-found]

        bind = op.get_bind()
        return str(bind.dialect.name)
    except Exception:
        return "postgresql"


def upgrade() -> None:
    """Apply revision 0001 (20 core tables + guard_profile singleton seed)."""
    from alembic import op  # type: ignore[import-not-found]

    dialect = _dialect_name()
    for stmt in get_revision_0001_up_sql(dialect):
        op.execute(stmt)


def downgrade() -> None:
    """Revert revision 0001 in reverse foreign-key dependency order."""
    from alembic import op  # type: ignore[import-not-found]

    for stmt in get_revision_0001_down_sql():
        op.execute(stmt)
