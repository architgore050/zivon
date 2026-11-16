"""Full-frontend foundation: accounts, auth sessions, catalogue, progress.

Revision ID: 0003_full_frontend
Revises: 0022_translation_memory_c3
Create Date: 2026-11-15

Chained onto the current single head. EX2's `0022` is a defensive no-op after
`0002` (it re-creates tables `0002` already ships with `IF NOT EXISTS`), so the
resulting schema is identical to running `0001 -> 0002 -> 0003`; the recorded
revision is what differs. This revision is the one the runtime chain
(`db/migrate.py`) and the Alembic CLI now agree on, so a database migrated by
either path converges and the graph keeps exactly one head.

Traces to: `docs/backend/adr/0029-accounts-and-session-cookies.md`,
`docs/backend/db-spec.md` §4.18, REQUIREMENTS §8.1/§8.2/§8.4.
"""

from __future__ import annotations

from db.schema import get_revision_0003_down_sql, get_revision_0003_up_sql

revision: str = "0003_full_frontend"
down_revision: str | None = "0022_translation_memory_c3"
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
    """Apply revision 0003 (9 account/catalogue/progress tables + device link)."""
    from alembic import op  # type: ignore[import-not-found]

    dialect = _dialect_name()
    for stmt in get_revision_0003_up_sql(dialect):
        op.execute(stmt)


def downgrade() -> None:
    """Revert revision 0003 in reverse foreign-key dependency order."""
    from alembic import op  # type: ignore[import-not-found]

    for stmt in get_revision_0003_down_sql():
        op.execute(stmt)
