"""Voice-loop configuration — every knob is a ``ZIVON_VOICE_*`` env var.

spec.md §12: all knobs have defaults; secrets come from the environment only
and are never logged, never rendered into manifests. The guard reads only the
``ZIVON_VOICE_CREDIT_*`` knobs (spec.md §8) — no credit logic anywhere else.

Secret names follow the `zivon-voice-env` Secret registry (gap-register
GAP-001/003): ``GNANI_PRISMA_API_KEY`` / ``GNANI_TIMBRE_API_KEY`` /
``ZIVON_VOICE_GEMINI_API_KEY``, with the spec.md §12 short names
(``GNANI_API_KEY``, ``GEMINI_API_KEY``) accepted as fallbacks so the mount
works under either naming. Session-token and IP-hash-salt keys come from the
core backend's registry (``ZIVON_SESSION_TOKEN_KEY``, ``ZIVON_IP_HASH_SALT``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["VoiceSettings"]


def _env(e: Mapping[str, str], *names: str, default: str = "") -> str:
    """First set variable wins; empty string means 'not configured'."""
    for name in names:
        value = e.get(name)
        if value:
            return value
    return default


def _env_float(e: Mapping[str, str], name: str, default: float) -> float:
    raw = _env(e, name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(e: Mapping[str, str], name: str, default: int) -> int:
    raw = _env(e, name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(e: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _env(e, name).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "on", "yes")


@dataclass(frozen=True)
class VoiceSettings:
    """Immutable voice-loop settings (spec.md §12 config family)."""

    # --- brain (Gemma 4 26B A4B via Gemini API, ADR-0017) -------------------
    brain_model: str = "gemma-4-26b-a4b-it"
    brain_transport: str = "gemini-direct"  # | openrouter
    brain_openrouter_base_url: str = "https://openrouter.ai/api/v1"
    brain_inactivity_s: float = 4.0  # [ASSUMPTION] between stream events
    brain_first_event_s: float = 3.0  # [ASSUMPTION] to first stream event
    brain_turn_deadline_s: float = 45.0  # hard close mid-stream
    brain_max_retries: int = 2  # only before any audio reached the client
    brain_first_event_retries: int = 1  # F2: initial attempt + one retry

    # --- thinking out loud (ADR-0018) ---------------------------------------
    thinking_summaries: bool = False  # flag default OFF until OQ-04 + falsification
    filler_silence_ms: int = 2000  # [ASSUMPTION]
    filler_max_chars: int = 120
    summaries_max_per_turn: int = 2
    summary_max_chars: int = 120

    # --- STT (Prisma v3.0, OQ-02 contract verified at build) ----------------
    stt_url: str = ""  # empty = not configured → F1 degraded path, honest
    stt_sample_rate: int = 16000
    stt_frame_ms: int = 100
    stt_languages: tuple[str, ...] = ("hi", "en")
    echo_guard_ms: int = 200  # drop STT events within 200 ms of playback stop

    # --- TTS (Timbre v3.0 realtime, OQ-03) ----------------------------------
    tts_url: str = ""  # empty = not configured → F4 degraded path, honest
    tts_voice: str = ""  # founder picks by ear (OQ-03)
    tts_char_cap_turn: int = 1200  # H3 per-turn char cap (tags bill as chars)
    tts_tag_max_per_turn: int = 8  # H3 tag cap (≤ 1 tag / 2 sentences)
    tts_tag_sentences_ratio: int = 2
    tts_first_audio_budget_ms: int = 200  # L6 vendor claim, measured not trusted

    # --- credit guard (H1–H4, ADR-0015 / NEED-009; founder config 2026-11-07)
    credit_daily_tranche: int = 1000
    credit_per_user_cap: int = 30
    credit_demo_tranche: int = 1000  # separate demo-day tranche
    credit_demo_session_cap: int = 100  # [ASSUMPTION A-05]
    credit_turn_estimate_stt_s: int = 15  # A-07 estimate figures
    credit_turn_estimate_tts_chars: int = 600
    credit_warn_ratio: float = 0.15  # ok → warn when remaining ≤ 15 %
    over_credit_line: str = "Itna hi aaj!"  # ≤ 15 chars of speech (H2)

    # --- WS channel (ws-contract.md; GAP-003 auth/abuse) --------------------
    ws_path: str = "/voice/ws"
    ws_version: int = 1  # mismatch → close 4409
    ws_max_concurrent_sessions: int = 10  # cluster cap at 1 replica (A-07)
    ws_connects_per_min: int = 10  # per IP hash (GAP-003)
    ws_ping_interval_s: float = 15.0
    ws_ping_miss_max: int = 2
    resume_window_s: float = 60.0  # ADR-0002 final-message replay window
    interrupt_storm_window_s: float = 10.0  # F8: > 3 interrupts / 10 s
    interrupt_storm_max: int = 3
    typed_text_max_chars: int = 1000  # backend-spec §7.2 typed.doubt

    # --- history / memory (spec.md §6) --------------------------------------
    history_turns_max: int = 6  # brain sees last ≤ 6 turns of text
    turn_ttl_days: int = 7  # A-02 hard delete, purged by voice.purge_expired
    snapshot_max_bytes: int = 4096  # ADR-0014 bound
    snapshot_stale_s: float = 2.0  # resend when older (spec.md §7)
    context_block_text_max: int = 600  # prompt context bound (spec.md §7)

    # --- secrets (runtime env only; never logged, never in manifests) -------
    gemini_api_key: str = field(default="", repr=False)
    gnani_stt_api_key: str = field(default="", repr=False)
    gnani_tts_api_key: str = field(default="", repr=False)
    session_token_key: str = field(default="", repr=False)
    ip_hash_salt: str = field(default="", repr=False)
    openrouter_api_key: str = field(default="", repr=False)

    # --- dev/mock mode (mock default; live probes only with founder keys) ---
    mock_mode: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> VoiceSettings:
        """Read every knob from the environment (first set name wins)."""
        e = env if env is not None else os.environ
        brain_transport = (
            e.get("ZIVON_VOICE_BRAIN_TRANSPORT", "gemini-direct").strip().lower()
        )
        if brain_transport not in ("gemini-direct", "openrouter"):
            brain_transport = "gemini-direct"
        thinking = e.get("ZIVON_VOICE_THINKING_SUMMARIES", "off").strip().lower()
        return cls(
            brain_model=e.get("ZIVON_VOICE_BRAIN_MODEL", "gemma-4-26b-a4b-it"),
            brain_transport=brain_transport,
            brain_openrouter_base_url=e.get(
                "ZIVON_VOICE_OPENROUTER_URL", "https://openrouter.ai/api/v1"
            ),
            brain_inactivity_s=_env_float(e, "ZIVON_VOICE_BRAIN_INACTIVITY_S", 4.0),
            brain_first_event_s=_env_float(e, "ZIVON_VOICE_BRAIN_FIRST_EVENT_S", 3.0),
            brain_turn_deadline_s=_env_float(
                e, "ZIVON_VOICE_BRAIN_TURN_DEADLINE_S", 45.0
            ),
            brain_max_retries=_env_int(e, "ZIVON_VOICE_BRAIN_MAX_RETRIES", 2),
            thinking_summaries=thinking in ("1", "true", "on", "yes"),
            filler_silence_ms=_env_int(e, "ZIVON_VOICE_FILLER_SILENCE_MS", 2000),
            stt_url=e.get("ZIVON_VOICE_STT_URL", ""),
            stt_sample_rate=_env_int(e, "ZIVON_VOICE_STT_SAMPLE_RATE", 16000),
            tts_url=e.get("ZIVON_VOICE_TTS_URL", ""),
            tts_voice=e.get("ZIVON_VOICE_TTS_VOICE", ""),
            tts_char_cap_turn=_env_int(e, "ZIVON_VOICE_TTS_CHAR_CAP_TURN", 1200),
            tts_tag_max_per_turn=_env_int(e, "ZIVON_VOICE_TTS_TAG_MAX_PER_TURN", 8),
            credit_daily_tranche=_env_int(e, "ZIVON_VOICE_CREDIT_DAILY_TRANCHE", 1000),
            credit_per_user_cap=_env_int(e, "ZIVON_VOICE_CREDIT_PER_USER_CAP", 30),
            credit_demo_tranche=_env_int(e, "ZIVON_VOICE_CREDIT_DEMO_TRANCHE", 1000),
            credit_demo_session_cap=_env_int(
                e, "ZIVON_VOICE_CREDIT_DEMO_SESSION_CAP", 100
            ),
            ws_path=e.get("ZIVON_VOICE_WS_PATH", "/voice/ws"),
            ws_max_concurrent_sessions=_env_int(e, "ZIVON_VOICE_WS_MAX_SESSIONS", 10),
            ws_ping_interval_s=_env_float(e, "ZIVON_VOICE_PING_INTERVAL_S", 15.0),
            gemini_api_key=_env(e, "ZIVON_VOICE_GEMINI_API_KEY", "GEMINI_API_KEY"),
            gnani_stt_api_key=_env(e, "GNANI_PRISMA_API_KEY", "GNANI_API_KEY"),
            gnani_tts_api_key=_env(e, "GNANI_TIMBRE_API_KEY", "GNANI_API_KEY"),
            session_token_key=_env(e, "ZIVON_SESSION_TOKEN_KEY"),
            ip_hash_salt=_env(e, "ZIVON_IP_HASH_SALT"),
            openrouter_api_key=_env(
                e, "ZIVON_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"
            ),
            mock_mode=_env_bool(e, "ZIVON_VOICE_MOCK", False),
        )

    @property
    def stt_configured(self) -> bool:
        """Live STT needs a URL + key; otherwise voice input degrades (F1)."""
        return bool(self.stt_url and self.gnani_stt_api_key)

    @property
    def tts_configured(self) -> bool:
        """Live TTS needs a URL + key; otherwise answers stay text-only (F4)."""
        return bool(self.tts_url and self.gnani_tts_api_key)

    @property
    def brain_configured(self) -> bool:
        """Brain needs a key on the selected transport (text fallback, F2)."""
        if self.mock_mode:
            return True
        if self.brain_transport == "openrouter":
            return bool(self.openrouter_api_key)
        return bool(self.gemini_api_key)
