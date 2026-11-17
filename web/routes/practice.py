"""Practice hub, player, summary, and history pages (`/app/practice/*`, F5).

Server-rendered pages behind the F0C account guard. The hub and history are
read-only; the player's answer form is a real `POST` that works with JavaScript
off, and `frontend/assets/practice.js` enhances it into an inline check (same
endpoint, same server-side grading). Session creation and completion are form
posts through the same domain functions the JSON API uses — there is no second
grading path and no answer key in the page before the student commits.

The tutor hand-off is honest: "Ask the tutor" links to the chapter's published
lesson page, where the real voice dock lives. No practice page pretends to own a
tutor pipeline it does not have.
"""

from __future__ import annotations

import math
from typing import Any, Final
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend.assessment import AssessmentError
from backend.practice import (
    PracticeUser,
    complete_session,
    create_session,
    practice_user,
    submit_answer,
)
from web.context import (
    AccountContext,
    FlashMessage,
    LoginRequired,
    ShellContext,
    require_account,
)
from web.flow import PageAccount, page_account, render_error_page
from web.forms import FormBadEncoding, FormTooLarge, read_form
from web.practice_views import (
    DATA_ERROR,
    safe_history_view,
    safe_hub_view,
    safe_player_view,
    safe_summary_view,
)
from web.render import render_page

router = APIRouter(tags=["web"])

_FORM_EXPIRED_TEXT: Final[str] = (
    "Reload the page and submit again. If it keeps happening, check that this "
    "browser allows cookies for Zivon."
)
_COUNT_ERROR: Final[str] = "Choose a set length inside the allowed range."
_NUMBER_ERROR: Final[str] = "Enter a number like 15 or 0.5 before checking."


# -- hub ---------------------------------------------------------------------


@router.get("/app/practice", response_class=HTMLResponse, include_in_schema=False)
def practice_hub(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the practice modes, honest availability, and recent sessions."""
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Practice",
    )
    hub = safe_hub_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        frontend_dir=_frontend_dir(request),
        requested_chapter=(request.query_params.get("chapter") or "").strip() or None,
    )
    return render_page(
        request,
        "app/practice/hub.html",
        shell=shell,
        extra={"practice": hub},
    )


@router.post("/app/practice/start", include_in_schema=False)
async def practice_start(request: Request) -> Response:
    """Create a set from the hub form, then show its first question."""
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db_or_error(request)
    if isinstance(db, HTMLResponse):
        return db
    mode = (form.get("mode") or "").strip()
    chapter_id = (form.get("chapter_id") or "").strip() or None
    raw_count = (form.get("count") or "").strip()
    count: int | None = None
    if raw_count:
        try:
            count = int(raw_count)
        except ValueError:
            return _hub_with_error(request, account, _COUNT_ERROR)
    try:
        session = create_session(
            db,
            _user(account),
            mode=mode,
            chapter_id=chapter_id,
            count=count,
        )
    except AssessmentError as exc:
        return _hub_with_error(request, account, _error_copy(exc))
    return _redirect(f"/app/practice/{session['session_id']}")


# -- player ------------------------------------------------------------------


@router.get(
    "/app/practice/history", response_class=HTMLResponse, include_in_schema=False
)
def practice_history(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Every saved practice session, newest first."""
    view = safe_history_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        frontend_dir=_frontend_dir(request),
    )
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Practice history",
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/practice/history.html",
        shell=shell,
        extra={"practice": view},
    )


@router.get(
    "/app/practice/{session_id}", response_class=HTMLResponse, include_in_schema=False
)
def practice_player(
    request: Request,
    session_id: str,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> Response:
    """One question at a time; the key is rendered only after an answer."""
    view = safe_player_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        session_id=session_id,
        frontend_dir=_frontend_dir(request),
        review_question_id=(request.query_params.get("answered") or "").strip() or None,
    )
    if view["state"] == "missing":
        return _missing_page(request, account, "Practice set not found", session_id)
    if view["state"] == "ok" and view["completed"]:
        return _redirect(f"/app/practice/{session_id}/summary")
    return _render_player(request, account, view, session_id)


