"""Personalized-learning TTL retention jobs (C22-C25, data-and-api.md §2.7).

Called from `backend/privacy.py::run_all_ttl_jobs` so the whole retention
posture runs in the existing CronJob path. Every job is idempotent, deletes
hard (no cold copy of child free text — D-PL-05), and logs counts only.

1. sessions `last_turn_at < now - 90 d` → delete (cascade messages);
   `last_turn_at`, NOT `updated_at`, drives the TTL (workstreams.md §2 risk).
2. artifacts `ready` and `last_used_at < now - 30 d` with no referencing
   message → delete (the refcount rule; referenced artifacts wait).
3. artifacts `failed` and `created_at < now - 7 d` → delete.
4. usage `created_at < now - 90 d` → delete.
5. quota periods older than yesterday (IST) → delete.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from ..logging_shim import log_event

if TYPE_CHECKING:
    from db.engine import DatabaseEngine


def _cutoff_iso(now: datetime.datetime, days: int) -> str:
    cutoff = now - datetime.timedelta(days=days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%S.") + f"{cutoff.microsecond // 1000:03d}Z"


def _ist_yesterday(now: datetime.datetime) -> str:
    import zoneinfo

    ist_now = now.astimezone(zoneinfo.ZoneInfo("Asia/Kolkata"))
    yesterday = (ist_now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return yesterday


def purge_expired_sessions(
    db: DatabaseEngine,
    *,
    now_dt: datetime.datetime | None = None,
    ttl_days: int = 90,
) -> int:
    """Sessions past 90 days since their LAST TURN are hard-deleted (messages cascade)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    cutoff = _cutoff_iso(now, ttl_days)
    with db.transaction() as tx:
        rows = tx.fetchall(
            """
            SELECT session_id FROM personalized_session
            WHERE last_turn_at IS NOT NULL AND last_turn_at < ?
            """,
            (cutoff,),
        )
        for row in rows:
            session_id = str(row["session_id"])
            tx.execute(
                "DELETE FROM personalized_message WHERE session_id = ?", (session_id,)
            )
            tx.execute(
                "UPDATE personalized_usage SET session_id = NULL WHERE session_id = ?",
                (session_id,),
            )
            tx.execute(
                "DELETE FROM personalized_session WHERE session_id = ?", (session_id,)
            )
        return len(rows)


def purge_unreferenced_artifacts(
    db: DatabaseEngine,
    *,
    now_dt: datetime.datetime | None = None,
    ttl_days: int = 30,
) -> int:
    """Ready artifacts unreferenced for 30 days are deleted (refcount rule)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    cutoff = _cutoff_iso(now, ttl_days)
    rows = db.fetchall(
        """
        SELECT artifact_id FROM personalized_artifact
        WHERE status = 'ready' AND last_used_at IS NOT NULL AND last_used_at < ?
        """,
        (cutoff,),
    )
    deleted = 0
    for row in rows:
        artifact_id = str(row["artifact_id"])
        ref = db.fetchone(
            """
            SELECT 1 AS ref FROM personalized_message
            WHERE kind = 'artifact_ref'
              AND REPLACE(payload, ' ', '') LIKE ?
            LIMIT 1
            """,
            (f'%"artifact_id":"{artifact_id}"%',),
        )
        if ref is None:
            db.execute(
                "DELETE FROM personalized_artifact WHERE artifact_id = ?",
                (artifact_id,),
            )
            deleted += 1
    return deleted


def purge_failed_artifacts(
    db: DatabaseEngine,
    *,
    now_dt: datetime.datetime | None = None,
    ttl_days: int = 7,
) -> int:
    """Failed artifact build records are deleted after 7 days."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    cutoff = _cutoff_iso(now, ttl_days)
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM personalized_artifact "
            "WHERE status = 'failed' AND created_at < ?",
            (cutoff,),
        )
        cnt = int(row["cnt"]) if row else 0
        if cnt > 0:
            tx.execute(
                "DELETE FROM personalized_artifact WHERE status = 'failed' AND created_at < ?",
                (cutoff,),
            )
        return cnt


def purge_expired_usage(
    db: DatabaseEngine,
    *,
    now_dt: datetime.datetime | None = None,
    ttl_days: int = 90,
) -> int:
    """Usage ledger rows (counts only, no text) past 90 days are deleted."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    cutoff = _cutoff_iso(now, ttl_days)
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM personalized_usage WHERE created_at < ?",
            (cutoff,),
        )
        cnt = int(row["cnt"]) if row else 0
        if cnt > 0:
            tx.execute("DELETE FROM personalized_usage WHERE created_at < ?", (cutoff,))
        return cnt


def prune_old_quota_periods(
    db: DatabaseEngine,
    *,
    now_dt: datetime.datetime | None = None,
) -> int:
    """Quota periods older than yesterday (IST) are deleted (§2.7 job 5)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    yesterday = _ist_yesterday(now)
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT COUNT(*) AS cnt FROM personalized_quota WHERE period < ?",
            (yesterday,),
        )
        cnt = int(row["cnt"]) if row else 0
        if cnt > 0:
            tx.execute("DELETE FROM personalized_quota WHERE period < ?", (yesterday,))
        return cnt


def run_personalized_retention(
    db: DatabaseEngine, *, now_dt: datetime.datetime | None = None
) -> dict[str, int]:
    """Run all five personalized retention jobs; log the counts (idempotent)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    counts = {
        "sessions_deleted": purge_expired_sessions(db, now_dt=now),
        "artifacts_unreferenced_deleted": purge_unreferenced_artifacts(db, now_dt=now),
        "artifacts_failed_deleted": purge_failed_artifacts(db, now_dt=now),
        "usage_deleted": purge_expired_usage(db, now_dt=now),
        "quota_periods_pruned": prune_old_quota_periods(db, now_dt=now),
    }
    log_event("personalized.retention.purged", {**counts})
    return counts
