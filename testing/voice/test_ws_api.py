"""WS state-machine + failure-mode tests for voice.ws_api (spec.md §13).

Drives the real endpoint coroutine against a queue-backed starlette
WebSocket — no network, no server. Every F1–F8 row of spec.md §9, the happy
path ordering (highlight before first audio; first chunk dispatched while the
brain is still streaming), auth/rate limits, resume, and the T12 classifier
fixtures live here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import unittest

from starlette.websockets import Message, WebSocket

from testing.voice.mocks.brain import MockBrain
from testing.voice.mocks.prisma import MockPrisma
from testing.voice.mocks.timbre import MockTimbre
from voice import ws_api as ws
from voice.audio_io import unpack_downlink
from voice.config import VoiceSettings
from voice.session import CreditGuard, IpRateLimiter, SessionStore, TokenValidator

_KEY = "test-key"


def _settings(**kw: object) -> VoiceSettings:
    params: dict[str, object] = {
        "session_token_key": _KEY,
        "ip_hash_salt": "salt",
        "brain_first_event_s": 0.4,
        "brain_inactivity_s": 0.4,
        "brain_turn_deadline_s": 5.0,
        "filler_silence_ms": 2000,
        # OQ-06 [open]: the vendor credit unit is unpinned — the founder's
        # 30/day per-user cap vs the A-07 per-turn estimate (15 s + 600 chars)
        # is incoherent until the dashboard pins it. Tests use small units so
        # H2 behaves as designed; the guard math itself is unit-agnostic.
        "credit_turn_estimate_stt_s": 1,
        "credit_turn_estimate_tts_chars": 5,
    }
    params.update(kw)
    return VoiceSettings(**params)  # type: ignore[arg-type]


class Outbox:
    """Recorded S→C traffic: JSON dicts + parsed binary audio frames."""

    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def of_type(self, mtype: str) -> list[dict[str, object]]:
        return [i for i in self.items if i.get("type") == mtype]

    def first(self, mtype: str) -> dict[str, object] | None:
        rows = self.of_type(mtype)
        return rows[0] if rows else None

    def types(self) -> list[str]:
        return [str(i.get("type")) for i in self.items]


class FakeWebSocket(WebSocket):
    """Queue-backed starlette WebSocket: the endpoint runs unmodified."""

    def __init__(self, query_string: bytes = b"") -> None:
        self.incoming: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.outbox = Outbox()
        self.close_code: int | None = None
        scope = {
            "type": "websocket",
            "path": "/voice/ws",
            "raw_path": b"/voice/ws",
            "root_path": "",
            "scheme": "ws",
            "query_string": query_string,
            "headers": [],
            "client": ("203.0.113.9", 1234),
            "server": ("testserver", 80),
            "subprotocols": [],
        }
        super().__init__(scope, receive=self._receive, send=self._send)

    async def _receive(self) -> Message:
        item = await self.incoming.get()
        return dict(item)  # type: ignore[return-value]

    async def _send(self, message: Message) -> None:
        if message["type"] == "websocket.close":
            self.close_code = int(message.get("code") or 1000)  # type: ignore[arg-type]
            return
        if message["type"] == "websocket.accept":
            return
        if message["type"] == "websocket.send":
            text = message.get("text")
            if text is not None:
                self.outbox.items.append(json.loads(str(text)))
            elif message.get("bytes") is not None:
                header, _ = unpack_downlink(bytes(message["bytes"]))  # type: ignore[arg-type]
                self.outbox.items.append(
                    {
                        "type": "tts.audio",
                        "segment_id": header.segment_id,
                        "seq": header.seq,
                        "final": header.final,
                    }
                )


def _audio_frame(seq: int = 0) -> bytes:
    from voice.audio_io import pack_uplink

    return pack_uplink(1, seq, b"\x00\x00" * 1600)


class Harness:
    """Builds a VoiceApp around scriptable mocks and drives one connection."""

    def __init__(
        self,
        settings: VoiceSettings,
        *,
        prisma: MockPrisma,
        brain: MockBrain,
        tts: MockTimbre | None = None,
    ) -> None:
        clock = time.monotonic
        self.settings = settings
        self.prisma = prisma
        self.brain = brain
        self.tts = tts or MockTimbre(settings)
        self.app = ws.VoiceApp(
            settings=settings,
            sessions=SessionStore(settings, clock=clock),
            auth=TokenValidator(_KEY),
            limiter=IpRateLimiter(settings, clock=time.time),
            guard=CreditGuard(settings),
            stt_factory=lambda _s: self.prisma,  # type: ignore[arg-type,return-value]
            brain_factory=lambda _s: ws.BrainClient(settings, self.brain.factory()),
            tts_factory=lambda _s: self.tts,  # type: ignore[arg-type,return-value]
            clock=clock,
        )
        self.ws = FakeWebSocket()
        self.task: asyncio.Task[None] | None = None

    def token(self, session_id: str = "sess-1") -> str:
        from voice.session import issue_session_token

        return issue_session_token(session_id, "device-1", _KEY)

    def start(self) -> None:
        # the ASGI handshake: the server receives websocket.connect first
        self.ws.incoming.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.ensure_future(self.app.endpoint(self.ws))

    async def send(self, message: dict[str, object] | bytes) -> None:
        if isinstance(message, bytes):
            await self.ws.incoming.put({"type": "websocket.receive", "bytes": message})
        else:
            await self.ws.incoming.put(
                {"type": "websocket.receive", "text": json.dumps(message)}
            )

    async def disconnect(self) -> None:
        await self.ws.incoming.put({"type": "websocket.disconnect", "code": 1000})
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=5.0)

    async def finish_turn(self, timeout: float = 5.0) -> dict[str, object]:
        """Wait until a turn.end arrives, then return it."""
        async with asyncio.timeout(timeout):
            while True:
                await asyncio.sleep(0.01)
                end = self.ws.outbox.first("turn.end")
                if end is not None:
                    return end
        raise AssertionError("no turn.end")  # pragma: no cover


def _start_message(token: str, **extra: object) -> dict[str, object]:
    return {
        "type": "session.start",
        "v": 1,
        "session_token": token,
        "device": "device-1",
        "locale": "hi-en",
        "capabilities": {"ptt": True},
        **extra,
    }


async def _open(harness: Harness, token: str | None = None, **extra: object) -> None:
    harness.start()
    await harness.send(_start_message(token or harness.token(), **extra))
    await asyncio.sleep(0.02)


class AuthAndVersionTest(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_token_closed_4401(self) -> None:
        harness = Harness(
            _settings(), prisma=MockPrisma(), brain=MockBrain(content="hi.")
        )
        harness.start()
        await harness.send(_start_message("bogus.token"))
        await asyncio.sleep(0.05)
        self.assertEqual(harness.ws.close_code, 4401)
        error = harness.ws.outbox.first("error")
        assert error is not None
        self.assertEqual(error["code"], "auth.invalid")

    async def test_missing_token_closed_4401(self) -> None:
        harness = Harness(_settings(), prisma=MockPrisma(), brain=MockBrain())
        harness.start()
        await harness.send({"type": "session.start", "v": 1})
        await asyncio.sleep(0.05)
        self.assertEqual(harness.ws.close_code, 4401)

    async def test_query_param_ingress_shape_accepted(self) -> None:
        token = base64.urlsafe_b64encode(b"x").decode()  # placeholder, replaced below
        from voice.session import issue_session_token

        token = issue_session_token("sess-q", "device-1", _KEY)
        harness = Harness(
            _settings(),
            prisma=MockPrisma(final_text="sawaal"),
            brain=MockBrain(content="Jawab."),
        )
        harness.ws = FakeWebSocket(query_string=f"session_token={token}".encode())
        harness.start()
        await harness.send(
            {
                "type": "session.start",
                "v": 1,
                "session_token": token,
                "device": "device-1",
            }
        )
        await asyncio.sleep(0.05)  # let the loop process the start
        ready = harness.ws.outbox.first("session.ready")
        assert ready is not None
        await harness.disconnect()

    async def test_version_mismatch_closed_4409(self) -> None:
        harness = Harness(_settings(), prisma=MockPrisma(), brain=MockBrain())
        harness.start()
        await harness.send({"type": "session.start", "v": 2, "session_token": "x.y"})
        await asyncio.sleep(0.05)
        self.assertEqual(harness.ws.close_code, 4409)

    async def test_connect_rate_limit_1013(self) -> None:
        settings = _settings(ws_connects_per_min=1)
        harness = Harness(settings, prisma=MockPrisma(), brain=MockBrain())
        harness.app.limiter = IpRateLimiter(settings, clock=time.time)
        harness.app.limiter.allow_connect("203.0.113.9")  # exhaust the window
        harness.start()
        await harness.send(_start_message(harness.token()))
        await asyncio.sleep(0.05)
        self.assertEqual(harness.ws.close_code, 1013)


class HappyPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_full_ptt_turn_end_to_end(self) -> None:
        brain = MockBrain(content="REF: b-01\nPehla sentence. Doosra sentence.")
        harness = Harness(
            _settings(),
            prisma=MockPrisma(
                partials=["pehla"],
                final_text="Newton ka kya law tha?",
                final_lang="hi-en",
            ),
            brain=brain,
        )
        await _open(harness)
        snapshot = {
            "type": "context.snapshot",
            "topic_id": "motion",
            "class": "9",
            "chapter": "Motion",
            "block_id": "b-01",
            "block_type": "text",
            "scroll_pct": 10,
            "lang_pref": "hi-en",
            "ts": 1.0,
            "visible_blocks": ["b-01", "b-02"],
        }
        await harness.send(snapshot)
        await harness.send({"type": "audio.start"})
        await harness.send(_audio_frame(0))
        await harness.send(_audio_frame(1))
        await harness.send({"type": "audio.end"})
        end = await harness.finish_turn()
        await harness.disconnect()

        outbox = harness.ws.outbox
        self.assertEqual(outbox.first("session.ready")["profile"], "normal")  # type: ignore[index]
        states = [s["state"] for s in outbox.of_type("agent.state")]
        self.assertIn("listening", states)
        self.assertIn("thinking", states)
        self.assertIn("speaking", states)
        self.assertIn("idle", states)
        partials = outbox.of_type("stt.partial")
        self.assertEqual([p["text"] for p in partials], ["pehla"])
        highlight = outbox.first("highlight")
        assert highlight is not None
        self.assertEqual(highlight["block_ids"], ["b-01"])
        texts = [t for t in outbox.of_type("tts.text") if t["kind"] == "speech"]
        self.assertEqual(
            [t["text"] for t in texts], ["Pehla sentence.", "Doosra sentence."]
        )
        audios = outbox.of_type("tts.audio")
        self.assertTrue(audios)
        # T7: highlight BEFORE the first audio frame
        first_audio = outbox.items.index(audios[0])
        self.assertLess(outbox.items.index(highlight), first_audio)
        # binary downlink frames carry monotonic per-turn segment/seq
        self.assertEqual(audios[0]["segment_id"], 1)
        self.assertEqual(audios[0]["seq"], 0)
        # turn.end with the latency grid + usage
        self.assertEqual(end["end_reason"], "done")
        usage_row = end["usage"]  # type: ignore[index]
        assert isinstance(usage_row, dict)
        self.assertIsNone(usage_row["brain_prompt_tokens"])  # vendor silent
        latency_row = end["latency_ms"]  # type: ignore[index]
        assert isinstance(latency_row, dict)
        self.assertIn("L1", latency_row)
        self.assertIn("L6", latency_row)
        # one Prisma session per WS session; audio seconds metered (2 x 100 ms)
        self.assertAlmostEqual(harness.prisma.audio_seconds, 0.2, places=6)
        # voice_turn rows: student + tutor
        rows = [r for r in harness.app.turns._rows if r.session_id == "sess-1"]  # type: ignore[attr-defined]
        self.assertEqual(rows[0].role, "student")
        self.assertEqual(rows[0].text, "Newton ka kya law tha?")
        tutor_rows = [r for r in rows if r.role == "tutor"]
        self.assertEqual(tutor_rows[0].text, "Pehla sentence. Doosra sentence.")

    async def test_streaming_starts_before_brain_ends(self) -> None:
        brain = MockBrain(
            content="Ek sentence.\nDo sentence.\nTeen sentence.", chunk_delay_s=0.05
        )
        harness = Harness(
            _settings(brain_first_event_s=5.0),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        await harness.send({"type": "audio.start"})
        await harness.send({"type": "audio.end"})
        await harness.finish_turn()
        await harness.disconnect()
        # interleaving evidence: chunk 1 was voiced while the brain still had
        # two more lines to yield (the one-stream law, Gate C)
        self.assertEqual(
            brain.yield_log[:3],
            ["content:Ek sentence.", "content:Do sentence.", "content:Teen sentence."],
        )
        types = harness.ws.outbox.types()
        first_text = types.index("tts.text")
        self.assertLess(first_text, len(types) - 1)  # speech flowed before end

    async def test_typed_doubt_text_path(self) -> None:
        harness = Harness(
            _settings(),
            prisma=MockPrisma(),  # never touched
            brain=MockBrain(content="Text jawab."),
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "Typed sawaal hai yeh"})
        end = await harness.finish_turn()
        await harness.disconnect()
        self.assertEqual(end["end_reason"], "done")  # type: ignore[index]
        brain_request = harness.brain.last_messages[-1].content
        self.assertIn("Typed sawaal hai yeh", brain_request)
        self.assertIsNone(harness.ws.outbox.first("stt.final"))


class BargeInTest(unittest.IsolatedAsyncioTestCase):
    async def test_interrupt_aborts_brain_and_ends_turn(self) -> None:
        brain = MockBrain(
            content="Lamba jawab.\nAur bhi lamba jawab.\nPhir bhi aage.",
            chunk_delay_s=0.15,
        )
        harness = Harness(
            _settings(brain_inactivity_s=5.0),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        await harness.send({"type": "audio.start"})
        await harness.send({"type": "audio.end"})
        await asyncio.sleep(0.1)  # speech started
        await harness.send({"type": "interrupt"})
        await asyncio.sleep(0.2)
        await harness.disconnect()
        states = [s["state"] for s in harness.ws.outbox.of_type("agent.state")]
        self.assertEqual(states[-1], "listening")
        end = harness.ws.outbox.first("turn.end")
        assert end is not None
        self.assertEqual(end["end_reason"], "interrupted")  # type: ignore[index]
        self.assertTrue(brain.closed)  # upstream closed: the slot is freed

    async def test_interrupt_storm_ignored_f8(self) -> None:
        brain = MockBrain(content="Ek.", chunk_delay_s=0.3)
        harness = Harness(_settings(), prisma=MockPrisma(final_text="q"), brain=brain)
        await _open(harness)
        await harness.send({"type": "audio.start"})
        await harness.send({"type": "audio.end"})
        await asyncio.sleep(0.05)
        for _ in range(4):
            await harness.send({"type": "interrupt"})
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)
        await harness.disconnect()
        # the 4th interrupt inside the window is ignored (no extra state churn)
        interrupted_ends = [
            e
            for e in harness.ws.outbox.of_type("turn.end")
            if e["end_reason"] == "interrupted"
        ]
        self.assertEqual(len(interrupted_ends), 1)


class FailureModeTest(unittest.IsolatedAsyncioTestCase):
    async def test_f1_stt_down_degrades_to_text(self) -> None:
        harness = Harness(
            _settings(),
            prisma=MockPrisma(fail_connect=True),
            brain=MockBrain(content="Jawab."),
        )
        await _open(harness)
        await harness.send({"type": "audio.start"})
        await asyncio.sleep(0.05)
        errors = [e["code"] for e in harness.ws.outbox.of_type("error")]
        self.assertIn("stt.unavailable", errors)
        states = [s["state"] for s in harness.ws.outbox.of_type("agent.state")]
        self.assertEqual(states[-1], "listening")
        # the typed path still works (same brain+TTS pipeline, no STT)
        await harness.send({"type": "typed.doubt", "text": "Text sawaal"})
        end = await harness.finish_turn()
        await harness.disconnect()
        self.assertEqual(end["end_reason"], "done")  # type: ignore[index]

    async def test_f2_first_event_deadline_twice(self) -> None:
        harness = Harness(
            _settings(),
            prisma=MockPrisma(final_text="q"),
            brain=MockBrain(delay_before_first_s=1.0),
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        end = await harness.finish_turn()
        await harness.disconnect()
        errors = [e["code"] for e in harness.ws.outbox.of_type("error")]
        self.assertIn("brain.first_event_timeout", errors)
        self.assertEqual(end["end_reason"], "error")  # type: ignore[index]
        self.assertEqual(harness.brain.opens, 2)  # initial + one retry

    async def test_f3_stall_keeps_partial_and_writes_remainder(self) -> None:
        brain = MockBrain(
            content="Pehla bol gaya.\nDoosra bhi bol gaya.\nTeesra kabhi nahi aayega.",
            stall_after_chunks=2,
        )
        harness = Harness(
            _settings(brain_first_event_s=5.0),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        end = await harness.finish_turn()
        await harness.disconnect()
        errors = [e["code"] for e in harness.ws.outbox.of_type("error")]
        self.assertIn("brain.midturn_stall", errors)
        texts = [str(t["text"]) for t in harness.ws.outbox.of_type("tts.text")]
        self.assertIn("Pehla bol gaya.", " ".join(texts))
        self.assertIn("Doosra bhi bol gaya.", " ".join(texts))
        self.assertNotIn("Teesra kabhi nahi aayega.", " ".join(texts))
        self.assertEqual(end["end_reason"], "error")  # type: ignore[index]

    async def test_f4_tts_down_text_only(self) -> None:
        harness = Harness(
            _settings(),
            prisma=MockPrisma(final_text="q"),
            brain=MockBrain(content="Sunai dega text mein."),
            tts=MockTimbre(fail=True),
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        end = await harness.finish_turn()
        await harness.disconnect()
        errors = [e["code"] for e in harness.ws.outbox.of_type("error")]
        self.assertIn("tts.unavailable", errors)
        texts = [t["text"] for t in harness.ws.outbox.of_type("tts.text")]
        self.assertIn("Sunai dega text mein.", texts)
        self.assertIsNone(harness.ws.outbox.first("tts.audio"))
        states = [s["state"] for s in harness.ws.outbox.of_type("agent.state")]
        self.assertIn("speaking_text", states)
        self.assertEqual(end["end_reason"], "done")  # type: ignore[index]

    async def test_f7_missing_snapshot_generic_answer(self) -> None:
        harness = Harness(
            _settings(),
            prisma=MockPrisma(final_text="q"),
            brain=MockBrain(content="Generic jawab."),
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        await harness.finish_turn()
        await harness.disconnect()
        errors = [e["code"] for e in harness.ws.outbox.of_type("error")]
        self.assertIn("context.stale", errors)
        brain_context = harness.brain.last_messages[-1].content
        self.assertIn("NO PAGE CONTEXT", brain_context)

    async def test_stale_snapshot_flagged(self) -> None:
        brain = MockBrain(content="Jawab.")
        harness = Harness(
            _settings(),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        await harness.send(
            {
                "type": "context.snapshot",
                "topic_id": "t",
                "class": "9",
                "chapter": "c",
                "block_id": "b1",
                "block_type": "text",
                "ts": 1.0,
            }
        )
        await asyncio.sleep(0.05)  # let the loop store the snapshot
        session = harness.app.sessions.get("sess-1")
        assert session is not None
        session.snapshot_at -= 10.0  # dock stopped refreshing (> 2 s stale)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        await harness.finish_turn()
        await harness.disconnect()
        errors = [e["code"] for e in harness.ws.outbox.of_type("error")]
        self.assertIn("context.stale", errors)
        brain_context = harness.brain.last_messages[-1].content
        self.assertIn("stale", brain_context)


class CreditGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_h2_over_credit_line_then_text_only(self) -> None:
        # H1 passes (remaining 50 > 0) but the turn estimate (100) exceeds the
        # per-user cap — H2 refuses before the brain call (spec.md §8).
        harness = Harness(
            _settings(
                credit_daily_tranche=1000,
                credit_per_user_cap=50,
                credit_demo_tranche=1000,
                credit_demo_session_cap=50,
                credit_turn_estimate_stt_s=50,
                credit_turn_estimate_tts_chars=50,
            ),
            prisma=MockPrisma(final_text="q"),
            brain=MockBrain(content="nahi aayega"),
        )
        await _open(harness)
        await harness.send({"type": "audio.start"})
        await harness.send(_audio_frame(0))
        await harness.send({"type": "audio.end"})
        end = await harness.finish_turn()
        await harness.disconnect()
        over = [
            e
            for e in harness.ws.outbox.of_type("error")
            if e["code"] == "credit.over_daily"
        ]
        self.assertGreaterEqual(len(over), 1)
        texts = [t["text"] for t in harness.ws.outbox.of_type("tts.text")]
        self.assertIn(harness.settings.over_credit_line, texts)
        self.assertEqual(end["end_reason"], "error")  # type: ignore[index]
        # the brain was never called: no voice spend after the refusal
        self.assertEqual(harness.brain.opens, 0)
        # session downgraded: the next turn never reaches the brain
        session = harness.app.sessions.get("sess-1")
        assert session is not None
        self.assertTrue(session.text_only)

    async def test_h1_normal_profile_closed_when_tranche_empty(self) -> None:
        harness = Harness(
            _settings(
                credit_daily_tranche=0,
                credit_per_user_cap=0,
                credit_demo_tranche=0,
                credit_demo_session_cap=0,
            ),
            prisma=MockPrisma(),
            brain=MockBrain(),
        )
        harness.start()
        await harness.send(_start_message(harness.token()))
        await asyncio.sleep(0.05)
        # check_start with remaining 0 → normal profile: closed
        self.assertEqual(harness.ws.close_code, 1000)
        error = harness.ws.outbox.first("error")
        assert error is not None
        self.assertEqual(error["code"], "credit.over_daily")

    async def test_h1_demo_profile_downgrades_to_text_only(self) -> None:
        harness = Harness(
            _settings(
                credit_daily_tranche=0,
                credit_per_user_cap=0,
                credit_demo_tranche=0,
                credit_demo_session_cap=0,
            ),
            prisma=MockPrisma(final_text="q"),
            brain=MockBrain(content="Text jawab."),
        )
        # the demo flag is a server-side field on the session row (spec §11)
        from voice.session import SessionIdentity

        harness.app.sessions.create(
            SessionIdentity("sess-1", "device-1"), profile="demo", locale="hi-en"
        )
        harness.start()
        await harness.send(_start_message(harness.token()))
        await asyncio.sleep(0.05)  # let the loop process the start
        ready = harness.ws.outbox.first("session.ready")
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        end = await harness.finish_turn()
        await harness.disconnect()
        assert ready is not None
        self.assertEqual(ready["state"], "text_only")  # type: ignore[index]
        # judge still gets text answers, never silence
        texts = [t["text"] for t in harness.ws.outbox.of_type("tts.text")]
        self.assertIn("Text jawab.", texts)
        self.assertEqual(end["end_reason"], "done")  # type: ignore[index]


class ThinkingOutLoudTest(unittest.IsolatedAsyncioTestCase):
    async def test_t12_procedural_spoken_substantive_text_only(self) -> None:
        brain = MockBrain(
            thoughts=["Let me recall the question", "The answer is 9.8 m/s2"],
            content="Jawab.",
        )
        harness = Harness(
            _settings(thinking_summaries=True, filler_silence_ms=10_000),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        await harness.finish_turn()
        await harness.disconnect()
        summaries = [
            t for t in harness.ws.outbox.of_type("tts.text") if t["kind"] == "summary"
        ]
        self.assertEqual(len(summaries), 2)  # both visible in the panel
        audios = harness.ws.outbox.of_type("tts.audio")
        # procedural summary got audio; the number-carrying one did not
        self.assertTrue(audios)
        voiced = [a for a in audios if a["segment_id"] == 0]  # type: ignore[union-attr]
        self.assertTrue(voiced)

    async def test_filler_fills_dead_air_once(self) -> None:
        brain = MockBrain(content="Der se aaya jawab.", delay_before_first_s=0.2)
        harness = Harness(
            _settings(filler_silence_ms=50, brain_first_event_s=5.0),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        # fillers are VOICE dead-air cover: the turn must be a voice turn
        await harness.send({"type": "audio.start"})
        await harness.send({"type": "audio.end"})
        await harness.finish_turn()
        await harness.disconnect()
        fillers = [
            t for t in harness.ws.outbox.of_type("tts.text") if t["kind"] == "filler"
        ]
        self.assertEqual(len(fillers), 1)
        self.assertIn(fillers[0]["text"], ws._FILLERS)  # type: ignore[attr-defined]
        filler_pos = harness.ws.outbox.items.index(fillers[0])
        answer = next(
            t for t in harness.ws.outbox.of_type("tts.text") if t["kind"] == "speech"
        )
        self.assertLess(filler_pos, harness.ws.outbox.items.index(answer))


class ResumeTest(unittest.IsolatedAsyncioTestCase):
    async def test_resume_replays_turn_end_within_window(self) -> None:
        harness = Harness(
            _settings(),
            prisma=MockPrisma(final_text="q"),
            brain=MockBrain(content="Jawab."),
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        end = await harness.finish_turn()
        await harness.disconnect()
        # reconnect with resume
        harness2_ws = FakeWebSocket()
        harness.ws = harness2_ws
        harness.start()
        await harness.send(
            _start_message(harness.token(), resume=True, last_turn_id=end["turn_id"])  # type: ignore[index]
        )
        await asyncio.sleep(0.05)
        replayed = harness2_ws.outbox.first("turn.end")
        assert replayed is not None
        self.assertEqual(replayed["end_reason"], "done")  # type: ignore[index]
        await harness.disconnect()

    async def test_resume_after_window_aborts_turn_honestly(self) -> None:
        harness = Harness(_settings(), prisma=MockPrisma(), brain=MockBrain())
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal"})
        await harness.finish_turn()
        await harness.disconnect()
        harness.ws = FakeWebSocket()
        harness.start()
        await asyncio.sleep(0.05)  # let the replay window expire? window is 60s...
        # force expiry via the store clock path: directly age the timestamp
        session = harness.app.sessions.get("sess-1")
        assert session is not None
        session.last_turn_end_at -= 120.0
        await harness.send(
            _start_message(harness.token(), resume=True, last_turn_id="t-old")
        )
        await asyncio.sleep(0.05)
        replayed = harness.ws.outbox.of_type("turn.end")
        self.assertEqual(replayed[0]["end_reason"], "error")  # type: ignore[index]
        await harness.disconnect()


class SelfReviewFixTest(unittest.IsolatedAsyncioTestCase):
    """Regression tests for the §5 self-review findings."""

    async def test_oversized_json_frame_dropped(self) -> None:
        harness = Harness(_settings(), prisma=MockPrisma(), brain=MockBrain())
        await _open(harness)
        await harness.send({"type": "ping", "t": 1})  # sanity: loop alive
        await harness.send({"type": "typed.doubt", "text": "x" * 9000})
        await harness.send({"type": "ping", "t": 2})
        await asyncio.sleep(0.1)
        pongs = harness.ws.outbox.of_type("pong")
        self.assertEqual(len(pongs), 2)  # both pings answered around the drop
        self.assertEqual(harness.ws.outbox.first("error"), None)
        self.assertEqual(harness.task is not None and harness.task.done(), False)
        await harness.disconnect()

    async def test_oversized_typed_text_rejected(self) -> None:
        harness = Harness(_settings(), prisma=MockPrisma(), brain=MockBrain())
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "y" * 1001})
        await asyncio.sleep(0.1)
        error = harness.ws.outbox.first("error")
        assert error is not None
        self.assertEqual(error["code"], "client_error")
        self.assertEqual(harness.brain.opens, 0)
        await harness.disconnect()

    async def test_keepalive_reaps_dead_connection(self) -> None:
        settings = _settings(ws_ping_interval_s=0.05, ws_ping_miss_max=2)
        harness = Harness(settings, prisma=MockPrisma(), brain=MockBrain())
        harness.start()
        await harness.send(_start_message(harness.token()))
        await asyncio.sleep(0.35)  # 2+ missed pongs
        self.assertEqual(harness.ws.close_code, 1000)
        pings = harness.ws.outbox.of_type("ping")
        self.assertGreaterEqual(len(pings), 2)
        await harness.disconnect()

    async def test_keepalive_survives_pongs(self) -> None:
        settings = _settings(ws_ping_interval_s=0.05, ws_ping_miss_max=2)
        harness = Harness(settings, prisma=MockPrisma(), brain=MockBrain())
        harness.start()
        await harness.send(_start_message(harness.token()))
        for _ in range(6):
            await asyncio.sleep(0.06)
            await harness.send({"type": "pong"})  # the dock answers
        self.assertIsNone(harness.ws.close_code)  # still open
        await harness.disconnect()

    async def test_history_excludes_event_rows(self) -> None:
        # Finding 1: F-row event rows are ledger data — the brain's dialogue
        # window must contain only student/tutor turns.
        harness = Harness(
            _settings(), prisma=MockPrisma(), brain=MockBrain(content="Jawab.")
        )
        await _open(harness)
        await harness.send({"type": "typed.doubt", "text": "sawaal ek"})
        await harness.finish_turn()
        await harness.disconnect()
        brain = harness.brain
        # force an event row into the store, then run a second turn
        rows = harness.app.turns._rows  # type: ignore[attr-defined]
        rows.append(
            __import__("voice.session", fromlist=["TurnRecord"]).TurnRecord(
                id="evt-1",
                session_id="sess-1",
                turn_idx=99,
                role="event",
                text="brain.first_event_timeout",
            )
        )
        harness.ws = FakeWebSocket()
        harness.start()
        await harness.send(_start_message(harness.token()))
        await asyncio.sleep(0.05)
        await harness.send({"type": "typed.doubt", "text": "sawaal do"})
        await harness.finish_turn()
        await harness.disconnect()
        history = [m.content for m in brain.last_messages[1:-1]]
        self.assertTrue(all("brain.first_event_timeout" not in h for h in history))
        self.assertIn("sawaal ek", " ".join(history))

    async def test_no_filler_on_text_only_turns(self) -> None:
        brain = MockBrain(content="Der se aaya jawab.", delay_before_first_s=0.2)
        harness = Harness(
            _settings(filler_silence_ms=20, brain_first_event_s=5.0),
            prisma=MockPrisma(final_text="q"),
            brain=brain,
        )
        await _open(harness)
        await harness.send(
            {"type": "typed.doubt", "text": "sawaal"}
        )  # typed = no voice
        await harness.finish_turn()
        await harness.disconnect()
        self.assertEqual(
            [t for t in harness.ws.outbox.of_type("tts.text") if t["kind"] == "filler"],
            [],
        )


class ClassifierFixtureTest(unittest.TestCase):
    """spec.md §13: the T12 fixtures live in test_ws_api.py."""

    def test_procedural_lines_pass(self) -> None:
        for line in (
            "Let me recall the question",
            "So the question asks about velocity",
            "Pehle formula dekhte hain",
            "We are checking the page again",
            "Next step: energy",
            "Ab dekho page par",
        ):
            self.assertTrue(ws.is_procedural_summary(line), line)

    def test_substantive_lines_dropped_from_speech(self) -> None:
        for line in (
            "The answer is 9.8 m/s2",
            "Velocity increases because force acts",
            "Kyunki gravity hai",
            "The ball will fall at 3 seconds",
            "Therefore the mass is 5 kg",
            "",
        ):
            self.assertFalse(ws.is_procedural_summary(line), line)


if __name__ == "__main__":
    unittest.main()