@router.post("/app/practice/{session_id}/answer", include_in_schema=False)
async def practice_answer_submit(request: Request, session_id: str) -> Response:
    """Record one answer through the server grader; no-JS path for Check."""
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db_or_error(request)
    if isinstance(db, HTMLResponse):
        return db
    question_id = (form.get("question_id") or "").strip()
    answer, parse_error = _form_answer(form)
    hints_used = 1 if (form.get("hints_used") or "").strip() in {"1", "on"} else 0
    if parse_error:
        view = safe_player_view(
            db,
            user_row=dict(account.context.user),
            session_id=session_id,
            frontend_dir=_frontend_dir(request),
        )
        if view["state"] != "ok":
            return _missing_page(request, account, "Practice set not found", session_id)
        view["answer_error"] = parse_error
        view["form_values"] = {
            "answer_index": (form.get("answer_index") or "").strip(),
            "answer_value": (form.get("answer_value") or "").strip(),
            "hints_used": hints_used,
        }
        return _render_player(request, account, view, session_id)
    try:
        result = submit_answer(
            db,
            _user(account),
            session_id,
            question_id=question_id,
            answer=answer,
            time_ms=_time_ms(form),
            hints_used=hints_used,
        )
    except AssessmentError as exc:
        if exc.code == "E-PRACTICE-CLOSED":
            return _redirect(f"/app/practice/{session_id}/summary")
        if exc.code == "E-PRACTICE-NOT-FOUND":
            return _missing_page(request, account, "Practice set not found", session_id)
        return _player_with_error(request, account, session_id, _error_copy(exc))
    if result is None:
        return _missing_page(request, account, "Practice set not found", session_id)
    return _redirect(
        f"/app/practice/{session_id}?answered={quote(question_id, safe='')}"
    )


@router.post("/app/practice/{session_id}/complete", include_in_schema=False)
async def practice_complete_submit(request: Request, session_id: str) -> Response:
    """Close the set (idempotent) and show the summary."""
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db_or_error(request)
    if isinstance(db, HTMLResponse):
        return db
    try:
        summary = complete_session(db, _user(account), session_id)
    except AssessmentError:
        return _missing_page(request, account, "Practice set not found", session_id)
    if summary is None:
        return _missing_page(request, account, "Practice set not found", session_id)
    return _redirect(f"/app/practice/{session_id}/summary")


# -- summary and history -----------------------------------------------------


@router.get(
    "/app/practice/{session_id}/summary",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def practice_summary(
    request: Request,
    session_id: str,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> Response:
    """Score, accuracy, concept breakdown, and honest next actions."""
    view = safe_summary_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        session_id=session_id,
        frontend_dir=_frontend_dir(request),
    )
    if view["state"] == "missing":
        return _missing_page(request, account, "Practice set not found", session_id)
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Practice summary",
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/practice/summary.html",
        shell=shell,
        extra={"practice": view, "session_id": session_id},
    )


# -- shared helpers ----------------------------------------------------------


def _require_account(request: Request) -> PageAccount:
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    return account


def _user(account: PageAccount) -> PracticeUser:
    return practice_user(account.context.user)


def _shell_account(account: Any) -> AccountContext:
    """Accept the guard slice or a resolved form session in one helper."""
    slice_ = getattr(account, "shell_account", None)
    return slice_ if slice_ is not None else account


def _frontend_dir(request: Request) -> str:
    config = getattr(request.app.state, "config", None)
    return str(getattr(config, "frontend_dir", "frontend") or "frontend")


