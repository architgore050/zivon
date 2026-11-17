"""Account guard and view context for the server-rendered web shell.

The shell never implements a second auth path: it reads the F0 account cookie,
validates the server-side session through the existing `AuthService`, and
exposes only the display fields a template may render (display name, class,
board, language). Session ids, token hashes, email addresses, and the raw
cookie never enter the template context.

Unauthenticated app requests redirect to `/login?next=<same-origin path>`.
The login screen itself belongs to F2; this module owns only the guard and the
redirect contract.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse

from .nav import NavItem, active_nav, nav_for

logger = logging.getLogger(__name__)

LOGIN_PATH: Final[str] = "/login"
# Fallback `next` when the requested path is not a plain same-origin path.
DEFAULT_NEXT_PATH: Final[str] = "/app"
SHELL_KIND_APP: Final[str] = "app"
SHELL_KIND_PUBLIC: Final[str] = "public"
NOTICE_KINDS: Final[frozenset[str]] = frozenset({"empty", "partial", "error"})


class LoginRequired(RuntimeError):
    """A guest asked for an account page; the shell redirects to `/login`."""


class AuthUnavailable(RuntimeError):
    """Account auth is not wired, or its store failed; the shell renders 503."""


@dataclass(frozen=True)
class AccountContext:
    """The safe slice of a resolved account session used by the shell."""

    user: Mapping[str, Any]
    csrf_token: str


@dataclass(frozen=True)
class FlashMessage:
    """A one-line status message rendered by the shell's notice slot."""

    text: str
    kind: str = "empty"

    def __post_init__(self) -> None:
        if self.kind not in NOTICE_KINDS:
            raise ValueError(f"unknown notice kind: {self.kind}")


@dataclass(frozen=True)
class ShellUser:
    """Only the profile data a shell template is allowed to render."""

    display_name: str | None
    class_level: int | None
    board: str
    language: str
    language_name: str
    language_native: str | None
    language_native_lang: str | None
    class_label: str
    account_line: str
    language_note: str | None

    @classmethod
    def from_user(cls, user: Mapping[str, Any]) -> ShellUser:
        """Build the template user from a `users` row (never pass the row on)."""
        class_level = _class_level(user.get("class_level"))
        class_label = (
            f"Class {class_level}" if class_level is not None else "Class not set"
        )
        (
            language,
            language_name,
            language_native,
            language_native_lang,
            language_note,
        ) = _language_context(user.get("language"))
        display_name = str(user.get("display_name") or "").strip() or None
        return cls(
            display_name=display_name,
            class_level=class_level,
            board=str(user.get("board") or "CBSE"),
            language=language,
            language_name=language_name,
            language_native=language_native,
            language_native_lang=language_native_lang,
            class_label=class_label,
            account_line=f"{class_label} · {language_name}",
            language_note=language_note,
        )


@dataclass(frozen=True)
class ShellContext:
    """Everything `base.html` needs beyond the page's own view model."""

    shell_kind: str
    page_title: str
    user: ShellUser | None = None
    csrf_token: str | None = None
    active_nav: str | None = None
    nav_items: tuple[NavItem, ...] = ()
    flash: tuple[FlashMessage, ...] = ()
    error: str | None = None
    auth_available: bool = True

    @classmethod
    def for_account(
        cls,
        account: AccountContext,
        *,
        path: str,
        page_title: str,
        flash: tuple[FlashMessage, ...] = (),
        error: str | None = None,
    ) -> ShellContext:
        """Build the signed-in shell context; `csrf_token` feeds future forms."""
        items = nav_for(SHELL_KIND_APP)
        return cls(
            shell_kind=SHELL_KIND_APP,
            page_title=page_title,
            user=ShellUser.from_user(account.user),
            csrf_token=account.csrf_token,
            active_nav=active_nav(path, items),
            nav_items=items,
            flash=flash,
            error=error,
        )

    @classmethod
    def for_public(
        cls,
        *,
        path: str,
        page_title: str,
        flash: tuple[FlashMessage, ...] = (),
        error: str | None = None,
        auth_available: bool = True,
    ) -> ShellContext:
        """Build the guest/auth shell context (error pages, F2 auth screens)."""
        items = nav_for(SHELL_KIND_PUBLIC)
        return cls(
            shell_kind=SHELL_KIND_PUBLIC,
            page_title=page_title,
            user=None,
            csrf_token=None,
            active_nav=active_nav(path, items),
            nav_items=items,
            flash=flash,
            error=error,
            auth_available=auth_available,
        )


