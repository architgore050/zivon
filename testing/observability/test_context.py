"""Context propagation (logging-api.md §3): contextvars helpers, async +
threaded propagation, the §7 header receive/propagate rules."""

from __future__ import annotations

import asyncio
import threading
import unittest
import uuid

from logging_manager import bind_context, context_scope, current_context
from logging_manager.context import (
    bind_from_headers,
    correlation_headers,
    get_id,
    new_request_id,
)

from .support import ContextIsolated


class ContextHelperTests(ContextIsolated):
    def test_bind_and_read(self) -> None:
        bind_context(run_id="motion-c9")
        self.assertEqual(current_context()["run_id"], "motion-c9")
        self.assertEqual(get_id("run_id"), "motion-c9")
        self.assertIsNone(get_id("session_id"))

    def test_bind_merges_not_replaces(self) -> None:
        bind_context(run_id="motion-c9")
        bind_context(session_id=str(uuid.uuid4()))
        ctx = current_context()
        self.assertEqual(ctx["run_id"], "motion-c9")
        self.assertIn("session_id", ctx)

    def test_unknown_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            bind_context(bogus_id="x")

    def test_scope_overrides_then_restores(self) -> None:
        bind_context(request_id="outer")
        with context_scope(request_id="inner"):
            self.assertEqual(current_context()["request_id"], "inner")
        self.assertEqual(current_context()["request_id"], "outer")

    def test_current_context_is_a_snapshot(self) -> None:
        bind_context(run_id="r1")
        snapshot = current_context()
        bind_context(run_id="r2")
        self.assertEqual(snapshot["run_id"], "r1")


class AsyncTests(ContextIsolated):
    def test_tasks_inherit_and_scopes_do_not_leak(self) -> None:
        bind_context(run_id="motion-c9")

        async def inner() -> str:
            with context_scope(turn_id="t-1"):
                await asyncio.sleep(0)
            return current_context().get("run_id", "?")

        async def main() -> tuple[str, str]:
            task = asyncio.create_task(inner())
            with context_scope(request_id="req-edge"):
                await asyncio.sleep(0)
                edge = current_context()["request_id"]
            return await task, edge

        child_run, edge = asyncio.run(main())
        self.assertEqual(child_run, "motion-c9")
        self.assertEqual(edge, "req-edge")

    def test_parallel_tasks_are_isolated(self) -> None:
        results: dict[str, str] = {}

        async def worker(name: str, scope_id: str) -> None:
            with context_scope(request_id=scope_id):
                await asyncio.sleep(0.01)
                results[name] = current_context()["request_id"]

        async def main() -> None:
            await asyncio.gather(worker("a", "req-a"), worker("b", "req-b"))

        asyncio.run(main())
        self.assertEqual(results["a"], "req-a")
        self.assertEqual(results["b"], "req-b")


class ThreadTests(ContextIsolated):
    def test_threads_have_isolated_contexts(self) -> None:
        """Factory stages run on threads. Threads do NOT inherit the spawner's
        context (stdlib semantics: each thread starts with an empty context) —
        which is exactly why factory/llm.py passes run_id explicitly and the
        spec says 'a new pipeline stage binds fresh'. Within a thread the
        helpers behave like anywhere else."""
        seen: dict[str, str | None] = {}

        def work() -> None:
            seen["initial_run_id"] = current_context().get("run_id")
            bind_context(run_id="thread-run")
            with context_scope(request_id="req-thread"):
                seen["in_scope"] = current_context()["request_id"]
            seen["after_scope"] = current_context().get("run_id")

        bind_context(run_id="spawner-run")
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertIsNone(seen["initial_run_id"])
        self.assertEqual(seen["in_scope"], "req-thread")
        self.assertEqual(seen["after_scope"], "thread-run")
        # the spawner's binding is untouched
        self.assertEqual(current_context()["run_id"], "spawner-run")


class HeaderTests(ContextIsolated):
    def test_correlation_headers_from_context(self) -> None:
        bind_context(
            request_id="0d0c8b2e-1111-4222-8333-444455556666", run_id="motion-c9"
        )
        headers = correlation_headers()
        self.assertEqual(
            headers["X-Request-Id"], "0d0c8b2e-1111-4222-8333-444455556666"
        )
        self.assertEqual(headers["X-Zivon-Run-Id"], "motion-c9")
        self.assertNotIn("X-Zivon-Session-Id", headers)

    def test_inbound_valid_ids_are_accepted(self) -> None:
        request_id = str(uuid.uuid4())
        got = bind_from_headers(
            {"X-Request-Id": request_id.upper(), "X-Zivon-Run-Id": "motion-c9"}
        )
        self.assertEqual(got, request_id.lower())
        self.assertEqual(current_context()["run_id"], "motion-c9")

    def test_inbound_malformed_ids_are_regenerated(self) -> None:
        got = bind_from_headers({"X-Request-Id": "not-a-uuid"})
        self.assertNotEqual(got, "not-a-uuid")
        self.assertRegex(got, r"^[0-9a-f-]{36}$")
        self.assertNotIn("run_id", current_context())

    def test_inbound_absent_id_is_generated(self) -> None:
        got = bind_from_headers({})
        self.assertRegex(got, r"^[0-9a-f-]{36}$")

    def test_uuid_shape_check_rejects_wrong_version_shape(self) -> None:
        got = bind_from_headers(
            {"X-Zivon-Session-Id": "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"}
        )
        self.assertNotIn("session_id", current_context())
        self.assertTrue(got)

    def test_new_request_id_is_a_uuid(self) -> None:
        self.assertRegex(new_request_id(), r"^[0-9a-f-]{36}$")


if __name__ == "__main__":
    unittest.main()
