"""Store lifecycle helpers that run without a live Postgres: the export
manifest roundtrip (via a stub connection), fallback ingestion bookkeeping,
l3 event derivation from the map, and the CLI's argument surface. The SQL
against a real database is exercised by the log-sync Job; the verify-then-
drop ordering is pinned here because a wrong ordering silently deletes
unsynced history."""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from datetime import UTC, datetime
from typing import Any, Self

from logging_manager import store as st

from .support import ObservabilityTest


class _StubCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.description: Any = None
        self.rowcount = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.last_sql = sql
        if "FROM log_events" in sql:
            self.description = [
                (c,)
                for c in (
                    "ts",
                    "schema_version",
                    "severity",
                    "event",
                    "component",
                    "env",
                    "run_id",
                    "session_id",
                    "turn_id",
                    "request_id",
                    "stage",
                    "latency_ms",
                    "error_class",
                    "fields",
                    "trace_id",
                    "span_id",
                )
            ]

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        return None


class _StubConnection:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.rows = rows or []

    def cursor(self) -> _StubCursor:
        return _StubCursor(self.rows)

    def commit(self) -> None:
        return None


class ExportManifestTests(ObservabilityTest):
    def test_export_writes_ndjson_and_verified_manifest(self) -> None:
        row = (
            datetime(2026, 11, 8, 10, 0, 0, tzinfo=UTC),
            1,
            "INFO",
            "voice.turn.e2e_latency",
            "voice",
            "dev",
            None,
            "sess-1",
            "turn-1",
            "req-1",
            None,
            3400,
            None,
            {"slowest_hop": "tts_first_audio"},
            None,
            None,
        )
        conn = _StubConnection([row])
        manifest = st.export_day(conn, "2026-11-08", self.runs_dir / "logs-exports")
        out = self.runs_dir / "logs-exports" / "2026-11-08.ndjson"
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["event"], "voice.turn.e2e_latency")
        self.assertEqual(record["session_id"], "sess-1")
        self.assertEqual(record["fields"], {"slowest_hop": "tts_first_audio"})
        self.assertEqual(manifest["rows"], 1)
        self.assertEqual(
            manifest["sha256"], hashlib.sha256(out.read_bytes()).hexdigest()
        )
        self.assertTrue(manifest["verified"])
        self.assertTrue(st.day_verified("2026-11-08", self.runs_dir / "logs-exports"))

    def test_row_to_record_omits_nulls(self) -> None:
        record = st._row_to_record(
            (
                datetime(2026, 11, 8, tzinfo=UTC),
                1,
                "INFO",
                "e",
                "c",
                "dev",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                {},
                None,
                None,
            )
        )
        self.assertNotIn("run_id", record)
        self.assertEqual(record["ts"], "2026-11-08T00:00:00.000Z")


class L3DerivationTests(unittest.TestCase):
    def test_l3_events_come_from_the_map(self) -> None:
        l3 = st.l3_events()
        # the audit-class rows the ADR-0025 retention table names
        self.assertIn("log.redaction_violation", l3)
        self.assertIn("dashboard.auth_failure", l3)
        self.assertIn("dashboard.action_triggered", l3)
        self.assertIn("privacy.subject_deleted", l3)
        self.assertNotIn("factory.stage.ok", l3)
        self.assertNotIn("voice.turn.e2e_latency", l3)

    def test_ttl_constants_match_adr0025(self) -> None:
        self.assertEqual(st.HOT_TTL_DAYS, 7)
        self.assertEqual(st.HOT_TTL_L3_DAYS, 30)
        self.assertEqual(st.SYNC_SIZE_CAP_BYTES, 200 * 1024 * 1024)


class FallbackIngestionTests(ObservabilityTest):
    def test_ingest_is_idempotent_per_file_hash(self) -> None:
        # an isolated runs dir: setUp's pre-engaged fallback event must not
        # land in the ingested set
        runs = self.runs_dir / "ingest"
        os.environ["ZIVON_RUNS_DIR"] = str(runs)
        logs = runs / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "ts": "2026-11-08T10:00:00.000Z",
                "schema_version": 1,
                "severity": "INFO",
                "event": "factory.stage.ok",
                "component": "factory",
                "env": "dev",
                "fields": {},
            }
        )
        (logs / "20261108-factory.jsonl").write_text(line + "\n", encoding="utf-8")
        out = self.runs_dir / "logs-exports"
        done_manifest = out / "fallback-ingested.json"

        original = st._insert_lines
        st.__dict__["_insert_lines"] = lambda conn, lines: True
        try:
            first = st.ingest_fallback_files(None, out)  # type: ignore[arg-type]
            self.assertEqual(first["rows"], 1)
            second = st.ingest_fallback_files(None, out)  # type: ignore[arg-type]
            self.assertEqual(second["skipped"], 1)
            self.assertEqual(second["rows"], 0)
        finally:
            st.__dict__["_insert_lines"] = original
            os.environ.pop("ZIVON_RUNS_DIR", None)
        self.assertTrue(done_manifest.is_file())  # the manifest recorded the hash

    def test_append_then_reingest_inserts_only_the_new_tail(self) -> None:
        """A file that grew must not re-insert its already-ingested head
        (the old whole-file-sha rule duplicated every old row)."""
        runs = self.runs_dir / "ingest-append"
        os.environ["ZIVON_RUNS_DIR"] = str(runs)
        logs = runs / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / "20261108-factory.jsonl"

        def _line(seconds: int) -> str:
            return json.dumps(
                {
                    "ts": f"2026-11-08T10:00:{seconds:02d}.000Z",
                    "schema_version": 1,
                    "severity": "INFO",
                    "event": "factory.stage.ok",
                    "component": "factory",
                    "env": "dev",
                    "fields": {},
                }
            )

        path.write_text(_line(0) + "\n", encoding="utf-8")
        out = self.runs_dir / "logs-exports-append"
        inserted: list[str] = []

        original = st._insert_lines

        def _capture(conn: Any, lines: list[str]) -> bool:
            inserted.extend(lines)
            return True

        st.__dict__["_insert_lines"] = _capture
        try:
            first = st.ingest_fallback_files(None, out)  # type: ignore[arg-type]
            self.assertEqual(first["rows"], 1)
            path.write_text(_line(0) + "\n" + _line(1) + "\n", encoding="utf-8")
            second = st.ingest_fallback_files(None, out)  # type: ignore[arg-type]
            # only the appended row is inserted; the head is not re-inserted
            self.assertEqual(second["rows"], 1)
            self.assertEqual(second["files"], 1)
            third = st.ingest_fallback_files(None, out)  # type: ignore[arg-type]
            self.assertEqual(third["rows"], 0)
            self.assertEqual(third["skipped"], 1)
        finally:
            st.__dict__["_insert_lines"] = original
            os.environ.pop("ZIVON_RUNS_DIR", None)
        self.assertEqual(len(inserted), 2)
        self.assertEqual(inserted, [_line(0), _line(1)])


class CliTests(unittest.TestCase):
    """The CLI (python -m logging_manager.store) is the k8s/51 Job's entry
    point; without a DSN it must refuse loudly BEFORE any DB touch."""

    def test_cli_requires_a_dsn(self) -> None:
        os.environ.pop("ZIVON_LOG_DSN", None)
        self.assertEqual(st.main(["sweep"]), 1)
        self.assertEqual(st.main(["sync"]), 1)
        self.assertEqual(st.main(["export", "--day", "2026-11-08"]), 1)


if __name__ == "__main__":
    unittest.main()
