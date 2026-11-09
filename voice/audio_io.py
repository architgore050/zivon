"""Server-side audio frame handling (spec.md §3 ``audio_io``).

Binary frame layout per ADR-0020 / ws-contract.md §3: 8-byte big-endian
header (magic 0xA5, version 1, u16 segment_id, u16 seq, u8 flags, u8
reserved) then payload. Client→server payload is PCM16 mono 16 kHz, 100 ms
(3,200 bytes); server→client payload is Opus 20 ms frames at Timbre's output
rate. Raw audio lives in WS-handler memory only — nothing audio-shaped is
persisted or logged (ADR-0008).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

__all__ = [
    "FLAG_FINAL",
    "FRAME_MAGIC",
    "FRAME_VERSION",
    "PCM_FRAME_BYTES",
    "AudioFrameError",
    "DownlinkHeader",
    "UplinkHeader",
    "pack_downlink",
    "pack_uplink",
    "unpack_downlink",
    "unpack_uplink",
]

FRAME_MAGIC = 0xA5
FRAME_VERSION = 1
FLAG_FINAL = 0x01  # bit0: final frame of the segment / flush

_HEADER = struct.Struct(">BBHHBB")  # magic, version, segment_id, seq, flags, reserved
HEADER_SIZE = _HEADER.size  # 8

# ws-contract.md §3: PCM16 mono 16 kHz at 100 ms per frame = 3,200 bytes.
PCM_FRAME_BYTES = 3200

# Tolerated uplink payload bounds: a 100 ms frame is exact, but cellular
# reassembly may deliver short tails; STT tolerates gaps, so anything outside
# the bound is dropped (counted), never crashed on.
_MIN_UPLINK_PAYLOAD = 64  # 2 ms of PCM16 — below this the frame is useless
_MAX_UPLINK_PAYLOAD = 8000  # 250 ms at 16 kHz — the contract's 2× hard bound


class AudioFrameError(ValueError):
    """Raised when a control-plane producer builds an invalid frame."""


@dataclass(frozen=True)
class UplinkHeader:
    """Parsed C→S (audio.chunk) header."""

    segment_id: int
    seq: int
    final: bool


@dataclass(frozen=True)
class DownlinkHeader:
    """Parsed S→C (tts.audio) header."""

    segment_id: int
    seq: int
    final: bool


def pack_uplink(
    segment_id: int, seq: int, payload: bytes, *, final: bool = False
) -> bytes:
    """Build a client→server audio.chunk frame (test/dev helper + codec docs)."""
    return _pack(segment_id, seq, payload, final)


def unpack_uplink(frame: bytes) -> tuple[UplinkHeader, bytes]:
    """Validate + split an audio.chunk frame.

    Returns (header, payload). Raises AudioFrameError on magic/version/
    reserved violations or a payload that is not whole PCM16 samples and
    within the tolerated bounds — the WS handler drops such frames with a
    counter (ws-contract.md §2: STT tolerates gaps, never crashes).
    """
    segment_id, seq, final, payload = _unpack(frame)
    if len(payload) % 2 != 0:
        raise AudioFrameError("payload is not whole PCM16 samples")
    if not _MIN_UPLINK_PAYLOAD <= len(payload) <= _MAX_UPLINK_PAYLOAD:
        raise AudioFrameError(f"payload out of bounds: {len(payload)} bytes")
    return UplinkHeader(segment_id=segment_id, seq=seq, final=bool(final)), payload


def pack_downlink(
    segment_id: int, seq: int, payload: bytes, *, final: bool = False
) -> bytes:
    """Build a server→client tts.audio frame."""
    return _pack(segment_id, seq, payload, final)


def unpack_downlink(frame: bytes) -> tuple[DownlinkHeader, bytes]:
    """Validate + split a tts.audio frame (used by tests and the dock codec)."""
    segment_id, seq, final, payload = _unpack(frame)
    return DownlinkHeader(segment_id=segment_id, seq=seq, final=bool(final)), payload


def _pack(segment_id: int, seq: int, payload: bytes, final: bool) -> bytes:
    if not 0 <= segment_id <= 0xFFFF:
        raise AudioFrameError(f"segment_id out of range: {segment_id}")
    if not 0 <= seq <= 0xFFFF:
        raise AudioFrameError(f"seq out of range: {seq}")
    header = _HEADER.pack(
        FRAME_MAGIC, FRAME_VERSION, segment_id, seq, FLAG_FINAL if final else 0, 0
    )
    return header + payload


def _unpack(frame: bytes) -> tuple[int, int, int, bytes]:
    if len(frame) < HEADER_SIZE:
        raise AudioFrameError(f"frame shorter than header: {len(frame)} bytes")
    magic, version, segment_id, seq, flags, reserved = _HEADER.unpack_from(frame)
    if magic != FRAME_MAGIC:
        raise AudioFrameError(f"bad magic: {magic:#x}")
    if version != FRAME_VERSION:
        raise AudioFrameError(f"unsupported version: {version}")
    if reserved != 0:
        raise AudioFrameError(f"reserved byte must be 0, got {reserved}")
    if flags & ~FLAG_FINAL:
        raise AudioFrameError(f"unknown flag bits set: {flags:#x}")
    return segment_id, seq, flags & FLAG_FINAL, frame[HEADER_SIZE:]


class UplinkStream:
    """Per-turn uplink validation: drop-stale by seq, gap counter.

    Frames arrive over one WS in order, but retransmits/reorders happen on
    cellular links; the STT tolerates gaps (ws-contract.md §2), so out-of-age
    frames are dropped silently with a counter — no error surfaces to the
    student. Raw PCM bytes are never retained past this call (ADR-0008).
    """

    def __init__(self) -> None:
        self.last_seq: int = -1
        self.dropped_stale: int = 0
        self.dropped_invalid: int = 0
        self.frames: int = 0
        self.audio_seconds: float = 0.0

    def accept(self, frame: bytes) -> bytes | None:
        """Validate one frame; return the PCM payload or None when dropped."""
        try:
            header, payload = unpack_uplink(frame)
        except AudioFrameError:
            self.dropped_invalid += 1
            return None
        if header.seq <= self.last_seq:
            self.dropped_stale += 1
            return None
        self.last_seq = header.seq
        self.frames += 1
        # 16 kHz mono PCM16 → 2 bytes/sample; 100 ms frames are the norm.
        self.audio_seconds += len(payload) / 2 / 16000.0
        return payload
