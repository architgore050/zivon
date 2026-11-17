"""Transient explain-back audio: a bounded WAV intake, never a stored file.

F6 (`REQUIREMENTS` §9.5/§10.10) uploads one short recording per attempt and
never persists raw audio. The browser records raw PCM through the Web Audio
API and sends a canonical 16 kHz mono 16-bit WAV; this module is the whole
server-side audio surface:

- read at most `MAX_UPLOAD_BYTES` (413 past it) — the body is held in memory
  for the length of one request and dropped when the response is written;
- parse RIFF/WAVE ourselves (the stdlib `wave` reader rejects files with
  unknown chunks, and a browser-written header is not guaranteed minimal);
- require the one wire format the capture path produces and the voice STT
  client consumes (16 kHz, mono, PCM16) — a mis-encoded upload is a client
  error, never a silently mis-transcribed one;
- split into Prisma frames (the voice loop's 100 ms shape) at the boundary.

Nothing here writes a temporary file, and no function returns anything but
the in-memory bytes a caller passes to `voice.stt_client.SttClient`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

__all__ = [
    "ALLOWED_SAMPLE_RATE",
    "HARD_MAX_DURATION_MS",
    "MAX_UPLOAD_BYTES",
    "MIN_DURATION_MS",
    "AudioError",
    "WavAudio",
    "parse_wav",
    "pcm_frames",
    "stt_credit_points",
]

# 45 s at 16 kHz mono PCM16 is 1.44 MB. Three megabytes leaves room for a
# padded header and a slower client without letting one request become a
# memory amplifier; the duration check is the real product bound.
MAX_UPLOAD_BYTES: Final[int] = 3_000_000
ALLOWED_SAMPLE_RATE: Final[int] = 16_000
HARD_MAX_DURATION_MS: Final[int] = 60_000
MIN_DURATION_MS: Final[int] = 800

_RIFF_HEADER_BYTES: Final[int] = 12
_CHUNK_HEADER_BYTES: Final[int] = 8
_FMT_MIN_BYTES: Final[int] = 16
_MAX_CHUNKS: Final[int] = 64
_PCM_FORMAT: Final[int] = 1


class AudioError(ValueError):
    """A request audio defect the route maps to a coded 4xx.

    `code` is stable (`E-SPEAKING-AUDIO`, `E-SPEAKING-AUDIO-SIZE`); the
    message is for logs, never shown to a student.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class WavAudio:
    """One decoded upload: PCM bytes plus the facts the route must state."""

    pcm: bytes
    sample_rate: int
    duration_ms: int


def _u32(value: bytes) -> int:
    return int.from_bytes(value, "little", signed=False)


def parse_wav(body: bytes) -> WavAudio:
    """Parse a canonical PCM16 WAV and bound it to the speaking contract.

    Raises `AudioError("E-SPEAKING-AUDIO")` for anything that is not the one
    accepted wire format. The caller has already enforced the byte cap; the
    length guard here keeps direct unit calls honest too.
    """
    if not body:
        raise AudioError("E-SPEAKING-AUDIO", "empty body")
    if len(body) > MAX_UPLOAD_BYTES:
        raise AudioError("E-SPEAKING-AUDIO-SIZE", "body over the upload cap")
    if len(body) < _RIFF_HEADER_BYTES:
        raise AudioError("E-SPEAKING-AUDIO", "shorter than a RIFF header")
    if body[0:4] != b"RIFF" or body[8:12] != b"WAVE":
        raise AudioError("E-SPEAKING-AUDIO", "not a RIFF/WAVE stream")

    offset = _RIFF_HEADER_BYTES
    fmt: tuple[int, int, int, int] | None = None
    data: bytes | None = None
    seen = 0
    while offset + _CHUNK_HEADER_BYTES <= len(body) and seen < _MAX_CHUNKS:
        seen += 1
        chunk_id = body[offset : offset + 4]
        size = _u32(body[offset + 4 : offset + 8])
        start = offset + _CHUNK_HEADER_BYTES
        end = start + size
        if end > len(body):
            raise AudioError("E-SPEAKING-AUDIO", "chunk runs past the body")
        payload = body[start:end]
        if chunk_id == b"fmt " and fmt is None:
            if size < _FMT_MIN_BYTES:
                raise AudioError("E-SPEAKING-AUDIO", "short fmt chunk")
            audio_format = int.from_bytes(payload[0:2], "little")
            channels = int.from_bytes(payload[2:4], "little")
            sample_rate = _u32(payload[4:8])
            bits = int.from_bytes(payload[14:16], "little")
            fmt = (audio_format, channels, sample_rate, bits)
        elif chunk_id == b"data" and data is None:
            data = payload
        # RIFF chunks are word-aligned; an odd-sized chunk has one pad byte.
        offset = end + (size & 1)

    if fmt is None or data is None:
        raise AudioError("E-SPEAKING-AUDIO", "missing fmt or data chunk")
    audio_format, channels, sample_rate, bits = fmt
    if audio_format != _PCM_FORMAT:
        raise AudioError("E-SPEAKING-AUDIO", "compressed audio is not accepted")
    if channels != 1:
        raise AudioError("E-SPEAKING-AUDIO", "mono only")
    if bits != 16:
        raise AudioError("E-SPEAKING-AUDIO", "16-bit PCM only")
    if sample_rate != ALLOWED_SAMPLE_RATE:
        raise AudioError("E-SPEAKING-AUDIO", "16 kHz only")
    if len(data) % 2:  # a stray odd byte cannot be a PCM16 sample
        data = data[:-1]
    if len(data) < 2:
        raise AudioError("E-SPEAKING-AUDIO", "no samples")
    duration_ms = round(len(data) / 2 / sample_rate * 1000)
    if duration_ms < MIN_DURATION_MS:
        raise AudioError("E-SPEAKING-AUDIO", "recording too short")
    if duration_ms > HARD_MAX_DURATION_MS:
        raise AudioError("E-SPEAKING-AUDIO", "recording too long")
    return WavAudio(pcm=data, sample_rate=sample_rate, duration_ms=duration_ms)


def pcm_frames(pcm: bytes, *, sample_rate: int, frame_ms: int) -> list[bytes]:
    """Split PCM16 mono into the voice loop's short frames (last may be short).

    `voice.stt_client.SttClient.send_audio` forwards each frame immediately
    and keeps no buffer (ADR-0008); this helper only shapes the request into
    the 64–6400-byte payloads the Prisma realtime contract accepts.
    """
    if sample_rate <= 0 or frame_ms <= 0:
        raise AudioError("E-SPEAKING-AUDIO", "invalid frame shape")
    frame_bytes = max(2, int(sample_rate * 2 * frame_ms / 1000))
    return [
        pcm[start : start + frame_bytes] for start in range(0, len(pcm), frame_bytes)
    ]


def stt_credit_points(duration_ms: int, seconds_per_point: int) -> int:
    """Credit points for one Prisma call (ceil, at least one point)."""
    factor = max(1, int(seconds_per_point))
    return max(1, math.ceil((duration_ms / 1000.0) / factor))
