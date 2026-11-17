"""`/app` home: the signed-in dashboard (F3).

The route, the guard, and the shell contract are F0C's and stay unchanged;
this module now loads the dashboard view model instead of the shell proof.
The dashboard is honest about what is live: reading, the progress map, and
bookmarks exist; practice, tests, speaking, and SWOT are labelled as not live
yet rather than linked to a 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..context import AccountContext, ShellContext, require_account
from ..progress_views import safe_dashboard_view
from ..render import render_page

router = APIRouter(tags=["web"])


@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
def app_home(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the signed-in dashboard; guests are redirected to `/login`."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Your dashboard",
    )
    config = getattr(request.app.state, "config", None)
    dashboard = safe_dashboard_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        user_class=_class_level(account.user.get("class_level")),
        frontend_dir=str(getattr(config, "frontend_dir", "frontend") or "frontend"),
    )
    return render_page(
        request, "app/dashboard.html", shell=shell, extra={"dashboard": dashboard}
    )


def _class_level(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


__all__ = ["router"]
