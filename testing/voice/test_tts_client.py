"""Unit tests for voice.tts_client (spec.md §13 test table).

Mock Timbre: tag whitelist (13 v3 tags → allowed subset), tag caps (H3),
char cap + closing line, char meter (tags bill as characters), audio frame
flow, F4 failure path.
"""

from __future__ import annotations

import unittest
from typing import Any

from testing.voice.mocks.timbre import MockTimbre
from voice.config import VoiceSettings
from voice.tts_client import (
    ALLOWED_TAGS,
    TtsAudio,
    TtsClient,
    TtsTransport,
    TtsUnavailableError,
)


class FakeTimbreTransport:
    """In-memory TtsTransport: speaks back one segment_end per request."""

    def __init__(self, auto_queue: bool = True) -> None:
        self.sent: list[str | bytes] = []
        self.replies: list[str | bytes] = []
        self.closed = False
        self.auto_queue = auto_queue

    def queue_segment(self, frames: int = 2) -> None:
        self.replies.extend([b"\x00" * 40] * frames + ['{"type": "segment_end"}'])

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if self.auto_queue and isinstance(data, str) and '"type": "speak"' in data:
            # real Timbre pushes frames as they synthesize; the fake queues
            # replies eagerly so speak() can drain them
            self.queue_segment()

    async def recv(self) -> str | bytes:
        if not self.replies:
            raise ConnectionError("mock: stream closed")
        return self.replies.pop(0)

    async def close(self) -> None:
        self.closed = True


def _client(**kw: Any) -> tuple[TtsClient, FakeTimbreTransport]:
    settings = VoiceSettings(
        tts_url="wss://timbre.example", gnani_tts_api_key="k", **kw
    )  # type: ignore[arg-type]
    transport = FakeTimbreTransport()

    async def connect() -> TtsTransport:
        return transport

    return TtsClient(settings, connect), transport


async def _drain(client: TtsClient, text: str, segment_id: int = 1) -> list[TtsAudio]:
    return [audio async for audio in client.speak(text, segment_id)]


