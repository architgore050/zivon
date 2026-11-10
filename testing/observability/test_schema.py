"""JSON line schema conformance (logging-api.md §4): field order, types,
ms-precision ts, order-insensitivity of `fields`, schema_version, the
closed enums, and dev-mode programmer errors."""

from __future__ import annotations

import json
import os
import re
import unittest
from datetime import datetime
from typing import Any

from logging_manager import LOG_SCHEMA_VERSION, ErrorClass, Severity, sink
from logging_manager import events as ev

from .support import ObservabilityTest

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
FIELD_ORDER = [
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
    "client_session_id",
    "stage",
    "latency_ms",
    "error_class",
    "fields",
    "trace_id",
    "span_id",
]


class SchemaShapeTests(ObservabilityTest):
    def test_line_is_compact_utf8_json_with_fixed_field_order(self) -> None:
        line = sink.serialize(
            {
                "ts": "2026-11-09T09:41:07.412Z",
                "schema_version": 1,
                "severity": "INFO",
                "event": "factory.stage.ok",
                "component": "factory",
                "env": "cluster",
                "run_id": "motion-c9",
                "stage": "03-check",
                "latency_ms": 51230,
                "fields": {"elapsed_s": 51.2, "blocks": 14},
            }
        )
        self.assertNotIn(", ", line)
        self.assertEqual(
            list(json.loads(line).keys()),
            [
                key
                for key in FIELD_ORDER
                if key
                not in (
                    "session_id",
                    "turn_id",
                    "request_id",
                    "client_session_id",
                    "error_class",
                    "trace_id",
                    "span_id",
                )
            ],
        )
        self.assertEqual(
            json.dumps(json.loads(line), separators=(",", ":"), ensure_ascii=False),
            line,
        )

    def test_absent_fields_are_omitted_never_empty_strings(self) -> None:
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
        record = self.last_event("factory.stage.ok")
        for absent in ("session_id", "turn_id", "request_id", "error_class"):
            self.assertNotIn(absent, record)
        self.assertEqual(record["fields"], {"blocks": 0, "attempts": 0})

    def test_ts_is_utc_ms_precision(self) -> None:
        sink.log_event("factory.stage.ok", {"blocks": 1, "attempts": 1})
        ts = self.last_event("factory.stage.ok")["ts"]
        self.assertRegex(ts, _TS_RE)
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")

    def test_schema_version_is_one(self) -> None:
        self.assertEqual(LOG_SCHEMA_VERSION, 1)
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
        self.assertEqual(self.last_event("factory.stage.ok")["schema_version"], 1)

    def test_env_from_zivon_env_default_dev(self) -> None:
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
        self.assertEqual(self.last_event("factory.stage.ok")["env"], "dev")
        os.environ["ZIVON_ENV"] = "cluster"
        try:
            sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
            self.assertEqual(self.last_event("factory.stage.ok")["env"], "cluster")
        finally:
            os.environ.pop("ZIVON_ENV")
        os.environ["ZIVON_ENV"] = "bogus"
        try:
            sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
            self.assertEqual(self.last_event("factory.stage.ok")["env"], "dev")
        finally:
            os.environ.pop("ZIVON_ENV")

    def test_fields_order_insensitive(self) -> None:
        sink.log_event("factory.stage.ok", {"b": 1, "a": 2})
        sink.log_event("factory.stage.ok", {"a": 2, "b": 1})
        self.assertEqual(
            self.of_event("factory.stage.ok")[0]["fields"],
            self.of_event("factory.stage.ok")[1]["fields"],
        )

    def test_component_from_map_row(self) -> None:
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0})
        self.assertEqual(self.last_event("factory.stage.ok")["component"], "factory")

    def test_client_session_id_rides_context(self) -> None:
        from logging_manager import bind_context

        bind_context(client_session_id="0f0e1d2c-3b4a-5968-8796-a5b4c3d2e1f0")
        sink.log_event("frontend.heartbeat", {})
        record = self.last_event("frontend.heartbeat")
        self.assertEqual(record["component"], "frontend")
        self.assertIn("client_session_id", record)


