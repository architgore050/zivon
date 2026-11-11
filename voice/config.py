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

**Credit unit (OQ-06 placeholder).** The guard counts *credit points*, never
raw vendor units, so the founder's per-user cap (30/day) and the A-07 per-turn
estimate are commensurable:

- 1 point = ``credit_stt_seconds_per_point`` seconds of Prisma audio (30 s),
- 1 point = ``credit_tts_chars_per_point`` Timbre characters (300, tags
  included).

The A-07 estimate (≈ 15 s STT + 600 TTS chars) therefore costs
``ceil(15/30) + ceil(600/300) = 3`` points per voice turn, i.e. ~10 voice
turns/day under the 30-point cap (typed turns skip the STT component: 2
points) and ~33 under the 100-point demo session cap. Actuals are converted
with the same factors at ``turn.end`` (H4), so reservations and spend always
share one unit. The factors are ``ZIVON_VOICE_CREDIT_*`` knobs: when OQ-06
pins the real Gnani dashboard unit, only these two factors change.
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


def _json_headers(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def _env_list(e: Mapping[str, str], name: str) -> tuple[str, ...]:
    """Comma-separated list value; empty means 'unset' (caller default)."""
    raw = _env(e, name)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class VoiceSettings:
    """Immutable voice-loop settings (spec.md §12 config family)."""

    # --- brain (Gemma 4 26B A4B via Gemini API, ADR-0017) -------------------
    brain_model: str = "gemma-4-26b-a4b-it"
    brain_transport: str = "gemini-direct"  # | openrouter
    brain_openrouter_base_url: str = "https://openrouter.ai/api/v1"
    brain_inactivity_s: float = 8.0  # Gemma 4 thinking gaps (measured 2026-11-10)
    brain_first_event_s: float = 12.0  # Gemma 4 thinks first (measured 2026-11-10)
    brain_turn_deadline_s: float = 45.0  # hard close mid-stream
    brain_connect_timeout_s: float = 10.0  # TCP/TLS connect to the model API
    brain_max_retries: int = 2  # only before any audio reached the client
    brain_first_event_retries: int = 1  # F2: initial attempt + one retry
    # Gemma 4 26B A4B on the Gemini API thinks unconditionally (2026-11-10
    # probe: thought parts arrive before the answer and consumed the default
    # budget, leaving truncated replies). The budget must cover thinking +
    # answer; 2048 was verified sufficient for a several-sentence tutor turn.
    # Gate A keeps Gemma 4 as the tutor. Gemma 4 on the free Gemini tier
    # thinks 20-120 s before its first content token (measured 2026-11-10),
    # so a bounded fallback model answers when Gemma breaches the first-event
    # budget. Empty = no fallback (tests/other transports).
    brain_fallback_model: str = ""
    brain_fallback_transport: str = "gemini-direct"  # or openrouter
    brain_fallback_base_url: str = ""
    brain_fallback_api_key: str = field(default="", repr=False)
    brain_extra_headers: dict[str, str] = field(default_factory=dict)
    brain_max_output_tokens: int = 8192
    brain_temperature: float = 0.4
    # Gemini thinking budget (-1 = don't send it, the model default). Set 0 on
    # a Gemini model for a real-time first content event; Gemma 4 rejects
    # thinking_config (measured 2026-11-10), so it is only sent when configured.
    brain_thinking_budget: int = -1

    # --- thinking out loud (ADR-0018) ---------------------------------------
    thinking_summaries: bool = False  # flag default OFF until OQ-04 + falsification
    filler_silence_ms: int = 2000  # [ASSUMPTION]
    filler_max_chars: int = 120
    summaries_max_per_turn: int = 2
    summary_max_chars: int = 120

    # --- STT (Prisma v3.0, OQ-02 — LIVE contract verified 2026-11-10) ------
    stt_url: str = ""  # empty = not configured → F1 degraded path, honest
    stt_model: str = "prisma-v3.0"  # realtime: `model` upgrade header
    stt_language: str = "indic-auto"  # code-mixed Hinglish auto-detect
    stt_sample_rate: int = 16000
    stt_frame_ms: int = 100
    stt_connect_timeout_s: float = 10.0  # websockets handshake budget
    stt_languages: tuple[str, ...] = ("hi", "en")
    echo_guard_ms: int = 200  # drop STT events within 200 ms of playback stop
    stt_final_timeout_s: float = (
        12.0  # Prisma commit->transcript; 8 s was tight on 2G vendor hops
    )

    # --- TTS (Timbre v3.0 realtime, OQ-03 — LIVE contract verified 2026-11-10)
    tts_url: str = ""  # empty = not configured → F4 degraded path, honest
    tts_model: str = "timbre-v3.0"
    tts_language: str = "hi-en"  # Hinglish; "auto" also valid
    # Reply-language default when neither Prisma nor session.start gave one
    # (voice/language.py precedence). Product default = the Hinglish mix.
    reply_locale_default: str = "hi-Latn"
    tts_sample_rate: int = 48000  # Timbre realtime audio_config.sample_rate
    tts_voice: str = "Shivani"  # Timbre v3.0 default; founder may re-pick (OQ-03)
    tts_connect_timeout_s: float = 10.0  # websockets handshake budget
    tts_char_cap_turn: int = 1200  # H3 per-turn char cap (tags bill as chars)
    tts_tag_max_per_turn: int = 8  # H3 tag cap (≤ 1 tag / 2 sentences)
    tts_tag_sentences_ratio: int = 2
    tts_first_audio_budget_ms: int = 200  # L6 vendor claim, measured not trusted

    # --- credit guard (H1–H4, ADR-0015 / NEED-009; founder config 2026-11-07)
    # Caps + tranches are in credit POINTS (see the module docstring): the
    # A-07 physical figures below are converted with the two per-point
    # factors, so every counter in the guard shares one unit.
    credit_daily_tranche: int = 1000
    credit_per_user_cap: int = 30
    credit_demo_tranche: int = 1000  # separate demo-day tranche
    credit_demo_session_cap: int = 100  # [ASSUMPTION A-05]
    credit_stt_seconds_per_point: int = 30  # OQ-06 placeholder: 1 pt / 30 s
    credit_tts_chars_per_point: int = 300  # OQ-06 placeholder: 1 pt / 300 chars
    credit_turn_estimate_stt_s: int = 15  # A-07 estimate figures (seconds)
    credit_turn_estimate_tts_chars: int = 600  # A-07 estimate figures (chars)
    credit_warn_ratio: float = 0.15  # ok → warn when remaining ≤ 15 %
    over_credit_line: str = "Itna hi aaj!"  # ≤ 15 chars of speech (H2)

    # --- WS channel (ws-contract.md; GAP-003 auth/abuse) --------------------
    ws_path: str = "/voice/ws"
    ws_version: int = 1  # mismatch → close 4409
    ws_max_concurrent_sessions: int = 10  # cluster cap at 1 replica (A-07)
    ws_connects_per_min: int = 10  # per IP hash + per device (GAP-003)
    # Origin check (backend-spec §7.1): empty tuple = same-origin only, i.e.
    # the browser Origin's host must equal the request Host. Configure full
    # origins (``https://zivon.example``) when the dock is served from a
    # different host than the WS endpoint.
    ws_allowed_origins: tuple[str, ...] = ()
    # Behind the ingress (or any reverse proxy) ``websocket.client.host`` is
    # the proxy pod's IP, which would turn the per-IP bucket into one global
    # bucket. List the trusted proxy IPs/CIDRs here and the limiter keys on
    # the last untrusted hop in ``X-Forwarded-For`` instead.
    ws_trusted_proxies: tuple[str, ...] = ()
    ws_ping_interval_s: float = 15.0
    # 3 missed pongs @15 s = ~45 s before a dead NAT is reaped. Two misses
    # (30 s) was tight for 2G/3G handovers and tore down live sessions.
    ws_ping_miss_max: int = 3
    resume_window_s: float = 60.0  # ADR-0002 final-message replay window
    interrupt_storm_window_s: float = 10.0  # F8: > 3 interrupts / 10 s
    interrupt_storm_max: int = 3
    typed_text_max_chars: int = 1000  # backend-spec §7.2 typed.doubt

    # --- history / memory (spec.md §6) --------------------------------------
    history_turns_max: int = 6  # brain sees last ≤ 6 turns of text
    turn_ttl_days: int = 7  # A-02 hard delete, purged by voice.purge_expired
    snapshot_max_bytes: int = 4096  # ADR-0014 bound
    snapshot_stale_s: float = 10.0  # turn-length window; client resends at turn start
    context_block_text_max: int = 600  # prompt context bound (spec.md §7)

    # --- secrets (runtime env only; never logged, never in manifests) -------
    gemini_api_key: str = field(default="", repr=False)
    gnani_stt_api_key: str = field(default="", repr=False)
    gnani_tts_api_key: str = field(default="", repr=False)
    session_token_key: str = field(default="", repr=False)
    ip_hash_salt: str = field(default="", repr=False)
    openrouter_api_key: str = field(default="", repr=False)

    # --- dev/mock mode (test marker only; live factory defaults in prod) ---
    # ``mock_mode`` is a TEST-only marker: it makes ``brain_configured`` true
    # so config tests can exercise the empty-key path without a key. No
    # production code path consults it — the vendor seams are injected
    # factories (``mount_voice(stt_factory=..., brain_factory=...,
    # tts_factory=...)``) and the shipped defaults are the live clients.
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
            brain_inactivity_s=_env_float(e, "ZIVON_VOICE_BRAIN_INACTIVITY_S", 8.0),
            brain_first_event_s=_env_float(e, "ZIVON_VOICE_BRAIN_FIRST_EVENT_S", 12.0),
            brain_turn_deadline_s=_env_float(
                e, "ZIVON_VOICE_BRAIN_TURN_DEADLINE_S", 45.0
            ),
            brain_connect_timeout_s=_env_float(
                e, "ZIVON_VOICE_BRAIN_CONNECT_TIMEOUT_S", 10.0
            ),
            brain_max_retries=_env_int(e, "ZIVON_VOICE_BRAIN_MAX_RETRIES", 2),
            brain_first_event_retries=_env_int(
                e, "ZIVON_VOICE_BRAIN_FIRST_EVENT_RETRIES", 1
            ),
            brain_fallback_model=e.get("ZIVON_VOICE_BRAIN_FALLBACK_MODEL", ""),
            brain_fallback_transport=e.get(
                "ZIVON_VOICE_BRAIN_FALLBACK_TRANSPORT", "gemini-direct"
            ),
            brain_fallback_base_url=e.get(
                "ZIVON_VOICE_BRAIN_FALLBACK_BASE_URL", ""
            ),
            brain_fallback_api_key=_env(e, "ZIVON_VOICE_BRAIN_FALLBACK_API_KEY"),
            brain_extra_headers=_json_headers(e.get("ZIVON_VOICE_BRAIN_EXTRA_HEADERS", "")),
            brain_max_output_tokens=_env_int(
                e, "ZIVON_VOICE_BRAIN_MAX_OUTPUT_TOKENS", 8192
            ),
            brain_temperature=_env_float(e, "ZIVON_VOICE_BRAIN_TEMPERATURE", 0.4),
            brain_thinking_budget=_env_int(e, "ZIVON_VOICE_BRAIN_THINKING_BUDGET", -1),
            thinking_summaries=thinking in ("1", "true", "on", "yes"),
            filler_silence_ms=_env_int(e, "ZIVON_VOICE_FILLER_SILENCE_MS", 2000),
            stt_url=e.get("ZIVON_VOICE_STT_URL", ""),
            stt_model=e.get("ZIVON_VOICE_STT_MODEL", "prisma-v3.0"),
            stt_language=e.get("ZIVON_VOICE_STT_LANGUAGE", "indic-auto"),
            stt_sample_rate=_env_int(e, "ZIVON_VOICE_STT_SAMPLE_RATE", 16000),
            stt_connect_timeout_s=_env_float(
                e, "ZIVON_VOICE_STT_CONNECT_TIMEOUT_S", 10.0
            ),
            stt_final_timeout_s=_env_float(
                e, "ZIVON_VOICE_STT_FINAL_TIMEOUT_S", 12.0
            ),
            echo_guard_ms=_env_int(e, "ZIVON_VOICE_ECHO_GUARD_MS", 200),
            tts_url=e.get("ZIVON_VOICE_TTS_URL", ""),
            tts_model=e.get("ZIVON_VOICE_TTS_MODEL", "timbre-v3.0"),
            tts_language=e.get("ZIVON_VOICE_TTS_LANGUAGE", "hi-en"),
            reply_locale_default=e.get(
                "ZIVON_VOICE_REPLY_LOCALE_DEFAULT", "hi-Latn"
            ),
            tts_sample_rate=_env_int(e, "ZIVON_VOICE_TTS_SAMPLE_RATE", 48000),
            tts_voice=e.get("ZIVON_VOICE_TTS_VOICE", "Shivani"),
            tts_connect_timeout_s=_env_float(
                e, "ZIVON_VOICE_TTS_CONNECT_TIMEOUT_S", 10.0
            ),
            tts_first_audio_budget_ms=_env_int(
                e, "ZIVON_VOICE_TTS_FIRST_AUDIO_BUDGET_MS", 200
            ),
            tts_char_cap_turn=_env_int(e, "ZIVON_VOICE_TTS_CHAR_CAP_TURN", 1200),
            tts_tag_max_per_turn=_env_int(e, "ZIVON_VOICE_TTS_TAG_MAX_PER_TURN", 8),
            credit_daily_tranche=_env_int(e, "ZIVON_VOICE_CREDIT_DAILY_TRANCHE", 1000),
            credit_per_user_cap=_env_int(e, "ZIVON_VOICE_CREDIT_PER_USER_CAP", 30),
            credit_demo_tranche=_env_int(e, "ZIVON_VOICE_CREDIT_DEMO_TRANCHE", 1000),
            credit_demo_session_cap=_env_int(
                e, "ZIVON_VOICE_CREDIT_DEMO_SESSION_CAP", 100
            ),
            credit_stt_seconds_per_point=_env_int(
                e, "ZIVON_VOICE_CREDIT_STT_SECONDS_PER_POINT", 30
            ),
            credit_tts_chars_per_point=_env_int(
                e, "ZIVON_VOICE_CREDIT_TTS_CHARS_PER_POINT", 300
            ),
            ws_path=e.get("ZIVON_VOICE_WS_PATH", "/voice/ws"),
            ws_max_concurrent_sessions=_env_int(e, "ZIVON_VOICE_WS_MAX_SESSIONS", 10),
            ws_connects_per_min=_env_int(e, "ZIVON_VOICE_WS_CONNECTS_PER_MIN", 10),
            ws_allowed_origins=_env_list(e, "ZIVON_VOICE_WS_ALLOWED_ORIGINS"),
            ws_trusted_proxies=_env_list(e, "ZIVON_VOICE_WS_TRUSTED_PROXIES"),
            ws_ping_interval_s=_env_float(e, "ZIVON_VOICE_PING_INTERVAL_S", 15.0),
            ws_ping_miss_max=_env_int(e, "ZIVON_VOICE_PING_MISS_MAX", 3),
            resume_window_s=_env_float(e, "ZIVON_VOICE_RESUME_WINDOW_S", 60.0),
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
