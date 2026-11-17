"""PostgreSQL/SQLite parity for runtime writes into BOOLEAN columns.

PostgreSQL's BOOLEAN type rejects the integers `1`/`0` that SQLite silently
accepts, so a write can pass every SQLite suite and still break the production
database (`DatatypeMismatch: column ... is of type boolean but expression is
of type smallint`). Two such writes shipped in the core runtime path:
`db.engine.append_consent` (`consent_record.guardian_flag`) and
`backend.sync.publish_and_verify_artifact` (`object_catalog.pinned`), plus
three literal `1`/`0` writes into `object_catalog.pinned` in `backend.sync`
(SYNC-02 C14 base backup, SYNC-03 C9 snapshot, SYNC-05 C4 run archive). This
module exercises the consent, publish, and nightly-sync flows on PostgreSQL
when `ZIVON_DB_URL` provides one (the CI `tests` job does), and always on
SQLite so the flows themselves stay covered key-free.

`run_base_backup` (SYNC-02) is covered on SQLite only: on PostgreSQL that flow
currently fails before its `object_catalog` insert because it feeds native
`Decimal`/`datetime` values from `fetchall` into `json.dumps` — a pre-existing
defect of a different class, deliberately left out of scope here.

Locally, without a PostgreSQL URL (or without psycopg), the PostgreSQL classes
**skip with a reason** — a skip is never converted into a pass.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend import BackendConfig
from backend.sync import ColdStorageSync, EvictionInvariantError
from db.engine import DatabaseEngine
from db.uuid7 import uuid7_str

PG_URL = os.environ.get("ZIVON_DB_URL", "").strip()
PARITY_DB = "zivon_bool_parity"
LEDGER_PARITY_DB = "zivon_bool_ledger_parity"


def _skip_reason() -> str | None:
    if not PG_URL.startswith("postgresql"):
        return "ZIVON_DB_URL is not a PostgreSQL URL (SQLite-only environment)"
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return "psycopg is not installed"
    return None


SKIP_REASON = _skip_reason()


def _db_url(database: str) -> str:
    """Point the configured DSN at another database on the same server.

    The query string is kept so unix-socket DSNs (`...?host=/dir`) still
    resolve; TCP DSNs in CI carry no query and are unchanged.
    """
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, ""))


def _admin_connection() -> Any:
    """Connect to the maintenance database to create/drop the parity database."""
    import psycopg

    return psycopg.connect(_db_url("postgres"), autocommit=True)


def _create_parity_db(name: str) -> None:
    admin = _admin_connection()
    try:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
            cur.execute(f'CREATE DATABASE "{name}"')
    except Exception as exc:  # no privilege means no parity run
        if "permission denied" in str(exc).lower():
            raise unittest.SkipTest(
                "the PostgreSQL role cannot CREATE DATABASE for the parity test"
            ) from exc
        raise
    finally:
        admin.close()


def _drop_parity_db(name: str) -> None:
    admin = _admin_connection()
    try:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        admin.close()


class BooleanParityFlows:
    """Consent/publish write flows shared by the SQLite and PostgreSQL classes."""

    db: DatabaseEngine
    cfg: BackendConfig

    def _append_consent(self, device_id: str, *, guardian_flag: bool) -> str:
        return self.db.append_consent(
            device_pseudo_id=device_id,
            consent_version="v1",
            notice_version="zivon-voice-notice-v1",
            guardian_flag=guardian_flag,
            action="granted" if guardian_flag else "declined",
        )

    def _latest_guardian_flag(self, device_id: str) -> bool:
        row = self.db.get_latest_consent(device_id)
        assert row is not None, "consent_record row must exist after append_consent"
        return bool(row["guardian_flag"])

    def _publish_artifact(
        self, artifact: Path, *, pinned: bool, version: str
    ) -> dict[str, Any]:
        return ColdStorageSync(self.db, self.cfg).publish_and_verify_artifact(
            artifact,
            class_id="C1",
            version=version,
            pinned=pinned,
        )

    def _object_pinned(self, object_id: str) -> bool:
        row = self.db.fetchone(
            "SELECT pinned FROM object_catalog WHERE object_id = ?", (object_id,)
        )
        assert row is not None, "object_catalog row must exist after publish"
        return bool(row["pinned"])

    def _write_artifact(self, name: str) -> Path:
        artifact = Path(self.cfg.cold_staging_dir).parent / name
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "index.html").write_text("<html>Motion</html>", encoding="utf-8")
        return artifact


class SqliteBooleanParityTests(BooleanParityFlows, unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            cold_staging_dir=str(self.tmp_path / "cold"),
            runs_dir=str(self.tmp_path / "runs"),
        )
        self.db = DatabaseEngine.from_url(self.cfg.db_url)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_consent_guardian_flag_write_round_trips_on_sqlite(self) -> None:
        # One consent row per device: two rows for one device can share the
        # millisecond-precision `recorded_at`, and uuid7 ordering within a
        # millisecond is random, so "latest" must not be relied on here.
        granted_device = uuid7_str()
        self._append_consent(granted_device, guardian_flag=True)
        self.assertTrue(
            self._latest_guardian_flag(granted_device),
            "guardian_flag=True must persist",
        )
        declined_device = uuid7_str()
        self._append_consent(declined_device, guardian_flag=False)
        self.assertFalse(
            self._latest_guardian_flag(declined_device),
            "guardian_flag=False must persist",
        )

    def test_publish_pinned_write_and_eviction_guard_on_sqlite(self) -> None:
        sync = ColdStorageSync(self.db, self.cfg)
        pinned_res = self._publish_artifact(
            self._write_artifact("lesson"), pinned=True, version="v-pinned"
        )
        self.assertTrue(
            self._object_pinned(pinned_res["object_id"]), "pinned=True must persist"
        )
        with self.assertRaises(EvictionInvariantError):
            sync.evict_hot_object(pinned_res["key"])

        unpinned_res = self._publish_artifact(
            self._write_artifact("narration"), pinned=False, version="v-unpinned"
        )
        self.assertFalse(
            self._object_pinned(unpinned_res["object_id"]),
            "pinned=False must persist",
        )
        self.assertEqual(sync.evict_hot_object(unpinned_res["key"])["state"], "evicted")

    def test_backup_and_nightly_pinned_literals_on_sqlite(self) -> None:
        run_dir = Path(self.cfg.runs_dir) / "motion-c9"
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(
            json.dumps({"completed_at": "2026-11-08T10:00:00Z"}), encoding="utf-8"
        )
        sync = ColdStorageSync(self.db, self.cfg)
        sync.run_base_backup()
        sync.run_nightly_sync()
        rows = {
            row["class_id"]: bool(row["pinned"])
            for row in self.db.fetchall("SELECT class_id, pinned FROM object_catalog")
        }
        self.assertTrue(rows.get("C14"), "SYNC-02 base backup row must be pinned")
        self.assertTrue(rows.get("C9"), "SYNC-03 snapshot row must be pinned")
        self.assertFalse(rows.get("C4"), "SYNC-05 run archive row must be unpinned")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class PostgresBooleanParityTests(BooleanParityFlows, unittest.TestCase):
    db: DatabaseEngine
    cfg: BackendConfig
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        _create_parity_db(PARITY_DB)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.cfg = BackendConfig(
            db_url=_db_url(PARITY_DB),
            cold_staging_dir=str(Path(cls._tmp.name) / "cold"),
            runs_dir=str(Path(cls._tmp.name) / "runs"),
        )
        cls.db = DatabaseEngine.from_url(cls.cfg.db_url, auto_migrate=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()
        _drop_parity_db(PARITY_DB)

    def test_consent_guardian_flag_write_on_postgres(self) -> None:
        # One consent row per device (see the SQLite twin for the tie reason).
        granted_device = uuid7_str()
        self._append_consent(granted_device, guardian_flag=True)
        self.assertTrue(
            self._latest_guardian_flag(granted_device),
            "guardian_flag=True must persist on the PostgreSQL BOOLEAN column",
        )
        declined_device = uuid7_str()
        self._append_consent(declined_device, guardian_flag=False)
        self.assertFalse(
            self._latest_guardian_flag(declined_device),
            "guardian_flag=False must persist on the PostgreSQL BOOLEAN column",
        )

    def test_publish_pinned_write_and_eviction_guard_on_postgres(self) -> None:
        sync = ColdStorageSync(self.db, self.cfg)
        pinned_res = self._publish_artifact(
            self._write_artifact("lesson"), pinned=True, version="v-pinned"
        )
        self.assertTrue(
            self._object_pinned(pinned_res["object_id"]),
            "pinned=True must persist on the PostgreSQL BOOLEAN column",
        )
        with self.assertRaises(EvictionInvariantError):
            sync.evict_hot_object(pinned_res["key"])

        unpinned_res = self._publish_artifact(
            self._write_artifact("narration"), pinned=False, version="v-unpinned"
        )
        self.assertFalse(
            self._object_pinned(unpinned_res["object_id"]),
            "pinned=False must persist on the PostgreSQL BOOLEAN column",
        )
        self.assertEqual(sync.evict_hot_object(unpinned_res["key"])["state"], "evicted")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class PostgresBooleanLedgerParityTests(BooleanParityFlows, unittest.TestCase):
    """SYNC-03/05 pinned literals against a pristine PostgreSQL database.

    Owns its own parity database so the C9/C13/C18 ledgers are empty: the
    nightly snapshot serializes their rows verbatim with `json.dumps`, and
    native TIMESTAMPTZ/NUMERIC values (the pre-existing, out-of-scope defect
    noted in the module docstring) would otherwise break the flow before its
    `object_catalog` writes.
    """

    db: DatabaseEngine
    cfg: BackendConfig
    _tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        _create_parity_db(LEDGER_PARITY_DB)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.cfg = BackendConfig(
            db_url=_db_url(LEDGER_PARITY_DB),
            cold_staging_dir=str(Path(cls._tmp.name) / "cold"),
            runs_dir=str(Path(cls._tmp.name) / "runs"),
        )
        cls.db = DatabaseEngine.from_url(cls.cfg.db_url, auto_migrate=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()
        _drop_parity_db(LEDGER_PARITY_DB)

    def test_nightly_ledger_and_run_archive_pinned_literals_on_postgres(self) -> None:
        run_dir = Path(self.cfg.runs_dir) / "motion-c9"
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(
            json.dumps({"completed_at": "2026-11-08T10:00:00Z"}), encoding="utf-8"
        )
        res = ColdStorageSync(self.db, self.cfg).run_nightly_sync()
        self.assertEqual(res["runs_archived"], 1, "the completed run must be archived")
        rows = {
            row["class_id"]: bool(row["pinned"])
            for row in self.db.fetchall(
                "SELECT class_id, pinned FROM object_catalog ORDER BY class_id"
            )
        }
        self.assertTrue(
            rows.get("C9"), "SYNC-03 snapshot row must be pinned on PostgreSQL"
        )
        self.assertFalse(
            rows.get("C4"), "SYNC-05 run archive row must be unpinned on PostgreSQL"
        )


if __name__ == "__main__":
    unittest.main()
