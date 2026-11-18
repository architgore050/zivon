"""Runtime configuration for the Zivon core backend monolith.

All secrets and environment settings are loaded at runtime from environment
variables (`ZIVON_*` / `GNANI_*`). Never hardcode secrets in code or manifests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Final

SUPPORTED_LOCALES: Final[tuple[str, ...]] = (
    "bn-IN",
    "en-IN",
    "gu-IN",
    "hi-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "pa-IN",
    "ta-IN",
    "te-IN",
    "hinglish",
    # BCP-47 short codes used by SP2 translation pipeline & frontend lang bar
    "en",
    "hi",
    "hi-Latn",
    "ta",
    "te",
    "mr",
    "bn",
    "gu",
    "kn",
    "ml",
    "pa",
)

CANONICAL_DB_LOCALES: Final[tuple[str, ...]] = (
    "bn-IN",
    "en-IN",
    "gu-IN",
    "hi-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "pa-IN",
    "ta-IN",
    "te-IN",
    "hinglish",
)

LOCALE_NORMALIZE_MAP: Final[dict[str, str]] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "hi-Latn": "hinglish",
    "bn": "bn-IN",
    "gu": "gu-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "pa": "pa-IN",
    "ta": "ta-IN",
    "te": "te-IN",
}

TIMBRE_V3_TAGS: Final[frozenset[str]] = frozenset(
    {
        "<laugh>",
        "<giggle>",
        "<sigh>",
        "<exhales>",
        "<sniffles>",
        "<yawns>",
        "<coughs>",
        "<clears throat>",
        "<whispers>",
        "<shouting>",
        "<excited>",
        "<slow>",
        "<pauses>",
    }
)

REPORT_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"wrong_physics", "bad_translation", "broken_sim", "other"}
)

CONSENT_ACTIONS: Final[frozenset[str]] = frozenset({"granted", "declined", "withdrawn"})

DEFAULT_NOTICE_VERSION: Final[str] = "zivon-voice-notice-v1"
DEFAULT_CONSENT_VERSION: Final[str] = "v1"

# SWOT placement modes (F8). `relative` is the frozen default; `absolute`
# exists behind the env var for calibration work and is never a student
# setting. See docs/specs/frontend/swot.md §8.
SWOT_MODES: Final[tuple[str, ...]] = ("relative", "absolute")
DEFAULT_SWOT_MODE: Final[str] = "relative"


class BackendConfigError(RuntimeError):
    """Raised when required backend configuration is missing or invalid."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise BackendConfigError(f"{name} must be an integer") from exc


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise BackendConfigError(f"{name} must be a number") from exc


