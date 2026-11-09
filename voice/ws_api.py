"""WebSocket API — the voice loop endpoint (spec.md §3 ``ws_api``).

Mounts into the core-backend FastAPI monolith via ``mount_voice(app)``
(ADR-0020, backend-spec §4.2): the only symbol the core backend imports is
``voice.mount_voice``. The contract is ``docs/specs/voice-agent/
ws-contract.md``: one WSS connection per dock session; JSON text frames for
control, 8-byte-header binary frames for audio; auth via ``session_token``
(API-001, both ingress shapes); server-enforced state machine.

Orchestration only — every capability lives in its module: frames/audio_io,
STT/stt_client, brain/brain_client, chunking/chunker, TTS/tts_client,
state+credits/session, context/anchoring, logging/logging_surface.

Failure modes (spec.md §9) are implemented where detected:

| F | Detection site | Student-visible behavior |
|---|---|---|
| F1 | stt connect at audio.start | ``stt.unavailable`` + text path stays open (typed.doubt, S0 message) |
| F2 | brain first-event deadline ×2 | honest ``brain.first_event_timeout`` error turn; typed path offered |
| F3 | brain stall/deadline mid-turn | partial stays; remainder written as text; ``brain.midturn_stall``/``brain.deadline`` |
| F4 | tts transport death | text-only continuation of the turn; ``tts.unavailable``; SpeechSynthesis never used |
| F5 | WS drop mid-turn | resume replays agent.state + turn.end within the 60 s window |
| F6 | guard H1/H2 breach | over-credit line spoken once, then text-only; demo profile downgrades at H1 |
| F7 | snapshot missing/stale | generic answer + honest "cannot see the page" note; ``context.stale`` |
| F8 | interrupt storm | > 3 interrupts / 10 s ignored until the next audio.start |

Known spec reconciliation points (flagged in the manifest, not re-decided):
spec.md F1 names a ``listening_text`` state that ws-contract.md §1 does not
list — this emits ``error`` (stt.unavailable) then ``listening``; spec.md F2
promises "text-only answer" prose that cannot exist when the brain never
produced a first event — this emits the honest error turn instead. The
``typed.doubt`` message (backend-spec §7.2, S0-owned) is honoured because F1
requires a text path the SP1 catalogue omits.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from . import anchoring
from .audio_io import UplinkStream, pack_downlink
from .brain_client import (
    BrainClient,
    BrainDeadlineError,
    BrainEvent,
    BrainFirstEventTimeout,
    BrainMessage,
    BrainRequest,
    BrainStallError,
)
from .chunker import Chunk, SegmentIds, SentenceChunker
from .config import VoiceSettings
from .logging_surface import ErrorClass, Severity, bind_context, log_event
from .session import (
    CreditGuard,
    InMemoryTurnRepository,
    IpRateLimiter,
    SessionStore,
    TokenValidator,
    TurnRecord,
    TurnRepository,
    VoiceSession,
    new_turn_id,
    turn_estimate,
)
from .stt_client import SttClient, SttUnavailableError
from .tts_client import TtsClient, TtsUnavailableError

__all__ = ["TUTOR_SYSTEM_PROMPT", "VoiceApp", "mount_voice"]

_WS_CLOSE_AUTH = 4401
_WS_CLOSE_VERSION = 4409
_WS_CLOSE_RATE = 1013
_WS_CLOSE_NORMAL = 1000

TUTOR_SYSTEM_PROMPT = """You are Zivon, a patient Physics tutor for a Class 9–12 student in India, speaking out loud.
The student hears you; they may be reading the page you are anchored to.

Goal: the student leaves this turn able to explain the idea in their own words — clear,
encouraging, step-by-step, in the student's language (Hindi, English, or the mix they used).

The page context below is the universe of this answer: teach from what is on the page. If a step
needs physics beyond the page, use generic method ("energy is conserved") and say the page will
cover it — never introduce a new claim or number you cannot see verified. If you are not sure a
step is right, say what you are checking instead of asserting it.

Spoken contract (the harness enforces parts of this mechanically):
- First line, only if you refer to page elements: `REF: <block_id>,<block_id>` using ids from the
  context's block list. Never put REF anywhere else; never mention it.
- Plain spoken words: no markdown, no LaTeX, no code blocks. Say formulas in words and numbers
  as digits ("x squared plus one", "3.06 metre per second squared").
- Short sentences — one idea each, ≤ ~15 words. Prefer 4–8 sentences per turn; end with ONE short
  Socratic follow-up question when the student is close to a step, not every turn.
- Where delivery helps, use at most these cues inline: <pauses> <slow> <excited> <whispers>.
  Nothing else; at most one cue per two sentences.
Match the student's language mix; keep proper nouns and technical terms in English."""

# ADR-0018 option A: fixed safe fillers, randomized without repetition across
# the last 3 turns, max 1/turn — the always-armed dead-air fallback.
_FILLERS = ("ek second…", "achha sawaal…", "sochte hain…")

# T12 classifier (spec.md §5): only PROCEDURAL summary lines may be voiced;
# anything substantive (a number, a causal claim) is dropped from speech —
# harness guarantee, never a prompt plea.
_PROCEDURAL_STARTS = (
    "let me",
    "so the question",
    "the question asks",
    "recall",
    "we are checking",
    "checking",
    "first",
    "next",
    "then",
    "now",
    "ab",
    "pehle",
    "sawaal",
    "yaad",
    "dekho",
    "sochte",
    "chalo",
    "the page",
    "page par",
    "formula",
    "relation",
    "step",
    "given",
    "data",
)
_CAUSAL_MARKERS = (
    "because",
    "kyunki",
    "therefore",
    "isliye",
    "thus",
    "so that",
    "leads to",
    "hence",
    "pata chalta hai",
    "iska matlab",
)

