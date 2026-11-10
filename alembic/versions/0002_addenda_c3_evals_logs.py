"""Wave-E addenda: C3 translation tables, C4 eval tables, and log_events (GAP-014).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

from __future__ import annotations

from db.schema import get_revision_0002_down_sql, get_revision_0002_up_sql

revision: str = "0002"
down_revision: str | None = "0001"
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
    """Apply revision 0002 (5 C3 translation tables, 5 C4 eval tables, log_events)."""
    from alembic import op  # type: ignore[import-not-found]

    dialect = _dialect_name()
    for stmt in get_revision_0002_up_sql(dialect):
        op.execute(stmt)


def downgrade() -> None:
    """Revert revision 0002 in reverse foreign-key dependency order."""
    from alembic import op  # type: ignore[import-not-found]

    for stmt in get_revision_0002_down_sql():
        op.execute(stmt)
