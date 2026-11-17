"""Test hub, builder, exam-paper player, results, and series pages (`/app/tests/*`, F7).

Server-rendered pages behind the F0C account guard. The hub, builder, history,
series catalogue, and review are read paths; the player's answer, flag, and
submit controls are real `POST`s that work with JavaScript off, and
`frontend/assets/tests.js` enhances them into autosave over the same-origin
JSON endpoint with the same CSRF contract. There is no second grading path:
the HTML route and the JSON API both call `backend.test_engine`, and the key is
graded only by `submit_test_attempt`.

The tutor hand-off is honest: "Ask the tutor" links to the chapter's published
lesson page, where the real voice dock lives. No test page pretends to own a
tutor pipeline it does not have.
"""

from __future__ import annotations

import math
from typing import Any, Final
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend.assessment import AssessmentError
from backend.test_engine import (
    chapter_options,
    create_chapter_test,
    create_custom_test,
    create_retry_test,
    save_answer,
    start_attempt,
    start_series_paper,
    submit_attempt,
    test_user,
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
from web.render import render_page
from web.test_views import (
    DATA_ERROR,
    safe_builder_view,
    safe_confirm_view,
    safe_history_view,
    safe_hub_view,
    safe_player_view,
    safe_review_view,
    safe_series_catalogue_view,
    safe_series_detail_view,
)

router = APIRouter(tags=["web"])

_FORM_EXPIRED_TEXT: Final[str] = (
    "Reload the page and submit again. If it keeps happening, check that this "
    "browser allows cookies for Zivon."
)
_CHAPTER_PREFIX: Final[str] = "chapter_"
_COUNT_ERROR: Final[str] = "Choose a question count between 5 and 30."
_NUMBER_ERROR: Final[str] = "Enter a number like 15 or 0.5 before saving."


# -- hub ---------------------------------------------------------------------


@router.get("/app/tests", response_class=HTMLResponse, include_in_schema=False)
def tests_hub(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render chapter tests, presets, series shortcuts, and recent papers."""
    shell = ShellContext.for_account(account, path=request.url.path, page_title="Tests")
    hub = safe_hub_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        frontend_dir=_frontend_dir(request),
    )
    return render_page(request, "app/tests/hub.html", shell=shell, extra={"tests": hub})


# -- builder -----------------------------------------------------------------


@router.get("/app/tests/new", response_class=HTMLResponse, include_in_schema=False)
def test_builder(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Render the custom-test builder, prefilled by a hub preset or chapter link."""
    selected: dict[str, Any] = {}
    count = (request.query_params.get("count") or "").strip()
    minutes = (request.query_params.get("minutes") or "").strip()
    chapter = (request.query_params.get("chapter") or "").strip()
    if count:
        selected["count"] = count
    if minutes:
        try:
            selected["duration_s"] = int(minutes) * 60
        except ValueError:
            selected["duration_s"] = None
    if chapter:
        selected["chapter_ids"] = [chapter]
    view = safe_builder_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        frontend_dir=_frontend_dir(request),
        selected=selected or None,
    )
    return _render_builder(request, account, view)


@router.post("/app/tests/start", include_in_schema=False)
async def test_start(request: Request) -> Response:
    """Create a custom/chapter/retry paper and open its first question."""
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db_or_error(request)
    if isinstance(db, HTMLResponse):
        return db
    kind = (form.get("kind") or "custom").strip()
    try:
        if kind == "chapter":
            test = create_chapter_test(
                db,
                test_user(dict(account.context.user)),
                chapter_id=(form.get("chapter_id") or "").strip(),
            )
        elif kind == "retry":
            test = create_retry_test(db, test_user(dict(account.context.user)))
        else:
            user = test_user(dict(account.context.user))
            chapters = _selected_chapters(form)
            if not chapters and form.get("preset"):
                chapters = [
                    row["chapter_id"] for row in chapter_options(db, user)["chapters"]
                ][:4]
            test = create_custom_test(
                db,
                user,
                chapter_ids=chapters,
                count=(form.get("count") or "").strip() or None,
                difficulty=(form.get("difficulty") or "mixed").strip(),
                duration_s=_duration_seconds(form),
            )
        started = start_attempt(
            db, test_user(dict(account.context.user)), test_id=test["test_id"]
        )
    except AssessmentError as exc:
        if kind == "custom":
            view = safe_builder_view(
                getattr(request.app.state, "db", None),
                user_row=dict(account.context.user),
                frontend_dir=_frontend_dir(request),
                selected={
                    "chapter_ids": _selected_chapters(form),
                    "count": form.get("count"),
                    "difficulty": form.get("difficulty"),
                    "duration_s": _duration_seconds(form) or "",
                    "error": _error_copy(exc),
                },
            )
            return _render_builder(request, account, view, status_code=422)
        return _hub_with_error(request, account, _error_copy(exc))
    return _redirect(f"/app/tests/{started['attempt']['attempt_id']}")


def _selected_chapters(form: dict[str, str]) -> list[str]:
    return [
        key[len(_CHAPTER_PREFIX) :]
        for key, value in form.items()
        if key.startswith(_CHAPTER_PREFIX) and value in {"1", "on", "true"}
    ]


def _duration_seconds(form: dict[str, str]) -> int | None:
    raw = (form.get("duration_min") or "").strip()
    if not raw:
        return None
    try:
        minutes = int(raw)
    except ValueError:
        return None
    return minutes * 60


# -- history -----------------------------------------------------------------


@router.get("/app/tests/history", response_class=HTMLResponse, include_in_schema=False)
def test_history_page(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """Every saved test attempt, newest first, with honest filters."""
    view = safe_history_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        frontend_dir=_frontend_dir(request),
        status=(request.query_params.get("status") or "").strip() or None,
        kind=(request.query_params.get("kind") or "").strip() or None,
    )
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Test history",
        error=view.get("data_error"),
    )
    return render_page(
        request, "app/tests/history.html", shell=shell, extra={"tests": view}
    )


