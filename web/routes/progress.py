"""`/app/progress` and `/app/bookmarks` (F3).

Both are server-rendered app pages behind the F0C account guard. The progress
map degrades to a chapter list without concepts when the concept catalogue is
not imported yet; the bookmarks page renders an honest empty state and lets a
small island remove a saved item through the same-origin API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..context import AccountContext, ShellContext, require_account
from ..progress_views import safe_bookmarks_view, safe_progress_view
from ..render import render_page

router = APIRouter(tags=["web"])


@router.get("/app/progress", response_class=HTMLResponse, include_in_schema=False)
def progress_page(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the class -> chapter -> concept map for one account."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Progress map",
    )
    config = getattr(request.app.state, "config", None)
    progress = safe_progress_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        frontend_dir=str(getattr(config, "frontend_dir", "frontend") or "frontend"),
    )
    return render_page(
        request, "app/progress.html", shell=shell, extra={"progress": progress}
    )


@router.get("/app/bookmarks", response_class=HTMLResponse, include_in_schema=False)
def bookmarks_page(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the account's saved chapters, concepts, sections, and questions."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Saved sections",
    )
    config = getattr(request.app.state, "config", None)
    bookmarks = safe_bookmarks_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        frontend_dir=str(getattr(config, "frontend_dir", "frontend") or "frontend"),
    )
    return render_page(
        request, "app/bookmarks.html", shell=shell, extra={"bookmarks": bookmarks}
    )


__all__ = ["router"]
