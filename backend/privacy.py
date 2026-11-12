"""Device-wipe deletion pipeline (NEED-013) and TTL retention jobs (GAP-005).

Implements:
1. 8-step guardian/device erasure pipeline (`storage-tiering.md` §6.2, `GAP-007`):
   - Step 1: Insert `deletion_request` tombstone (`status='requested'`) first.
   - Step 2: Hard-delete `voice_turn`, `eval_kid_session`, `telemetry_event`,
     `session`, `consent_record`, `problem_report`, and `device` for
     `device_pseudo_id` while preserving `credit_ledger` and `audit_log`.
   - Step 3-4: Mark any `object_catalog` rows with `subject_ref = device_pseudo_id`
     as `deleted` and enqueue cold deletion in `outbox`.
   - Step 5-6: Scrub `log_events` (hot DB + JSONL fallback) for all sessions of
     the device via `delete_subject(session_id)`.
   - Step 7-8: Stamp `deletion_request` `status='completed'` with counts (serving
     as the `REDEL-01` re-delete-on-restore list) and append `audit_log`.
2. Idempotent TTL retention jobs (`storage-tiering.md` §6.3, `k8s/53`):
   - `ttl-voice-turn` (7-day hard delete on `voice_turn`, A-02)
   - `ttl-coverage` (24-hour idle clear on `session.coverage`)
   - `ttl-abuse-bucket` (72-hour rolling expiry on `abuse_bucket`, A-12)
   - `rollup-daily-stats` (daily roll-up into `daily_stats` + 30-day `session` hard delete)
   - `ttl-telemetry` (90-day hard delete on `telemetry_event` and resolved `problem_report`)
"""

from __future__ import annotations

import datetime
import json
import sys
from typing import Any

from db.engine import DatabaseEngine
from db.uuid7 import uuid7_str

