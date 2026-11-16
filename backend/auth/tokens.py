"""Opaque-token minting, hashing, and request-derived privacy hashes (ADR-0029).

Rules:
- Tokens are generated with `secrets` and never stored in plaintext. The table
  keeps `keyed_hash(key, "<domain>", token)` so a database read alone cannot
  replay a session, CSRF, verify, reset, or OAuth state token.
- The key is the backend's existing `ZIVON_SESSION_TOKEN_KEY` secret,
  domain-separated per purpose, so one leaked database does not yield another.
- The digest is keyed **BLAKE2b** (a MAC), not a bare fast hash. Password
  storage is Argon2id (`backend/auth/passwords.py`); this module never hashes a
  password.
- Client IPs and user agents are only ever stored as salted hashes (A-12); the
  raw values never reach the tables or logs.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Final

from ..abuse import compute_ip_hmac, extract_client_ip
from ..config import BackendConfig

SESSION_TOKEN_DOMAIN: Final[str] = "auth-session:"
CSRF_TOKEN_DOMAIN: Final[str] = "auth-csrf:"
EMAIL_TOKEN_DOMAIN: Final[str] = "auth-email:"
OAUTH_STATE_DOMAIN: Final[str] = "auth-oauth:"

# BLAKE2b limits: key <= 64 bytes, person <= 16 bytes. Every domain above fits.
_MAX_KEY_BYTES: Final[int] = 64
_MAX_PERSON_BYTES: Final[int] = 16


def new_token(nbytes: int = 32) -> str:
    """Return a URL-safe opaque token (256 bits by default)."""
    return secrets.token_urlsafe(nbytes)


def _key_bytes(secret_key: str) -> bytes:
    raw = secret_key.encode("utf-8")
    if len(raw) <= _MAX_KEY_BYTES:
        return raw
    return hashlib.blake2b(raw, digest_size=32).digest()


def keyed_hash(secret_key: str, domain: str, value: str) -> str:
    """Return a hex keyed BLAKE2b MAC of `value` bound to its purpose."""
    return hashlib.blake2b(
        value.encode("utf-8"),
        digest_size=32,
        key=_key_bytes(secret_key),
        person=domain.encode("ascii")[:_MAX_PERSON_BYTES],
    ).hexdigest()


def derive_csrf(secret_key: str, raw_session_token: str) -> str:
    """Derive the CSRF token from the session token (no extra stored secret).

    The server keeps only `keyed_hash(key, CSRF domain, csrf_token)` in
    `auth_session`, so a database read cannot produce a usable CSRF token
    either. The client receives this value in the session/register/login
    response body and echoes it in `X-CSRF-Token`; the cookie alone is therefore
    not enough to mutate state from a cross-site form.
    """
    digest = hashlib.blake2b(
        raw_session_token.encode("utf-8"),
        digest_size=32,
        key=_key_bytes(secret_key),
        person=CSRF_TOKEN_DOMAIN.encode("ascii")[:_MAX_PERSON_BYTES],
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
