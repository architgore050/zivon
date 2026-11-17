"""Mount the server-rendered web shell into the core backend app.

`backend.app.create_app` calls `mount_web(app)` once, after the JSON API
routers and the voice mount. The shell adds HTML routes only; it never
registers `/v1/*`, `/voice/*`, or `/admin/*`.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import Response

from .context import (
    AuthUnavailable,
    LoginRequired,
    ShellContext,
    login_redirect,
)
from .render import render_page
from .routes import router

logger = logging.getLogger(__name__)

AUTH_UNAVAILABLE_TITLE = "Sign-in is temporarily unavailable"
AUTH_UNAVAILABLE_TEXT = (
    "Your account session cannot be checked right now. Reading a chapter still "
    "works without an account; try this page again in a minute."
)


def mount_web(app: FastAPI) -> None:
    """Register the HTML shell: error handlers first, then the routes."""
    app.add_exception_handler(LoginRequired, _login_required_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AuthUnavailable, _auth_unavailable_handler)  # type: ignore[arg-type]
    app.include_router(router)


async def _login_required_handler(request: Request, exc: LoginRequired) -> Response:
    del exc
    return login_redirect(request)


async def _auth_unavailable_handler(request: Request, exc: AuthUnavailable) -> Response:
    logger.warning("web shell rendered 503: %s", exc)
    shell = ShellContext.for_public(
        path=request.url.path,
        page_title=AUTH_UNAVAILABLE_TITLE,
        auth_available=False,
    )
    return render_page(
        request,
        "error.html",
        shell=shell,
        status_code=503,
        extra={
            "status_code": 503,
            "error_title": AUTH_UNAVAILABLE_TITLE,
            "error_text": AUTH_UNAVAILABLE_TEXT,
        },
    )


__all__ = ["AUTH_UNAVAILABLE_TEXT", "AUTH_UNAVAILABLE_TITLE", "mount_web"]
