"""MockTimbre — scriptable TTS double (spec.md §13 test seams).

Returns deterministic audio bytes per prepared segment, records everything
the real client would bill, and can fail on demand (F4):

    tts = MockTimbre(fail=True)          # TtsUnavailableError on speak
    tts = MockTimbre()                   # audio frames + segment_end marker
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace

from voice.config import VoiceSettings
from voice.tts_client import TtsAudio, TtsUnavailableError

__all__ = ["MockTimbre"]


class MockTimbre:
    def __init__(
        self,
        settings: VoiceSettings | None = None,
        *,
        fail: bool = False,
        frames_per_segment: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or VoiceSettings()
        self.fail = fail
        self.frames_per_segment = frames_per_segment
        self.clock = clock
        self.spoken: list[str] = []
        self.segment_ids: list[int] = []
        self.kinds: list[str] = []
        self.closed = False
        self.aborted = False
        self.chars_billed = 0
        # the real client exposes per-turn meters; the mock mirrors the shape
        self.meters = SimpleNamespace(chars_billed=self.chars_billed)

    async def start_turn(self) -> None:
        if self.fail:
            raise TtsUnavailableError("mock: Timbre unreachable")

    async def speak(
        self, text: str, segment_id: int, kind: str = "speech"
    ) -> AsyncIterator[TtsAudio]:
        if self.fail:
            raise TtsUnavailableError("mock: Timbre unreachable")
        self.spoken.append(text)
        self.segment_ids.append(segment_id)
        self.kinds.append(kind)
        self.chars_billed += len(text)
        self.meters.chars_billed = self.chars_billed
        for index in range(self.frames_per_segment):
            # deterministic fake opus frame; nothing audio-shaped is stored
            yield TtsAudio(data=bytes([segment_id % 256, index]), final=False)
        yield TtsAudio(data=b"", final=True)

    async def close_turn(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    async def abort(self) -> None:
        """Barge-in seam (the real client drains the cancelled segment)."""
        self.aborted = True

    def last_request(self) -> dict[str, object]:
        return {
            "text": self.spoken[-1] if self.spoken else "",
            "segment_id": self.segment_ids[-1] if self.segment_ids else 0,
        }
