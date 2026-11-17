"""`/app` home: the signed-in shell proof, owned by F0C.

This is intentionally a placeholder, not the dashboard: F3 owns
`web/templates/app/dashboard.html` and replaces this page's body when the
study log lands. The route, the guard, and the shell contract are stable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..context import AccountContext, ShellContext, require_account
from ..render import render_page

router = APIRouter(tags=["web"])


@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
def app_home(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the signed-in shell; guests are redirected to `/login`."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Your room",
    )
    return render_page(request, "app/index.html", shell=shell)


__all__ = ["router"]