def _db_or_error(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        return render_error_page(
            request,
            status_code=503,
            title="Practice is unavailable",
            message=(
                "The practice store cannot be reached right now. Reading a "
                "chapter still works; try this page again in a minute."
            ),
        )
    return db


async def _read_or_error(request: Request) -> dict[str, str] | HTMLResponse:
    try:
        return await read_form(request)
    except (FormBadEncoding, FormTooLarge):
        return render_error_page(
            request,
            status_code=400,
            title="That form did not arrive",
            message="Go back, reload the page, and submit again.",
        )


def _csrf_error(request: Request) -> HTMLResponse:
    return render_error_page(
        request,
        status_code=403,
        title="This form expired",
        message=_FORM_EXPIRED_TEXT,
    )


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


def _hub_with_error(
    request: Request, account: PageAccount, message: str
) -> HTMLResponse:
    hub = safe_hub_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.context.user),
        frontend_dir=_frontend_dir(request),
        requested_chapter=(request.query_params.get("chapter") or "").strip() or None,
    )
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Practice",
        flash=(FlashMessage(message, kind="partial"),),
    )
    return render_page(
        request,
        "app/practice/hub.html",
        shell=shell,
        extra={"practice": hub},
    )


def _render_player(
    request: Request,
    account: Any,
    view: dict[str, Any],
    session_id: str,
) -> HTMLResponse:
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Practice",
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/practice/player.html",
        shell=shell,
        extra={
            "practice": view,
            "session_id": session_id,
            "answer_action": f"/app/practice/{session_id}/answer",
            "complete_action": f"/app/practice/{session_id}/complete",
        },
    )


def _player_with_error(
    request: Request,
    account: PageAccount,
    session_id: str,
    message: str,
) -> HTMLResponse:
    view = safe_player_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.context.user),
        session_id=session_id,
        frontend_dir=_frontend_dir(request),
    )
    if view["state"] != "ok":
        return _missing_page(request, account, "Practice set not found", session_id)
    view["answer_error"] = message
    return _render_player(request, account, view, session_id)


def _missing_page(
    request: Request, account: Any, title: str, session_id: str
) -> HTMLResponse:
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title=title,
    )
    return render_page(
        request,
        "app/practice/player.html",
        shell=shell,
        status_code=404,
        extra={
            "practice": {"state": "missing"},
            "session_id": session_id,
            "answer_action": f"/app/practice/{session_id}/answer",
            "complete_action": f"/app/practice/{session_id}/complete",
        },
    )


def _form_answer(form: dict[str, str]) -> tuple[dict[str, Any] | None, str | None]:
    kind = (form.get("answer_kind") or "").strip()
    if kind == "value":
        raw = (form.get("answer_value") or "").strip()
        if not raw:
            return None, _NUMBER_ERROR
        try:
            value = float(raw)
        except ValueError:
            return None, _NUMBER_ERROR
        if not math.isfinite(value):
            return None, _NUMBER_ERROR
        return {"value": value}, None
    raw_index = (form.get("answer_index") or "").strip()
    if not raw_index:
        return None, "Choose one option before checking."
    try:
        index = int(raw_index)
    except ValueError:
        return None, "Choose one option before checking."
    if index < 0:
        return None, "Choose one option before checking."
    return {"index": index}, None


def _time_ms(form: dict[str, str]) -> int:
    raw = (form.get("time_ms") or "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(0, min(value, 3_600_000))


def _error_copy(exc: AssessmentError) -> str:
    return {
        "E-PRACTICE-EMPTY": (
            "This chapter has no imported practice questions yet. "
            "Practice appears when its question pack is imported."
        ),
        "E-PRACTICE-CLASS": (
            "Set your class in Settings first, then the Daily 5 can choose "
            "questions for it."
        ),
        "E-PRACTICE-NO-MISTAKES": (
            "You have no unresolved mistakes to retry yet. Finish a set and a "
            "wrong answer will appear here."
        ),
        "E-PRACTICE-NO-WEAK": (
            "No weak topic is recorded in this chapter yet. Answer a few "
            "questions first."
        ),
        "E-PRACTICE-COUNT": _COUNT_ERROR,
        "E-ANSWER-INVALID": _NUMBER_ERROR,
        "E-PRACTICE-CLOSED": "This set is already finished.",
        "E-PRACTICE-QUESTIONS": DATA_ERROR,
    }.get(exc.code, "That practice set could not be used. Try again.")


__all__ = ["router"]
