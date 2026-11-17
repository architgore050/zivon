"""Jinja2 environment and response helper for the server-rendered shell.

Every shell response is HTML, never JSON: these are pages a student reads.
Headers are set here as well as in `docker/nginx.conf` so the backend is safe
when reached directly in development, and the meta CSP mirrors the nginx app
location for browsers that honour the tag first.

Templates may not use inline `<script>`/`<style>` or DOM event attributes;
`testing/backend/test_web_shell.py` enforces that contract. Islands ship as
same-origin files under `frontend/assets/`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .context import ShellContext

_TEMPLATES_DIR: Final[Path] = Path(__file__).resolve().parent / "templates"

TEMPLATES: Final[Jinja2Templates] = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# The app shell is the only non-lesson surface allowed to call the same-origin
# API (`connect-src 'self'`) because F3/F5/F6/F7 render small islands that
# fetch /v1/*. The nginx app location repeats this exact string; the meta tag
# carries it minus `frame-ancestors`, which browsers ignore in a meta policy.
CSP_POLICY: Final[str] = (
    "default-src 'self'; style-src 'self'; script-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
    "object-src 'none'"
)
CSP_META: Final[str] = (
    "default-src 'self'; style-src 'self'; script-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; object-src 'none'"
)


def csrf_field(token: str | None) -> Markup:
    """Render the hidden CSRF input a future server-rendered form posts back.

    The value is escaped by `Markup.format`; the token itself is derived from
    the session by `AuthService.csrf_for`, never the raw cookie.
    """
    if not token:
        return Markup("")
    return Markup('<input type="hidden" name="csrf_token" value="{}">').format(token)


TEMPLATES.env.globals["csrf_field"] = csrf_field


def page_headers() -> dict[str, str]:
    """Private-page headers shared by every shell response."""
    return {
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "Content-Security-Policy": CSP_POLICY,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


def render_page(
    request: Request,
    template_name: str,
    *,
    shell: ShellContext,
    status_code: int = 200,
    extra: Mapping[str, Any] | None = None,
) -> HTMLResponse:
    """Render a shell page with the shared context and private-page headers."""
    config = getattr(request.app.state, "config", None)
    release_tag = str(getattr(config, "release_tag", "") or "")
    context: dict[str, Any] = {
        # The copy is English until the UI-translation workstream lands. The
        # student's saved language is shown as data, not claimed as markup.
        "page_lang": "en",
        "page_title": shell.page_title,
        "shell_kind": shell.shell_kind,
        "user": shell.user,
        "csrf_token": shell.csrf_token,
        "nav_items": shell.nav_items,
        "active_nav": shell.active_nav,
        "flash": shell.flash,
        "error": shell.error,
        "auth_available": shell.auth_available,
        "csp_meta": CSP_META,
        "release_tag": release_tag,
    }
    if extra:
        context.update(extra)
    response = TEMPLATES.TemplateResponse(
        request,
        template_name,
        context=context,
        status_code=status_code,
        headers=page_headers(),
    )
    return response


__all__ = [
    "CSP_META",
    "CSP_POLICY",
    "TEMPLATES",
    "csrf_field",
    "page_headers",
    "render_page",
]
