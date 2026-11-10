"""Opus encoding and ST-04 content-hash naming for narration assets.

Serving contract (backend-spec ST-04, gap-register GAP-015):

    GET /audio/{course_id}/{block_id}.{lang}.{content-hash}.opus
    immutable, max-age=31536000 (the content-hash path IS the cache key)

The hash is a TEXT hash, not an audio-bytes hash: C2 (data-classification)
defines the narration asset key as `text_hash`, and the audio-engineering
skill's batch-TTS pattern demands per-item IDEMPOTENCY keys - the same
spoken text under the same voice/language must always map to the same
address, so a re-triggered run finds its completed work and skips it
(zero credits), while any republish with changed content bumps the hash and
the old asset stays addressable until eviction.

Encoding: Gnani may return opus directly (passed through untouched) or
another format (WAV/MP3/...), which is transcoded to 24 kbps mono 48 kHz
Opus via the ffmpeg CLI - the audio-engineering skill's narration ladder.
ffmpeg must be on PATH (or ZIVON_FFMPEG_PATH): the factory image needs it
for narration builds (recorded as a TIMELINE.md infra TODO because the
Dockerfile is outside this brief's file boundary).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .env import STAGE_ID
from .errors import NarrationError

OPUS_BITRATE_KBPS = 24  # audio-engineering skill: 24 kb/s is the narration rung

_OGG_MAGIC = b"OggS"
_OPUS_HEAD = b"OpusHead"


def content_hash(lang: str, voice: str, text: str) -> str:
    """The ST-04 content-hash key: text-hash of (lang, voice, spoken form).

    voice participates because re-voicing the same words is new audio; the
    16-hex truncation matches the repo's fingerprint convention and keeps
    filenames comfortable.
    """
    payload = f"{lang}|{voice}|{text}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def asset_rel_path(course_id: str, block_id: str, lang: str, hash_: str) -> str:
    """ST-04 path, relative to the web root (so nginx serves it at /audio/...)."""
    return f"audio/{course_id}/{block_id}.{lang}.{hash_}.opus"


def is_opus(data: bytes) -> bool:
    """True for an Ogg Opus stream (RFC 7845): Ogg container + OpusHead."""
    return data[:4] == _OGG_MAGIC and _OPUS_HEAD in data[:64]


def ffmpeg_binary() -> str:
    """Locate ffmpeg: ZIVON_FFMPEG_PATH first, then PATH. A configured
    binary that does not exist is a loud config error, not a FileNotFoundError
    from deep inside subprocess."""
    configured = os.environ.get("ZIVON_FFMPEG_PATH", "").strip()
    if configured:
        if not Path(configured).is_file():
            raise NarrationError(
                STAGE_ID,
                f"ZIVON_FFMPEG_PATH={configured!r} does not point at an "
                "existing ffmpeg binary",
            )
        return configured
    found = shutil.which("ffmpeg")
    if not found:
        raise NarrationError(
            STAGE_ID,
            "ffmpeg is required to encode narration to Opus (24 kb/s mono) "
            "but was not found on PATH. Install it (e.g. apt-get install "
            "ffmpeg) or point ZIVON_FFMPEG_PATH at the binary; the factory "
            "image must carry it for narration builds (TIMELINE.md infra "
            "TODO).",
        )
    return found


def encode_opus(raw: bytes, content_type: str = "") -> bytes:
    """Encode provider audio to 24 kbps mono Opus; opus input passes through.

    Provider audio arrives via stdin; encoded opus leaves via stdout. stderr
    is captured (never secrets - it can only contain ffmpeg diagnostics) and
    surfaces in the error when the encode fails, loud by design.
    """
    if is_opus(raw):
        return raw
    if not raw:
        raise NarrationError(STAGE_ID, "refusing to encode empty audio input")
    binary = ffmpeg_binary()
    try:
        proc = subprocess.run(
            [
                binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-map_metadata",
                "-1",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                f"{OPUS_BITRATE_KBPS}k",
                "-f",
                "opus",
                "pipe:1",
            ],
            input=raw,
            capture_output=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise NarrationError(
            STAGE_ID,
            f"ffmpeg opus encode timed out after 300s ({content_type or 'unknown'} "
            f"input, {len(raw)} bytes) - the provider audio may be corrupt",
        ) from exc
    if proc.returncode != 0 or not proc.stdout:
        stderr_tail = proc.stderr.decode("utf-8", "replace").strip()[-400:]
        raise NarrationError(
            STAGE_ID,
            f"ffmpeg opus encode failed (rc={proc.returncode}, "
            f"{content_type or 'unknown'} input, {len(raw)} bytes): "
            f"{stderr_tail or 'no diagnostics'}",
        )
    return proc.stdout


def write_asset(frontend_root: Path, rel_path: str, data: bytes) -> Path:
    """Write one immutable asset under the web root. Existing files are never
    rewritten: the content-hash name is the idempotency key (audio-engineering
    skill), and a rewrite of an addressed, possibly already-cold-verified
    asset would break immutability."""
    target = frontend_root / rel_path
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".opus.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target


def probe_duration_ms(data: bytes) -> int | None:
    """Measured duration of an opus asset in ms (ffprobe), or None when
    ffprobe is unavailable. The narration manifest records the MEASURED
    duration (GAP-015 {chars, duration_ms}), never an estimate."""
    binary = shutil.which("ffprobe")
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                "pipe:0",
            ],
            input=data,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    try:
        return round(float(proc.stdout.decode().strip()) * 1000)
    except ValueError:
        return None
