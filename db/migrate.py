"""Alembic migration runner and programmatic migration verification (ADR-0016).

Maintains linear migration history (`0001` -> `0002`) per
`skills/zivon-backend-engineering-skills/README.md` §1 (`alembic heads` returns
a single head). Works with both the Alembic CLI (when installed) and direct
execution via `python -m db.migrate` against PostgreSQL or SQLite.

Relationship to Alembic's graph (EX6 weld, 2026-11-10): this runtime chain is
what the cluster's migrate Job runs (`k8s/26` -> `python -m db.migrate upgrade
head`), and it deliberately stops at `0002` because `0002` is a schema superset
(and SQLite-portable — `0022`'s PostgreSQL-only DDL would not run on the SQLite
path used by local dev/tests). Alembic's CLI graph extends it with EX2's
`0022_translation_memory_c3` (down_revision `0002`, in `migrations/versions`,
listed in alembic.ini's `version_locations`). On PostgreSQL, 0022 is a
defensive no-op after 0002 (`CREATE TABLE IF NOT EXISTS` / seed `ON CONFLICT DO
NOTHING`), so both tools converge on the same schema; only the recorded
`alembic_version` value differs (`0002` here, `0022_translation_memory_c3`
after an Alembic run). Any future revision chained onto 0022 must therefore
also be reachable from this chain — or the cluster path switched to the
Alembic CLI.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .schema import (
    get_revision_0001_down_sql,
    get_revision_0001_up_sql,
    get_revision_0002_down_sql,
    get_revision_0002_up_sql,
)

if TYPE_CHECKING:
    from .engine import DatabaseEngine


@dataclass(frozen=True)
class RevisionSpec:
    revision: str
    down_revision: str | None
    description: str
    up_sql_fn: Callable[[str], list[str]]
    down_sql_fn: Callable[[], list[str]]


REVISION_CHAIN: Final[tuple[RevisionSpec, ...]] = (
    RevisionSpec(
        revision="0001",
        down_revision=None,
        description="Initial 20 core backend tables (db-spec.md)",
        up_sql_fn=get_revision_0001_up_sql,
        down_sql_fn=get_revision_0001_down_sql,
    ),
    RevisionSpec(
        revision="0002",
        down_revision="0001",
        description="Wave-E addenda: C3 translation tables, C4 eval tables, and log_events (GAP-014)",
        up_sql_fn=get_revision_0002_up_sql,
        down_sql_fn=get_revision_0002_down_sql,
    ),
)

LATEST_REVISION: Final[str] = REVISION_CHAIN[-1].revision


def get_heads() -> list[str]:
    """Return all branch heads in the migration graph (must be exactly 1)."""
    down_revs = {
        rev.down_revision for rev in REVISION_CHAIN if rev.down_revision is not None
    }
    return [rev.revision for rev in REVISION_CHAIN if rev.revision not in down_revs]


def ensure_version_table(engine: DatabaseEngine) -> None:
    """Create `alembic_version` table if it does not exist."""
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL PRIMARY KEY
        )
        """
    )


def get_current_revision(engine: DatabaseEngine) -> str | None:
    """Return the current revision recorded in `alembic_version`, or None."""
    try:
        rows = engine.fetchall("SELECT version_num FROM alembic_version LIMIT 1")
        if not rows:
            return None
        return str(rows[0]["version_num"])
    except Exception:  # noqa: BLE001
        return None


def upgrade_db(engine: DatabaseEngine, target: str = "head") -> str:
    """Apply migrations linearly up to `target` ('head', '0001', or '0002')."""
    target_rev = LATEST_REVISION if target == "head" else target
    valid_revs = [r.revision for r in REVISION_CHAIN]
    if target_rev not in valid_revs:
        raise ValueError(f"Unknown target revision '{target}'")

    ensure_version_table(engine)
    current = get_current_revision(engine)
    start_idx = 0
    if current is not None:
        if current not in valid_revs:
            raise RuntimeError(f"Database at unknown revision '{current}'")
        start_idx = valid_revs.index(current) + 1

    target_idx = valid_revs.index(target_rev)
    for idx in range(start_idx, target_idx + 1):
        spec = REVISION_CHAIN[idx]
        with engine.transaction() as tx:
            for stmt in spec.up_sql_fn(engine.dialect):
                tx.execute(stmt)
            tx.execute("DELETE FROM alembic_version")
            tx.execute(
                "INSERT INTO alembic_version (version_num) VALUES (?)",
                (spec.revision,),
            )
        current = spec.revision

    return current or target_rev


def downgrade_db(engine: DatabaseEngine, target: str = "base") -> str | None:
    """Downgrade migrations linearly down to `target` ('base' or '0001')."""
    valid_revs = [r.revision for r in REVISION_CHAIN]
    if target != "base" and target not in valid_revs:
        raise ValueError(f"Unknown downgrade target '{target}'")

    ensure_version_table(engine)
    current = get_current_revision(engine)
    if current is None:
        return None

    curr_idx = valid_revs.index(current)
    stop_idx = -1 if target == "base" else valid_revs.index(target)

    for idx in range(curr_idx, stop_idx, -1):
        spec = REVISION_CHAIN[idx]
        with engine.transaction() as tx:
            for stmt in spec.down_sql_fn():
                tx.execute(stmt)
            tx.execute("DELETE FROM alembic_version")
            if spec.down_revision is not None:
                tx.execute(
                    "INSERT INTO alembic_version (version_num) VALUES (?)",
                    (spec.down_revision,),
                )
        current = spec.down_revision

    return current


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m db.migrate [upgrade [head]|downgrade [base]|heads|current]`."""
    import os

    from .engine import DatabaseEngine

    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "upgrade"
    db_url = os.environ.get("ZIVON_DB_URL", "sqlite:///:memory:")
    engine = DatabaseEngine.from_url(db_url, auto_migrate=False)

    if cmd == "heads":
        for head in get_heads():
            print(head)
        return 0
    if cmd == "current":
        print(get_current_revision(engine) or "base")
        return 0
    if cmd == "upgrade":
        target = args[1] if len(args) > 1 else "head"
        rev = upgrade_db(engine, target)
        print(f"[migrate] upgraded to {rev}")
        return 0
    if cmd == "downgrade":
        target = args[1] if len(args) > 1 else "base"
        # downgrade_db may return None (no revision left) — keep it in its own
        # variable so the upgrade branch's `rev: str` is not widened.
        downgraded = downgrade_db(engine, target)
        print(f"[migrate] downgraded to {downgraded or 'base'}")
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
