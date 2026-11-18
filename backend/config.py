"""Runtime configuration for the Zivon core backend monolith.

All secrets and environment settings are loaded at runtime from environment
variables (`ZIVON_*` / `GNANI_*`). Never hardcode secrets in code or manifests.
"""

from __future__ import annotations

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

        return cls(
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
        )