class ClosedVocabularyTests(unittest.TestCase):
    def test_severity_names_match_stdlib(self) -> None:
        self.assertEqual(
            [s.value for s in Severity],
            ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        )

    def test_error_class_is_the_spec_closed_enum(self) -> None:
        self.assertEqual(
            sorted(e.value for e in ErrorClass),
            sorted(
                [
                    "transport_error",
                    "validation_error",
                    "gate_fail",
                    "repair_exhausted",
                    "infra_error",
                    "quota_error",
                    "auth_error",
                    "client_error",
                    "privacy_violation",
                    "store_error",
                ]
            ),
        )


class DevModeErrorTests(ObservabilityTest):
    def setUp(self) -> None:
        super().setUp()
        os.environ["ZIVON_LOG_LEVEL"] = "DEBUG"

    def tearDown(self) -> None:
        os.environ.pop("ZIVON_LOG_LEVEL")
        super().tearDown()

    def test_unknown_event_raises_in_dev(self) -> None:
        with self.assertRaises(ValueError):
            sink.log_event("not.in.the.map.event", {})

    def test_unknown_error_class_raises_in_dev(self) -> None:
        bad_class: Any = "not_a_class"  # deliberately outside the closed enum
        with self.assertRaises(ValueError):
            sink.log_event(
                "factory.stage.ok", {"blocks": 0, "attempts": 0}, error_class=bad_class
            )

    def test_negative_latency_raises_in_dev(self) -> None:
        with self.assertRaises(ValueError):
            sink.log_event(
                "factory.stage.ok", {"blocks": 0, "attempts": 0}, latency_ms=-1
            )

    def test_events_validate_map_values_in_dev(self) -> None:
        row = ev.known_event("factory.stage.ok")
        self.assertIsNotNone(row)
        self.assertEqual(row.severity, "INFO")  # type: ignore[union-attr]


class NeverRaisesTests(ObservabilityTest):
    def test_delivery_never_raises_outside_dev_mode(self) -> None:
        # garbage payload, bad error class, bad latency: all delivered, none raised
        bad_class: Any = "bogus"  # deliberately outside the closed enum
        sink.log_event("factory.stage.ok", {"weird": object()})
        sink.log_event(
            "factory.stage.ok", {"blocks": 0, "attempts": 0}, error_class=bad_class
        )
        sink.log_event("factory.stage.ok", {"blocks": 0, "attempts": 0}, latency_ms=-5)
        self.assertEqual(len(self.of_event("factory.stage.ok")), 3)

    def test_unknown_event_is_delivered_and_flagged(self) -> None:
        sink.log_event("some.unknown.event", {"k": 1})
        self.assertEqual(self.last_event("some.unknown.event")["fields"], {"k": 1})
        unknown = self.last_event("log.event_unknown")
        self.assertEqual(unknown["fields"], {"offender_event": "some.unknown.event"})


class LevelFilterTests(ObservabilityTest):
    def test_debug_filtered_at_default_info(self) -> None:
        sink.log_event(
            "factory.stage.ok", {"blocks": 0, "attempts": 0}, severity=Severity.DEBUG
        )
        self.assertEqual(self.of_event("factory.stage.ok"), [])

    def test_debug_kept_when_level_debug(self) -> None:
        os.environ["ZIVON_LOG_LEVEL"] = "DEBUG"
        try:
            sink.log_event(
                "factory.stage.ok",
                {"blocks": 0, "attempts": 0},
                severity=Severity.DEBUG,
            )
        finally:
            os.environ.pop("ZIVON_LOG_LEVEL")
        self.assertEqual(len(self.of_event("factory.stage.ok")), 1)

    def test_warning_kept_at_default_info(self) -> None:
        sink.log_event("log.store_fallback", {"dsn_set": False, "target_path": "x"})
        self.assertEqual(len(self.of_event("log.store_fallback")), 1)


if __name__ == "__main__":
    unittest.main()
