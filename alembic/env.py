"""Alembic migration environment for Zivon hot database (ADR-0016).

Reads `ZIVON_DB_URL` from the environment at runtime (never hardcoded secrets)
and runs ONE linear chain whose revisions live in two directories (see
`version_locations` in alembic.ini): EX0's baseline (`alembic/versions/0001`,
`0002`) and EX2's Class-C3 translation revision
(`migrations/versions/0022_translation_memory_c3`, wired onto `0002`).

This is the CLI path and it is what CI's upgrade-from-empty gate exercises. It
uses the real Alembic revision graph — never the hand-rolled `db.migrate`
chain — so a missing driver or a broken revision fails loudly here instead of
silently falling back to a different SQL path.

Database resolution rules (fail loud):
- `ZIVON_DB_URL` set -> use it verbatim.
- Not set and `ZIVON_ENV != "cluster"` -> fall back to the alembic config's
  `sqlalchemy.url` if present, else the dev/sqlite in-memory fallback (local
  dev only — never persisted).
- Not set and `ZIVON_ENV == "cluster"` -> RuntimeError: a cluster migration
  must never touch a wrong/nonexistent database.
"""

from __future__ import annotations

import os

# The monolith's schema is hand-authored DDL (`db/schema.py`), not SQLAlchemy
# ORM models, so autogenerate/`alembic check` has nothing to compare against.
# The drift gate is the idempotent second `upgrade head` in CI plus the schema
# round-trip in `testing/backend/test_alembic_migrations.py`.
target_metadata = None


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
        # runs — but a real misconfiguration must not be hidden.
        print(f"[alembic.env] no alembic config context: {exc!r}", flush=True)
    return "sqlite:///:memory:"


def sqlalchemy_url(url: str) -> str:
    """Normalize a Zivon DSN to the SQLAlchemy dialect this image ships.

    `backend/requirements.txt` pins `psycopg[binary]` (psycopg 3), NOT psycopg2.
    SQLAlchemy's default driver for a bare `postgresql://` URL is psycopg2, so
    an un-normalized URL dies with `ModuleNotFoundError: psycopg2` and used to
    be swallowed into the hand-rolled fallback. Name the driver explicitly.
    """
    cleaned = url.strip()
    if cleaned.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + cleaned[len("postgresql+asyncpg://") :]
    if cleaned.startswith("postgresql://"):
        return "postgresql+psycopg://" + cleaned[len("postgresql://") :]
    return cleaned


def run_migrations() -> None:
    """Run the revision graph against the configured database."""
    from sqlalchemy import create_engine  # type: ignore[import-not-found]

    from alembic import context  # type: ignore[import-not-found]

    url = sqlalchemy_url(get_database_url())
    if context.is_offline_mode():
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = create_engine(url)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
