"""Gnani Timbre v3.0 client for build-time narration.

The repo rule (AGENTS.md): no module hand-rolls ad-hoc HTTP to a model
endpoint - every external model call lives in a focused client module with
honest timeouts and bounded transport retries, mirroring the llm_manager
patterns (httpx, connect/read timeouts, exponential backoff + jitter on
429/5xx/transport errors, evidence-friendly failure types, nothing printed
from inside the client - the caller owns the voice).

Contract [ASSUMPTION - calibrate against docs.gnani.ai / the Gnani dashboard
before the first live narration run, the same way A-01 prices are a founder
calibration item]:

    POST {ZIVON_TIMBRE_BASE_URL}{ZIVON_TIMBRE_TTS_PATH, default /v1/tts}
    Authorization: Bearer <ZIVON_TIMBRE_API_KEY>   (only if a key is set)
    {"text": <spoken form>, "language": <ADR-0009 TTS language>,
     "voice": <optional voice id>, "format": "ogg-opus", "sample_rate": 48000}
    200 -> audio bytes ("audio/ogg" opus preferred; other formats are
           transcoded to opus by factory.narration.audio)

Retry policy: 429 / 500 / 502 / 503 / 504 and transport errors (connect or
read timeout, connection reset) are retried up to ZIVON_TIMBRE_MAX_ATTEMPTS
with exponential backoff (base * 2**attempt + jitter). Any other 4xx is a
permanent rejection - retrying cannot fix a bad request, so it raises
immediately. The API key and the request body never appear in error messages.

Mock mode: when no Timbre endpoint is configured (or mode=mock), the mock
client produces deterministic 16 kHz mono WAV silence sized by the spoken
character count - the full build path (hash, encode, manifests, budget
accounting) is exercised without spending credits. Mock assets are labelled
everywhere they are recorded and are never for the live site.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import random
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ..errors import ConfigError
from .env import NarrationEnv
from .errors import NarrationError
from .select import strip_non_whitelisted_tags

# Live Timbre v3.0 realtime contract (verified against docs.gnani.ai and a
# real call on 2026-11-10). The REST shape this client originally assumed
# 404s on the live API; the realtime WS is the supported path:
#   WSS {ZIVON_TIMBRE_BASE_URL}  (e.g. wss://api.vachana.ai/api/v1/tts)
#   header X-API-Key-ID: <key>
#   one JSON synthesis request -> {"type":"audio","data":{"audio":<base64>}}
#   frames ... -> {"type":"complete"}
TIMBRE_DEFAULT_MODEL = "timbre-v3.0"
TIMBRE_DEFAULT_VOICE = "Shivani"
TIMBRE_WS_SAMPLE_RATE = 48000

# Locale (ADR-0009) -> Timbre `language` value.
_LOCALE_TO_TIMBRE = {
    "en": "en-IN",
    "hi": "hi-IN",
    "hi-Latn": "hi-en",
}

# Mock speech rate (chars per second): a measured narration pace for Physics
# prose is ~14-15 chars/s; the mock needs only a plausible, deterministic
# duration so manifests carry a sane duration_ms.
MOCK_CHARS_PER_SEC = 14.0
MOCK_MAX_DURATION_S = 45.0
MOCK_SAMPLE_RATE = 16000

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class SynthesisResult:
    """Raw provider audio (not yet encoded/hashed)."""

    audio: bytes
    content_type: str
    latency_s: float
    attempts: int


class TimbreClient:
    """The narration synthesis boundary: spoken text in, audio bytes out."""

    def synthesize(self, text: str, language: str) -> SynthesisResult:
        raise NotImplementedError


class MockTimbreClient(TimbreClient):
    """Deterministic silence, sized like real speech. Zero credits."""

    def synthesize(self, text: str, language: str) -> SynthesisResult:
        safe_text = strip_non_whitelisted_tags(text)
        duration_s = min(
            MOCK_MAX_DURATION_S, max(1.0, len(safe_text) / MOCK_CHARS_PER_SEC)
        )
        return SynthesisResult(
            audio=_silence_wav(duration_s),
            content_type="audio/wav",
            latency_s=0.0,
            attempts=1,
        )


class LiveTimbreClient(TimbreClient):
    """The Gnani Timbre v3.0 HTTP client (llm_manager patterns).

    transport: injectable for tests (httpx.MockTransport); production passes
    nothing and gets a real connection pool.
    """

    def __init__(
        self,
        env: NarrationEnv,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        ws_connect: Callable[..., object] | None = None,
    ):
        if not env.timbre_base_url:
            raise ConfigError(
                "LiveTimbreClient needs ZIVON_TIMBRE_BASE_URL (the Gnani "
                "Timbre v3.0 endpoint) - live mode was selected without it"
            )
        self.env = env
        self.url = env.timbre_base_url.rstrip("/") + env.timbre_tts_path
        # wss:// base = the verified realtime endpoint; https:// keeps the
        # legacy REST path for alternate providers/tests.
        self.ws_url = (
            env.timbre_base_url.rstrip("/")
            if env.timbre_base_url.startswith(("ws://", "wss://"))
            else ""
        )
        self._sleep = sleep
        self._transport = transport
        self._ws_connect = ws_connect

    def synthesize(self, text: str, language: str) -> SynthesisResult:
        # Harness defense (like SP1's tag whitelist): only the narration
        # whitelist (<pauses> <slow> <excited> <whispers>) is ever posted.
        # The stage already caps tags in select.spoken_text; this strip makes
        # direct callers safe too and never bills non-whitelisted characters.
        safe_text = strip_non_whitelisted_tags(text)
        if self.ws_url:
            return self._synthesize_ws(safe_text, language)
        return self._synthesize_rest(safe_text, language)

    # --- realtime WS (the live contract) -------------------------------------

    def _synthesize_ws(self, text: str, language: str) -> SynthesisResult:
        payload = {
            "text": text,
            "voice": self.env.timbre_voice or TIMBRE_DEFAULT_VOICE,
            "model": TIMBRE_DEFAULT_MODEL,
            "language": _LOCALE_TO_TIMBRE.get(language, language or "en-IN"),
            "speed": 1.0,
            "audio_config": {
                "sample_rate": TIMBRE_WS_SAMPLE_RATE,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": "raw",
            },
        }
        last_error = ""
        for attempt in range(1, self.env.timbre_max_attempts + 1):
            t0 = time.monotonic()
            try:
                pcm = asyncio.run(self._ws_once(payload))
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:200]
                if attempt < self.env.timbre_max_attempts:
                    self._backoff(attempt)
                    continue
                raise NarrationError(
                    "12-narration",
                    f"Timbre realtime synthesis failed after {attempt} "
                    f"attempt(s): {last_error} (check ZIVON_TIMBRE_BASE_URL is "
                    "the wss:// realtime endpoint and the key is valid)",
                ) from exc
            if not pcm:
                last_error = "provider returned no audio"
                if attempt < self.env.timbre_max_attempts:
                    self._backoff(attempt)
                    continue
                raise NarrationError("12-narration", last_error)
            return SynthesisResult(
                audio=_pcm16_to_wav(pcm, TIMBRE_WS_SAMPLE_RATE),
                content_type="audio/wav",
                latency_s=round(time.monotonic() - t0, 2),
                attempts=attempt,
            )
        raise NarrationError(  # pragma: no cover - loop returns or raises
            "12-narration",
            f"Timbre synthesis failed after {self.env.timbre_max_attempts} "
            f"attempt(s): {last_error}",
        )

    async def _ws_once(self, payload: dict[str, object]) -> bytes:
        if self._ws_connect is not None:
            connect = self._ws_connect
        else:  # lazy import keeps the client testable without websockets
            try:
                import websockets.asyncio.client as _wsclient

                connect = _wsclient.connect
            except ImportError:  # websockets < 13
                import websockets as _wslegacy

                connect = _wslegacy.connect

        headers = {"X-API-Key-ID": self.env.timbre_api_key}
        cm: Any
        try:
            cm = connect(
                self.ws_url,
                additional_headers=headers,
                open_timeout=self.env.timbre_connect_timeout_s,
                max_size=None,
            )
        except TypeError:  # websockets < 14 named it extra_headers
            cm = connect(
                self.ws_url,
                extra_headers=headers,
                open_timeout=self.env.timbre_connect_timeout_s,
                max_size=None,
            )
        pcm = bytearray()
        async with cm as ws:
            await ws.send(json.dumps(payload))
            while True:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=self.env.timbre_timeout_s
                )
                if isinstance(raw, bytes):
                    pcm += raw  # tolerated alternate binary downlink
                    continue
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "audio":
                    chunk = (msg.get("data") or {}).get("audio") or ""
                    if chunk:
                        pcm += _b64decode(chunk)
                elif kind == "complete":
                    return bytes(pcm)
                elif kind == "error":
                    raise NarrationError(
                        "12-narration",
                        f"Timbre realtime error: {msg.get('message', 'unknown')}",
                    )
        return bytes(pcm)

    # --- legacy REST path -----------------------------------------------------

    def _synthesize_rest(self, safe_text: str, language: str) -> SynthesisResult:
        headers = {"Content-Type": "application/json"}
        if self.env.timbre_api_key:
            headers["Authorization"] = f"Bearer {self.env.timbre_api_key}"
        payload: dict[str, object] = {
            "text": safe_text,
            "language": language,
            "format": "ogg-opus",
            "sample_rate": 48000,
        }
        if self.env.timbre_voice:
            payload["voice"] = self.env.timbre_voice

        last_error = ""
        for attempt in range(1, self.env.timbre_max_attempts + 1):
            t0 = time.monotonic()
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(
                        self.env.timbre_timeout_s,
                        connect=self.env.timbre_connect_timeout_s,
                    ),
                    transport=self._transport,
                ) as client:
                    response = client.post(self.url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"transport error: {type(exc).__name__}"
                if attempt < self.env.timbre_max_attempts:
                    self._backoff(attempt)
                    continue
                raise NarrationError(
                    "12-narration",
                    f"Timbre synthesis failed after {attempt} attempt(s): "
                    f"{last_error} (timeouts/retries: ZIVON_TIMBRE_TIMEOUT_S="
                    f"{self.env.timbre_timeout_s}s, ZIVON_TIMBRE_MAX_ATTEMPTS="
                    f"{self.env.timbre_max_attempts})",
                ) from exc
            latency = time.monotonic() - t0
            if response.status_code == 200:
                return SynthesisResult(
                    audio=response.content,
                    content_type=response.headers.get(
                        "content-type", "application/octet-stream"
                    ),
                    latency_s=round(latency, 2),
                    attempts=attempt,
                )
            last_error = f"HTTP {response.status_code}"
            if (
                response.status_code in _RETRYABLE_STATUSES
                and attempt < self.env.timbre_max_attempts
            ):
                self._backoff(attempt)
                continue
            # Non-retryable 4xx (400/401/403/404/422...): retrying cannot fix
            # a bad request. Status only - never the key, never the body.
            raise NarrationError(
                "12-narration",
                f"Timbre rejected the synthesis request permanently "
                f"({last_error}) after {attempt} attempt(s) - a retry cannot "
                "fix this; check ZIVON_TIMBRE_* configuration against the "
                "Gnani Timbre v3.0 contract (see factory/narration/timbre.py)",
            )
        raise NarrationError(  # pragma: no cover - loop returns or raises
            "12-narration",
            f"Timbre synthesis failed after {self.env.timbre_max_attempts} "
            f"attempt(s): {last_error}",
        )

    def _backoff(self, attempt: int) -> None:
        base = self.env.timbre_backoff_base_s
        self._sleep(base * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5))


def _b64decode(chunk: str) -> bytes:
    try:
        return base64.b64decode(chunk)
    except (ValueError, TypeError):
        try:
            return base64.b64decode(chunk + "=" * (-len(chunk) % 4))
        except (ValueError, TypeError):
            return b""


def _pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw little-endian PCM16 mono in a WAV container.

    ffmpeg can then infer the format without extra flags, and the downstream
    opus encoder path stays provider-agnostic.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _silence_wav(duration_s: float) -> bytes:
    """Deterministic 16 kHz mono 16-bit WAV of pure silence."""
    frames = int(duration_s * MOCK_SAMPLE_RATE)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(MOCK_SAMPLE_RATE)
        # 1-second zero frames at a time keeps memory flat for long blocks.
        zeros = bytes(MOCK_SAMPLE_RATE * 2)  # 16-bit samples, all zero
        remaining = frames
        while remaining > 0:
            step = min(remaining, MOCK_SAMPLE_RATE)
            wav.writeframes(zeros if step == MOCK_SAMPLE_RATE else bytes(step * 2))
            remaining -= step
    return buffer.getvalue()
