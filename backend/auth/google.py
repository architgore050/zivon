"""Google OAuth 2.0 / OIDC client with a mockable transport (ADR-0029).

The callback exchanges the authorization code (with PKCE) at Google's token
endpoint and then reads the user's profile from the OIDC userinfo endpoint over
TLS. `email_verified` must be true before the identity is trusted.

Id-token signature verification (JWKS) is deliberately not implemented: the
userinfo response is fetched directly from Google with a token that was just
issued to this client over an authenticated TLS channel, so it carries the same
trust as the id_token for our purposes. Revisit if Google returns identity
claims from a source other than its own endpoint.

Tests inject a `GoogleTransport`; no live Google call ever runs in the suite.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import time
from typing import Any, Final, Protocol

from ..config import BackendConfig, BackendConfigError
from .tokens import (
    OAUTH_STATE_DOMAIN,
    b64url,
    b64url_decode,
    keyed_hash,
    new_token,
)

AUTHORIZE_ENDPOINT: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT: Final[str] = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES: Final[str] = "openid email profile"
STATE_TTL_SECONDS: Final[int] = 600


class GoogleAuthError(Exception):
    """A Google flow failure carrying the public API error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str | None


class GoogleTransport(Protocol):
    def post_form(
        self, url: str, data: dict[str, str], *, timeout_s: float
    ) -> dict[str, Any]: ...

    def get_json(
        self, url: str, headers: dict[str, str], *, timeout_s: float
    ) -> dict[str, Any]: ...


def code_challenge(verifier: str) -> str:
    """S256 PKCE challenge (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return b64url(digest)


def sign_state(config: BackendConfig, payload: dict[str, Any]) -> str:
    """Sign the short-lived OAuth transaction into an HttpOnly cookie value."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = b64url(raw)
    signature = keyed_hash(config.session_token_key, OAUTH_STATE_DOMAIN, encoded)
    return f"{encoded}.{signature}"


def verify_state(
    config: BackendConfig, value: str | None, *, now_ts: int | None = None
) -> dict[str, Any] | None:
    if not value or "." not in value:
        return None
    encoded, signature = value.rsplit(".", 1)
    expected = keyed_hash(config.session_token_key, OAUTH_STATE_DOMAIN, encoded)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(b64url_decode(encoded).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    now = int(time.time() if now_ts is None else now_ts)
    if int(payload.get("exp", 0)) < now:
        return None
    if not payload.get("state") or not payload.get("verifier"):
        return None
    if payload.get("intent") not in ("login", "link"):
        return None
    return payload


class HttpxGoogleTransport:
    """Production transport. Local import keeps httpx off the dev/test path."""

    def post_form(
        self, url: str, data: dict[str, str], *, timeout_s: float
    ) -> dict[str, Any]:
        import httpx

        try:
            response = httpx.post(url, data=data, timeout=timeout_s)
        except httpx.HTTPError as exc:
            raise GoogleAuthError("E-SERVICE-UNAVAILABLE") from exc
        if response.status_code >= 400:
            raise GoogleAuthError("E-AUTH-INVALID")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleAuthError("E-SERVICE-UNAVAILABLE") from exc
        if not isinstance(payload, dict):
            raise GoogleAuthError("E-SERVICE-UNAVAILABLE")
        return payload

    def get_json(
        self, url: str, headers: dict[str, str], *, timeout_s: float
    ) -> dict[str, Any]:
        import httpx

        try:
            response = httpx.get(url, headers=headers, timeout=timeout_s)
        except httpx.HTTPError as exc:
            raise GoogleAuthError("E-SERVICE-UNAVAILABLE") from exc
        if response.status_code >= 400:
            raise GoogleAuthError("E-AUTH-INVALID")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleAuthError("E-SERVICE-UNAVAILABLE") from exc
        if not isinstance(payload, dict):
            raise GoogleAuthError("E-SERVICE-UNAVAILABLE")
        return payload


class GoogleOAuthClient:
    """Authorization-URL builder + code exchange for the Google identity flow."""

    def __init__(
        self,
        config: BackendConfig,
        *,
        transport: GoogleTransport | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.config = config
        self.transport: GoogleTransport = transport or HttpxGoogleTransport()
        self.timeout_s = timeout_s

    @property
    def configured(self) -> bool:
        cfg = self.config
        return bool(cfg.google_client_id and cfg.google_client_secret)

    def redirect_uri(self, base_url: str | None = None) -> str:
        if self.config.google_redirect_uri:
            return self.config.google_redirect_uri
        base = (base_url or self.config.app_base_url).rstrip("/")
        return f"{base}/v1/auth/google/callback"

    def start(
        self,
        *,
        intent: str,
        next_path: str,
        base_url: str | None = None,
        now_ts: int | None = None,
    ) -> tuple[str, str]:
        """Return `(authorization_url, state_cookie_value)`."""
        if not self.configured:
            raise BackendConfigError("Google OAuth is not configured")
        if intent not in ("login", "link"):
            raise GoogleAuthError("E-VALIDATION")
        state = new_token(24)
        verifier = new_token(48)
        now = int(time.time() if now_ts is None else now_ts)
        redirect = self.redirect_uri(base_url)
        from urllib.parse import urlencode

        query = urlencode(
            {
                "client_id": self.config.google_client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPES,
                "state": state,
                "code_challenge": code_challenge(verifier),
                "code_challenge_method": "S256",
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        cookie = sign_state(
            self.config,
            {
                "state": state,
                "verifier": verifier,
                "intent": intent,
                "next": next_path,
                "exp": now + STATE_TTL_SECONDS,
            },
        )
        return f"{AUTHORIZE_ENDPOINT}?{query}", cookie

    def exchange(
        self, *, code: str, verifier: str, base_url: str | None = None
    ) -> GoogleIdentity:
        if not self.configured:
            raise BackendConfigError("Google OAuth is not configured")
        token = self.transport.post_form(
            TOKEN_ENDPOINT,
            {
                "code": code,
                "client_id": str(self.config.google_client_id),
                "client_secret": str(self.config.google_client_secret),
                "redirect_uri": self.redirect_uri(base_url),
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout_s=self.timeout_s,
        )
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GoogleAuthError("E-AUTH-INVALID")
        profile = self.transport.get_json(
            USERINFO_ENDPOINT,
            {"Authorization": f"Bearer {access_token}"},
            timeout_s=self.timeout_s,
        )
        subject = profile.get("sub")
        email = profile.get("email")
        if not isinstance(subject, str) or not subject:
            raise GoogleAuthError("E-AUTH-INVALID")
        if not isinstance(email, str) or "@" not in email:
            raise GoogleAuthError("E-AUTH-INVALID")
        name = profile.get("name") if isinstance(profile.get("name"), str) else None
        return GoogleIdentity(
            subject=subject,
            email=email.strip().lower(),
            email_verified=profile.get("email_verified") is True,
            name=name,
        )
