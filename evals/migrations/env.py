"""Alembic migration environment for `evals/migrations/`."""

from __future__ import annotations

import os


def get_database_url() -> str:
    """Resolve database URL from `EVAL_DB_URL` or `DATABASE_URL`."""
    return os.environ.get("EVAL_DB_URL") or os.environ.get("DATABASE_URL") or ""
