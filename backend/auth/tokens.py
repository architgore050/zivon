"""Opaque-token minting, hashing, and request-derived privacy hashes (ADR-0029).

Rules:
- Tokens are generated with `secrets` and never stored in plaintext. The table
  keeps `HMAC-SHA256(key, "<domain>:" + token)` so a database read alone cannot
  replay a session, CSRF, verify, reset, or OAuth state token.
- The HMAC key is the backend's existing `ZIVON_SESSION_TOKEN_KEY` secret,
  domain-separated per purpose, so one leaked database does not yield another.
- Client IPs and user agents are only ever stored as salted hashes (A-12); the
  raw values never reach the tables or logs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Final

from ..abuse import compute_ip_hmac, extract_client_ip
from ..config import BackendConfig

SESSION_TOKEN_DOMAIN: Final[str] = "auth-session:"
CSRF_TOKEN_DOMAIN: Final[str] = "auth-csrf:"
EMAIL_TOKEN_DOMAIN: Final[str] = "auth-email:"
OAUTH_STATE_DOMAIN: Final[str] = "auth-oauth:"


def new_token(nbytes: int = 32) -> str:
    """Return a URL-safe opaque token (256 bits by default)."""
    return secrets.token_urlsafe(nbytes)


def keyed_hash(secret_key: str, domain: str, value: str) -> str:
    """Return a hex HMAC-SHA256 of `value` bound to its purpose."""
    return hmac.new(
        secret_key.encode("utf-8"),
        (domain + value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def derive_csrf(secret_key: str, raw_session_token: str) -> str:
    """Derive the CSRF token from the session token (no extra stored secret).

    The server keeps only `HMAC(CSRF domain, csrf_token)` in `auth_session`,
    so a database read cannot produce a usable CSRF token either. The client
    receives this value in the session/register/login response body and echoes
    it in `X-CSRF-Token`; the cookie alone is therefore not enough to mutate
    state from a cross-site form.
    """
    digest = hmac.new(
        secret_key.encode("utf-8"),
        (CSRF_TOKEN_DOMAIN + raw_session_token).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return b64url(digest)


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(text + pad)


def request_ip_hash(config: BackendConfig, raw_ip: str) -> str | None:
    """Daily-rotating salted IP hash, or None for a blank IP."""
    cleaned = (raw_ip or "").strip()
    if not cleaned:
        return None
    return compute_ip_hmac(cleaned, config.ip_hash_salt)


def request_ip_hash_from_request(config: BackendConfig, request: object) -> str | None:
    """Convenience wrapper used by routes (takes a FastAPI Request)."""
    try:
        raw_ip = extract_client_ip(request)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    return request_ip_hash(config, raw_ip)


def user_agent_hash(config: BackendConfig, user_agent: str | None) -> str | None:
    agent = (user_agent or "").strip()
    if not agent:
        return None
    return keyed_hash(config.ip_hash_salt, "ua:", agent[:512])[:32]
