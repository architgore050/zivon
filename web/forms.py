"""HTML form plumbing for the server-rendered auth and settings pages (F2).

Two CSRF contracts meet here, and neither is a second auth implementation:

- A **signed-in** form renders the session-derived token with F0C's
  `csrf_field()` and the route verifies it with `AuthService.verify_csrf`.
- A **guest** form (sign in, sign up, reset, verification) has no session yet,
  so there is no session-derived token. It uses a signed, double-submitted
  token: the GET issues a random nonce in an HttpOnly cookie and renders
  `keyed_hash(secret, "form-csrf:", nonce)` as the hidden field. A cross-site
  form cannot read the nonce, and it cannot set a cookie on this origin, so a
  forged POST cannot produce a matching pair. The token is not bound to a
  form name: one open tab may move between the auth screens.

Bodies are parsed here with the standard library (`parse_qs`) rather than
Starlette's `request.form()`, which needs the `python-multipart` package that
the backend image does not ship. Only `application/x-www-form-urlencoded`,
the default browser encoding, is accepted.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import Response

from backend.auth.passwords import same_secret
from backend.auth.tokens import keyed_hash, new_token
from backend.config import BackendConfig

from .context import config_for

GUEST_FORM_COOKIE: Final[str] = "zivon_form_token"
GUEST_FORM_COOKIE_MAX_AGE: Final[int] = 2 * 3600
_FORM_TOKEN_DOMAIN: Final[str] = "form-csrf:"
_URLENCODED: Final[str] = "application/x-www-form-urlencoded"
_MAX_FORM_BYTES: Final[int] = 16 * 1024
_MAX_FORM_FIELDS: Final[int] = 32


class FormTooLarge(ValueError):
    """The posted body exceeds the small budget an auth/settings form needs."""


class FormBadEncoding(ValueError):
    """The posted body is not a browser URL-encoded form."""


def _sign(config: BackendConfig, nonce: str) -> str:
    return keyed_hash(config.session_token_key, _FORM_TOKEN_DOMAIN, nonce)


def new_guest_token(config: BackendConfig) -> tuple[str, str]:
    """Mint `(form_token, cookie_value)` for one guest form render.

    The cookie value is the nonce; the form token is its keyed MAC. The raw
    nonce is not a credential on its own (the MAC cannot be forged without the
    server key), so both halves travel.
    """
    nonce = new_token(24)
    return _sign(config, nonce), nonce


def attach_guest_cookie(
    response: Response, config: BackendConfig, cookie_value: str
) -> None:
    """Set the double-submit nonce cookie on a fresh form render."""
    response.set_cookie(
        key=GUEST_FORM_COOKIE,
        value=cookie_value,
        max_age=GUEST_FORM_COOKIE_MAX_AGE,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def guest_token_valid(request: Request, submitted: str | None) -> bool:
    """Compare the submitted MAC with the MAC of this browser's nonce cookie."""
    token = (submitted or "").strip()
    cookie_value = request.cookies.get(GUEST_FORM_COOKIE, "").strip()
    if not token or not cookie_value:
        return False
    expected = _sign(config_for(request), cookie_value)
    # Constant-time compare: the MAC is a secret-derived value.
    return same_secret(expected, token)


async def read_form(request: Request) -> dict[str, str]:
    """Parse a URL-encoded form body into one value per field.

    Rejects an oversized body and a non-form content type instead of guessing;
    a browser form post always carries the URL-encoded type. The body is read
    in chunks and abandoned as soon as it passes the budget, so an unauthenticated
    oversized post cannot make the app buffer it whole.
    """
    content_type = (request.headers.get("content-type") or "").split(";", 1)[0]
    if content_type.strip().lower() != _URLENCODED:
        raise FormBadEncoding("form posts must be application/x-www-form-urlencoded")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_FORM_BYTES:
            raise FormTooLarge("form body too large")
    try:
        parsed = parse_qs(
            body.decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=_MAX_FORM_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise FormBadEncoding("form body is not valid URL-encoded UTF-8") from exc
    # A repeated field is not a feature of any auth/settings form; the last
    # value wins, matching how a browser submits a hidden duplicate.
    return {key: values[-1] for key, values in parsed.items()}


__all__ = [
    "GUEST_FORM_COOKIE",
    "FormBadEncoding",
    "FormTooLarge",
    "attach_guest_cookie",
    "guest_token_valid",
    "new_guest_token",
    "read_form",
]
