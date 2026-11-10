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

CONSENT_ACTIONS: Final[frozenset[str]] = frozenset(
    {"granted", "declined", "withdrawn"}
)

DEFAULT_NOTICE_VERSION: Final[str] = "zivon-voice-notice-v1"
DEFAULT_CONSENT_VERSION: Final[str] = "v1"


class BackendConfigError(RuntimeError):
    """Raised when required backend configuration is missing or invalid."""


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
        )