class TagWhitelistTest(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_subset_spoken(self) -> None:
        client, transport = _client()
        await client.start_turn()
        frames = await _drain(client, "Dekho <pauses> yeh <slow> concept hai.")
        sent = [s for s in transport.sent if isinstance(s, str)]
        self.assertEqual(len(frames), 3)  # 2 audio + final
        self.assertIn("<pauses>", sent[-1])  # one cue allowed for the chunk
        self.assertNotIn("<slow>", sent[-1])  # ratio: 1 sentence → 1 tag

    async def test_unknown_and_non_whitelisted_tags_stripped(self) -> None:
        client, _ = _client()
        prepared = client.prepare(
            "Haha <laugh> aur <clears throat> dekho <whispers> yeh."
        )
        self.assertNotIn("<laugh>", prepared.text)
        self.assertNotIn("<clears throat>", prepared.text)
        self.assertIn("<whispers>", prepared.text)
        self.assertEqual(prepared.tags_stripped, 2)
        self.assertEqual(prepared.tags_kept, 1)

    def test_allowlist_is_the_appendix_a_subset(self) -> None:
        self.assertEqual(ALLOWED_TAGS, {"pauses", "slow", "excited", "whispers"})

    async def test_tag_ratio_one_per_two_sentences(self) -> None:
        client, _ = _client()
        # two sentences → one tag allowed
        prepared = client.prepare("<excited> Pehla. Doosra.")
        self.assertEqual(prepared.tags_kept, 1)
        # a second tag inside the same two sentences is stripped
        prepared2 = client.prepare("<slow> Teesra. Chautha. <excited> Panthwa.")
        self.assertEqual(prepared2.tags_kept, 1)  # cumulative 4 sentences → 2 total
        self.assertEqual(prepared2.tags_stripped, 1)

    async def test_tag_hard_cap_per_turn(self) -> None:
        client, _ = _client(tts_tag_max_per_turn=2)
        text = "Ek. Do. Teen. Chaar. Paanch. Chheh. <pauses> <slow> <excited>"
        prepared = client.prepare(text)
        self.assertEqual(prepared.tags_kept, 2)  # hard cap reached
        self.assertEqual(prepared.tags_stripped, 1)


class CharCapTest(unittest.IsolatedAsyncioTestCase):
    async def test_char_cap_truncates_with_closing_line(self) -> None:
        client, _ = _client(tts_char_cap_turn=1200)
        client.meters.chars_billed = 1150  # simulate a turn nearly at cap
        prepared = client.prepare(
            "Yeh jawab ka bahut lamba hissa hai jo cap paar karega"
        )
        self.assertTrue(prepared.truncated)
        self.assertIn("agle turn mein", prepared.text)
        self.assertLessEqual(prepared.chars_billed, 50)  # 1200 - 1150 budget

    async def test_char_meter_counts_tag_characters(self) -> None:
        client, _transport = _client()
        await client.start_turn()
        await _drain(client, "Ek <pauses> do.", segment_id=1)
        # tags bill as characters: billed length includes the tag markup
        self.assertEqual(client.meters.chars_billed, len("Ek <pauses> do."))

    async def test_zero_budget_speaks_nothing(self) -> None:
        client, _ = _client()
        client.meters.chars_billed = 1200  # cap exhausted
        prepared = client.prepare("Kuch bhi")
        self.assertEqual(prepared.text, "")
        self.assertEqual(prepared.chars_billed, 0)


class BargeInDrainTest(unittest.IsolatedAsyncioTestCase):
    """A cancelled segment's unread frames must never leak into the next turn."""

    async def test_abort_drains_old_segment_before_next_turn(self) -> None:
        settings = VoiceSettings(tts_url="wss://timbre.example", gnani_tts_api_key="k")
        transport = FakeTimbreTransport(auto_queue=False)

        async def connect() -> TtsTransport:
            return transport

        client = TtsClient(settings, connect)
        await client.start_turn()
        # segment 1 is mid-flight: one frame read, the rest still queued
        transport.replies.extend([b"old-1", b"old-2", '{"type": "segment_end"}'])
        iterator = client.speak("Purana jawab.", 1)
        first = await anext(iterator)
        self.assertEqual(first.data, b"old-1")
        await iterator.aclose()  # what a cancelled turn leaves behind
        self.assertEqual(len(transport.replies), 2)  # old tail still waiting
        await client.abort()  # barge-in: drain to segment_end
        self.assertEqual(transport.replies, [])
        # the next turn starts clean: frames come from the new segment only
        transport.auto_queue = True
        await client.start_turn()
        frames = [audio async for audio in client.speak("Naya jawab.", 2)]
        self.assertEqual(frames[-1].final, True)
        self.assertTrue(all(frame.data[:3] != b"old" for frame in frames if frame.data))

    async def test_abort_without_frames_is_a_noop(self) -> None:
        client, _transport = _client()
        await client.abort()  # never connected: must not raise
        await client.start_turn()
        self.assertIsNotNone(client.meters)


class AudioFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_frames_stream_and_segment_ends(self) -> None:
        client, _ = _client()
        await client.start_turn()
        frames = await _drain(client, "Namaste dosto.")
        self.assertEqual([f.final for f in frames], [False, False, True])
        self.assertEqual(client.meters.segments, 1)
        self.assertIsNotNone(client.meters.first_audio_s)

    async def test_f4_transport_death_raises(self) -> None:
        mock = MockTimbre(fail=True)
        with self.assertRaises(TtsUnavailableError):
            await mock.start_turn()

    async def test_close_turn_keeps_meters_readable(self) -> None:
        client, _ = _client()
        await client.start_turn()
        await _drain(client, "Ek. Do.")
        await client.close_turn()
        self.assertEqual(client.meters.chars_billed, len("Ek. Do."))
        await client.close()