# -- player ------------------------------------------------------------------


@router.get(
    "/app/tests/{attempt_id}", response_class=HTMLResponse, include_in_schema=False
)
def test_player(
    request: Request,
    attempt_id: str,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> Response:
    """One question at a time with a palette and a server-derived clock."""
    view = safe_player_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        attempt_id=attempt_id,
        frontend_dir=_frontend_dir(request),
        question_id=(request.query_params.get("q") or "").strip() or None,
    )
    if view["state"] == "missing":
        return _missing_page(request, account, attempt_id)
    if view["state"] == "submitted":
        return _redirect(f"/app/tests/{attempt_id}/review")
    if view["state"] == "error":
        return _render_player(request, account, view, attempt_id)
    return _render_player(request, account, view, attempt_id)


@router.post("/app/tests/{attempt_id}/answer", include_in_schema=False)
async def test_answer_submit(request: Request, attempt_id: str) -> Response:
    """Save one answer or mark a question, through the server's autosave path."""
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
    action = (form.get("action") or "save").strip()
    answer, parse_error = (None, None)
    if action != "flag":
        answer, parse_error = _form_answer(form)
    flag_value: bool | None = None
    if action == "flag":
        flag_value = True
    elif "flagged" in form:
        flag_value = form.get("flagged") in {"1", "on", "true"}
    if parse_error:
        return _player_with_error(request, account, attempt_id, parse_error, form)
    try:
        save_answer(
            db,
            test_user(dict(account.context.user)),
            attempt_id=attempt_id,
            question_id=question_id,
            answer=answer,
            flagged=flag_value,
            time_ms=_time_ms(form),
        )
    except AssessmentError as exc:
        if exc.code == "E-TEST-EXPIRED":
            return _redirect(f"/app/tests/{attempt_id}/submit")
        if exc.code == "E-TEST-ATTEMPT-CLOSED":
            return _redirect(f"/app/tests/{attempt_id}/review")
        if exc.code == "E-TEST-ATTEMPT-NOT-FOUND":
            return _missing_page(request, account, attempt_id)
        return _player_with_error(request, account, attempt_id, _error_copy(exc), form)
    return _redirect(f"/app/tests/{attempt_id}?q={quote(question_id, safe='')}")


# -- submit ------------------------------------------------------------------


@router.get(
    "/app/tests/{attempt_id}/submit",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def test_submit_confirm(
    request: Request,
    attempt_id: str,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> Response:
    """Confirm what is answered, marked, and missing before grading."""
    view = safe_confirm_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        attempt_id=attempt_id,
    )
    if view["state"] == "missing":
        return _missing_page(request, account, attempt_id)
    if view["state"] == "submitted":
        return _redirect(f"/app/tests/{attempt_id}/review")
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Review and submit",
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/tests/submit.html",
        shell=shell,
        extra={"tests": view},
        status_code=int(view.get("status_code") or 503)
        if view["state"] == "error"
        else 200,
    )


