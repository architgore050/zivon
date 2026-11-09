"""MockPrisma — scriptable in-memory STT double (spec.md §13 test seams).

Implements the same surface as ``voice.stt_client.SttClient`` so ws_api tests
run key-free and network-free. Script the event stream, then feed frames:

    stt = MockPrisma(partials=["yeh"], final_text="yeh kya hai?")
    await stt.start(); await stt.send_audio(b"...")
    await stt.finish(); event = await stt.next_event()  # partials, then final

Failure scripting: ``fail_connect=True`` → SttUnavailableError on start (F1);
``die_after=<n events>`` → the stream ends early.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from voice.config import VoiceSettings
from voice.stt_client import SttEvent, SttUnavailableError

__all__ = ["MockPrisma"]


class MockPrisma:
    def __init__(
        self,
        settings: VoiceSettings | None = None,
        *,
        partials: list[str] | None = None,
        final_text: str = "",
        final_lang: str = "hi-en",
        final_confidence: float = 0.93,
        fail_connect: bool = False,
        die_after: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or VoiceSettings()
        self._script: list[SttEvent] = []
        for text in partials or []:
            self._script.append(SttEvent(kind="partial", text=text, seq=0))
        if final_text:
            self._script.append(
                SttEvent(
                    kind="final",
                    text=final_text,
                    seq=0,
                    lang=final_lang,
                    confidence=final_confidence,
                )
            )
        self._fail_connect = fail_connect
        self._die_after = die_after
        self._clock = clock
        self._cursor = 0
        self._started = False
        self._finished = False
        self._closed = False
        self.audio_seconds = 0.0
        self.frames_received = 0
        self.echo_guard_until = 0.0
        self.dropped_echo = 0
        self.reconnects = 0
        self.sent_final = False

    async def start(self) -> None:
        if self._fail_connect:
            raise SttUnavailableError("mock: Prisma unreachable")
        self._started = True

    async def send_audio(self, pcm: bytes) -> None:
        if not self._started or self._closed:
            raise SttUnavailableError("mock: not streaming")
        self.frames_received += 1
        self.audio_seconds += len(pcm) / 2 / self.settings.stt_sample_rate

    async def finish(self) -> None:
        self._finished = True

    def arm_echo_guard(self, duration_ms: int | None = None) -> None:
        ms = self.settings.echo_guard_ms if duration_ms is None else duration_ms
        self.echo_guard_until = max(self.echo_guard_until, self._clock() + ms / 1000.0)

    async def next_event(self) -> SttEvent | None:
        if not self._started or self._closed:
            return None
        if self._die_after is not None and self._cursor >= self._die_after:
            return None  # upstream died: caller sees an honest early end
        if self._cursor >= len(self._script):
            return None
        event = self._script[self._cursor]
        self._cursor += 1
        if self._clock() < self.echo_guard_until:
            self.dropped_echo += 1
            return await self.next_event()
        if event.kind == "final":
            self.sent_final = True
        return event

    async def close(self) -> None:
        self._closed = True