# ws_api.py is the only voice module allowed to import the logging shim
# bridge directly through .logging_surface (done above) — call sites log ids,
# latencies, counters; transcripts never enter fields (logging-api.md §6).

SttFactory = Callable[[VoiceSettings], Any]
BrainFactory = Callable[[VoiceSettings], BrainClient]
TtsFactory = Callable[[VoiceSettings], TtsClient]
Clock = Callable[[], float]


def is_procedural_summary(line: str) -> bool:
    """T12 harness filter: True → may be voiced; False → text-only (T7)."""
    text = line.strip().lower()
    if not text:
        return False
    if not text.startswith(_PROCEDURAL_STARTS):
        return False  # unknown shape ⇒ substantive ⇒ never voiced
    if re.search(r"\d", text):
        return False  # a number ⇒ unverified claim ⇒ drop from speech
    return not any(marker in text for marker in _CAUSAL_MARKERS)  # causal ⇒ drop


class SttSession(Protocol):
    """The slice of the STT client ws_api drives (SttClient or MockPrisma)."""

    async def start(self) -> None: ...

    async def send_audio(self, pcm: bytes) -> None: ...

    async def finish(self) -> None: ...

    async def next_event(self) -> Any: ...

    def arm_echo_guard(self, duration_ms: int | None = None) -> None: ...

    async def close(self) -> None: ...


