"""Alembic migration environment for Zivon hot database (ADR-0016).

Reads `ZIVON_DB_URL` from the environment at runtime (never hardcoded secrets)
and supports both standard Alembic CLI invocations and programmatic execution
via `db.migrate`.
"""

from __future__ import annotations

import os

from db.engine import DatabaseEngine
from db.migrate import upgrade_db


def get_database_url() -> str:
    """Resolve database URL from ZIVON_DB_URL or alembic config fallback."""
    url = os.environ.get("ZIVON_DB_URL", "").strip()
    if url:
        return url
    try:
        from alembic import context  # type: ignore[import-not-found]

        cfg_url = context.config.get_main_option("sqlalchemy.url")
        if cfg_url:
            return str(cfg_url)
    except Exception:
        pass
    return "sqlite:///:memory:"


def run_migrations_online() -> None:
    """Run migrations against the configured database URL."""
    url = get_database_url()
    try:
        from alembic import context  # type: ignore[import-not-found]
        from sqlalchemy import create_engine  # type: ignore[import-not-found]

        sa_url = url.replace("postgresql+asyncpg://", "postgresql://")
        connectable = create_engine(sa_url)
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
        return
    except ImportError:
        engine = DatabaseEngine.from_url(url, auto_migrate=False)
        upgrade_db(engine, "head")


try:
    from alembic import context as _alembic_ctx  # type: ignore[import-not-found]

    if _alembic_ctx.is_offline_mode():
        run_migrations_online()
    else:
        run_migrations_online()
except Exception:
    pass
