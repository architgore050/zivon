"""Shared helpers for the observability test set (EX3-OBS).

The logging sink writes stdout on every event; tests capture events by
temporarily swapping the stdout writer (the module-level seam) and resetting
all sink state per test so env leakage cannot cross tests.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from logging_manager import sink
from logging_manager.context import _CONTEXT as _LOG_CONTEXT


class ObservabilityTest(unittest.TestCase):
    """Base: isolated sink state + a temp runs dir per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.runs_dir = Path(self._tmp.name)
        self.events: list[dict[str, Any]] = []
        sink.reset_for_tests(runs_dir=str(self.runs_dir))
        reset_context()
        # Pre-engage the JSONL fallback so tests count ONLY their own events
        # (the very first emission would otherwise add a log.store_fallback
        # switch event to the stream).
        sink._mark_degraded(dsn_set=False)
        self.events.clear()
        self._original_stdout_writer = sink._write_stdout
        sink._write_stdout = self._collect

    def tearDown(self) -> None:
        sink._write_stdout = self._original_stdout_writer
        sink.reset_for_tests()
        self._tmp.cleanup()

    def _collect(self, line: str) -> None:
        parsed = sink.parse_line(line)
        if parsed is not None:
            self.events.append(parsed)

    def of_event(self, name: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["event"] == name]

    def last_event(self, name: str) -> dict[str, Any]:
        matches = self.of_event(name)
        assert matches, (
            f"no {name} event emitted; got {[e['event'] for e in self.events]}"
        )
        return matches[-1]


def reset_context() -> None:
    """Correlation context isolation for tests (contextvars persist across
    tests within a thread — clear them)."""
    _LOG_CONTEXT.set({})


class ContextIsolated(unittest.TestCase):
    """Base for tests that assert exact context state."""

    def setUp(self) -> None:
        reset_context()

    def tearDown(self) -> None:
        reset_context()


@contextmanager
def capture_events() -> Any:
    """Collect the JSON lines log_event writes to stdout, as parsed records."""
    collected: list[dict[str, Any]] = []
    original = sink._write_stdout

    def collect(line: str) -> None:
        parsed = sink.parse_line(line)
        if parsed is not None:
            collected.append(parsed)

    sink._write_stdout = collect
    try:
        yield collected
    finally:
        sink._write_stdout = original


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(
                json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
