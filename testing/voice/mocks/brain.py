"""MockBrain — scriptable brain-stream double (spec.md §13 test seams).

Produces the same event stream shape the real transports normalize into
(``voice.brain_client.RawChunk``) with controllable timing, so reliability
budgets are tested without network:

    brain = MockBrain(content="REF: b1\\nAnswer sentence one.\\nAnd two.")
    client = BrainClient(settings, brain.factory())
    async for event in client.stream(brain.request("sawaal")): ...

Scripting knobs: ``delay_before_first_s`` (first-event deadline),
``stall_after_chunks`` (inactivity), ``thoughts`` (OQ-04-style summaries),
``usage``, ``fail_times`` (HTTP failures), ``hang_forever`` (wall-clock +
abort paths). ``closed`` records that the upstream saw the stream torn down
(barbe-in abort frees the server slot — ADR-0017 semantics).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field

from voice.brain_client import (
    BrainHTTPError,
    BrainMessage,
    BrainRequest,
    RawChunk,
    TokenUsage,
)

__all__ = ["MockBrain"]


def _word_deltas(line: str) -> list[str]:
    """Split a scripted line into transport-sized deltas (words + spaces)."""
    if not line:
        return []
    parts = line.split(" ")
    return [part + " " for part in parts[:-1]] + [parts[-1]]


@dataclass
class MockBrain:
    content: str = ""
    thoughts: list[str] = field(default_factory=list)
    usage: TokenUsage | None = None
    chunk_delay_s: float = 0.0
    delay_before_first_s: float = 0.0
    stall_after_chunks: int | None = None  # then hang (inactivity budget fires)
    fail_times: int = 0  # raise BrainHTTPError(502) for the first N opens
    hang_forever: bool = False  # never emits; tests the wall-clock/abort paths
    clock: Callable[[], float] = time.monotonic

    # introspection for tests
    opens: int = 0
    closed: bool = False
    last_messages: list[BrainMessage] = field(default_factory=list)
    yield_log: list[str] = field(default_factory=list)  # interleaving evidence

    def request(
        self, transcript: str, history: tuple[BrainMessage, ...] = ()
    ) -> BrainRequest:
        return BrainRequest(
            system="system prompt", history=history, transcript=transcript
        )

    def factory(self) -> Callable[[list[BrainMessage]], AsyncGenerator[RawChunk, None]]:
        async def factory(
            messages: list[BrainMessage],
        ) -> AsyncGenerator[RawChunk, None]:
            self.last_messages = list(messages)
            self.opens += 1
            if self.opens <= self.fail_times:
                raise BrainHTTPError(502, "mock: bad gateway", retryable=True)
            try:
                if self.hang_forever:
                    await asyncio.sleep(3600)  # the client's deadlines fire first
                    return
                if self.delay_before_first_s:
                    await asyncio.sleep(self.delay_before_first_s)
                if self.thoughts:
                    for thought in self.thoughts:
                        self.yield_log.append(f"thought:{thought}")
                        yield RawChunk(thought=thought)
                        if self.chunk_delay_s:
                            await asyncio.sleep(self.chunk_delay_s)
                lines = self.content.split("\n") if self.content else []
                for index, line in enumerate(lines):
                    if (
                        self.stall_after_chunks is not None
                        and index >= self.stall_after_chunks
                    ):
                        await asyncio.sleep(3600)  # inactivity budget must fire
                        return
                    self.yield_log.append(f"content:{line}")
                    # realistic transport shape (Gemini/OpenRouter): the words
                    # of a line arrive as deltas with NO newline; the newline
                    # is a separate chunk after the line. A parser that waits
                    # for "\n" therefore starves the chunker (first-audio bug).
                    for token in _word_deltas(line):
                        yield RawChunk(content=token)
                        if self.chunk_delay_s:
                            await asyncio.sleep(self.chunk_delay_s)
                    if index < len(lines) - 1:
                        yield RawChunk(content="\n")
                        if self.chunk_delay_s:
                            await asyncio.sleep(self.chunk_delay_s)
                if self.usage is not None:
                    yield RawChunk(usage=self.usage)
            except (asyncio.CancelledError, GeneratorExit):
                self.closed = True  # abort()/barge-in closed the upstream
                raise

        return factory
