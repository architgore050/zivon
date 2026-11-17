"""Shared view helpers for the F2 auth and settings pages.

The pages render through the F0C shell (`ShellContext`, `render_page`) and use
only the F0 account service (`AuthService.resolve`, `verify_csrf`, `csrf_for`,
`register`, `login`, ...). Nothing here re-implements password, OAuth, or
session logic; the routes translate HTML forms into service calls and service
results into pages.

The cookie read and the session lookup live in `web/context.py`
(`resolve_auth_session`), so the guard and the HTML forms share one resolver;
this module only adds the view-model pieces the F2 pages need.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.auth import SessionGrant
from backend.config import BackendConfig

from .context import (
    AuthSession,
    FlashMessage,
    ShellContext,
    config_for,
    resolve_auth_session,
    service_for,
)
from .render import render_page

LANGUAGE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("en-IN", "English"),
    ("hi-IN", "Hindi (हिन्दी)"),
    ("hinglish", "Hinglish (Hindi in Roman script)"),
)
BOARD_CHOICES: Final[tuple[str, ...]] = ("CBSE", "ICSE", "State Board")
CLASS_CHOICES: Final[tuple[int, ...]] = (9, 10, 11, 12)

_NOTICE_OK: Final[str] = "empty"

# The route-facing name for a resolved session; `AuthSession` carries the
# `AuthContext` (and its CSRF hash) that `AuthService.verify_csrf` needs.
PageAccount = AuthSession


def page_account(request: Request) -> PageAccount | None:
    """Resolve the account cookie through the shared F0C resolver."""
    return resolve_auth_session(request)


def public_shell(
    request: Request,
    title: str,
    *,
    flash: Sequence[FlashMessage] = (),
    error: str | None = None,
) -> ShellContext:
    """The single-paper-card auth shell: no account chip, no self sign-in link."""
    return ShellContext.for_public(
        path=request.url.path,
        page_title=title,
        flash=tuple(flash),
        error=error,
        auth_available=False,
    )


def account_shell(
    request: Request,
    account: PageAccount,
    title: str,
    *,
    flash: Sequence[FlashMessage] = (),
    error: str | None = None,
) -> ShellContext:
    return ShellContext.for_account(
        account.shell_account,
        path=request.url.path,
        page_title=title,
        flash=tuple(flash),
        error=error,
    )


def notice(text: str, kind: str = _NOTICE_OK) -> FlashMessage:
    """One shell notice. `kind` is the F0C set: empty/partial/error."""
    return FlashMessage(text, kind=kind)


def render_public_page(
    request: Request,
    template: str,
    title: str,
    *,
    status_code: int = 200,
    extra: dict[str, object] | None = None,
    flash: Sequence[FlashMessage] = (),
    error: str | None = None,
) -> HTMLResponse:
    """Render a public (guest/auth) page through the F0C shell."""
    shell = public_shell(request, title, flash=flash, error=error)
    return render_page(
        request, template, shell=shell, status_code=status_code, extra=extra
    )


def render_error_page(
    request: Request,
    *,
    status_code: int,
    title: str,
    message: str,
    retry_after: int | None = None,
) -> HTMLResponse:
    """Render the branded error page for an HTML route (never the JSON envelope)."""
    shell = ShellContext.for_public(
        path=request.url.path,
        page_title=title,
        error=message,
    )
    response = render_page(
        request,
        "error.html",
        shell=shell,
        status_code=status_code,
        extra={"status_code": status_code, "error_title": title, "error_text": message},
    )
    if retry_after is not None:
        response.headers["Retry-After"] = str(max(1, retry_after))
    return response


def redirect_with_session(
    config: BackendConfig, grant: SessionGrant, url: str
) -> RedirectResponse:
    """303 after a successful auth write, setting the F0 HttpOnly session cookie."""
    from backend.routes.auth import _set_session_cookie

    response = RedirectResponse(url=url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, config, grant)
    return response


def redirect_and_clear_session(config: BackendConfig, url: str) -> RedirectResponse:
    """303 after sign-out or account deletion, clearing the F0 session cookie."""
    from backend.routes.auth import _clear_session_cookie

    response = RedirectResponse(url=url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response, config)
    return response


def password_reason_copy(reason: str | None) -> str:
    """Map F0's stable rejection codes to honest, fixable copy."""
    return {
        "too_short": "Use at least 10 characters.",
        "too_long": "That password is too long. Use 128 characters or fewer.",
        "too_common": "That password is too common. Choose something harder to guess.",
        "too_simple": "Use more than one repeated character.",
        "too_predictable": "Do not use your email address as the password.",
    }.get(reason or "", "Choose a different password.")


def validation_copy(reason: str | None) -> str:
    return {
        "invalid_email": "Enter a valid email address.",
        "invalid_class_level": "Choose a class between 9 and 12.",
        "invalid_language": "Choose English, Hindi, or Hinglish.",
        "invalid_board": "That board name is too long. Use 40 characters or fewer.",
        "display_name_too_long": "Use 80 characters or fewer.",
        "no_fields": "Change at least one field before saving.",
    }.get(reason or "", "Check the values and try again.")


def retry_after_seconds(exc: Exception) -> int:
    value = getattr(exc, "retry_after", None)
    if value is None:
        return 60
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return 60
    return max(1, min(seconds, 3600))


def rate_limit_copy(exc: Exception) -> str:
    seconds = retry_after_seconds(exc)
    return f"Too many attempts from this connection. Try again in about {seconds} s."


__all__ = [
    "BOARD_CHOICES",
    "CLASS_CHOICES",
    "LANGUAGE_CHOICES",
    "PageAccount",
    "account_shell",
    "config_for",
    "notice",
    "page_account",
    "password_reason_copy",
    "public_shell",
    "rate_limit_copy",
    "redirect_and_clear_session",
    "redirect_with_session",
    "render_error_page",
    "render_public_page",
    "retry_after_seconds",
    "service_for",
    "validation_copy",
]