from . import logging_shim as _logging_shim
from .config import BackendConfig
from .logging_shim import (
    ErrorClass,
    Severity,
    delete_subject,
    log_event,
)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _fmt_iso(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    else:
        dt = dt.astimezone(datetime.UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _day_window(day: str) -> tuple[str, str]:
    """`(start, end)` ISO bounds of a UTC day, dialect-portable.

    The TTL rollup must work on both SQLite (ISO TEXT columns; lexical compare)
    and Postgres (timestamptz). `substr(col, 1, 10)` is SQLite-only and
    `MAX(a, b)` is SQLite-only scalar-vs-aggregate overloading, so the rollup
    filters with range comparisons on the timestamp column and does the day
    bucketing in Python. Both dialects accept the ISO strings as parameters.
    """
    start = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.UTC)
    end = start + datetime.timedelta(days=1)
    return _fmt_iso(start), _fmt_iso(end)


def _day_of(value: object) -> str:
    """UTC day (`YYYY-MM-DD`) of a DB timestamp value (str in SQLite, datetime in PG)."""
    return str(value)[:10]


class DeletionAndRetentionService:
    """Orchestrates NEED-013 erasure cascade and storage-tiering §6.3 TTL jobs."""

    def __init__(self, db: DatabaseEngine) -> None:
        self.db = db

    def wipe_device(
        self,
        device_pseudo_id: str,
        *,
        now_dt: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Execute the 8-step device-scoped erasure pipeline (NEED-013).

        Returns `{deleted: {sessions, consents, events, turns, reports}, tombstone_id}`.
        Idempotent: a second call for an already-wiped device returns zero counts
        and the existing tombstone ID (`backend-spec.md` §6.1 API-007).
        """
        norm_dev = device_pseudo_id.strip().lower()
        now = now_dt or _utc_now()
        now_iso = _fmt_iso(now)

        # Check if device is already wiped and has a completed tombstone
        dev_exists = self.db.fetchone(
            "SELECT device_pseudo_id FROM device WHERE device_pseudo_id = ?",
            (norm_dev,),
        )
        rep_exists = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM problem_report WHERE device_pseudo_id = ?",
            (norm_dev,),
        )
        has_reports = bool(rep_exists and int(rep_exists["cnt"]) > 0)
        if dev_exists is None and not has_reports:
            prev_tomb = self.db.fetchone(
                """
                SELECT request_id FROM deletion_request
                WHERE device_pseudo_id = ? AND status = 'completed'
                ORDER BY requested_at DESC LIMIT 1
                """,
                (norm_dev,),
            )
            if prev_tomb is not None:
                zero_counts = {
                    "sessions": 0,
                    "consents": 0,
                    "events": 0,
                    "turns": 0,
                    "reports": 0,
                }
                return {
                    "deleted": zero_counts,
                    "tombstone_id": str(prev_tomb["request_id"]),
                }

        # Step 1: Insert deletion_request tombstone (`requested` -> `in_progress`)
        request_id = uuid7_str()
        self.db.execute(
            """
            INSERT INTO deletion_request (
                request_id, device_pseudo_id, scope, status, counts, requested_at
            ) VALUES (?, ?, 'device', 'in_progress', NULL, ?)
            """,
            (request_id, norm_dev, now_iso),
        )

        session_ids: list[str] = []
        with self.db.transaction() as tx:
            sess_rows = tx.fetchall(
                "SELECT session_id FROM session WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            session_ids = [str(r["session_id"]) for r in sess_rows]

            turns_row = tx.fetchone(
                """
                SELECT COUNT(*) AS cnt FROM voice_turn
                WHERE session_id IN (SELECT session_id FROM session WHERE device_pseudo_id = ?)
                """,
                (norm_dev,),
            )
            consents_row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM consent_record WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            events_row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM telemetry_event WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            reports_row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM problem_report WHERE device_pseudo_id = ?",
                (norm_dev,),
            )

            counts = {
                "sessions": len(session_ids),
                "consents": int(consents_row["cnt"]) if consents_row else 0,
                "events": int(events_row["cnt"]) if events_row else 0,
                "turns": int(turns_row["cnt"]) if turns_row else 0,
                "reports": int(reports_row["cnt"]) if reports_row else 0,
            }

            # Step 2: Explicit fan-out deletion across child tables + device anchor
            # Note: credit_ledger and audit_log are intentionally NOT deleted per db-spec §6.
            tx.execute(
                """
                DELETE FROM voice_turn
                WHERE session_id IN (SELECT session_id FROM session WHERE device_pseudo_id = ?)
                """,
                (norm_dev,),
            )
            tx.execute(
                """
                DELETE FROM eval_kid_session
                WHERE consent_record_id IN (SELECT consent_id FROM consent_record WHERE device_pseudo_id = ?)
                """,
                (norm_dev,),
            )
            tx.execute(
                "DELETE FROM telemetry_event WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            tx.execute(
                "DELETE FROM session WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            tx.execute(
                "DELETE FROM consent_record WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            tx.execute(
                "DELETE FROM problem_report WHERE device_pseudo_id = ?",
                (norm_dev,),
            )
            tx.execute(
                "DELETE FROM device WHERE device_pseudo_id = ?",
                (norm_dev,),
            )

            # Step 3 & 4: Object catalog subject_ref fan-out
            obj_rows = tx.fetchall(
                "SELECT object_id, key FROM object_catalog WHERE subject_ref = ? AND state != 'deleted'",
                (norm_dev,),
            )
            for obj in obj_rows:
                oid = str(obj["object_id"])
                tx.execute(
                    "UPDATE object_catalog SET state = 'deleted' WHERE object_id = ?",
                    (oid,),
                )
                tx.execute(
                    """
                    INSERT INTO outbox (idempotency_key, object_id, job_type, payload, created_at)
                    VALUES (?, ?, 'delete', ?, ?)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        f"delete:{oid}",
                        oid,
                        json.dumps({"object_id": oid, "key": obj["key"]}),
                        now_iso,
                    ),
                )

        # Step 5-8: DB scrub, stamp 'completed', and audit — any failure must
        # stamp the tombstone 'failed' and log CRITICAL privacy.delete_failed
        # instead of completing. Deletion never silently half-completes.
        completed_iso = _fmt_iso(_utc_now())
        try:
            for sid in session_ids:
                delete_subject(sid)
            with self.db.transaction() as tx:
                tx.execute(
                    """
                    UPDATE deletion_request
                    SET status = 'completed', counts = ?, completed_at = ?
                    WHERE request_id = ?
                    """,
                    (json.dumps(counts), completed_iso, request_id),
                )
                tx.execute(
                    """
                    INSERT INTO audit_log (audit_id, actor, action, target, before_hash, after_hash, at)
                    VALUES (?, 'system', 'deletion.complete', ?, NULL, ?, ?)
                    """,
                    (
                        uuid7_str(),
                        request_id,
                        json.dumps(counts, sort_keys=True),
                        completed_iso,
                    ),
                )
        except Exception:
            try:
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE deletion_request SET status = 'failed' WHERE request_id = ?",
                        (request_id,),
                    )
            except Exception:  # noqa: BLE001
                log_event(
                    "privacy.delete_failed.stamp_error",
                    {"tombstone_id": request_id, "reason_code": "stamp_tx_failed"},
                    severity=Severity.CRITICAL,
                    error_class=ErrorClass.STORE_ERROR,
                )
            log_event(
                "privacy.delete_failed",
                {
                    "tombstone_id": request_id,
                    "target": norm_dev,
                    "reason_code": "scrub_or_stamp_failed",
                    "counts_before_failure": counts,
                },
                severity=Severity.CRITICAL,
                error_class=ErrorClass.PRIVACY_VIOLATION,
            )
            raise

        scrub_unreadable = list(_logging_shim.LAST_SCRUB_UNREADABLE)
        return {
            "deleted": counts,
            "tombstone_id": request_id,
            "unreadable_log_files": len(scrub_unreadable),
        }

    def purge_expired_voice_turns(
        self, *, now_dt: datetime.datetime | None = None, ttl_days: int = 7
    ) -> int:
        """Job `ttl-voice-turn`: Hard-delete `voice_turn` rows older than 7 days (A-02)."""
        now = now_dt or _utc_now()
        cutoff = _fmt_iso(now - datetime.timedelta(days=ttl_days))
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM voice_turn WHERE created_at < ?",
                (cutoff,),
            )
            cnt = int(row["cnt"]) if row else 0
            if cnt > 0:
                tx.execute(
                    "DELETE FROM voice_turn WHERE created_at < ?",
                    (cutoff,),
                )
            return cnt

    def purge_idle_coverage(
        self, *, now_dt: datetime.datetime | None = None, ttl_hours: int = 24
    ) -> int:
        """Job `ttl-coverage`: Clear `session.coverage` idle for > 24 hours (db-spec §4.2)."""
        now = now_dt or _utc_now()
        cutoff = _fmt_iso(now - datetime.timedelta(hours=ttl_hours))
        with self.db.transaction() as tx:
            row = tx.fetchone(
                """
                SELECT COUNT(*) AS cnt FROM session
                WHERE coverage != '[]'
                  AND COALESCE(coverage_updated_at, started_at) < ?
                """,
                (cutoff,),
            )
            cnt = int(row["cnt"]) if row else 0
            if cnt > 0:
                tx.execute(
                    """
                    UPDATE session
                    SET coverage = '[]', coverage_synced = FALSE
                    WHERE coverage != '[]'
                      AND COALESCE(coverage_updated_at, started_at) < ?
                    """,
                    (cutoff,),
                )
            return cnt

    def purge_expired_abuse_buckets(
        self, *, now_dt: datetime.datetime | None = None
    ) -> int:
        """Job `ttl-abuse-bucket`: Delete `abuse_bucket` rows past 72h expiry (A-12)."""
        now = now_dt or _utc_now()
        cutoff = _fmt_iso(now)
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM abuse_bucket WHERE expires_at <= ?",
                (cutoff,),
            )
            cnt = int(row["cnt"]) if row else 0
            if cnt > 0:
                tx.execute(
                    "DELETE FROM abuse_bucket WHERE expires_at <= ?",
                    (cutoff,),
                )
            return cnt

    def rollup_daily_stats_and_prune_sessions(
        self, *, now_dt: datetime.datetime | None = None, session_ttl_days: int = 30
    ) -> dict[str, int]:
        """Job `rollup-daily-stats`: Roll up session/ledger metrics into `daily_stats`, then delete sessions > 30d."""
        now = now_dt or _utc_now()
        today_str = now.strftime("%Y-%m-%d")
        cutoff_30d = _fmt_iso(now - datetime.timedelta(days=session_ttl_days))

        with self.db.transaction() as tx:
            days_rows = tx.fetchall(
                "SELECT started_at FROM session WHERE started_at IS NOT NULL"
            )
            days = {_day_of(r["started_at"]) for r in days_rows if r.get("started_at")}
            days.add(today_str)

            for day in sorted(days):
                day_start, day_end = _day_window(day)
                s_agg = tx.fetchone(
                    """
                    SELECT COUNT(*) AS sessions,
                           COALESCE(SUM(turn_count), 0) AS turns
                    FROM session WHERE started_at >= ? AND started_at < ?
                    """,
                    (day_start, day_end),
                )
                v_agg = tx.fetchone(
                    """
                    SELECT COUNT(DISTINCT session_id) AS voice_sessions
                    FROM voice_turn
                    WHERE modality = 'voice' AND created_at >= ? AND created_at < ?
                    """,
                    (day_start, day_end),
                )
                t_agg = tx.fetchone(
                    """
                    SELECT COUNT(DISTINCT session_id) AS typed_sessions
                    FROM voice_turn
                    WHERE modality = 'typed' AND created_at >= ? AND created_at < ?
                    """,
                    (day_start, day_end),
                )
                e_agg = tx.fetchone(
                    "SELECT COUNT(*) AS events FROM telemetry_event WHERE ts >= ? AND ts < ?",
                    (day_start, day_end),
                )
                stt_agg = tx.fetchone(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger WHERE model = 'prisma' AND created_at >= ? AND created_at < ?",
                    (day_start, day_end),
                )
                tts_agg = tx.fetchone(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger WHERE model = 'timbre' AND created_at >= ? AND created_at < ?",
                    (day_start, day_end),
                )
                llm_agg = tx.fetchone(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM credit_ledger WHERE model = 'gemma_gpu' AND created_at >= ? AND created_at < ?",
                    (day_start, day_end),
                )
                # Portable monotonic upsert: `ON CONFLICT ... MAX(a, b)` is
                # SQLite-only (Postgres needs GREATEST and would reject the
                # two-arg MAX as an aggregate over excluded). Read the existing
                # row and write the max explicitly in Python.
                new_vals = {
                    "sessions": int(s_agg["sessions"]) if s_agg else 0,
                    "voice_sessions": int(v_agg["voice_sessions"]) if v_agg else 0,
                    "typed_sessions": int(t_agg["typed_sessions"]) if t_agg else 0,
                    "turns": int(s_agg["turns"]) if s_agg else 0,
                    "events": int(e_agg["events"]) if e_agg else 0,
                    "stt_seconds": float(stt_agg["total"]) if stt_agg else 0.0,
                    "tts_chars": float(tts_agg["total"]) if tts_agg else 0.0,
                    "llm_tokens": float(llm_agg["total"]) if llm_agg else 0.0,
                }
                cols = list(new_vals)
                existing = tx.fetchone(
                    "SELECT " + ", ".join(cols) + " FROM daily_stats WHERE day = ?",
                    (day,),
                )
                if existing is None:
                    tx.execute(
                        "INSERT INTO daily_stats (day, "
                        + ", ".join(cols)
                        + ") VALUES (?, "
                        + ", ".join("?" for _ in cols)
                        + ")",
                        (day, *(new_vals[c] for c in cols)),
                    )
                else:
                    merged = {
                        c: max(float(existing[c] or 0), float(new_vals[c]))
                        for c in cols
                    }
                    tx.execute(
                        "UPDATE daily_stats SET "
                        + ", ".join(f"{c} = ?" for c in cols)
                        + " WHERE day = ?",
                        (*(merged[c] for c in cols), day),
                    )

            old_sess = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM session WHERE started_at < ?",
                (cutoff_30d,),
            )
            pruned_sessions = int(old_sess["cnt"]) if old_sess else 0
            if pruned_sessions > 0:
                tx.execute(
                    "DELETE FROM session WHERE started_at < ?",
                    (cutoff_30d,),
                )

            old_gc = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM guard_counter WHERE period < ?",
                (today_str,),
            )
            pruned_counters = int(old_gc["cnt"]) if old_gc else 0
            if pruned_counters > 0:
                tx.execute(
                    "DELETE FROM guard_counter WHERE period < ?",
                    (today_str,),
                )

            return {
                "days_rolled_up": len(days),
                "pruned_sessions": pruned_sessions,
                "pruned_guard_counters": pruned_counters,
            }

    def purge_expired_telemetry_and_reports(
        self, *, now_dt: datetime.datetime | None = None, ttl_days: int = 90
    ) -> dict[str, int]:
        """Job `ttl-telemetry`: Delete `telemetry_event` > 90d and resolved `problem_report` > 90d."""
        now = now_dt or _utc_now()
        cutoff = _fmt_iso(now - datetime.timedelta(days=ttl_days))
        with self.db.transaction() as tx:
            ev_row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM telemetry_event WHERE ts < ?",
                (cutoff,),
            )
            ev_cnt = int(ev_row["cnt"]) if ev_row else 0
            if ev_cnt > 0:
                tx.execute("DELETE FROM telemetry_event WHERE ts < ?", (cutoff,))

            rep_row = tx.fetchone(
                """
                SELECT COUNT(*) AS cnt FROM problem_report
                WHERE status IN ('fixed', 'shipped_next_run')
                  AND resolved_at IS NOT NULL
                  AND resolved_at < ?
                """,
                (cutoff,),
            )
            rep_cnt = int(rep_row["cnt"]) if rep_row else 0
            if rep_cnt > 0:
                tx.execute(
                    """
                    DELETE FROM problem_report
                    WHERE status IN ('fixed', 'shipped_next_run')
                      AND resolved_at IS NOT NULL
                      AND resolved_at < ?
                    """,
                    (cutoff,),
                )
            return {"telemetry_deleted": ev_cnt, "reports_deleted": rep_cnt}

    def run_all_ttl_jobs(
        self, *, now_dt: datetime.datetime | None = None
    ) -> dict[str, Any]:
        """Run all P0 TTL and rollup jobs in sequence."""
        return {
            "ttl_voice_turn": self.purge_expired_voice_turns(now_dt=now_dt),
            "ttl_coverage": self.purge_idle_coverage(now_dt=now_dt),
            "ttl_abuse_bucket": self.purge_expired_abuse_buckets(now_dt=now_dt),
            "rollup_daily_stats": self.rollup_daily_stats_and_prune_sessions(
                now_dt=now_dt
            ),
            "ttl_telemetry": self.purge_expired_telemetry_and_reports(now_dt=now_dt),
        }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for K8s CronJobs (`k8s/53-sync-cronjobs.yaml`)."""
    args = argv if argv is not None else sys.argv[1:]
    job = args[0] if args else "all-ttl"
    # Fail loud in cluster mode: BackendConfig.from_env raises a clear
    # RuntimeError when ZIVON_DB_URL is unset (no sqlite fallback in pods).
    # In dev, from_env defaults to the sqlite in-memory DB.
    db_url = BackendConfig.from_env(strict_secrets=False).db_url
    engine = DatabaseEngine.from_url(db_url, auto_migrate=True)
    svc = DeletionAndRetentionService(engine)

    if job == "ttl-voice-turn":
        deleted = svc.purge_expired_voice_turns()
        print(f"[ttl-voice-turn] deleted={deleted}")
        return 0
    if job == "ttl-coverage":
        cleared = svc.purge_idle_coverage()
        print(f"[ttl-coverage] cleared={cleared}")
        return 0
    if job == "ttl-abuse-bucket":
        deleted = svc.purge_expired_abuse_buckets()
        print(f"[ttl-abuse-bucket] deleted={deleted}")
        return 0
    if job == "rollup-daily-stats":
        res = svc.rollup_daily_stats_and_prune_sessions()
        print(f"[rollup-daily-stats] {json.dumps(res)}")
        return 0
    if job == "ttl-telemetry":
        res = svc.purge_expired_telemetry_and_reports()
        print(f"[ttl-telemetry] {json.dumps(res)}")
        return 0
    if job == "all-ttl":
        res = svc.run_all_ttl_jobs()
        print(f"[all-ttl] {json.dumps(res)}")
        return 0

    print(f"Unknown privacy/TTL job: {job}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