@router.post("/app/tests/{attempt_id}/submit", include_in_schema=False)
async def test_submit(request: Request, attempt_id: str) -> Response:
    """Grade every saved answer once, then show the review."""
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
        review = submit_attempt(
            db, test_user(dict(account.context.user)), attempt_id=attempt_id
        )
    except AssessmentError as exc:
        return _player_with_error(request, account, attempt_id, _error_copy(exc), form)
    if review is None:
        return _missing_page(request, account, attempt_id)
    return _redirect(f"/app/tests/{attempt_id}/review")


# -- review ------------------------------------------------------------------


@router.get(
    "/app/tests/{attempt_id}/review",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def test_review(
    request: Request,
    attempt_id: str,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> Response:
    """Score, accuracy, breakdowns, and every question with its explanation."""
    view = safe_review_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        attempt_id=attempt_id,
        frontend_dir=_frontend_dir(request),
    )
    if view["state"] == "missing":
        return _missing_page(request, account, attempt_id)
    if view["state"] == "not_submitted":
        return _redirect(f"/app/tests/{attempt_id}")
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Test review",
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/tests/review.html",
        shell=shell,
        extra={"tests": view},
        status_code=int(view.get("status_code") or 503)
        if view["state"] == "error"
        else 200,
    )


# -- series ------------------------------------------------------------------


@router.get("/app/series", response_class=HTMLResponse, include_in_schema=False)
def series_catalogue(
    request: Request,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> HTMLResponse:
    """The six series, with approved copy and honest availability."""
    view = safe_series_catalogue_view(
        getattr(request.app.state, "db", None), user_row=dict(account.user)
    )
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title="Test series",
        error=view.get("data_error"),
    )
    return render_page(
        request, "app/tests/series.html", shell=shell, extra={"series": view}
    )


@router.get("/app/series/{slug}", response_class=HTMLResponse, include_in_schema=False)
def series_page(
    request: Request,
    slug: str,
    account: AccountContext = Depends(require_account),  # noqa: B008 — FastAPI DI
) -> Response:
    """One series: coverage, papers, copy rule, and the start/resume path."""
    view = safe_series_detail_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.user),
        slug=slug,
    )
    if view["state"] == "missing":
        return _series_missing(request, account)
    shell = ShellContext.for_account(
        account,
        path=request.url.path,
        page_title=str(view.get("label") or "Series"),
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/tests/series_detail.html",
        shell=shell,
        extra={"series": view},
        status_code=503 if view["state"] == "error" else 200,
    )


@router.post("/app/series/{slug}/start", include_in_schema=False)
async def series_start(request: Request, slug: str) -> Response:
    """Start or resume a published series paper."""
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
        started = start_series_paper(
            db,
            test_user(dict(account.context.user)),
            slug=slug,
            test_id=(form.get("test_id") or "").strip(),
        )
    except AssessmentError as exc:
        return _series_with_error(request, account, slug, _error_copy(exc))
    return _redirect(f"/app/tests/{started['attempt']['attempt_id']}")


# -- shared helpers ----------------------------------------------------------


def _require_account(request: Request) -> PageAccount:
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    return account


def _frontend_dir(request: Request) -> str:
    config = getattr(request.app.state, "config", None)
    return str(getattr(config, "frontend_dir", "frontend") or "frontend")


