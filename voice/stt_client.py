"""Prisma v3.0 streaming STT client (spec.md §3 ``stt_client``).

One Prisma streaming session per WS session (spec.md §2 stage 3): partials
are forwarded to the dock for live display, the brain is called only on the
final transcript (correctness over cleverness). Code-mixed Hinglish is normal
input, not an edge case.

OQ-02 [ASSUMPTION] — the exact Prisma v3.0 realtime contract (WS URL, auth
header, event JSON) is verified by a live probe at build time and recorded in
ws-contract.md §2 notes. Until then this client codes against the assumed
shape: auth via ``Authorization: Bearer <GNANI key>``; JSON text events
``{"type": "partial"|"final", "text", "lang"?, "confidence"?}``; EOS sent as
``{"type": "audio_end"}``. The event parser treats anything else as a
tolerated gap (counted, never crashes) — matching ws-contract.md §2 "STT
tolerates gaps".

Failure mode F1 (spec.md §9): connect/reconnect errors surface as
``SttUnavailableError``; the caller degrades to the typed-text path with the
same brain + TTS pipeline. No silent fallbacks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .config import VoiceSettings
from .logging_surface import ErrorClass, Severity, log_event

__all__ = [
    "FinalSource",
    "SttClient",
    "SttEvent",
    "SttTransport",
    "SttUnavailableError",
]


class SttUnavailableError(RuntimeError):
    """Prisma stream could not be opened or died past its retry budget (F1)."""


class SttTransport(Protocol):
    """The slice of a websocket connection the client uses (test seam)."""

    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


ConnectFactory = Callable[[VoiceSettings], Awaitable[SttTransport]]


def default_connect(settings: VoiceSettings) -> Callable[[], Awaitable[SttTransport]]:
    """Live transport: Prisma v3.0 realtime WS (verified against docs.gnani.ai
    2026-11-10: all configuration travels as upgrade headers, audio as binary
    PCM16, end-of-speech as a JSON ``{"type": "commit"}``)."""

    async def _connect() -> SttTransport:
        try:  # websockets >= 13 (new asyncio implementation)
            from websockets.asyncio.client import connect as ws_connect
        except ImportError:  # websockets 12 (legacy client, same surface)
            from websockets import connect as ws_connect  # type: ignore[no-redef]

        headers = {
            "x-api-key-id": settings.gnani_stt_api_key,
            "model": settings.stt_model,
            "language_code": settings.stt_language,
            "x-sample-rate": str(settings.stt_sample_rate),
        }
        try:
            return await ws_connect(settings.stt_url, additional_headers=headers)  # type: ignore[no-untyped-call]
        except TypeError:  # websockets < 14 named the option extra_headers
            return await ws_connect(settings.stt_url, extra_headers=headers)  # type: ignore[no-untyped-call,no-redef]

    return _connect


@dataclass(frozen=True)
class SttEvent:
    """A normalized Prisma event (partials and the final transcript)."""

    kind: str  # "partial" | "final"
    text: str
    seq: int
    lang: str = ""
    confidence: float | None = None


class SttClient:
    """Streaming STT session: send mic PCM, yield partial/final events.

    The client never buffers audio beyond the in-flight frame (ADR-0008):
    frames are forwarded to Prisma immediately and forgotten. Reconnects keep
    the same logical session (resume hint) within a small budget; past it the
    client raises SttUnavailableError so the caller can degrade honestly (F1).
    """

    def __init__(
        self,
        settings: VoiceSettings,
        connect_factory: Callable[[], Awaitable[SttTransport]] | None = None,
        *,
        reconnect_attempts: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._connect_factory = connect_factory or default_connect(settings)
        self._reconnect_attempts = reconnect_attempts
        self._clock = clock
        self._ws: SttTransport | None = None
        self._closed = False
        self._seq = 0
        self.echo_guard_until: float = 0.0
        # counters only — never the audio, never the transcript text
        self.audio_seconds = 0.0
        self.partials = 0
        self.finals = 0
        self.dropped_echo = 0
        self.dropped_unparsed = 0
        self.reconnects = 0

    async def start(self) -> None:
        """Open the upstream stream.

        Prisma v3.0 realtime takes its configuration (model, language,
        sample rate, key) as WebSocket upgrade headers, so there is no
        in-band config message — see ``default_connect``.
        """
        if self._closed:
            raise SttUnavailableError("client already closed")
        if self._ws is None:
            self._ws = await self._open_with_retry()

    async def send_audio(self, pcm: bytes) -> None:
        """Forward one mic frame; bytes are dropped from memory after send."""
        if self._ws is None:
            raise SttUnavailableError("start() first")
        await self._send_bytes(pcm)
        self.audio_seconds += len(pcm) / 2 / self._settings.stt_sample_rate

    async def finish(self) -> None:
        """Signal end-of-speech upstream (Prisma realtime EOS = ``commit``)."""
        await self._send(json.dumps({"type": "commit"}))

    async def next_event(self) -> SttEvent | None:
        """Next normalized event, or None when the upstream stream ended.

        The echo guard (ws-contract.md §5): STT events arriving within
        ``echo_guard_ms`` after tutor playback stops are dropped — the
        loudspeaker tail leak must not echo a tutor phrase back (OQ-07).
        """
        while not self._closed:
            if self._ws is None:
                raise SttUnavailableError("start() first")
            try:
                raw = await self._ws.recv()
            except Exception:  # noqa: BLE001 — any transport death → reconnect/F1
                if await self._maybe_reconnect():
                    continue
                return None
            if isinstance(raw, bytes):  # binary from upstream: not in contract
                self.dropped_unparsed += 1
                continue
            event = self._parse(raw)
            if event is None:
                continue
            if self._clock() < self.echo_guard_until:
                self.dropped_echo += 1
                continue
            return event
        return None

    def arm_echo_guard(self, duration_ms: int | None = None) -> None:
        """Drop STT events for the next ``duration_ms`` (playback just stopped)."""
        ms = self._settings.echo_guard_ms if duration_ms is None else duration_ms
        self.echo_guard_until = max(self.echo_guard_until, self._clock() + ms / 1000.0)

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None

    # --- internals -----------------------------------------------------------

    def _parse(self, raw: str) -> SttEvent | None:
        try:
            payload = json.loads(raw)
            kind = payload["type"]
        except (json.JSONDecodeError, KeyError, TypeError):
            self.dropped_unparsed += 1
            return None
        # Prisma v3.0 realtime emits one ``transcript`` event per VAD segment
        # (verified 2026-11-10); there is no separate partial stream. A
        # transcript is therefore the turn's final. ``partial``/``final`` stay
        # accepted so the mock transports and older shapes keep working.
        if kind == "transcript":
            text = payload.get("text")
            if not isinstance(text, str):
                self.dropped_unparsed += 1
                return None
            self.finals += 1
            self._seq += 1
            return SttEvent(
                kind="final",
                text=text,
                seq=self._seq - 1,
                lang=str(
                    payload.get("detected_language_code") or payload.get("lang") or ""
                ),
                confidence=None,
            )
        text = payload.get("text")
        if kind not in ("partial", "final") or not isinstance(text, str):
            self.dropped_unparsed += 1
            return None
        if kind == "partial":
            self.partials += 1
        else:
            self.finals += 1
        confidence = payload.get("confidence")
        event = SttEvent(
            kind=kind,
            text=text,
            seq=self._seq,
            lang=str(payload.get("lang", "")),
            confidence=float(confidence) if confidence is not None else None,
        )
        if kind == "final":
            self._seq += 1
        return event

    async def _open_with_retry(self) -> SttTransport:
        last: Exception | None = None
        for attempt in range(1 + self._reconnect_attempts):
            try:
                return await self._connect_factory()
            except Exception as exc:  # noqa: BLE001 — transport-agnostic seam
                last = exc
                log_event(
                    "voice.stt.connect_retry",
                    {"attempt": attempt + 1},
                    severity=Severity.WARNING,
                    error_class=ErrorClass.TRANSPORT_ERROR,
                )
        raise SttUnavailableError(f"Prisma connect failed: {last}")

    async def _maybe_reconnect(self) -> bool:
        if self._closed or self.reconnects >= self._reconnect_attempts:
            return False
        self.reconnects += 1
        try:
            self._ws = await self._open_with_retry()
        except SttUnavailableError:
            return False
        # Configuration lives in the upgrade headers, so the reconnect is
        # self-describing; there is no in-band resume handshake to replay.
        return True

    async def _send(self, data: str) -> None:
        if self._ws is None:
            raise SttUnavailableError("start() first")
        try:
            await self._ws.send(data)
        except Exception as exc:
            self._ws = None
            raise SttUnavailableError(f"Prisma send failed: {exc}") from exc

    async def _send_bytes(self, data: bytes) -> None:
        if self._ws is None:
            raise SttUnavailableError("start() first")
        try:
            await self._ws.send(data)
        except Exception as exc:
            self._ws = None
            raise SttUnavailableError(f"Prisma send failed: {exc}") from exc


class FinalSource(Protocol):
    """Anything that yields SttEvents (SttClient, mocks, core-backend adapter)."""

    async def next_event(self) -> SttEvent | None: ...


async def wait_for_final(
    source: FinalSource, timeout_s: float, clock: Callable[[], float] = time.monotonic
) -> SttEvent:
    """Await the final transcript (L1 row) or raise SttUnavailableError.

    Partials arriving before the final are consumed; ws_api runs its own
    event loop when it needs to forward partials live — this helper is for
    simple call sites and tests.
    """
    deadline = clock() + timeout_s
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise SttUnavailableError("stt.final did not arrive in time (L1)")
        try:
            event = await asyncio.wait_for(source.next_event(), timeout=remaining)
        except TimeoutError as exc:
            raise SttUnavailableError("stt.final did not arrive in time (L1)") from exc
        if event is None:
            raise SttUnavailableError("Prisma stream closed before stt.final")
        if event.kind == "final":
            return event
