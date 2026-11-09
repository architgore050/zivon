"""Unit tests for voice.brain_client (spec.md §13 test table).

No network: MockBrain's factory is injected; the timing knobs are real
asyncio sleeps scaled down so the reliability budgets are exercised exactly
as configured (settings knobs set to test-scale seconds).
"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import AsyncIterator

from testing.voice.mocks.brain import MockBrain
from voice.brain_client import (
    BrainClient,
    BrainDeadlineError,
    BrainEvent,
    BrainFirstEventTimeout,
    BrainHTTPError,
    BrainMessage,
    BrainRequest,
    BrainStallError,
    BrainTransportError,
    RawChunk,
    TokenUsage,
    build_messages,
)
from voice.config import VoiceSettings


def _settings(**overrides: object) -> VoiceSettings:
    defaults: dict[str, object] = {
        "brain_first_event_s": 0.3,
        "brain_inactivity_s": 0.3,
        "brain_turn_deadline_s": 1.0,
        "brain_max_retries": 2,
        "brain_first_event_retries": 1,
    }
    defaults.update(overrides)
    return VoiceSettings(**defaults)  # type: ignore[arg-type]


async def collect(client: BrainClient, request: BrainRequest) -> list[BrainEvent]:
    return [event async for event in client.stream(request)]


class StreamParsingTest(unittest.IsolatedAsyncioTestCase):
    async def test_ref_line_parsed_and_stripped_from_content(self) -> None:
        mock = MockBrain(content="REF: b1,b2\nYeh formula dekho.")
        client = BrainClient(_settings(), mock.factory())
        events = await collect(client, mock.request("sawaal"))  # type: ignore[arg-type]
        refs = [e for e in events if e.kind == "ref"]
        contents = [e for e in events if e.kind == "content"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].ref_ids, ("b1", "b2"))
        joined = "".join(e.text for e in contents)
        self.assertNotIn("REF:", joined)
        self.assertIn("Yeh formula dekho.", joined)

    async def test_marker_summaries_extracted_as_summary_events(self) -> None:
        mock = MockBrain(content=">> sawaal yaad kar raha hoon\nAb dekhte hain.")
        client = BrainClient(_settings(), mock.factory())
        events = await collect(client, mock.request("sawaal"))  # type: ignore[arg-type]
        summaries = [e for e in events if e.kind == "summary"]
        contents = "".join(e.text for e in events if e.kind == "content")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].text, "sawaal yaad kar raha hoon")
        self.assertNotIn(">>", contents)
        self.assertIn("Ab dekhte hain.", contents)

    async def test_thought_events_surfaced_when_transport_reports(self) -> None:
        mock = MockBrain(thoughts=["let me recall the question"], content="Answer.")
        client = BrainClient(_settings(), mock.factory())
        events = await collect(client, mock.request("q"))  # type: ignore[arg-type]
        thoughts = [e for e in events if e.kind == "thought"]
        self.assertEqual(
            thoughts, [BrainEvent(kind="thought", text="let me recall the question")]
        )

    async def test_usage_capture_and_done(self) -> None:
        mock = MockBrain(content="Answer.", usage=TokenUsage(10, 5, 2))
        client = BrainClient(_settings(), mock.factory())
        events = await collect(client, mock.request("q"))  # type: ignore[arg-type]
        usage = [e for e in events if e.kind == "usage"]
        self.assertEqual(usage[-1].usage, TokenUsage(10, 5, 2))
        self.assertEqual(events[-1].kind, "done")

    async def test_cumulative_usage_not_flooded(self) -> None:
        async def factory(messages: list[BrainMessage]) -> AsyncIterator[RawChunk]:
            for _ in range(3):
                yield RawChunk(content="x", usage=TokenUsage(1, 1))
            yield RawChunk(content="x", usage=TokenUsage(1, 3))

        client = BrainClient(_settings(), factory)  # type: ignore[arg-type]
        events = await collect(client, BrainRequest(system="s", transcript="q"))
        usage_events = [e for e in events if e.kind == "usage"]
        self.assertEqual(len(usage_events), 2)  # emitted on change, not per chunk

    async def test_build_messages_shape_and_history_window(self) -> None:
        history = (
            BrainMessage("user", "pehla sawaal"),
            BrainMessage("assistant", "pehla jawab"),
        )
        messages = build_messages(
            BrainRequest(
                system="sys", context_block="CTX", history=history, transcript="naya"
            )
        )
        self.assertEqual(messages[0].role, "system")
        self.assertEqual([m.role for m in messages[1:]], ["user", "assistant", "user"])
        self.assertIn("PAGE CONTEXT", messages[-1].content)
        self.assertIn("STUDENT SAID: naya", messages[-1].content)
        self.assertIn("CTX", messages[-1].content)

    async def test_openrouter_usage_null_is_tolerated(self) -> None:
        # OpenRouter may report usage: null (known node caveat) — the client
        # must still stream content and land latency metrics, not crash.
        async def factory(messages: list[BrainMessage]) -> AsyncIterator[RawChunk]:
            yield RawChunk(content="hello ")

        client = BrainClient(_settings(), factory)  # type: ignore[arg-type]
        events = await collect(client, BrainRequest(system="s", transcript="q"))
        self.assertEqual(
            "".join(e.text for e in events if e.kind == "content"), "hello \n"
        )


class ReliabilityBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_event_deadline_fires_then_retry_then_f2(self) -> None:
        mock = MockBrain(delay_before_first_s=0.6)  # > 0.3 s deadline, both tries
        client = BrainClient(_settings(), mock.factory())
        with self.assertRaises(BrainFirstEventTimeout):
            await collect(client, mock.request("q"))  # type: ignore[arg-type]
        self.assertEqual(mock.opens, 2)  # initial attempt + its one retry

    async def test_first_event_retry_succeeds(self) -> None:
        state = {"opens": 0}

        async def factory(messages: list[BrainMessage]) -> AsyncIterator[RawChunk]:
            state["opens"] += 1
            if state["opens"] == 1:
                await asyncio.sleep(0.6)  # breach the 0.3 s first-event budget
                return
            yield RawChunk(content="fast answer\n")

        client = BrainClient(_settings(), factory)  # type: ignore[arg-type]
        events = await collect(client, BrainRequest(system="s", transcript="q"))
        self.assertEqual(state["opens"], 2)
        self.assertTrue(
            any(e.kind == "content" and "fast answer" in e.text for e in events)
        )
        self.assertEqual(client.retries_used, 1)

    async def test_inactivity_stall_fires_f3(self) -> None:
        mock = MockBrain(content="line one\nline two\nline three", stall_after_chunks=1)
        client = BrainClient(_settings(), mock.factory())
        with self.assertRaises(BrainStallError):
            await collect(client, mock.request("q"))  # type: ignore[arg-type]

    async def test_wall_clock_deadline_closes_mid_stream(self) -> None:
        mock = MockBrain(hang_forever=True)
        client = BrainClient(
            _settings(brain_turn_deadline_s=0.2, brain_first_event_s=10.0),
            mock.factory(),
        )
        with self.assertRaises(BrainDeadlineError):
            await collect(client, mock.request("q"))  # type: ignore[arg-type]

    async def test_transport_error_retries_then_raises(self) -> None:
        mock = MockBrain(fail_times=3)  # more failures than the retry budget
        client = BrainClient(_settings(), mock.factory())
        with self.assertRaises(BrainHTTPError):
            await collect(client, mock.request("q"))  # type: ignore[arg-type]
        self.assertEqual(mock.opens, 3)  # initial + 2 retries

    async def test_no_retry_after_events_reached_consumer(self) -> None:
        # speech already started (an event was yielded): a stall must NOT
        # retry — it raises so the caller degrades (spec.md §4 retry table).
        mock = MockBrain(content="spoken line\n", stall_after_chunks=1)
        client = BrainClient(_settings(), mock.factory())
        events: list[BrainEvent] = []
        with self.assertRaises(BrainStallError):
            async for event in client.stream(mock.request("q")):  # type: ignore[arg-type]
                events.append(event)
        self.assertTrue(events)  # something was spoken
        self.assertEqual(mock.opens, 1)  # no second attempt
        self.assertEqual(client.retries_used, 0)

    async def test_abort_closes_upstream_mid_stream(self) -> None:
        mock = MockBrain(hang_forever=True)
        client = BrainClient(
            _settings(brain_turn_deadline_s=30, brain_first_event_s=10.0),
            mock.factory(),
        )

        async def consume() -> list[BrainEvent]:
            return await collect(client, mock.request("q"))  # type: ignore[arg-type]

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())  # still streaming (hung upstream)
        await client.abort()  # barge-in: close the upstream now
        with self.assertRaises((asyncio.CancelledError, BrainTransportError)):
            await asyncio.wait_for(task, timeout=1.0)
        self.assertTrue(mock.closed)  # upstream saw the close (slot freed)
