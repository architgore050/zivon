"""Sink behavior (logging-api.md §5, ADR-0025): stdout always, JSONL
fallback layout, fallback switching + recovery, DEBUG filtering cost, and
the store helper seams that do not need a live Postgres."""

from __future__ import annotations

import os
import unittest

from logging_manager import sink
from logging_manager.store import day_verified, sync_dir

from .support import ObservabilityTest, write_jsonl


class StdoutTests(ObservabilityTest):
    def test_every_event_hits_stdout_once(self) -> None:
        sink.log_event("factory.stage.ok", {"blocks": 1, "attempts": 1})
        sink.log_event("factory.stage.ok", {"blocks": 2, "attempts": 1})
        self.assertEqual(len(self.of_event("factory.stage.ok")), 2)


class JsonlFallbackTests(ObservabilityTest):
    def test_fallback_file_layout_by_day_and_component(self) -> None:
        sink.log_event("factory.stage.ok", {"blocks": 1, "attempts": 1})
        # the factory component's file, exactly (the pre-engaged fallback state
        # means no extra log.store_fallback event writes a log- component file)
        files = list((self.runs_dir / "logs").glob("*-factory.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertRegex(files[0].name, r"^\d{8}-factory\.jsonl$")

    def test_fallback_lines_are_byte_identical_schema(self) -> None:
        sink.log_event(
            "voice.turn.e2e_latency", {"slowest_hop": "tts"}, latency_ms=3400
        )
        path = next((self.runs_dir / "logs").glob("*-voice.jsonl"))
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = sink.parse_line(lines[0])
        self.assertEqual(record["event"], "voice.turn.e2e_latency")  # type: ignore[index]
        self.assertEqual(record["schema_version"], 1)  # type: ignore[index]

    def test_first_switch_emits_store_fallback_once(self) -> None:
        # the base class pre-engages the fallback for determinism; this test
        # needs the real first transition, so start from clean state
        sink.reset_for_tests(runs_dir=str(self.runs_dir))
        self.events.clear()
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
        switches = self.of_event("log.store_fallback")
        self.assertEqual(len(switches), 1)
        self.assertEqual(switches[0]["fields"]["dsn_set"], False)
        self.assertEqual(switches[0]["error_class"], "store_error")

    def test_env_override_redirects_the_fallback(self) -> None:
        os.environ["ZIVON_RUNS_DIR"] = str(self.runs_dir / "elsewhere")
        try:
            sink._jsonl_sink = None  # re-read the env
            sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
            files = list((self.runs_dir / "elsewhere" / "logs").glob("*.jsonl"))
            self.assertEqual(len(files), 1)
        finally:
            os.environ.pop("ZIVON_RUNS_DIR")


class PostgresDegradationTests(ObservabilityTest):
    def test_unreachable_dsn_falls_back_after_one_retry(self) -> None:
        """A DSN that cannot connect: the batch retries once, then falls back
        to JSONL with ONE loud store_fallback (spec §5 / §6)."""
        # reset FIRST (it clears the env), then point at a dead DSN
        sink.reset_for_tests(runs_dir=str(self.runs_dir))
        self.events.clear()
        os.environ["ZIVON_LOG_DSN"] = "postgresql://nobody@127.0.0.1:1/nowhere"
        try:
            sink._jsonl_sink = None
            for i in range(3):
                sink.log_event("factory.stage.ok", {"blocks": i, "attempts": 1})
            # the flusher thread degrades within its 1s tick; give it a moment
            for _ in range(100):
                if self.of_event("log.store_fallback"):
                    break
                if sink._pg_sink is not None:
                    sink._pg_sink.flush()  # drive the flusher deterministically
            switches = self.of_event("log.store_fallback")
            self.assertEqual(len(switches), 1)
            self.assertEqual(switches[0]["fields"]["dsn_set"], True)
            # the batch content survived in the fallback file
            path = next((self.runs_dir / "logs").glob("*-factory.jsonl"))
            self.assertGreaterEqual(
                len(path.read_text(encoding="utf-8").splitlines()), 3
            )
        finally:
            os.environ.pop("ZIVON_LOG_DSN", None)

    def test_recovery_emits_store_recovered(self) -> None:
        """Mark degraded, then let a successful flush flip back with the
        INFO recovery event (ADR-0025: loud on both directions)."""
        sink.reset_for_tests(runs_dir=str(self.runs_dir))
        self.events.clear()
        sink._mark_degraded(dsn_set=True)
        self.assertEqual(len(self.of_event("log.store_fallback")), 1)
        sink._mark_recovered()
        self.assertEqual(len(self.of_event("log.store_recovered")), 1)
        self.assertEqual(self.last_event("log.store_recovered")["severity"], "INFO")
        # idempotent transitions: no duplicate events
        sink._mark_recovered()
        sink._mark_degraded(dsn_set=True)
        sink._mark_degraded(dsn_set=True)
        self.assertEqual(len(self.of_event("log.store_recovered")), 1)
        self.assertEqual(len(self.of_event("log.store_fallback")), 2)


class FlushCostTests(ObservabilityTest):
    def test_filtered_debug_event_writes_nothing(self) -> None:
        from logging_manager import Severity

        sink.log_event(
            "factory.stage.ok", {"blocks": 0, "attempts": 0}, severity=Severity.DEBUG
        )
        # nothing reached the factory's fallback file (the log- component file
        # from setUp's pre-engaged switch event is expected and unrelated)
        self.assertEqual(list((self.runs_dir / "logs").glob("*-factory.jsonl")), [])
        self.assertEqual(self.of_event("factory.stage.ok"), [])


class StoreHelperTests(ObservabilityTest):
    def test_day_verified_requires_manifest_and_checksum(self) -> None:
        day = "2026-11-08"
        out = self.runs_dir / "logs-exports"
        out.mkdir(parents=True, exist_ok=True)
        payload = '{"ts":"x"}\n'
        (out / f"{day}.ndjson").write_text(payload, encoding="utf-8")
        self.assertFalse(day_verified(day, out), "no manifest yet")
        import hashlib
        import json

        manifest = {
            "day": day,
            "rows": 1,
            "sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "verified": True,
        }
        (out / f"{day}.manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        self.assertTrue(day_verified(day, out))
        # a byte flipped -> checksum fails -> the day is NOT sweepable
        (out / f"{day}.ndjson").write_text(payload + "extra\n", encoding="utf-8")
        self.assertFalse(day_verified(day, out))

    def test_sync_dir_follows_runs_env(self) -> None:
        self.assertEqual(sync_dir(), self.runs_dir / "logs-exports")

    def test_delete_subject_rewrites_fallback_and_audits(self) -> None:
        """Guardian deletion (ADR-0025 §4b): the subject's rows leave the
        fallback files; one L3 privacy.subject_deleted event (IDs only)."""
        from logging_manager import delete_subject

        session = "0d0c8b2e-1111-4222-8333-444455556666"
        logs = self.runs_dir / "logs"
        write_jsonl(
            logs / "20261108-voice.jsonl",
            [
                {
                    "ts": "2026-11-08T10:00:00.000Z",
                    "schema_version": 1,
                    "severity": "INFO",
                    "event": "voice.turn.e2e_latency",
                    "component": "voice",
                    "env": "dev",
                    "session_id": session,
                    "latency_ms": 3300,
                    "fields": {},
                },
                {
                    "ts": "2026-11-08T10:00:01.000Z",
                    "schema_version": 1,
                    "severity": "INFO",
                    "event": "voice.turn.e2e_latency",
                    "component": "voice",
                    "env": "dev",
                    "session_id": "other-subject",
                    "latency_ms": 3400,
                    "fields": {},
                },
            ],
        )
        summary = delete_subject(session)
        path = logs / "20261108-voice.jsonl"
        remaining = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(remaining), 1)
        self.assertIn("other-subject", remaining[0])
        self.assertEqual(summary["session_count"], 1)
        self.assertIn("fallback", summary["stores_touched"])
        self.assertEqual(summary["status"], "ok")
        self.assertTrue(summary["ok"])
        audit = self.last_event("privacy.subject_deleted")
        self.assertEqual(audit["component"], "privacy")
        self.assertEqual(audit["fields"]["session_count"], 1)
        self.assertEqual(audit["fields"]["status"], "ok")
        self.assertEqual(audit["session_id"], session)

    def test_delete_subject_surfaced_when_postgres_fails(self) -> None:
        """A hot-store failure must be surfaced (status failed + audit
        carries the error), never returned as success — otherwise the
        guardian 24 h SLA is missed invisibly."""
        import sys
        import unittest.mock

        from logging_manager import delete_subject

        session = "0d0c8b2e-1111-4222-8333-444455556666"
        os.environ["ZIVON_LOG_DSN"] = "postgresql://fake/fake"
        try:
            with unittest.mock.patch.dict(
                sys.modules,
                {
                    "psycopg": unittest.mock.Mock(
                        connect=unittest.mock.Mock(side_effect=RuntimeError("db down"))
                    )
                },
            ):
                summary = delete_subject(session)
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["ok"])
            self.assertIn("db down", summary["error"])
            self.assertNotIn("hot", summary["stores_touched"])
            audit = self.last_event("privacy.subject_deleted")
            self.assertEqual(audit["fields"]["status"], "failed")
            self.assertEqual(audit["severity"], "ERROR")
        finally:
            os.environ.pop("ZIVON_LOG_DSN", None)


class JsonlDeletionIsolationTests(ObservabilityTest):
    def test_remove_session_handles_missing_dir(self) -> None:
        self.assertEqual(
            sink._JsonlSink(str(self.runs_dir / "none")).remove_session("s"), 0
        )


if __name__ == "__main__":
    unittest.main()
