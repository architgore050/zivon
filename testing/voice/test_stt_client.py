"""Unit tests for voice.stt_client (spec.md §13 test table)."""

from __future__ import annotations

import asyncio
import unittest

from testing.voice.mocks.prisma import MockPrisma
from voice.config import VoiceSettings
from voice.stt_client import SttClient, SttEvent, SttUnavailableError


class FakeTransport:
    """In-memory SttTransport: records sends, replays scripted recv lines."""

    def __init__(self, incoming: list[str], fail_sends: bool = False) -> None:
        self.incoming = list(incoming)
        self.sent: list[str | bytes] = []
        self.fail_sends = fail_sends
        self.closed = False

    async def send(self, data: str | bytes) -> None:
        if self.fail_sends:
            raise ConnectionError("mock: send failed")
        self.sent.append(data)

    async def recv(self) -> str | bytes:
        if not self.incoming:
            raise ConnectionError("mock: upstream closed")
        return self.incoming.pop(0)

    async def close(self) -> None:
        self.closed = True


def _settings() -> VoiceSettings:
    return VoiceSettings(stt_url="wss://prisma.example/stream", gnani_stt_api_key="k")


class SttClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_partial_and_final_mapping(self) -> None:
        transport = FakeTransport(
            [
                '{"type":"partial","text":"Newton"}',
                '{"type":"partial","text":"Newton ka"}',
                '{"type":"final","text":"Newton ka second law","lang":"hi-en","confidence":0.91}',
            ]
        )
        client = SttClient(
            _settings(), connect_factory=lambda: asyncio.sleep(0, result=transport)
        )
        await client.start()
        events: list[SttEvent] = []
        while True:
            event = await client.next_event()
            if event is None:
                break
            events.append(event)
        self.assertEqual([e.kind for e in events], ["partial", "partial", "final"])
        final = events[-1]
        self.assertEqual(final.text, "Newton ka second law")
        self.assertEqual(final.lang, "hi-en")
        self.assertEqual(final.confidence, 0.91)

    async def test_commit_is_the_eos_and_no_inband_config(self) -> None:
        transport = FakeTransport([])
        client = SttClient(
            _settings(), connect_factory=lambda: asyncio.sleep(0, result=transport)
        )
        await client.start()
        await client.send_audio(b"\x00\x00" * 1600)
        await client.finish()
        kinds = [s for s in transport.sent if isinstance(s, str)]
        # Prisma v3.0 realtime: config travels in upgrade headers, EOS is
        # `commit` (verified against docs.gnani.ai 2026-11-10).
        self.assertFalse(any('"type": "config"' in s for s in kinds))
        self.assertEqual(kinds, ['{"type": "commit"}'])
        # mic audio crosses upstream as binary PCM frames (ws-contract.md §3)
        self.assertEqual(sum(isinstance(s, bytes) for s in transport.sent), 1)
        await client.close()

    async def test_transcript_event_maps_to_final(self) -> None:
        transport = FakeTransport(
            [
                '{"type":"transcript","text":"Impulse aur momentum same kyun?","detected_language_code":"hi-IN","segment_id":"seg_1","latency":320}',
            ]
        )
        client = SttClient(
            _settings(), connect_factory=lambda: asyncio.sleep(0, result=transport)
        )
        await client.start()
        event = await client.next_event()
        assert event is not None
        self.assertEqual(event.kind, "final")
        self.assertEqual(event.text, "Impulse aur momentum same kyun?")
        self.assertEqual(event.lang, "hi-IN")

    async def test_garbage_events_tolerated_never_crash(self) -> None:
        transport = FakeTransport(
            ["not json", '{"type":"weird","text":"x"}', '{"type":"final","text":"ok"}']
        )
        client = SttClient(
            _settings(), connect_factory=lambda: asyncio.sleep(0, result=transport)
        )
        await client.start()
        final = await client.next_event()
        assert final is not None
        self.assertEqual(final.text, "ok")
        self.assertEqual(client.dropped_unparsed, 2)

    async def test_reconnect_with_resume(self) -> None:
        dead = FakeTransport([])  # recv() raises immediately: upstream closed
        live = FakeTransport(['{"type":"final","text":"after resume"}'])
        made: list[FakeTransport] = []

        def factory() -> object:
            transport = live if made else dead
            made.append(transport)
            return transport

        async def connect() -> object:
            return factory()

        client = SttClient(_settings(), connect_factory=connect)  # type: ignore[arg-type]
        await client.start()
        final = await client.next_event()
        assert final is not None
        self.assertEqual(final.text, "after resume")
        self.assertEqual(client.reconnects, 1)
        # config is header-carried; a reconnect sends no in-band resume frame
        self.assertFalse(any(isinstance(s, str) and s for s in live.sent))

    async def test_stream_death_past_budget_returns_none(self) -> None:
        transport = FakeTransport([])

        async def connect() -> FakeTransport:
            return transport

        client = SttClient(_settings(), connect_factory=connect, reconnect_attempts=1)
        await client.start()
        self.assertIsNone(await client.next_event())
        self.assertEqual(client.reconnects, 1)

    async def test_echo_guard_window_drops_events(self) -> None:
        # ws-contract.md §5: STT events within 200 ms after playback stop are
        # DROPPED (loudspeaker tail leak) — not deferred, never echoed back.
        now = [100.0]
        transport = FakeTransport(['{"type":"final","text":"echoed tutor phrase"}'])
        client = SttClient(
            _settings(),
            connect_factory=lambda: asyncio.sleep(0, result=transport),
            clock=lambda: now[0],
        )
        await client.start()
        client.arm_echo_guard(duration_ms=200)  # window: 100.0 → 100.2
        self.assertIsNone(await client.next_event())  # dropped inside window
        self.assertEqual(client.dropped_echo, 1)
        now[0] = 100.5  # past the window
        transport.incoming.append('{"type":"final","text":"real doubt"}')
        event = await client.next_event()
        assert event is not None
        self.assertEqual(event.text, "real doubt")

    async def test_audio_seconds_metered(self) -> None:
        client = MockPrisma()
        await client.start()
        await client.send_audio(b"\x00\x00" * 1600)  # 100 ms @ 16 kHz
        self.assertAlmostEqual(client.audio_seconds, 0.1, places=6)

    async def test_wait_for_final_returns_final_event(self) -> None:
        from voice.stt_client import wait_for_final

        mock = MockPrisma(partials=["partial text"], final_text="done text")
        await mock.start()
        event = await wait_for_final(mock, timeout_s=1.0)
        self.assertEqual(event.text, "done text")

    async def test_wait_for_final_timeout_is_f1_shaped(self) -> None:
        from voice.stt_client import wait_for_final

        mock = MockPrisma(final_text="")  # never sends a final
        await mock.start()
        with self.assertRaises(SttUnavailableError):
            await wait_for_final(mock, timeout_s=0.01)


if __name__ == "__main__":
    unittest.main()