def _json_env(name: str) -> dict[str, str] | None:
    """A JSON-object env var (§7.3 `ZIVON_PERSONALIZED_EXTRA_HEADERS`);
    malformed JSON fails loudly at boot."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackendConfigError(f"{name} must be a JSON object") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()
    ):
        raise BackendConfigError(f"{name} must be a JSON object of string pairs")
    return parsed


def _swot_mode(raw: str | None) -> str:
    """Validate `ZIVON_SWOT_MODE` at load time; a bad value refuses to boot."""
    mode = (raw or DEFAULT_SWOT_MODE).strip().lower()
    if mode not in SWOT_MODES:
        raise BackendConfigError(
            f"ZIVON_SWOT_MODE must be one of {'|'.join(SWOT_MODES)}"
        )
    return mode


def normalize_locale(locale: str) -> str:
    """Normalize a UI or Gnani locale code to the canonical DB enum value."""
    cleaned = locale.strip()
    if cleaned in CANONICAL_DB_LOCALES:
        return cleaned
    if cleaned in LOCALE_NORMALIZE_MAP:
        return LOCALE_NORMALIZE_MAP[cleaned]
    raise ValueError(f"Unsupported locale '{locale}'")


@dataclass(frozen=True)
class BackendConfig:
    """Immutable runtime configuration for the core backend monolith."""

    db_url: str
    env: str = "dev"
    release_tag: str = "0.1.0"
    session_token_key: str = "dev-only-session-token-key-change-in-cluster"
    ip_hash_salt: str = "dev-only-ip-hash-salt-change-in-cluster"
    admin_token: str | None = None
    current_notice_version: str = DEFAULT_NOTICE_VERSION
    current_consent_version: str = DEFAULT_CONSENT_VERSION
    session_ttl_seconds: int = 12 * 3600
    confirm_token_ttl_seconds: int = 600
    cold_provider: str = "b2"
    cold_bucket_primary: str = "zivon-cold-primary"
    cold_bucket_secondary: str = "zivon-cold-secondary"
    cold_staging_dir: str = "/tmp/zivon-cold-staging"
    runs_dir: str = "runs"
    frontend_dir: str = "frontend"
    voice_brain_transport: str = "gemini-direct"
    voice_brain_model: str = "gemma-4-26b-a4b-it"
    # Rate limits per minute per IP hash (backend-spec §8.3)
    rate_limit_api_per_min: int = 30
    rate_limit_ws_per_min: int = 10
    rate_limit_events_per_min: int = 12
    rate_limit_reports_per_min: int = 5
    rate_limit_delete_per_min: int = 3
    # Personalized-learning families (data-and-api.md §4.1, D-PL-01): the
    # create family uses a per-HOUR window, the rest per-minute (abuse.py).
    rate_limit_personalized_turn_per_min: int = 6
    rate_limit_personalized_create_per_hour: int = 5
    rate_limit_personalized_read_per_min: int = 60
    rate_limit_personalized_ip_per_min: int = 20
    ws_max_concurrent_per_session: int = 1
    ws_max_concurrent_cluster: int = 10
    # Account auth, email, and Google OAuth (ADR-0029). Secrets stay runtime-only.
    auth_session_ttl_seconds: int = 30 * 24 * 3600
    auth_verify_token_ttl_seconds: int = 48 * 3600
    auth_reset_token_ttl_seconds: int = 3600
    auth_cookie_name: str = "zivon_session"
    auth_cookie_secure: bool = True
    auth_cookie_domain: str | None = None
    auth_register_per_min: int = 5
    auth_login_per_min: int = 10
    auth_reset_per_min: int = 3
    auth_verify_per_min: int = 10
    auth_google_per_min: int = 10
    app_base_url: str = "http://localhost:8081"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    email_backend: str = "dev"
    email_from: str = "Zivon <no-reply@zivon.local>"
    dev_email_dir: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    resend_api_key: str | None = None
    swot_mode: str = DEFAULT_SWOT_MODE
    # Personalized learning (W5.5 PL1, data-and-api.md §2.6/D-PL-01). The
    # numbers are the open D-PL-01 recommendations: a founder change is an
    # env/config change, never a migration. No paywall/plan fields exist.
    personalized_enabled: bool = True
    personalized_turn_engine_enabled: bool = False  # PL2 flips this with the real route
    personalized_turns_per_user_per_day: int = 40
    personalized_turn_concurrency: int = 2
    personalized_sessions_per_user_per_day: int = 5
    personalized_artifacts_per_user_per_day: int = 12
    personalized_turns_global_per_day: int = 1500
    personalized_artifacts_global_per_day: int = 300
    personalized_retention_session_days: int = 90
    personalized_retention_artifact_days: int = 30
    personalized_retention_artifact_failed_days: int = 7
    personalized_retention_usage_days: int = 90
    # Personalized-learning model route (W5.5 PL2, D-PL-07 / ADR-0030):
    # DeepSeek V4.1 Flash via the OpenCode OpenAI-format API, called through
    # the in-process `llm_manager` library with its OWN secret/config —
    # separate from the voice tutor (Gemini) and the factory. Secrets are
    # runtime-only; the API key lives in the `zivon-personalized-env` K8s
    # Secret. Boot refuses to wire the turn engine when the switch is on and
    # the route is incomplete (loud, no silent default, §7.3).
    personalized_model_base_url: str | None = None
    personalized_model_api_key: str | None = None
    personalized_model: str = "deepseek-v4.1-flash"
    personalized_model_extra_headers: dict[str, str] | None = None
    personalized_model_user_agent: str = "zivon-personalized/1"
    personalized_model_timeout_s: float = 8.0
    personalized_model_deadline_s: float = 30.0
    personalized_model_reasoning_effort: str = "low"
    personalized_index_dir: str | None = None
    # The D-PL-07 route (ADR-0030): one DeepSeek/OpenCode config + secret for
    # the personalized-learning model calls, separate from both the voice
    # tutor and the factory. `personalized_artifact_build_enabled` is the PL3
    # build switch: fail-closed OFF, and boot refuses the ON state without the
    # route configured (loud, no silent default — ADR-0030 consequence).
    personalized_artifact_build_enabled: bool = False
    personalized_llm_base_url: str | None = None
    personalized_llm_api_key: str | None = None
    personalized_llm_model: str = "deepseek-v4.1-flash"
    personalized_llm_call_deadline_s: int = 120

    @classmethod
    def from_env(cls, *, strict_secrets: bool = False) -> BackendConfig:
        """Load configuration from environment variables."""
        env = os.environ.get("ZIVON_ENV", "dev").strip() or "dev"
        db_url = os.environ.get("ZIVON_DB_URL", "").strip()
        if not db_url:
            if strict_secrets or env in ("cluster", "prod"):
                raise BackendConfigError(
                    "ZIVON_DB_URL must be set in cluster/prod environments"
                )
            db_url = "sqlite:///:memory:"

        session_token_key = os.environ.get("ZIVON_SESSION_TOKEN_KEY", "").strip()
        ip_hash_salt = os.environ.get("ZIVON_IP_HASH_SALT", "").strip()
        if strict_secrets or env in ("cluster", "prod"):
            if not session_token_key:
                raise BackendConfigError(
                    "ZIVON_SESSION_TOKEN_KEY must be set in cluster/prod environments"
                )
            if not ip_hash_salt:
                raise BackendConfigError(
                    "ZIVON_IP_HASH_SALT must be set in cluster/prod environments"
                )
        else:
            session_token_key = (
                session_token_key or "dev-only-session-token-key-change-in-cluster"
            )
            ip_hash_salt = ip_hash_salt or "dev-only-ip-hash-salt-change-in-cluster"

        admin_token_raw = os.environ.get("ZIVON_ADMIN_TOKEN", "").strip()
        admin_token = admin_token_raw if admin_token_raw else None

        config = cls(
            db_url=db_url,
            env=env,
            release_tag=os.environ.get("ZIVON_BACKEND_RELEASE", "0.1.0").strip()
            or "0.1.0",
            session_token_key=session_token_key,
            ip_hash_salt=ip_hash_salt,
            admin_token=admin_token,
            current_notice_version=os.environ.get(
                "ZIVON_NOTICE_VERSION", DEFAULT_NOTICE_VERSION
            ).strip()
            or DEFAULT_NOTICE_VERSION,
            current_consent_version=os.environ.get(
                "ZIVON_CONSENT_VERSION", DEFAULT_CONSENT_VERSION
            ).strip()
            or DEFAULT_CONSENT_VERSION,
            cold_provider=os.environ.get("COLD_PROVIDER", "b2").strip() or "b2",
            cold_bucket_primary=os.environ.get(
                "COLD_BUCKET_PRIMARY", "zivon-cold-primary"
            ).strip()
            or "zivon-cold-primary",
            cold_bucket_secondary=os.environ.get(
                "COLD_BUCKET_SECONDARY", "zivon-cold-secondary"
            ).strip()
            or "zivon-cold-secondary",
            cold_staging_dir=os.environ.get(
                "ZIVON_COLD_STAGING_DIR", "/tmp/zivon-cold-staging"
            ).strip()
            or "/tmp/zivon-cold-staging",
            runs_dir=os.environ.get("ZIVON_RUNS_DIR", "runs").strip() or "runs",
            frontend_dir=os.environ.get("ZIVON_FRONTEND_DIR", "frontend").strip()
            or "frontend",
            voice_brain_transport=os.environ.get(
                "ZIVON_VOICE_BRAIN_TRANSPORT", "gemini-direct"
            ).strip()
            or "gemini-direct",
            voice_brain_model=os.environ.get(
                "ZIVON_VOICE_BRAIN_MODEL", "gemma-4-26b-a4b-it"
            ).strip()
            or "gemma-4-26b-a4b-it",
            auth_session_ttl_seconds=_env_int(
                "ZIVON_AUTH_SESSION_TTL_S", 30 * 24 * 3600
            ),
            auth_verify_token_ttl_seconds=_env_int(
                "ZIVON_AUTH_VERIFY_TTL_S", 48 * 3600
            ),
            auth_reset_token_ttl_seconds=_env_int("ZIVON_AUTH_RESET_TTL_S", 3600),
            auth_cookie_name=os.environ.get(
                "ZIVON_AUTH_COOKIE_NAME", "zivon_session"
            ).strip()
            or "zivon_session",
            auth_cookie_secure=_env_bool(
                "ZIVON_AUTH_COOKIE_SECURE", env not in ("dev",)
            ),
            auth_cookie_domain=_optional_env("ZIVON_AUTH_COOKIE_DOMAIN"),
            auth_register_per_min=_env_int("ZIVON_AUTH_REGISTER_PER_MIN", 5),
            auth_login_per_min=_env_int("ZIVON_AUTH_LOGIN_PER_MIN", 10),
            auth_reset_per_min=_env_int("ZIVON_AUTH_RESET_PER_MIN", 3),
            auth_verify_per_min=_env_int("ZIVON_AUTH_VERIFY_PER_MIN", 10),
            auth_google_per_min=_env_int("ZIVON_AUTH_GOOGLE_PER_MIN", 10),
            app_base_url=os.environ.get(
                "ZIVON_APP_BASE_URL", "http://localhost:8081"
            ).strip()
            or "http://localhost:8081",
            google_client_id=_optional_env("GOOGLE_CLIENT_ID"),
            google_client_secret=_optional_env("GOOGLE_CLIENT_SECRET"),
            google_redirect_uri=_optional_env("GOOGLE_REDIRECT_URI"),
            email_backend=os.environ.get("ZIVON_EMAIL_BACKEND", "dev").strip() or "dev",
            email_from=os.environ.get(
                "ZIVON_EMAIL_FROM", "Zivon <no-reply@zivon.local>"
            ).strip()
            or "Zivon <no-reply@zivon.local>",
            dev_email_dir=_optional_env("ZIVON_DEV_EMAIL_DIR"),
            smtp_host=_optional_env("ZIVON_SMTP_HOST"),
            smtp_port=_env_int("ZIVON_SMTP_PORT", 587),
            smtp_user=_optional_env("ZIVON_SMTP_USER"),
            smtp_password=_optional_env("ZIVON_SMTP_PASSWORD"),
            smtp_starttls=_env_bool("ZIVON_SMTP_STARTTLS", True),
            resend_api_key=_optional_env("ZIVON_RESEND_API_KEY"),
            swot_mode=_swot_mode(os.environ.get("ZIVON_SWOT_MODE")),
            personalized_enabled=_env_bool("ZIVON_PERSONALIZED_ENABLED", True),
            personalized_turn_engine_enabled=_env_bool(
                "ZIVON_PERSONALIZED_TURN_ENGINE_ENABLED", False
            ),
            personalized_turns_per_user_per_day=_env_int(
                "ZIVON_PERSONALIZED_TURNS_PER_USER_DAY", 40
            ),
            personalized_turn_concurrency=_env_int(
                "ZIVON_PERSONALIZED_TURN_CONCURRENCY", 2
            ),
            personalized_sessions_per_user_per_day=_env_int(
                "ZIVON_PERSONALIZED_SESSIONS_PER_USER_DAY", 5
            ),
            personalized_artifacts_per_user_per_day=_env_int(
                "ZIVON_PERSONALIZED_ARTIFACTS_PER_USER_DAY", 12
            ),
            personalized_turns_global_per_day=_env_int(
                "ZIVON_PERSONALIZED_TURNS_GLOBAL_DAY", 1500
            ),
            personalized_artifacts_global_per_day=_env_int(
                "ZIVON_PERSONALIZED_ARTIFACTS_GLOBAL_DAY", 300
            ),
            personalized_retention_session_days=_env_int(
                "ZIVON_PERSONALIZED_RETENTION_SESSION_DAYS", 90
            ),
            personalized_retention_artifact_days=_env_int(
                "ZIVON_PERSONALIZED_RETENTION_ARTIFACT_DAYS", 30
            ),
            personalized_retention_artifact_failed_days=_env_int(
                "ZIVON_PERSONALIZED_RETENTION_ARTIFACT_FAILED_DAYS", 7
            ),
            personalized_retention_usage_days=_env_int(
                "ZIVON_PERSONALIZED_RETENTION_USAGE_DAYS", 90
            ),
            personalized_model_base_url=_optional_env("ZIVON_PERSONALIZED_BASE_URL"),
            personalized_model_api_key=_optional_env("ZIVON_PERSONALIZED_API_KEY"),
            personalized_model=os.environ.get(
                "ZIVON_PERSONALIZED_MODEL", "deepseek-v4.1-flash"
            ).strip()
            or "deepseek-v4.1-flash",
            personalized_model_extra_headers=_json_env(
                "ZIVON_PERSONALIZED_EXTRA_HEADERS"
            ),
            personalized_model_user_agent=os.environ.get(
                "ZIVON_PERSONALIZED_USER_AGENT", "zivon-personalized/1"
            ).strip()
            or "zivon-personalized/1",
            personalized_model_timeout_s=_env_float(
                "ZIVON_PERSONALIZED_TIMEOUT_S", 8.0
            ),
            personalized_model_deadline_s=_env_float(
                "ZIVON_PERSONALIZED_DEADLINE_S", 30.0
            ),
            personalized_model_reasoning_effort=os.environ.get(
                "ZIVON_PERSONALIZED_REASONING_EFFORT", "low"
            ).strip()
            or "low",
            personalized_index_dir=_optional_env("ZIVON_PERSONALIZED_INDEX_DIR"),
            personalized_artifact_build_enabled=_env_bool(
                "ZIVON_PERSONALIZED_ARTIFACT_BUILDS", False
            ),
            personalized_llm_base_url=_optional_env("ZIVON_PERSONALIZED_LLM_BASE_URL"),
            personalized_llm_api_key=_optional_env("ZIVON_PERSONALIZED_API_KEY"),
            personalized_llm_model=os.environ.get(
                "ZIVON_PERSONALIZED_LLM_MODEL", "deepseek-v4.1-flash"
            ).strip()
            or "deepseek-v4.1-flash",
            personalized_llm_call_deadline_s=_env_int(
                "ZIVON_PERSONALIZED_CALL_DEADLINE_S", 120
            ),
        )
        cls._validate_personalized_route(config)
        if config.personalized_artifact_build_enabled and (
            not config.personalized_llm_base_url
            or not config.personalized_llm_api_key
        ):
            raise BackendConfigError(
                "ZIVON_PERSONALIZED_ARTIFACT_BUILDS=true requires the D-PL-07 route "
                "(ZIVON_PERSONALIZED_LLM_BASE_URL + ZIVON_PERSONALIZED_API_KEY); "
                "boot refuses an enabled build path without its own secret"
            )
        return config

    @staticmethod
    def _validate_personalized_route(config: BackendConfig) -> None:
        """Boot refusal when the turn engine is switched on without a route
        (§7.3: loud, no silent default). The error never quotes the key."""
        if config.personalized_turn_engine_enabled and (
            not config.personalized_model_base_url
            or not config.personalized_model_api_key
        ):
            missing = [
                name
                for name, value in (
                    ("ZIVON_PERSONALIZED_BASE_URL", config.personalized_model_base_url),
                    ("ZIVON_PERSONALIZED_API_KEY", config.personalized_model_api_key),
                )
                if not value
            ]
            raise BackendConfigError(
                "ZIVON_PERSONALIZED_TURN_ENGINE_ENABLED is set but the "
                f"personalized model route is incomplete; missing: {', '.join(missing)}"
            )
