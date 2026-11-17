"""`/app/speaking` hub, `/app/speaking/{prompt_id}` recorder, and history (F6).

Server-rendered pages behind the F0C account guard. The hub and history are
read-only SSR; the recorder is SSR plus one vanilla-JS island
(`/assets/app-speaking.js`) that owns the microphone, the 45 s timer, the
transient upload, and the result rendering. No page inlines script or style;
the CSP is the app-shell policy set in `web/render.py`.

The consent gate is the existing device-scoped voice gate: the template ships
the same notice text and the current notice version, the island records a
decision through `PUT /v1/consent`, and the API re-checks the stored row before
a frame moves. The mic control starts disabled, so nothing captures audio
before consent — with JS off there is no capture path at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from backend.speaking import pipeline_for

from ..context import AccountContext, ShellContext, require_account
from ..render import render_page
from ..speaking_views import safe_history_view, safe_hub_view, safe_recorder_view

router = APIRouter(tags=["web"])


@router.get("/app/speaking", response_class=HTMLResponse, include_in_schema=False)
def speaking_hub(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Chapter prompts, the last attempt, and the start links."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Explain it back",
    )
    config = getattr(request.app.state, "config", None)
    view = safe_hub_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        ui_language=_ui_language(account.user.get("language")),
        frontend_dir=str(getattr(config, "frontend_dir", "frontend") or "frontend"),
    )
    return render_page(
        request, "app/speaking/hub.html", shell=shell, extra={"speaking": view}
    )


@router.get(
    "/app/speaking/history", response_class=HTMLResponse, include_in_schema=False
)
def speaking_history(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Every kept transcript and its AI feedback, newest first."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Explain-back history",
    )
    config = getattr(request.app.state, "config", None)
    view = safe_history_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        ui_language=_ui_language(account.user.get("language")),
        frontend_dir=str(getattr(config, "frontend_dir", "frontend") or "frontend"),
    )
    return render_page(
        request, "app/speaking/history.html", shell=shell, extra={"speaking": view}
    )


@router.get(
    "/app/speaking/{prompt_id}", response_class=HTMLResponse, include_in_schema=False
)
def speaking_recorder(
    prompt_id: str,
    request: Request,
    language: str | None = Query(default=None, max_length=8),
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """One prompt: recorder, last result, and earlier attempts."""
    ui_language = (
        language if language in ("en", "hi", "hi-Latn") else None
    ) or _ui_language(account.user.get("language"))
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Explain it back",
    )
    config = getattr(request.app.state, "config", None)
    view = safe_recorder_view(
        getattr(request.app.state, "db", None),
        user_id=str(account.user["user_id"]),
        prompt_id=prompt_id,
        ui_language=ui_language,
        frontend_dir=str(getattr(config, "frontend_dir", "frontend") or "frontend"),
    )
    if not view.get("not_found") and not view.get("data_error"):
        pipeline = pipeline_for(request.app)
        view["speech_available"] = pipeline.available
        view["mock_mode"] = pipeline.mock_mode
    else:
        view.setdefault("speech_available", False)
        view.setdefault("mock_mode", False)
    view["consent_notice_version"] = str(
        getattr(config, "current_notice_version", "zivon-voice-notice-v1")
    )
    view["consent_version"] = str(getattr(config, "current_consent_version", "v1"))
    status = 200
    if view.get("not_found"):
        status = 404
    return render_page(
        request,
        "app/speaking/recorder.html",
        shell=shell,
        status_code=status,
        extra={"speaking": view},
    )


def _ui_language(value: object) -> str:
    """Map the stored canonical locale to the three shipped UI locales."""
    raw = str(value or "en-IN").strip()
    if raw in ("hi", "hi-IN"):
        return "hi"
    if raw in ("hinglish", "hi-Latn"):
        return "hi-Latn"
    return "en"


__all__ = ["router"]