class VoiceApp:
    """The mounted voice endpoint + its dependencies (DI for the merge agent).

    Defaults implement ADR-0002's memory store so a dev run works standalone;
    the core backend injects its Postgres-backed adapters via ``mount_voice``:
    sessions/turns (store), auth (token validator against the core session
    table), limiter/guard (cluster-shared implementations), and the three
    vendor factories (stt/brain/tts) for mock or alternate transports.
    """

    def __init__(
        self,
        *,
        settings: VoiceSettings | None = None,
        sessions: SessionStore | None = None,
        turns: TurnRepository | None = None,
        auth: TokenValidator | None = None,
        limiter: IpRateLimiter | None = None,
        guard: CreditGuard | None = None,
        stt_factory: SttFactory | None = None,
        brain_factory: BrainFactory | None = None,
        tts_factory: TtsFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings or VoiceSettings()
        clock = clock or time.time
        self.sessions: SessionStore = sessions or SessionStore(
            self.settings, clock=clock
        )
        self.turns: TurnRepository = turns or InMemoryTurnRepository(clock=clock)
        self.auth: TokenValidator = auth or TokenValidator(
            self.settings.session_token_key
        )
        self.limiter: IpRateLimiter = limiter or IpRateLimiter(
            self.settings, clock=clock
        )
        self.guard: CreditGuard = guard or CreditGuard(self.settings)
        self.stt_factory: SttFactory = stt_factory or (lambda s: SttClient(s))
        self.brain_factory: BrainFactory = brain_factory or (lambda s: BrainClient(s))
        self.tts_factory: TtsFactory = tts_factory or (lambda s: TtsClient(s))
        self._clock: Clock = clock

    async def endpoint(self, websocket: WebSocket) -> None:
        """The /voice/ws handler (registered by :meth:`mount`)."""
        await _endpoint(self, websocket)

    def mount(self, app: Any) -> None:
        """Register the WS route on a FastAPI/Starlette app."""
        add = getattr(app, "add_api_websocket_route", None)
        if add is not None:
            add(self.settings.ws_path, self.endpoint)
        else:  # plain Starlette
            app.router.add_websocket_route(self.settings.ws_path, self.endpoint)


def mount_voice(app: Any, **deps: Any) -> VoiceApp:
    """mount_voice(app) — the core backend's only voice integration point."""
    voice = VoiceApp(**deps)
    voice.mount(app)
    return voice


@dataclass
class _Turn:
    """One in-flight turn's bookkeeping (latency grid L0–L8, usage, guards)."""

    turn_id: str
    turn_idx: int
    kind: str  # audio | typed
    transcript: str = ""
    lang: str = ""
    confidence: float | None = None
    started_at: float = 0.0
    audio_end_at: float | None = None  # L0 anchor (end-of-speech at the server)
    stt_final_at: float | None = None  # L1
    brain_called_at: float | None = None  # L2 end / L3 start
    first_segment_at: float | None = None  # L4/L5
    first_audio_at: float | None = None  # L6
    highlight_sent: bool = False
    audio_dispatched: bool = False
    interrupted: bool = False
    spoken_chars: int = 0
    stt_seconds: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    latency: dict[str, int | None] = field(
        default_factory=lambda: {f"L{i}": None for i in range(9)}
    )
    reserved: int = 0
    end_reason: str = "done"
    audio_seq: int = 0  # per-turn monotonic tts.audio seq (ws-contract §3)
    answer_text: str = ""  # accumulated tutor speech for the voice_turn row

    def stamp(self, hop: str, at: float) -> None:
        if self.latency.get(hop) is None and self.audio_end_at is not None:
            self.latency[hop] = int((at - self.audio_end_at) * 1000)


class _Connection:
    """Per-connection state: clients, pump task, send lock."""

    def __init__(self, app: VoiceApp, websocket: WebSocket) -> None:
        self.app = app
        self.ws = websocket
        self.settings = app.settings
        self.session: VoiceSession | None = None
        self.stt: SttSession | None = None
        self.stt_uplink = UplinkStream()
        self.brain: BrainClient | None = None
        self.tts: TtsClient | None = None
        self.stt_queue: asyncio.Queue[Any] = asyncio.Queue()
        self.pump_task: asyncio.Task[None] | None = None
        self.turn_task: asyncio.Task[None] | None = None
        self.current_turn: _Turn | None = None
        self._tts_turn_open = False
        self._snapshot_obj: Any = None  # ContextSnapshot (set by _store_snapshot)
        self.send_lock = asyncio.Lock()
        self.pong_misses = 0

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            if self.ws.client_state == WebSocketState.CONNECTED:
                await self.ws.send_text(
                    json.dumps({**payload, "v": 1}, ensure_ascii=False)
                )

    async def send_bytes(self, data: bytes) -> None:
        async with self.send_lock:
            if self.ws.client_state == WebSocketState.CONNECTED:
                await self.ws.send_bytes(data)


# --- endpoint -----------------------------------------------------------------


async def _endpoint(app: VoiceApp, websocket: WebSocket) -> None:
    """The /voice/ws handler: auth → session.ready → message loop."""
    conn = _Connection(app, websocket)
    settings = app.settings
    now = app._clock

    await websocket.accept()
    ip = websocket.client.host if websocket.client else ""
    if not app.limiter.allow_connect(ip):  # GAP-003: 10 connects/min/IP
        await conn.send_json(
            {
                "type": "error",
                "code": "E-RATE-LIMIT",
                "message": "too many connects",
                "recoverable": True,
            }
        )
        await websocket.close(_WS_CLOSE_RATE)
        return

    # First message MUST be session.start carrying v + session_token.
    try:
        first = json.loads(await websocket.receive_text())
    except WebSocketDisconnect:
        return
    except (json.JSONDecodeError, KeyError):
        await conn.send_json(
            {
                "type": "error",
                "code": "auth.invalid",
                "message": "first message must be session.start",
                "recoverable": False,
            }
        )
        await websocket.close(_WS_CLOSE_AUTH)
        return
    if first.get("type") != "session.start" or first.get("v") != settings.ws_version:
        code = (
            "version.mismatch"
            if first.get("type") == "session.start"
            else "auth.invalid"
        )
        await websocket.close(
            _WS_CLOSE_VERSION if code == "version.mismatch" else _WS_CLOSE_AUTH
        )
        return

    # Auth: both ingress shapes (query param S0 + payload SP1), same validator.
    query_token = websocket.query_params.get("session_token")
    payload_token = first.get("session_token")
    if query_token and payload_token and query_token != payload_token:
        identity = None  # conflicting tokens: never guess
    else:
        identity = app.auth.validate(payload_token or query_token)
    if identity is None:
        await conn.send_json(
            {
                "type": "error",
                "code": "auth.invalid",
                "message": "invalid session token",
                "recoverable": False,
            }
        )
        await websocket.close(_WS_CLOSE_AUTH)
        return
    bind_context(session_id=identity.session_id)

    if not app.sessions.acquire_channel(identity.session_id):  # 1/session, 10 global
        await conn.send_json(
            {
                "type": "error",
                "code": "E-RATE-LIMIT",
                "message": "session channel busy",
                "recoverable": True,
            }
        )
        await websocket.close(_WS_CLOSE_RATE)
        return

    session = app.sessions.get(identity.session_id)
    resume = bool(first.get("resume"))
    if session is None:
        session = app.sessions.create(
            identity, profile="normal", locale=str(first.get("locale") or "hi-en")
        )
    # profile is SERVER-asserted (spec.md §11); the demo flag lives on the
    # session row the core backend owns — the client can never claim it.
    conn.session = session

    if resume:
        await _replay(conn, session, str(first.get("last_turn_id") or ""))
    else:
        # H1 — remaining tranche (profile-aware) vs 0 (spec.md §8).
        decision = app.guard.check_start(session.profile, session.user_key, now=now())
        if not decision.allowed and session.profile != "demo":
            await conn.send_json(
                {
                    "type": "error",
                    "code": decision.reason_code,
                    "message": "daily credit tranche exhausted",
                    "recoverable": False,
                }
            )
            await websocket.close(_WS_CLOSE_NORMAL)
            app.sessions.release_channel(session.session_id)
            return
        if not decision.allowed:  # demo profile: downgrade, judge still gets text
            session.text_only = True
        session.state = "idle"
        await _send_state(conn, "idle")
        await conn.send_json(
            {
                "type": "session.ready",
                "session_id": session.session_id,
                "profile": session.profile,
                "state": "text_only" if session.text_only else decision.state,
                "server_time": int(now() * 1000),
            }
        )
        anchor = first.get("anchor")
        if isinstance(anchor, dict):
            _store_snapshot(conn, anchor)

    # Pre-open the vendors the turn will need (mock mode or configured keys).
    if settings.mock_mode or settings.stt_configured or settings.brain_configured:
        pass  # factories are lazy: built at first use, per spec factories DI

    try:
        await _message_loop(conn)
    finally:
        app.sessions.release_channel(session.session_id)
        if conn.pump_task is not None:
            conn.pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await conn.pump_task
        if conn.turn_task is not None and not conn.turn_task.done():
            conn.turn_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await conn.turn_task
        if conn.stt is not None:
            with contextlib.suppress(Exception):
                await conn.stt.close()
        if conn.tts is not None:
            with contextlib.suppress(Exception):
                await conn.tts.close()
        log_event(
            "voice.session.closed",
            {"turns": session.turn_idx},
            session_id=session.session_id,
        )


async def _replay(conn: _Connection, session: VoiceSession, last_turn_id: str) -> None:
    """F5 resume: replay agent.state + the lost turn's turn.end (60 s window)."""
    app = conn.app
    if app.sessions.replay_window_alive(session, now=app._clock()):
        if session.last_state_message:
            await conn.send_json(session.last_state_message)
        await conn.send_json(session.last_turn_end or {})
        await conn.send_json(
            {
                "type": "session.ready",
                "session_id": session.session_id,
                "profile": session.profile,
                "state": "resumed",
                "server_time": int(app._clock() * 1000),
            }
        )
        return
    # window expired: abort the lost turn honestly (F5 → F3 semantics)
    lost = {
        "type": "turn.end",
        "turn_id": last_turn_id or "unknown",
        "end_reason": "error",
        "latency_ms": {},
        "usage": {},
    }
    await conn.send_json(lost)
    session.last_turn_end = lost
    session.last_turn_end_at = app._clock()
    await conn.send_json(
        {
            "type": "session.ready",
            "session_id": session.session_id,
            "profile": session.profile,
            "state": "resumed",
            "server_time": int(app._clock() * 1000),
        }
    )


def _store_snapshot(conn: _Connection, payload: dict[str, Any]) -> None:
    try:
        snapshot = anchoring.parse_snapshot(
            payload, max_bytes=conn.settings.snapshot_max_bytes
        )
        assert conn.session is not None  # set before any snapshot can arrive
        conn.session.snapshot = payload
        conn.session.snapshot_at = conn.app._clock()
        conn._snapshot_obj = snapshot
    except anchoring.SnapshotError:
        # keep the last good snapshot; a bad one never crashes the loop (F7)
        log_event(
            "voice.snapshot.rejected",
            {},
            severity=Severity.WARNING,
            error_class=ErrorClass.CLIENT_ERROR,
            session_id=conn.session.session_id if conn.session else None,
        )


async def _send_state(conn: _Connection, state: str, reason: str | None = None) -> None:
    if conn.session is not None:
        conn.session.state = state
    message = {"type": "agent.state", "state": state}
    if reason:
        message["reason"] = reason
    await conn.send_json(message)


async def _send_error(
    conn: _Connection, code: str, message: str, recoverable: bool
) -> None:
    await conn.send_json(
        {"type": "error", "code": code, "message": message, "recoverable": recoverable}
    )


# --- message loop ---------------------------------------------------------------


async def _message_loop(conn: _Connection) -> None:
    app = conn.app
    settings = app.settings
    websocket = conn.ws
    while True:
        try:
            received = await websocket.receive()
        except WebSocketDisconnect:
            return
        if received["type"] == "websocket.disconnect":
            return
        if received.get("bytes"):
            await _on_audio_chunk(conn, received["bytes"])
            continue
        text = received.get("text")
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            continue  # tolerated: control frames are JSON per contract
        mtype = message.get("type")
        if mtype == "ping":
            await conn.send_json({"type": "pong", "t": message.get("t")})
            conn.pong_misses = 0
        elif mtype == "pong":
            conn.pong_misses = 0
        elif mtype == "context.snapshot":
            _store_snapshot(conn, message)
        elif mtype == "audio.start":
            await _on_audio_start(conn)
        elif mtype == "audio.end":
            await _on_audio_end(conn)
        elif mtype == "typed.doubt":  # S0 message: the F1 text path
            await _on_typed_doubt(conn, message)
        elif mtype == "interrupt":
            await _on_interrupt(conn)
        elif mtype == "session.start":
            await conn.send_json(
                {
                    "type": "error",
                    "code": "auth.invalid",
                    "message": "session already started",
                    "recoverable": False,
                }
            )
        else:
            log_event(
                "voice.ws.unknown_message",
                {"mtype": str(mtype)},
                severity=Severity.WARNING,
                error_class=ErrorClass.CLIENT_ERROR,
                session_id=conn.session.session_id if conn.session else None,
            )
        if settings.ws_ping_interval_s <= 0:  # pragma: no cover — tests drive
            continue


# --- audio-path handlers ----------------------------------------------------------


def _ensure_stt(conn: _Connection) -> SttSession:
    """One Prisma session per WS session (spec.md §2 stage 3), opened lazily."""
    if conn.stt is None:
        conn.stt = conn.app.stt_factory(conn.settings)
    return conn.stt


def _arm_stt_pump(conn: _Connection) -> None:
    """(Re)arm the upstream event pump — AFTER stt.start().

    The pump forwards upstream events into the queue; when the stream dies
    (``None``) the pump exits and is re-armed at the next ``audio.start`` —
    the SttClient itself owns reconnect-with-resume inside its budget.
    """
    if conn.pump_task is not None and not conn.pump_task.done():
        return

    async def pump() -> None:
        assert conn.stt is not None
        while True:
            event = await conn.stt.next_event()
            await conn.stt_queue.put(event)  # None = stream died (F1)
            if event is None:
                return  # re-armed at the next audio.start

    conn.pump_task = asyncio.ensure_future(pump())


def _ensure_tts(conn: _Connection) -> TtsClient:
    if conn.tts is None:
        conn.tts = conn.app.tts_factory(conn.settings)
    return conn.tts


def _ensure_brain(conn: _Connection) -> BrainClient:
    if conn.brain is None:
        conn.brain = conn.app.brain_factory(conn.settings)
    return conn.brain


async def _on_audio_start(conn: _Connection) -> None:
    session = conn.session
    assert session is not None
    session.interrupt_times.clear()  # F8: window resets at each new press
    conn.stt_uplink = UplinkStream()
    while not conn.stt_queue.empty():  # stale events never pollute the turn
        conn.stt_queue.get_nowait()
    if session.text_only:
        await _send_state(conn, "listening", reason="text_only")
        return
    try:
        stt = _ensure_stt(conn)
        await stt.start()
        _arm_stt_pump(conn)  # pump runs only once the upstream is open
        await _send_state(conn, "listening")
    except Exception:  # noqa: BLE001 — F1: any STT failure degrades to text
        conn.stt = None
        await _send_error(
            conn, "stt.unavailable", "voice input unavailable — type your doubt", True
        )
        await _send_state(conn, "listening", reason="text_input")


async def _on_audio_chunk(conn: _Connection, frame: bytes) -> None:
    session = conn.session
    assert session is not None
    if session.text_only:
        return  # text-only dock keeps mic closed; be safe anyway
    pcm = conn.stt_uplink.accept(frame)
    if pcm is None or conn.stt is None:
        return
    try:
        await conn.stt.send_audio(pcm)
    except SttUnavailableError:
        conn.stt = None
        await _send_error(
            conn, "stt.unavailable", "voice input unavailable — type your doubt", True
        )
        await _send_state(conn, "listening", reason="text_input")


async def _on_audio_end(conn: _Connection) -> None:
    session = conn.session
    assert session is not None
    if conn.turn_task is not None and not conn.turn_task.done():
        return  # a turn is already in flight: ignore double EOS
    if session.text_only or conn.stt is None:
        await _send_state(conn, "listening", reason="text_input")
        return
    with contextlib.suppress(Exception):
        await conn.stt.finish()  # EOS reaches Prisma: the final may now land
    turn = _Turn(
        turn_id=new_turn_id(),
        turn_idx=session.turn_idx + 1,
        kind="audio",
        started_at=conn.app._clock(),
        audio_end_at=conn.app._clock(),
    )
    conn.turn_task = asyncio.ensure_future(_run_audio_turn(conn, turn))


async def _on_typed_doubt(conn: _Connection, message: dict[str, Any]) -> None:
    session = conn.session
    assert session is not None
    if conn.turn_task is not None and not conn.turn_task.done():
        await _send_error(conn, "client_error", "a turn is already in progress", True)
        return
    text = str(message.get("text") or "").strip()
    if not text or len(text) > conn.settings.typed_text_max_chars:
        await _send_error(
            conn, "client_error", "typed doubt must be 1..1000 chars", True
        )
        return
    turn = _Turn(
        turn_id=new_turn_id(),
        turn_idx=session.turn_idx + 1,
        kind="typed",
        transcript=text,
        started_at=conn.app._clock(),
        audio_end_at=conn.app._clock(),
    )
    conn.turn_task = asyncio.ensure_future(_run_brain_turn(conn, turn, typed=True))


async def _on_interrupt(conn: _Connection) -> None:
    """Barge-in (ADR-0010 + ws-contract §5) with the F8 storm guard."""
    session = conn.session
    assert session is not None
    now = conn.app._clock()
    session.interrupt_times.append(now)
    window = [
        t
        for t in session.interrupt_times
        if now - t <= conn.settings.interrupt_storm_window_s
    ]
    session.interrupt_times = window
    if len(window) > conn.settings.interrupt_storm_max:
        await _send_state(
            conn, session.state or "listening", reason="interrupt_ignored"
        )
        return
    if conn.turn_task is None or conn.turn_task.done():
        return  # harmless no-op (contract: repeat = same intent)
    if conn.current_turn is not None:
        conn.current_turn.interrupted = True  # finalize will say "interrupted"
    if conn.brain is not None:
        await conn.brain.abort()  # close upstream mid-stream: frees the slot
    conn.turn_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await conn.turn_task
    conn.current_turn = None
    await _send_state(conn, "listening")
    if conn.stt is not None:  # echo guard: tutor audio just stopped
        conn.stt.arm_echo_guard(conn.settings.echo_guard_ms)


# --- turn pipeline ------------------------------------------------------------


async def _run_audio_turn(conn: _Connection, turn: _Turn) -> None:
    """audio.end → stt.final → H2 → brain → chunker → TTS → turn.end."""
    session = conn.session
    assert session is not None
    now = conn.app._clock
    try:
        assert conn.stt is not None
        deadline = now() + conn.settings.stt_final_timeout_s
        partial_seq = 0
        while True:
            remaining = deadline - now()
            if remaining <= 0:
                raise SttUnavailableError("stt.final did not arrive (L1)")
            try:
                event = await asyncio.wait_for(conn.stt_queue.get(), timeout=remaining)
            except TimeoutError as exc:
                raise SttUnavailableError("stt.final did not arrive (L1)") from exc
            if event is None:
                raise SttUnavailableError("Prisma stream closed before stt.final")
            if event.kind == "partial":
                partial_seq += 1
                await conn.send_json(
                    {
                        "type": "stt.partial",
                        "turn_id": turn.turn_id,
                        "seq": partial_seq,
                        "text": event.text,
                    }
                )
                continue
            turn.transcript = event.text
            turn.lang = event.lang or "hi-en"
            turn.confidence = event.confidence
            break
        turn.stt_final_at = now()
        turn.stamp("L1", turn.stt_final_at)
        turn.stt_seconds = conn.stt_uplink.audio_seconds
        await _run_brain_turn(conn, turn, typed=False)
    except SttUnavailableError as exc:
        # F1-adjacent: EOS arrived but no final — honest error turn.
        await _send_error(conn, "stt.unavailable", str(exc), True)
        await _send_state(conn, "listening", reason="text_input")
        await _finalize_turn(conn, turn, end_reason="error", event="stt.no_final")
    except asyncio.CancelledError:
        raise


async def _run_brain_turn(conn: _Connection, turn: _Turn, *, typed: bool) -> None:
    """Shared turn core: H2 → context → brain stream → chunker → TTS."""
    session = conn.session
    assert session is not None
    app = conn.app
    now = app._clock
    settings = app.settings
    await _send_state(conn, "thinking")  # NFR-06: cue ≤ 300 ms after EOS
    session.turn_idx = turn.turn_idx
    conn.current_turn = turn

    # H2 — estimated turn cost vs remaining (spec.md §8; ADR-0015 reserve).
    # Text turns (typed path, or a text_only session) spend NO Gnani credits:
    # brain tokens are tracked for capacity, never metered (backend-spec
    # §8.4) — so their voice estimate is 0 and they keep working when voice
    # is exhausted (F6: "text turns keep working (brain only)").
    estimate = 0 if (typed or session.text_only) else turn_estimate(settings)
    decision = app.guard.check_turn(
        session.profile, session.user_key, session.session_id, estimate, now=now()
    )
    turn.reserved = decision.reserved
    if not decision.allowed:
        await _over_credit_turn(conn, turn, decision.reason_code)
        return

    # F7 — snapshot freshness (stale > 2 s or missing → generic + honest).
    snapshot_obj = getattr(conn, "_snapshot_obj", None)
    stale = (
        snapshot_obj is None
        or (now() - session.snapshot_at) > settings.snapshot_stale_s
    )
    if snapshot_obj is None or stale:
        await _send_error(conn, "context.stale", "page ka context nahi mil raha", True)
    context_block = anchoring.build_prompt_context(snapshot_obj, settings, stale=stale)
    if stale:
        context_block = (
            context_block
            or "NO PAGE CONTEXT — answer generically, say you cannot see the page."
        )

    history = await app.turns.recent_turns(
        session.session_id, limit=settings.history_turns_max
    )
    messages = tuple(
        BrainMessage(
            "user" if row.role == "student" else "assistant",
            row.text,
        )
        for row in history
    )
    request = BrainRequest(
        system=TUTOR_SYSTEM_PROMPT,
        context_block=context_block,
        history=messages,
        transcript=turn.transcript,
    )
    turn.brain_called_at = now()
    turn.stamp("L2", turn.brain_called_at)

    # F4 at turn start: audio is disabled for the whole turn, the answer
    # still flows as text (spec.md F4: "reply text appears in dock immediately")
    await _ensure_tts_turn(conn)
    brain = _ensure_brain(conn)
    brain.retries_used = 0
    brain.events_yielded = 0
    ids = SegmentIds()
    chunker = SentenceChunker(ids, clock=now)
    filler_task = asyncio.ensure_future(_filler_timer(conn, turn))
    first_event_at: float | None = None
    usage: dict[str, Any] = {}
    brain_error: Exception | None = None
    summaries_voiced = 0
    try:
        async for event in brain.stream(request):
            if event.kind == "usage":
                usage = _usage_dict(event, usage)
                continue
            if first_event_at is None and event.kind != "done":
                first_event_at = now()
                turn.stamp("L3", first_event_at)
            if event.kind == "ref":
                validated = anchoring.validate_ref_ids(event.ref_ids, snapshot_obj)
                if validated and not turn.highlight_sent:
                    # T7: highlight BEFORE or atomically with first audio
                    await conn.send_json(
                        {
                            "type": "highlight",
                            "turn_id": turn.turn_id,
                            "block_ids": list(validated),
                        }
                    )
                    turn.highlight_sent = True
                continue
            if event.kind == "thought" and settings.thinking_summaries:
                summaries_voiced = await _speak_summary(
                    conn, turn, event.text, summaries_voiced
                )
                continue
            if event.kind == "summary":
                summaries_voiced = await _speak_summary(
                    conn, turn, event.text, summaries_voiced
                )
                continue
            if event.kind == "content":
                for chunk in chunker.feed(event.text):
                    await _dispatch_chunk(conn, turn, chunk)
        for chunk in chunker.flush():
            await _dispatch_chunk(conn, turn, chunk)
    except BrainFirstEventTimeout:
        brain_error = BrainFirstEventTimeout()  # F2
    except BrainStallError as exc:
        brain_error = exc  # F3
    except BrainDeadlineError as exc:
        brain_error = exc  # F3
    except TtsUnavailableError as exc:
        brain_error = exc  # F4 — handled inside _dispatch_chunk, but escape guard
    except asyncio.CancelledError:
        filler_task.cancel()
        await _finalize_turn(
            conn, turn, end_reason="interrupted", event="turn.interrupted"
        )
        raise
    finally:
        filler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await filler_task
        if brain is not None:
            with contextlib.suppress(Exception):
                await brain.abort()  # ensure the upstream is closed at turn end
        await _close_tts_turn(conn)

    if brain_error is not None:
        await _brain_error_turn(conn, turn, brain_error, chunker, usage)
        return

    turn.usage = usage
    await _finalize_turn(conn, turn, end_reason="done", event=None)


def _usage_dict(event: BrainEvent, usage: dict[str, Any]) -> dict[str, Any]:
    if event.usage is not None:
        if event.usage.prompt_tokens is not None:
            usage["brain_prompt_tokens"] = event.usage.prompt_tokens
        if event.usage.completion_tokens is not None:
            usage["brain_completion_tokens"] = event.usage.completion_tokens
        if event.usage.thinking_tokens is not None:
            usage["thinking_tokens"] = event.usage.thinking_tokens
    return usage


async def _filler_timer(conn: _Connection, turn: _Turn) -> None:
    """ADR-0018 option A: one safe filler if dead air passes the budget."""
    session = conn.session
    assert session is not None
    settings = conn.settings
    await asyncio.sleep(settings.filler_silence_ms / 1000.0)
    if turn.audio_dispatched or turn.end_reason != "done":
        return
    pool = [f for f in _FILLERS if f not in session.recent_fillers] or list(_FILLERS)
    filler = random.choice(pool)
    session.recent_fillers.append(filler)
    session.recent_fillers = session.recent_fillers[-3:]
    turn.answer_text = (turn.answer_text + " " + filler).strip()
    await _send_state(conn, "speaking", reason="filler")
    await conn.send_json(
        {
            "type": "tts.text",
            "turn_id": turn.turn_id,
            "segment_id": 0,
            "kind": "filler",
            "text": filler,
        }
    )
    await _speak_text(conn, turn, filler, kind="filler")


async def _speak_summary(
    conn: _Connection, turn: _Turn, text: str, already_voiced: int
) -> int:
    """Thinking-out-loud harness (ADR-0018): whitelist → TTS now; else text.

    Both paths surface the line in the transcript panel (tts.text); only the
    T12-procedural ones additionally reach the speaker, and the T7 ordering
    rule (highlight before first audio) is preserved because everything here
    is awaited inline.
    """
    panel = {
        "type": "tts.text",
        "turn_id": turn.turn_id,
        "segment_id": 0,
        "kind": "summary",
        "text": text,
    }
    over_budget = (
        already_voiced >= conn.settings.summaries_max_per_turn
        or len(text) > conn.settings.summary_max_chars
    )
    if over_budget or not is_procedural_summary(text):
        # T12: substantive/over-budget — visible, never voiced.
        await conn.send_json(panel)
        return already_voiced
    await conn.send_json(panel)
    await _speak_text(conn, turn, text, kind="summary")
    return already_voiced + 1


async def _dispatch_chunk(conn: _Connection, turn: _Turn, chunk: Chunk) -> None:
    """Chunk → tts.text (panel) → tts.audio frames; T7 ordering; F4 degrade."""
    now = conn.app._clock
    if turn.first_segment_at is None:
        turn.first_segment_at = now()
        turn.stamp("L4", turn.first_segment_at)
        turn.stamp("L5", turn.first_segment_at)  # chunker+whitelist handoff
    turn.answer_text = (turn.answer_text + " " + chunk.text).strip()
    await conn.send_json(
        {
            "type": "tts.text",
            "turn_id": turn.turn_id,
            "segment_id": chunk.segment_id,
            "kind": chunk.kind,
            "text": chunk.text,
        }
    )
    await _speak_text(
        conn, turn, chunk.text, kind=chunk.kind, segment_id=chunk.segment_id
    )


async def _ensure_tts_turn(conn: _Connection) -> bool:
    """Open Timbre once per turn — the H3 meters are per turn (spec.md §8).

    False ⇒ F4: the turn continues text-only (SpeechSynthesis is never used).
    """
    tts = _ensure_tts(conn)
    if conn._tts_turn_open:
        return True
    try:
        await tts.start_turn()
    except TtsUnavailableError:
        conn._tts_turn_open = False
        await _send_error(
            conn, "tts.unavailable", "audio nahi aa paya — jawab text mein hai", True
        )
        await _send_state(conn, "speaking_text")
        return False
    conn._tts_turn_open = True
    return True


async def _close_tts_turn(conn: _Connection) -> None:
    if conn.tts is not None and conn._tts_turn_open:
        with contextlib.suppress(Exception):
            await conn.tts.close_turn()
    conn._tts_turn_open = False


async def _speak_text(
    conn: _Connection,
    turn: _Turn,
    text: str,
    *,
    kind: str,
    segment_id: int | None = None,
) -> None:
    """Stream one segment through Timbre; on F4 degrade to text-only."""
    now = conn.app._clock
    if not await _ensure_tts_turn(conn):
        return  # text already on the panel
    tts = _ensure_tts(conn)
    seg = segment_id if segment_id is not None else 0
    try:
        async for audio in tts.speak(text, seg, kind=kind):
            if audio.final:
                break
            if turn.first_audio_at is None:
                turn.first_audio_at = now()
                turn.stamp("L6", turn.first_audio_at)
                if not turn.audio_dispatched:
                    turn.audio_dispatched = True
                    await _send_state(conn, "speaking")
            payload = pack_downlink(seg, _next_audio_seq(turn), audio.data)
            await conn.send_bytes(payload)
        final_frame = pack_downlink(seg, _next_audio_seq(turn), b"", final=True)
        await conn.send_bytes(final_frame)
    except TtsUnavailableError:
        conn._tts_turn_open = False
        # F4: text-only for the rest of the turn; tts.text already on the panel
        await _send_error(
            conn, "tts.unavailable", "audio nahi aa paya — jawab text mein hai", True
        )
        await _send_state(conn, "speaking_text")


def _next_audio_seq(turn: _Turn) -> int:
    seq = turn.audio_seq  # monotonic per segment, from 0 (ws-contract §3)
    turn.audio_seq += 1
    return seq


async def _over_credit_turn(conn: _Connection, turn: _Turn, reason_code: str) -> None:
    """H2 breach: fixed ≤ 15-char line, honest error, text-only henceforth."""
    session = conn.session
    assert session is not None
    line = conn.settings.over_credit_line
    await _send_state(conn, "speaking", reason="over_credit")
    await conn.send_json(
        {
            "type": "tts.text",
            "turn_id": turn.turn_id,
            "segment_id": 1,
            "kind": "speech",
            "text": line,
        }
    )
    turn.answer_text = (turn.answer_text + " " + line).strip()
    if await _ensure_tts_turn(conn):
        try:
            tts = _ensure_tts(conn)
            async for audio in tts.speak(line, 1, kind="speech"):
                if audio.final:
                    break
                await conn.send_bytes(
                    pack_downlink(1, _next_audio_seq(turn), audio.data)
                )
            await conn.send_bytes(
                pack_downlink(1, _next_audio_seq(turn), b"", final=True)
            )
        except TtsUnavailableError:
            conn._tts_turn_open = False
            await _send_state(conn, "speaking_text")
    await _close_tts_turn(conn)
    await _send_error(conn, reason_code, "daily credit limit reached", False)
    session.text_only = True  # F6: text turns keep working (brain only)
    await _finalize_turn(conn, turn, end_reason="error", event="credit.over")


async def _brain_error_turn(
    conn: _Connection,
    turn: _Turn,
    error: Exception,
    chunker: SentenceChunker,
    usage: dict[str, Any],
) -> None:
    """F2 (first-event) / F3 (stall|deadline) — the honest degraded paths."""
    turn.usage = usage
    if isinstance(error, BrainFirstEventTimeout):
        code = "brain.first_event_timeout"
    elif isinstance(error, BrainDeadlineError):
        code = "brain.deadline"
    else:
        code = "brain.midturn_stall"
    # F3: whatever was already spoken stays; the unspoken remainder is written
    for chunk in chunker.flush():
        await conn.send_json(
            {
                "type": "tts.text",
                "turn_id": turn.turn_id,
                "segment_id": chunk.segment_id,
                "kind": "speech",
                "text": chunk.text,
            }
        )
    await _send_error(conn, code, str(error) or "brain timeout", recoverable=True)
    await _send_state(conn, "error", reason=code)
    await _finalize_turn(conn, turn, end_reason="error", event=f"brain.{code}")


async def _finalize_turn(
    conn: _Connection, turn: _Turn, *, end_reason: str, event: str | None
) -> None:
    """turn.end + H4 ledger write (meters read NOW, not at turn start)."""
    session = conn.session
    assert session is not None
    app = conn.app
    turn.end_reason = end_reason if not turn.interrupted else "interrupted"
    usage = dict(turn.usage)
    usage.setdefault("brain_prompt_tokens", None)
    usage.setdefault("brain_completion_tokens", None)
    usage.setdefault("thinking_tokens", None)
    usage.update(
        {
            "stt_audio_s": round(turn.stt_seconds, 3),
            "tts_chars": _tts_chars(conn),
            "retries": conn.brain.retries_used if conn.brain is not None else 0,
        }
    )
    message = {
        "type": "turn.end",
        "turn_id": turn.turn_id,
        "end_reason": turn.end_reason,
        "latency_ms": turn.latency,
        "usage": usage,
    }
    await conn.send_json(message)
    session.last_turn_end = message
    session.last_turn_end_at = app._clock()

    # H4 — credit ledger (OQ-06 unit placeholder: STT seconds + TTS chars)
    actual = int(turn.stt_seconds + usage["tts_chars"])
    app.guard.commit_turn(
        session.profile,
        session.user_key,
        session.session_id,
        estimate=turn.reserved,
        actual=actual,
        now=app._clock(),
    )

    # voice_turn rows (A-02, Appendix B) — transcripts only, never audio
    try:
        await app.turns.append_turn(
            TurnRecord(
                id=turn.turn_id,
                session_id=session.session_id,
                turn_idx=turn.turn_idx,
                role="student",
                text=turn.transcript,
                lang=turn.lang,
                stt_confidence=turn.confidence,
                latency_ms=turn.latency,
                usage_json=usage,
                credit_cost=float(actual),
                profile=session.profile,
            )
        )
        if turn.answer_text:
            await app.turns.append_turn(
                TurnRecord(
                    id=str(uuid.uuid4()),
                    session_id=session.session_id,
                    turn_idx=turn.turn_idx,
                    role="tutor",
                    text=turn.answer_text,
                    lang=turn.lang,
                    block_ids_ref=(),
                    usage_json={"tts_chars": usage["tts_chars"]},
                    credit_cost=0.0,
                    profile=session.profile,
                )
            )
        if event:
            await app.turns.append_turn(
                TurnRecord(
                    id=str(uuid.uuid4()),
                    session_id=session.session_id,
                    turn_idx=turn.turn_idx,
                    role="event",
                    text=event,  # incident id only — never audio, never transcripts
                    profile=session.profile,
                )
            )
    except Exception:  # noqa: BLE001 — ledger write must not break the loop
        log_event(
            "voice.turn.ledger_failed",
            {},
            severity=Severity.ERROR,
            error_class=ErrorClass.STORE_ERROR,
            session_id=session.session_id,
            turn_id=turn.turn_id,
        )
    await _send_state(conn, "idle")
    log_event(
        "voice.turn.e2e_latency",
        {"end_reason": turn.end_reason},
        latency_ms=turn.latency.get("L6") or 0,
        session_id=session.session_id,
        turn_id=turn.turn_id,
    )


def _tts_chars(conn: _Connection) -> int:
    return conn.tts.meters.chars_billed if conn.tts is not None else 0
