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

import io
import random
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ..errors import ConfigError
from .env import NarrationEnv
from .errors import NarrationError

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
        duration_s = min(MOCK_MAX_DURATION_S, max(1.0, len(text) / MOCK_CHARS_PER_SEC))
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
    ):
        if not env.timbre_base_url:
            raise ConfigError(
                "LiveTimbreClient needs ZIVON_TIMBRE_BASE_URL (the Gnani "
                "Timbre v3.0 endpoint) - live mode was selected without it"
            )
        self.env = env
        self.url = env.timbre_base_url.rstrip("/") + env.timbre_tts_path
        self._sleep = sleep
        self._transport = transport

    def synthesize(self, text: str, language: str) -> SynthesisResult:
        headers = {"Content-Type": "application/json"}
        if self.env.timbre_api_key:
            headers["Authorization"] = f"Bearer {self.env.timbre_api_key}"
        payload: dict[str, object] = {
            "text": text,
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
