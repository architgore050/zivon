"""Narration stage configuration: environment only, never files.

The factory's rule (AGENTS.md, factory/config.py) is that behaviour lives in
config.json and MODEL-PATH settings live in the environment. Narration is a
third kind of setting: it configures an EXTERNAL paid API (Gnani Timbre) and
a money cap (the A-15 build tranche), so every knob is an environment
variable - same discipline as ZIVON_API_KEY. Nothing here ever appears in
config.json, artifacts, logs (beyond booleans/counters), or git.

Budget semantics (backend-spec A-15, adopted 2026-11-07):
    The narration build budget is a bounded ONE-TIME Gnani-credit tranche for
    factory TTS, separate from the voice-agent daily tranche. Proposed cap
    <= 1,500 credits total [ASSUMPTION - founder approval before the first
    live narration run; re-calibrate against the Gnani dashboard when A-01
    publishes the real per-character prices].

Credit price: capacity-and-cost.md plans ~90,000 characters for the 6-topic
challenge batch against the 1,500-credit cap, which gives the default price
below (0.0167 credits/char). The real price is A-01 [ASSUMPTION]; the guard
refuses before a call would push the cumulative spend over the tranche.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import _env_bool, _env_number, _env_raw  # repo env helpers
from ..errors import ConfigError
from .errors import NarrationError

STAGE_ID = "12-narration"

# ADR-0009 / A-04: the locale enum is the 10 Gnani codes plus `hinglish`;
# TTS maps every locale onto a Timbre v3.0 language code (every v3.0 voice
# speaks all 10 languages; hinglish rides the hi-IN polyglot path). Keys are
# the locale tokens the product/factory uses (short code, full Gnani code,
# or hinglish); values are the TTS `language` parameter.
LOCALE_TO_TTS_LANGUAGE: dict[str, str] = {
    "en": "en-IN",
    "en-IN": "en-IN",
    "hi": "hi-IN",
    "hi-IN": "hi-IN",
    "hi-Latn": "hi-IN",
    "hinglish": "hi-IN",
    "ta": "ta-IN",
    "ta-IN": "ta-IN",
    "te": "te-IN",
    "te-IN": "te-IN",
    "mr": "mr-IN",
    "mr-IN": "mr-IN",
    "bn": "bn-IN",
    "bn-IN": "bn-IN",
    "gu": "gu-IN",
    "gu-IN": "gu-IN",
    "kn": "kn-IN",
    "kn-IN": "kn-IN",
    "ml": "ml-IN",
    "ml-IN": "ml-IN",
    "pa": "pa-IN",
    "pa-IN": "pa-IN",
}

# The challenge-window narration languages (factory language is English;
# per-locale expansion is a budgeted post-challenge tranche decision per
# capacity-and-cost.md). The env knob can widen it after founder approval.
DEFAULT_LANGS = ("en",)


@dataclass(frozen=True)
class NarrationEnv:
    """Validated view of the narration environment variables."""

    enabled: bool
    mode: str  # "auto" | "mock" | "live"
    langs: tuple[str, ...]
    budget_credits: float
    repair_rounds: int
    timbre_base_url: str | None
    # The API key is runtime-secret material: it is carried here so the live
    # client can authenticate, but it must NEVER be written to artifacts,
    # ledgers, or logs by any narration code path.
    timbre_api_key: str | None
    timbre_tts_path: str
    timbre_voice: str
    credits_per_char: float
    timbre_timeout_s: float
    timbre_connect_timeout_s: float
    timbre_max_attempts: int
    timbre_backoff_base_s: float
    coldstore_upload_cmd: str | None
    coldstore_readback_cmd: str | None
    coldstore_prefix: str
    coldstore_timeout_s: float

    @classmethod
    def from_env(cls) -> NarrationEnv:
        """Parse + validate the narration env vars. Missing optional vars
        take the documented defaults; a WRONG value is a hard error (a typo
        must crash the stage, not silently run with a default)."""
        enabled = _env_bool("ZIVON_NARRATION_ENABLED", False)
        mode = (_env_raw("ZIVON_NARRATION_MODE") or "auto").lower()
        if mode not in ("auto", "mock", "live"):
            raise ConfigError(
                f"ZIVON_NARRATION_MODE must be one of auto|mock|live (got {mode!r})"
            )
        langs_raw = _env_raw("ZIVON_NARRATION_LANGS") or ",".join(DEFAULT_LANGS)
        langs = tuple(lang.strip() for lang in langs_raw.split(",") if lang.strip())
        if not langs:
            raise ConfigError(
                "ZIVON_NARRATION_LANGS resolves to an empty language list"
            )
        unknown = [lang for lang in langs if lang not in LOCALE_TO_TTS_LANGUAGE]
        if unknown:
            raise ConfigError(
                f"ZIVON_NARRATION_LANGS has locale(s) outside the ADR-0009 "
                f"enum: {unknown}. Valid: {sorted(set(LOCALE_TO_TTS_LANGUAGE))}"
            )
        budget_credits = _env_number(
            "ZIVON_NARRATION_BUDGET_CREDITS", 1500.0, integer=False
        )
        if budget_credits < 0:
            raise ConfigError("ZIVON_NARRATION_BUDGET_CREDITS must be >= 0")
        repair_rounds = int(
            _env_number("ZIVON_NARRATION_REPAIR_ROUNDS", 2, integer=True)
        )
        if not 0 <= repair_rounds <= 5:
            raise ConfigError("ZIVON_NARRATION_REPAIR_ROUNDS must be 0..5")
        credits_per_char = _env_number(
            "ZIVON_TIMBRE_CREDITS_PER_CHAR", 1500.0 / 90000.0, integer=False
        )
        if credits_per_char <= 0:
            raise ConfigError("ZIVON_TIMBRE_CREDITS_PER_CHAR must be > 0")
        tts_path = _env_raw("ZIVON_TIMBRE_TTS_PATH") or "/v1/tts"
        if not tts_path.startswith("/"):
            raise ConfigError(
                "ZIVON_TIMBRE_TTS_PATH must start with '/' (it is appended to "
                "ZIVON_TIMBRE_BASE_URL)"
            )
        timeout_s = _env_number("ZIVON_TIMBRE_TIMEOUT_S", 120.0, integer=False)
        if timeout_s < 5:
            raise ConfigError("ZIVON_TIMBRE_TIMEOUT_S must be >= 5 seconds")
        connect_timeout_s = _env_number(
            "ZIVON_TIMBRE_CONNECT_TIMEOUT_S", 10.0, integer=False
        )
        if connect_timeout_s < 1:
            raise ConfigError("ZIVON_TIMBRE_CONNECT_TIMEOUT_S must be >= 1 second")
        max_attempts = int(_env_number("ZIVON_TIMBRE_MAX_ATTEMPTS", 3, integer=True))
        if max_attempts < 1:
            raise ConfigError("ZIVON_TIMBRE_MAX_ATTEMPTS must be >= 1")
        backoff_base_s = _env_number("ZIVON_TIMBRE_BACKOFF_BASE_S", 2.0, integer=False)
        if backoff_base_s < 0:
            raise ConfigError("ZIVON_TIMBRE_BACKOFF_BASE_S must be >= 0")
        coldstore_timeout_s = _env_number(
            "ZIVON_COLDSTORE_TIMEOUT_S", 120.0, integer=False
        )
        if coldstore_timeout_s < 5:
            raise ConfigError("ZIVON_COLDSTORE_TIMEOUT_S must be >= 5 seconds")
        env = cls(
            enabled=enabled,
            mode=mode,
            langs=langs,
            budget_credits=budget_credits,
            repair_rounds=repair_rounds,
            timbre_base_url=_env_raw("ZIVON_TIMBRE_BASE_URL"),
            timbre_api_key=_env_raw("ZIVON_TIMBRE_API_KEY"),
            timbre_tts_path=tts_path,
            timbre_voice=_env_raw("ZIVON_TIMBRE_VOICE") or "",
            credits_per_char=credits_per_char,
            timbre_timeout_s=timeout_s,
            timbre_connect_timeout_s=connect_timeout_s,
            timbre_max_attempts=max_attempts,
            timbre_backoff_base_s=backoff_base_s,
            coldstore_upload_cmd=_env_raw("ZIVON_COLDSTORE_UPLOAD_CMD"),
            coldstore_readback_cmd=_env_raw("ZIVON_COLDSTORE_READBACK_CMD"),
            coldstore_prefix=_env_raw("ZIVON_COLDSTORE_PREFIX") or "narration",
            coldstore_timeout_s=coldstore_timeout_s,
        )
        if env.enabled and env.resolved_mode == "live" and not env.timbre_base_url:
            raise NarrationError(
                STAGE_ID,
                "ZIVON_NARRATION_MODE=live needs ZIVON_TIMBRE_BASE_URL (the "
                "Gnani Timbre v3.0 endpoint). Set it (and ZIVON_TIMBRE_API_KEY) "
                "in the environment, or drop the mode to auto/mock.",
            )
        return env

    @property
    def resolved_mode(self) -> str:
        """auto resolves to live when a Timbre endpoint is configured, mock
        otherwise. A mock build is always printed loudly by the stage (its
        assets are silence placeholders, never for the live site)."""
        if self.mode == "auto":
            return "live" if self.timbre_base_url else "mock"
        return self.mode

    def tts_language(self, locale: str) -> str:
        """ADR-0009/A-04 locale -> Timbre v3.0 language parameter."""
        language = LOCALE_TO_TTS_LANGUAGE.get(locale)
        if language is None:
            raise NarrationError(
                STAGE_ID,
                f"locale {locale!r} is outside the ADR-0009 enum; extend "
                "LOCALE_TO_TTS_LANGUAGE deliberately (with the ADR), never "
                "guess a code at the API boundary",
            )
        return language

    def redacted(self) -> dict[str, Any]:
        """Artifact-safe view (no endpoint assumptions beyond the URL host,
        no API key). Used in the stage output."""
        return {
            "enabled": self.enabled,
            "mode": self.resolved_mode,
            "langs": list(self.langs),
            "budget_credits": self.budget_credits,
            "repair_rounds": self.repair_rounds,
            "timbre_configured": bool(self.timbre_base_url),
            "timbre_voice": self.timbre_voice or "(provider default)",
            "credits_per_char": self.credits_per_char,
            "coldstore_configured": bool(
                self.coldstore_upload_cmd and self.coldstore_readback_cmd
            ),
        }
