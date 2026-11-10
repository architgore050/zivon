"""Timbre v3.0 realtime TTS client — spec.md §3 ``tts_client``, ADR-0020.

Streams tutor text in (whitelisted audio tags inline), audio frames out;
carries the per-turn char meter for the H3 credit guard. Tags bill as
characters (AGENTS.md), so the meter counts the outgoing text INCLUDING tag
characters.

H3 is a harness guarantee, not prompt prose (spec.md §8 hook table):

- only the whitelisted subset of the Timbre v3 13-tag catalog may be spoken
  — the tutor prompt contract allows ``<pauses> <slow> <excited>
  <whispers>`` (spec.md Appendix A); every other tag (known or unknown) is
  stripped server-side;
- tag budget: ≤ 1 tag per 2 sentences cumulatively per turn, ≤
  ``tts_tag_max_per_turn`` hard cap — excess tags stripped before send;
- char cap: ``ZIVON_VOICE_TTS_CHAR_CAP_TURN`` (default 1200) — text beyond
  the cap is truncated and a fixed closing line is spoken instead; the cap
  can never be blown by the dead-air policy (ADR-0018 budgets share it).

OQ-03 [ASSUMPTION] — the exact Timbre realtime contract (WS vs REST, output
format/rate) is verified by a live probe at build time and recorded in
ws-contract.md §3 notes. Until then this client codes against the assumed
shape: auth via ``Authorization: Bearer <GNANI key>``, per-segment JSON text
requests, binary Opus 20 ms frames back with a JSON
``{"type": "segment_end"}`` marker. A REST fallback path exists for
non-streaming synthesis (probes + degraded modes).

Failure mode F4 (spec.md §9): connect/send errors surface as
``TtsUnavailableError``; the caller degrades to text-only for the turn —
browser SpeechSynthesis is never used (product story = Gnani voice).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .config import VoiceSettings
from .logging_surface import ErrorClass, Severity, log_event

__all__ = [
    "ALLOWED_TAGS",
    "CLOSING_LINE",
    "TIMBRE_V3_TAGS",
    "PreparedSpeech",
    "TtsAudio",
    "TtsClient",
    "TtsTransport",
    "TtsUnavailableError",
]

# The 13-tag Timbre v3.0 catalog (AGENTS.md Gnani notes, verified 2026-11-07).
TIMBRE_V3_TAGS = frozenset(
    {
        "laugh",
        "giggle",
        "sigh",
        "exhales",
        "sniffles",
        "yawns",
        "coughs",
        "clears throat",
        "whispers",
        "shouting",
        "excited",
        "slow",
        "pauses",
    }
)
# The tutor's whitelisted subset (spec.md Appendix A spoken contract).
ALLOWED_TAGS = frozenset({"pauses", "slow", "excited", "whispers"})

# Spoken when the turn's char cap truncates the answer (H3 closing line).
CLOSING_LINE = "<pauses>… theek hai, aage ka agle turn mein."

_TAG_RX = re.compile(r"<([a-zA-Z ]+?)>")
_SENTENCE_END = re.compile(r"[।.!?…]\s*")

# Barge-in drain budget: Timbre's tail frames of a cancelled segment arrive
# within ~a segment's synthesis time; past this the socket is reset instead.
_ABORT_DRAIN_S = 0.75


class TtsUnavailableError(RuntimeError):
    """Timbre could not be opened or died mid-turn (F4 → text-only)."""


class TtsTransport(Protocol):
    """The slice of a websocket connection the client uses (test seam)."""

    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


ConnectFactory = Callable[[], Awaitable[TtsTransport]]


def default_connect(settings: VoiceSettings) -> Callable[[], Awaitable[TtsTransport]]:
    """Live transport: Timbre v3.0 realtime WS with the Gnani key header."""

    async def _connect() -> TtsTransport:
        try:  # websockets >= 13 (new asyncio implementation)
            from websockets.asyncio.client import connect as ws_connect
        except ImportError:  # websockets 12 (legacy client, same surface)
            from websockets import connect as ws_connect  # type: ignore[no-redef]

        headers = {"Authorization": f"Bearer {settings.gnani_tts_api_key}"}
        try:
            return await ws_connect(settings.tts_url, additional_headers=headers)  # type: ignore[no-untyped-call]
        except TypeError:  # websockets < 14 named the option extra_headers
            return await ws_connect(settings.tts_url, extra_headers=headers)  # type: ignore[no-untyped-call,no-redef]

    return _connect


@dataclass(frozen=True)
class PreparedSpeech:
    """The H3-guarded outcome for one outbound text chunk."""

    text: str  # exactly what is billed and sent (may include kept tags)
    chars_billed: int
    tags_kept: int
    tags_stripped: int
    truncated: bool


@dataclass(frozen=True)
class TtsAudio:
    """One audio frame from Timbre (format pinned at OQ-03)."""

    data: bytes
    final: bool


@dataclass
class _TurnMeters:
    """Per-turn meters (H3 + H4); audio bytes are never retained (ADR-0008)."""

    chars_billed: int = 0
    tags_used: int = 0
    sentences: int = 0
    segments: int = 0
    first_audio_s: float | None = None
    tags_stripped_total: int = 0


class TtsClient:
    """Streaming TTS with the H3 harness guarantees and char metering.

    One client per WS session; ``start_turn``/``close_turn`` bracket a turn.
    Audio frames exist only inside the iterator — the client never stores
    them (ADR-0008).
    """

    def __init__(
        self,
        settings: VoiceSettings,
        connect_factory: Callable[[], Awaitable[TtsTransport]] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._connect_factory = connect_factory or default_connect(settings)
        self._clock = clock
        self._ws: TtsTransport | None = None
        self._turn_open = False
        self._turn_start = 0.0
        self.meters = _TurnMeters()

    async def start_turn(self) -> None:
        """Open the Timbre session (per turn; reconnects are per session)."""
        if self._ws is None:
            self._ws = await self._open()
        self._turn_open = True
        self._turn_start = self._clock()
        self.meters = _TurnMeters()

    async def speak(
        self, text: str, segment_id: int, kind: str = "speech"
    ) -> AsyncGenerator[TtsAudio, None]:
        """Send one prepared chunk; yield audio frames as they arrive.

        Raises TtsUnavailableError on transport death (F4) — the caller
        degrades to text-only; meters keep what was already spoken.
        """
        if not self._turn_open or self._ws is None:
            raise TtsUnavailableError("start_turn() first")
        prepared = self.prepare(text, kind=kind)
        if not prepared.text:
            return
        self.meters.segments += 1
        request = {
            "type": "speak",
            "segment_id": segment_id,
            "kind": kind,
            "text": prepared.text,
            "voice": self._settings.tts_voice,
            "format": "opus_20ms",  # ADR-0020 downlink; pinned at OQ-03
        }
        await self._send(json.dumps(request))
        while True:
            try:
                raw = await self._ws.recv()
            except Exception as exc:
                self._ws = None
                raise TtsUnavailableError(f"Timbre stream died: {exc}") from exc
            if isinstance(raw, bytes):
                if self.meters.first_audio_s is None:
                    self.meters.first_audio_s = self._clock() - self._turn_start
                yield TtsAudio(data=raw, final=False)
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue  # tolerated gap: OQ-03 contract is not final yet
            if event.get("type") == "segment_end":
                if self.meters.first_audio_s is None:
                    self.meters.first_audio_s = self._clock() - self._turn_start
                yield TtsAudio(data=b"", final=True)
                return
            if event.get("type") == "error":
                raise TtsUnavailableError(str(event.get("message", "timbre error")))

    async def close_turn(self) -> None:
        """End the turn; meters stay readable for the H4 ledger write."""
        self._turn_open = False

    async def abort(self) -> None:
        """Barge-in: discard the cancelled segment's unread frames.

        One Timbre socket is shared across turns, so a cancelled ``speak()``
        iterator leaves frames (and the segment's ``segment_end``) waiting in
        the socket. Draining to ``segment_end`` here is what stops the next
        turn from playing the previous answer's tail. If the drain cannot
        finish within its small budget, the socket is closed and the next
        ``start_turn`` reconnects — honesty over a stuck stream.
        """
        self._turn_open = False
        ws = self._ws
        if ws is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _ABORT_DRAIN_S
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await self.close()  # could not reach segment_end: reconnect next
                return
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except Exception:  # noqa: BLE001 — transport-agnostic seam
                await self.close()
                return
            if not isinstance(raw, str):
                continue  # an audio frame of the cancelled segment
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "segment_end":
                return  # tail fully consumed; the socket is clean for the next turn
            if event.get("type") == "error":
                await self.close()
                return

    async def close(self) -> None:
        self._turn_open = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None

    # --- H3 guard -------------------------------------------------------------

    def prepare(self, text: str, kind: str = "speech") -> PreparedSpeech:
        """Apply the tag whitelist, tag budget, and char cap to one chunk.

        Pure function of the text + the turn's meters — deterministic and
        unit-testable without a transport (spec.md §8: the cap is a harness
        guarantee).
        """
        settings = self._settings
        sentences = len(_SENTENCE_END.findall(text))
        self.meters.sentences += sentences

        def _tag_budget() -> int:
            # ≤ 1 tag / 2 sentences cumulatively (min 1 so a short first
            # chunk may still carry one cue), ≤ hard cap per turn.
            by_ratio = max(1, self.meters.sentences // settings.tts_tag_sentences_ratio)
            remaining_ratio = max(0, by_ratio - self.meters.tags_used)
            remaining_hard = max(
                0, settings.tts_tag_max_per_turn - self.meters.tags_used
            )
            return min(remaining_ratio, remaining_hard)

        parts: list[str] = []
        last_end = 0
        kept: list[str] = []
        tags_kept = 0
        tags_stripped = 0
        for match in _TAG_RX.finditer(text):
            name = match.group(1).strip().lower()
            allowed = name in ALLOWED_TAGS
            if allowed and tags_kept < _tag_budget():
                tags_kept += 1
                kept.append(name)
                parts.append(text[last_end : match.end()])  # keep the tag
            else:
                tags_stripped += 1
                parts.append(text[last_end : match.start()])  # drop the tag
            last_end = match.end()
        parts.append(text[last_end:])
        stripped_text = "".join(parts)
        # normalize doubled spaces left by stripped tags
        stripped_text = re.sub(r" {2,}", " ", stripped_text).strip()

        cap_left = max(0, settings.tts_char_cap_turn - self.meters.chars_billed)
        truncated = False
        if len(stripped_text) > cap_left:
            truncated = True
            closing = CLOSING_LINE
            if cap_left > len(closing) + 1:
                piece = stripped_text[: cap_left - len(closing) - 1].rstrip()
                stripped_text = piece + " " + closing
            elif cap_left > 0:
                stripped_text = closing[:cap_left]
            else:
                stripped_text = ""
        billed = len(stripped_text)
        # prepare() owns the meters: every call is exactly what would be
        # billed and spoken (speak() forwards its result unchanged).
        self.meters.chars_billed += billed
        self.meters.tags_used += tags_kept
        self.meters.tags_stripped_total += tags_stripped
        return PreparedSpeech(
            text=stripped_text,
            chars_billed=billed,
            tags_kept=tags_kept,
            tags_stripped=tags_stripped,
            truncated=truncated,
        )

    # --- internals ------------------------------------------------------------

    async def _open(self) -> TtsTransport:
        last: Exception | None = None
        for _ in range(2):
            try:
                return await self._connect_factory()
            except Exception as exc:  # noqa: BLE001 — transport-agnostic seam
                last = exc
                log_event(
                    "voice.tts.connect_retry",
                    {},
                    severity=Severity.WARNING,
                    error_class=ErrorClass.TRANSPORT_ERROR,
                )
        raise TtsUnavailableError(f"Timbre connect failed: {last}")

    async def _send(self, data: str) -> None:
        if self._ws is None:
            raise TtsUnavailableError("not connected")
        try:
            await self._ws.send(data)
        except Exception as exc:
            self._ws = None
            raise TtsUnavailableError(f"Timbre send failed: {exc}") from exc
