"""Zivon hot database (U2) package (db-spec.md, ADR-0001, ADR-0016)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .uuid7 import uuid7_str

if TYPE_CHECKING:
    from .engine import DatabaseEngine
    from .migrate import (
        LATEST_REVISION,
        REVISION_CHAIN,
        downgrade_db,
        get_current_revision,
        get_heads,
        upgrade_db,
    )

__all__ = [
    "LATEST_REVISION",
    "REVISION_CHAIN",
    "DatabaseEngine",
    "downgrade_db",
    "get_current_revision",
    "get_heads",
    "upgrade_db",
    "uuid7_str",
]


def __getattr__(name: str) -> Any:
    if name == "DatabaseEngine":
        from .engine import DatabaseEngine

        return DatabaseEngine
    if name in (
        "LATEST_REVISION",
        "REVISION_CHAIN",
        "downgrade_db",
        "get_current_revision",
        "get_heads",
        "upgrade_db",
    ):
        from . import migrate

        return getattr(migrate, name)
    raise AttributeError(f"module 'db' has no attribute '{name}'")
