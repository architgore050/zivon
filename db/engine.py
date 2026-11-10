"""Database engine abstraction and repository operations for U2 Hot Database.

Supports PostgreSQL 16 (`postgresql://` / `postgresql+asyncpg://` via psycopg or
SQLAlchemy when installed in cluster/CI) and SQLite 3 (`sqlite://` via stdlib
`sqlite3` for local dev and unit/contract tests). Enforces foreign keys, thread
safety, and atomic transactions.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

from .migrate import get_current_revision, upgrade_db
from .uuid7 import uuid7_str


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class _TransactionCursor:
    """Wrapper normalizing parameter placeholders (`?` -> `%s` for Postgres)."""

    def __init__(self, conn: Any, dialect: str) -> None:
        self._conn = conn
        self._dialect = dialect

    def _adapt_sql(self, sql: str) -> str:
        if self._dialect == "postgresql":
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        adapted = self._adapt_sql(sql)
        cur = self._conn.cursor()
        cur.execute(adapted, params)
        return cur

    def fetchone(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        if hasattr(cur, "description") and cur.description:
            cols = [col[0] for col in cur.description]
            return dict(zip(cols, row))
        return dict(row)

    def fetchall(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], sqlite3.Row):
            return [dict(r) for r in rows]
        if hasattr(cur, "description") and cur.description:
            cols = [col[0] for col in cur.description]
            return [dict(zip(cols, r)) for r in rows]
        return [dict(r) for r in rows]


class DatabaseEngine:
    """Thread-safe relational engine for Zivon core backend and repositories."""

    def __init__(
        self,
        url: str,
        *,
        dialect: str,
        conn_factory: Any,
        auto_migrate: bool = True,
    ) -> None:
        self.url = url
        self.dialect = dialect
        self._conn_factory = conn_factory
        self._lock = threading.RLock()
        self._shared_conn: Any | None = (
            conn_factory() if dialect == "sqlite" else None
        )
        if auto_migrate:
            upgrade_db(self, "head")

    @classmethod
    def from_url(cls, url: str, *, auto_migrate: bool = True) -> DatabaseEngine:
        cleaned = url.strip()
        if cleaned.startswith("postgresql"):
            pg_url = cleaned.replace("postgresql+asyncpg://", "postgresql://").replace(
                "postgresql+psycopg://", "postgresql://"
            )

            def _pg_factory() -> Any:
                try:
                    import psycopg  # type: ignore[import-not-found]

                    return psycopg.connect(pg_url)
                except ImportError:
                    import psycopg2  # type: ignore[import-not-found]

                    return psycopg2.connect(pg_url)

            return cls(
                cleaned,
                dialect="postgresql",
                conn_factory=_pg_factory,
                auto_migrate=auto_migrate,
            )

        if cleaned.startswith("sqlite:///"):
            raw_path = cleaned[len("sqlite:///") :]
        elif cleaned.startswith("sqlite://"):
            raw_path = cleaned[len("sqlite://") :]
        else:
            raw_path = ":memory:"

        if raw_path and raw_path != ":memory:":
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)

        def _sqlite_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(
                raw_path or ":memory:",
                check_same_thread=False,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn

        return cls(
            cleaned,
            dialect="sqlite",
            conn_factory=_sqlite_factory,
            auto_migrate=auto_migrate,
        )

    @contextlib.contextmanager
    def transaction(self) -> Iterator[_TransactionCursor]:
        """Execute a block inside a serialized atomic DB transaction."""
        with self._lock:
            conn = (
                self._shared_conn
                if self._shared_conn is not None
                else self._conn_factory()
            )
            try:
                if self.dialect == "sqlite":
                    conn.execute("BEGIN IMMEDIATE")
                tx = _TransactionCursor(conn, self.dialect)
                yield tx
                if self.dialect == "sqlite":
                    conn.execute("COMMIT")
                else:
                    conn.commit()
            except Exception:
                if self.dialect == "sqlite":
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass
                else:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                raise
            finally:
                if self._shared_conn is None:
                    conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.transaction() as tx:
            tx.execute(sql, params)

    def fetchone(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        with self.transaction() as tx:
            return tx.fetchone(sql, params)

    def fetchall(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.fetchall(sql, params)

    def ping(self) -> bool:
        try:
            row = self.fetchone("SELECT 1 AS ok")
            return bool(row and int(row["ok"]) == 1)
        except Exception:
            return False

    def schema_version(self) -> str:
        return get_current_revision(self) or "0000"

    def list_tables(self) -> list[str]:
        if self.dialect == "sqlite":
            rows = self.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            return [str(r["name"]) for r in rows]
        rows = self.fetchall(
            "SELECT tablename AS name FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        return [str(r["name"]) for r in rows]

    # --- Repository methods for logging_shim & core entities -----------------

    def write_log_event(self, record: dict[str, Any]) -> None:
        """Insert a structured log event into `log_events` (ADR-0025)."""
        self.execute(
            """
            INSERT INTO log_events (
                ts, schema_version, severity, event, component, env,
                run_id, session_id, turn_id, request_id, stage,
                latency_ms, error_class, fields, trace_id, span_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("ts") or _utc_now_iso(),
                int(record.get("schema_version", 1)),
                str(record.get("severity", "INFO")),
                str(record.get("event", "unknown")),
                str(record.get("component", "voice")),
                str(record.get("env", "dev")),
                record.get("run_id"),
                record.get("session_id"),
                record.get("turn_id"),
                record.get("request_id"),
                record.get("stage"),
                record.get("latency_ms"),
                record.get("error_class"),
                json.dumps(record.get("fields") or {}),
                record.get("trace_id"),
                record.get("span_id"),
            ),
        )

    def delete_subject_logs(self, session_id: str) -> int:
        """Delete `log_events` rows matching a pseudonymous `session_id`."""
        with self.transaction() as tx:
            row = tx.fetchone(
                "SELECT COUNT(*) AS cnt FROM log_events WHERE session_id = ?",
                (session_id,),
            )
            cnt = int(row["cnt"]) if row else 0
            if cnt > 0:
                tx.execute(
                    "DELETE FROM log_events WHERE session_id = ?",
                    (session_id,),
                )
            return cnt

    def upsert_device(self, device_pseudo_id: str, locale: str = "en-IN") -> None:
        """Ensure pseudonymous anchor row exists in `device` (db-spec §4.1)."""
        now = _utc_now_iso()
        self.execute(
            """
            INSERT INTO device (device_pseudo_id, first_seen_at, last_seen_at, locale)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (device_pseudo_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                locale = excluded.locale
            """,
            (device_pseudo_id, now, now, locale),
        )

    def get_latest_consent(
        self, device_pseudo_id: str
    ) -> dict[str, Any] | None:
        """Fetch latest derived consent record for a device (db-spec §4.4, AP-01/10)."""
        return self.fetchone(
            """
            SELECT consent_id, device_pseudo_id, consent_version, notice_version,
                   guardian_flag, action, source, recorded_at
            FROM consent_record
            WHERE device_pseudo_id = ?
            ORDER BY recorded_at DESC, consent_id DESC
            LIMIT 1
            """,
            (device_pseudo_id,),
        )

    def append_consent(
        self,
        *,
        device_pseudo_id: str,
        consent_version: str,
        notice_version: str,
        guardian_flag: bool,
        action: str,
        source: str = "overlay",
        recorded_at: str | None = None,
    ) -> str:
        """Append a consent event with 60s same-action deduplication (API-004)."""
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        ts = recorded_at or _utc_now_iso()
        cutoff = (now_dt - datetime.timedelta(seconds=60)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        with self.transaction() as tx:
            tx.execute(
                """
                INSERT INTO device (device_pseudo_id, first_seen_at, last_seen_at, locale)
                VALUES (?, ?, ?, 'en-IN')
                ON CONFLICT (device_pseudo_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (device_pseudo_id, ts, ts),
            )
            existing = tx.fetchone(
                """
                SELECT consent_id, action, recorded_at
                FROM consent_record
                WHERE device_pseudo_id = ?
                ORDER BY recorded_at DESC, consent_id DESC
                LIMIT 1
                """,
                (device_pseudo_id,),
            )
            if (
                existing is not None
                and existing["action"] == action
                and str(existing["recorded_at"]) >= cutoff
            ):
                return str(existing["consent_id"])

            consent_id = uuid7_str()
            tx.execute(
                """
                INSERT INTO consent_record (
                    consent_id, device_pseudo_id, consent_version, notice_version,
                    guardian_flag, action, source, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    consent_id,
                    device_pseudo_id,
                    consent_version,
                    notice_version,
                    1 if guardian_flag else 0,
                    action,
                    source,
                    ts,
                ),
            )
            if action in ("withdrawn", "declined"):
                tx.execute(
                    """
                    UPDATE session
                    SET flags = ?, coverage_synced = 0
                    WHERE device_pseudo_id = ?
                    """,
                    (
                        json.dumps(
                            {
                                "voice_enabled": False,
                                "typed_only": False,
                                "voice_off": True,
                            }
                        ),
                        device_pseudo_id,
                    ),
                )
            return consent_id

    def record_audit(
        self,
        *,
        actor: str,
        action: str,
        target: str | None = None,
        before_hash: str | None = None,
        after_hash: str | None = None,
    ) -> str:
        """Append an entry to `audit_log` (db-spec §4.14)."""
        audit_id = uuid7_str()
        self.execute(
            """
            INSERT INTO audit_log (audit_id, actor, action, target, before_hash, after_hash, at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                actor,
                action,
                target,
                before_hash,
                after_hash,
                _utc_now_iso(),
            ),
        )
        return audit_id
