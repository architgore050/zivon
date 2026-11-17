"""`/app/swot` and `/app/swot/how` (F8).

Both are server-rendered app pages behind the F0C account guard, noindex.
The page renders the 2×2 grid, the unrated row, and one next action per
card; `/app/swot/how` publishes the exact method (the explainability page).
No island is needed: SSR completes before bytes, and the panel error state
is a rendered notice, not a spinner.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..context import AccountContext, ShellContext, require_account
from ..render import render_page
from ..swot_views import safe_swot_how_view, safe_swot_view

router = APIRouter(tags=["web"])


def _mode(request: Request) -> str:
    config = getattr(request.app.state, "config", None)
    return str(getattr(config, "swot_mode", "relative") or "relative")


def _frontend_dir(request: Request) -> str:
    config = getattr(request.app.state, "config", None)
    return str(getattr(config, "frontend_dir", "frontend") or "frontend")


@router.get("/app/swot", response_class=HTMLResponse, include_in_schema=False)
def swot_page(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the student's SWOT grid for one account."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Your SWOT",
    )
    swot = safe_swot_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        frontend_dir=_frontend_dir(request),
        mode=_mode(request),
    )
    return render_page(request, "app/swot.html", shell=shell, extra={"swot": swot})


@router.get("/app/swot/how", response_class=HTMLResponse, include_in_schema=False)
def swot_how_page(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the explainability page: the method and this student's numbers."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="How your SWOT works",
    )
    how = safe_swot_how_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        frontend_dir=_frontend_dir(request),
        mode=_mode(request),
    )
    return render_page(request, "app/swot_how.html", shell=shell, extra={"how": how})


__all__ = ["router"]