def _db_or_error(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        return render_error_page(
            request,
            status_code=503,
            title="Tests are unavailable",
            message=(
                "The test store cannot be reached right now. Reading a chapter "
                "still works; try this page again in a minute."
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
    """303 to a same-origin app path, never to an attacker-supplied host.

    Every target is built from a fixed `/app/...` prefix plus a store id or a
    path parameter; this guard makes the same-origin property explicit (and
    keeps a future refactor from turning the helper into an open redirect).
    """
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path.startswith("/app/"):
        raise ValueError("refusing an off-origin redirect")
    safe = urlunsplit(("", "", parts.path, parts.query, ""))
    response = RedirectResponse(url=safe, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


def _render_builder(
    request: Request,
    account: Any,
    view: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Build a test",
        error=view.get("data_error"),
    )
    return render_page(
        request,
        "app/tests/new.html",
        shell=shell,
        extra={"tests": view},
        status_code=status_code,
    )


def _render_player(
    request: Request, account: Any, view: dict[str, Any], attempt_id: str
) -> HTMLResponse:
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Test",
        error=view.get("message") if view["state"] == "error" else None,
    )
    return render_page(
        request,
        "app/tests/player.html",
        shell=shell,
        extra={"tests": view, "attempt_id": attempt_id},
        status_code=(
            int(view.get("status_code") or 503) if view["state"] == "error" else 200
        ),
    )


def _player_with_error(
    request: Request,
    account: Any,
    attempt_id: str,
    message: str,
    form: dict[str, str],
) -> HTMLResponse:
    view = safe_player_view(
        getattr(request.app.state, "db", None),
        user_row=dict(_shell_account(account).user),
        attempt_id=attempt_id,
        frontend_dir=_frontend_dir(request),
        question_id=(form.get("question_id") or "").strip() or None,
    )
    if view["state"] != "ok":
        return _missing_page(request, account, attempt_id)
    view["answer_error"] = message
    view["form_values"] = {
        "answer_index": (form.get("answer_index") or "").strip(),
        "answer_value": (form.get("answer_value") or "").strip(),
        "flagged": form.get("flagged") in {"1", "on", "true"},
    }
    return _render_player(request, account, view, attempt_id)


def _missing_page(request: Request, account: Any, attempt_id: str) -> HTMLResponse:
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Test not found",
    )
    return render_page(
        request,
        "app/tests/player.html",
        shell=shell,
        status_code=404,
        extra={"tests": {"state": "missing"}, "attempt_id": attempt_id},
    )


def _hub_with_error(
    request: Request, account: PageAccount, message: str
) -> HTMLResponse:
    hub = safe_hub_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.context.user),
        frontend_dir=_frontend_dir(request),
    )
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Tests",
        flash=(FlashMessage(message, kind="partial"),),
    )
    return render_page(request, "app/tests/hub.html", shell=shell, extra={"tests": hub})


def _series_with_error(
    request: Request, account: PageAccount, slug: str, message: str
) -> Response:
    view = safe_series_detail_view(
        getattr(request.app.state, "db", None),
        user_row=dict(account.context.user),
        slug=slug,
    )
    if view["state"] == "missing":
        return _series_missing(request, account)
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title=str(view.get("label") or "Series"),
        flash=(FlashMessage(message, kind="partial"),),
    )
    return render_page(
        request,
        "app/tests/series_detail.html",
        shell=shell,
        extra={"series": view},
    )


def _series_missing(request: Request, account: Any) -> HTMLResponse:
    shell = ShellContext.for_account(
        _shell_account(account),
        path=request.url.path,
        page_title="Series not found",
    )
    return render_page(
        request,
        "app/tests/series_detail.html",
        shell=shell,
        status_code=404,
        extra={"series": {"state": "missing"}},
    )


def _shell_account(account: Any) -> AccountContext:
    """Accept the guard slice or a resolved form session in one helper."""
    slice_ = getattr(account, "shell_account", None)
    return slice_ if slice_ is not None else account


def _form_answer(
    form: dict[str, str],
) -> tuple[dict[str, Any] | None, str | None]:
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
        return None, "Choose one option before saving."
    try:
        index = int(raw_index)
    except ValueError:
        return None, "Choose one option before saving."
    if index < 0:
        return None, "Choose one option before saving."
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
        "E-TEST-EMPTY": (
            "The selected chapters do not have enough imported questions yet. "
            "A test needs at least three. Chapter tests work as soon as a bank "
            "is imported."
        ),
        "E-TEST-NO-MISTAKES": (
            "You have no unresolved test mistakes to retry yet. Submit a test "
            "and a wrong answer will appear here."
        ),
        "E-TEST-CONTENT-MODE": (
            "This paper carries a source that is not cleared for practice yet, "
            "so it cannot be opened."
        ),
        "E-TEST-COUNT": _COUNT_ERROR,
        "E-TEST-DURATION": "Choose a time between 5 and 60 minutes.",
        "E-TEST-DIFFICULTY": "Choose mixed, easy, medium, or hard.",
        "E-TEST-CHAPTERS": "Choose between one and four chapters.",
        "E-TEST-QUESTION-UNKNOWN": "That question is not on this paper.",
        "E-TEST-EXPIRED": "Time is up for this paper.",
        "E-TEST-TIME": DATA_ERROR,
        "E-ANSWER-INVALID": _NUMBER_ERROR,
        "E-NOT-FOUND": "That paper is not here.",
        "E-TEST-NOT-FOUND": "That paper is not here.",
    }.get(exc.code, "That test could not be opened. Try again.")


__all__ = ["router"]
