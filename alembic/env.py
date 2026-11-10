"""Alembic migration environment for Zivon hot database (ADR-0016).

Reads `ZIVON_DB_URL` from the environment at runtime (never hardcoded secrets)
and supports both standard Alembic CLI invocations and programmatic execution
via `db.migrate`.

Database resolution rules (fail loud):
- `ZIVON_DB_URL` set -> use it verbatim.
- Not set and `ZIVON_ENV != "cluster"` -> fall back to the alembic config's
  `sqlalchemy.url` if present, else the dev/sqlite in-memory fallback (local
  dev + unit tests only — never persisted).
- Not set and `ZIVON_ENV == "cluster"` -> RuntimeError: a cluster migration
  must never touch a wrong/nonexistent database.
"""

from __future__ import annotations

import os

from db.engine import DatabaseEngine
from db.migrate import upgrade_db


def get_database_url() -> str:
    """Resolve database URL from ZIVON_DB_URL, alembic config, or dev fallback."""
    url = os.environ.get("ZIVON_DB_URL", "").strip()
    if url:
        return url

    zivon_env = os.environ.get("ZIVON_ENV", "dev").strip().lower() or "dev"
    if zivon_env in ("cluster", "prod", "k8s"):
        raise RuntimeError(
            "ZIVON_DB_URL is not set but ZIVON_ENV is "
            f"'{zivon_env}': refusing to run migrations against a fallback "
            "database. Configure the zivon-voice-env Secret (key ZIVON_DB_URL)."
        )

    try:
        from alembic import context  # type: ignore[import-not-found]

        cfg_url = context.config.get_main_option("sqlalchemy.url")
        if cfg_url:
            return str(cfg_url)
    except Exception as exc:  # noqa: BLE001
        # The alembic context legitimately does not exist in programmatic
        # (db.migrate) runs — but a real misconfiguration must not be hidden.
        print(f"[alembic.env] no alembic config context: {exc!r}", flush=True)
    return "sqlite:///:memory:"


def run_migrations_online() -> None:
    """Run migrations against the configured database URL."""
    url = get_database_url()
    try:
        from sqlalchemy import create_engine  # type: ignore[import-not-found]

        from alembic import context  # type: ignore[import-not-found]

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


_alembic_ctx = None
try:
    from alembic import context as _alembic_ctx  # type: ignore[import-not-found]

    _ALEMBIC_PRESENT = True
except ImportError:
    _ALEMBIC_PRESENT = False

if _ALEMBIC_PRESENT and _alembic_ctx is not None:
    if _alembic_ctx.is_offline_mode():
        run_migrations_online()
    else:
        run_migrations_online()