def resolve_account(request: Request) -> AccountContext | None:
    """Resolve the F0 cookie to an account, or None for a guest.

    Raises `AuthUnavailable` when the auth service is missing or its session
    store fails, so an HTML route can render a 503 shell instead of leaking a
    JSON 500. A present-but-invalid or expired cookie is simply a guest.
    """
    service = getattr(request.app.state, "auth", None)
    if service is None:
        raise AuthUnavailable("account auth service is not configured")
    raw = request.cookies.get(_account_cookie_name(request))
    if not raw:
        return None
    try:
        ctx = service.resolve(raw)
    except Exception as exc:
        logger.exception("account session resolution failed")
        raise AuthUnavailable("account session store is unavailable") from exc
    if ctx is None:
        return None
    return AccountContext(user=ctx.user, csrf_token=service.csrf_for(raw))


def require_account(request: Request) -> AccountContext:
    """FastAPI dependency: return the signed-in account or redirect to login."""
    account = resolve_account(request)
    if account is None:
        raise LoginRequired()
    return account


def login_redirect(request: Request) -> RedirectResponse:
    """303 to `/login?next=...`, preserving the requested path and query.

    `next` is always a path on this origin, never a host, so the login screen
    cannot be turned into an open redirect. The query string is percent-encoded
    (CR/LF included), so it cannot inject a response header.
    """
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    # The value must stay a same-origin path: a leading `//` is a
    # protocol-relative URL and would send the browser to another host. F2
    # re-validates the value with `safe_next_path`; this keeps the producer
    # honest even if it does not.
    if not target.startswith("/") or target.startswith("//"):
        target = DEFAULT_NEXT_PATH
    response = RedirectResponse(
        url=f"{LOGIN_PATH}?next={quote(target, safe='/')}",
        status_code=303,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _account_cookie_name(request: Request) -> str:
    config = getattr(request.app.state, "config", None)
    name = getattr(config, "auth_cookie_name", None)
    if not name:
        raise AuthUnavailable("account cookie name is not configured")
    return str(name)


def _class_level(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _language_context(
    value: Any,
) -> tuple[str, str, str | None, str | None, str | None]:
    """Map a canonical DB locale to the three shipped UI locales.

    Returns `(ui_locale, english_name, native_label, native_lang, note)`.
    A locale with no UI bundle falls back to English and says so; the shell
    copy is English until the translation workstream lands, so every
    non-English choice carries the honest "saved, not rendered yet" note.
    """
    db_locale = str(value or "en-IN").strip()
    entry = _LANGUAGE_BY_DB.get(db_locale)
    if entry is None:
        return (
            "en",
            "English",
            None,
            None,
            (
                "Your saved language is not built into this screen yet; it is "
                "in English for now."
            ),
        )
    ui_locale, name, native, native_lang = entry
    note = None
    if ui_locale != "en":
        note = f"This screen is in English for now; your {name} choice is saved."
    return ui_locale, name, native, native_lang, note


# Canonical DB locale -> (UI locale, English name, native label, label lang).
_LANGUAGE_BY_DB: Final[dict[str, tuple[str, str, str | None, str | None]]] = {
    "en-IN": ("en", "English", None, None),
    "en": ("en", "English", None, None),
    "hi-IN": ("hi", "Hindi", "हिन्दी", "hi"),
    "hi": ("hi", "Hindi", "हिन्दी", "hi"),
    "hinglish": ("hi-Latn", "Hinglish", None, None),
    "hi-Latn": ("hi-Latn", "Hinglish", None, None),
}


__all__ = [
    "DEFAULT_NEXT_PATH",
    "LOGIN_PATH",
    "AccountContext",
    "AuthUnavailable",
    "FlashMessage",
    "LoginRequired",
    "ShellContext",
    "ShellUser",
    "login_redirect",
    "require_account",
    "resolve_account",
]
