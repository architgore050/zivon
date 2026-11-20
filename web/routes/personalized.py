"""`/app/personalized` hub, session screen, and the settings instructions
section (PL4, workstreams.md §5).

Server-rendered pages behind the F0C account guard. Reads go through the PL1
store/quota view models (`web/personalized_views.py`); the teaching turn is
**always** the PL2 JSON/SSE API (`POST /v1/personalized/sessions/{id}/turns`,
`API-PL-10`) called by `frontend/assets/personalized.js` — no route here
re-implements admission, quota reservation, or scoring (data-and-api.md §4.6).

The small HTML write routes (start, end, resume, delete, preferences
save/clear) call the same PL1 domain functions the JSON API uses
(`PersonalizedStore`, `save_preferences`/`clear_preferences`) with the
session-derived CSRF token — there is no second write path, no answer key in
any page, and no student text in any log line (the domain functions already
emit counts-only events). Resume (API-PL-16) reopens a completed session and
lands back on the session screen; a cap-exhausted one is refused by the store
and lands on the hub with the truthful start-new explanation.

Guests get the shell's `303 /login?next=…`; another user's session id is a
branded 404, never a 403 (data-and-api.md §4.1, no existence oracle). The
instructions form redirects back to `/app/settings` and the PL4 partial
renders the status line from the query params, so the F2 route file needs no
edit beyond the one sanctioned include.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from backend.errors import APIError
from backend.personalized.personalization import PreferencesRejected
from backend.personalized.preferences import clear_preferences, save_preferences
from backend.personalized.quota import QuotaService
from backend.personalized.store import PersonalizedStore

from ..context import LoginRequired
from ..flow import (
    PageAccount,
    account_shell,
    config_for,
    notice,
    page_account,
    render_error_page,
)
from ..forms import FormBadEncoding, FormTooLarge, read_form
from ..personalized_views import (
    HUB_DATA_ERROR,
    KILL_SWITCH_NOTICE,
    WEAKNESS_MAX_CHARS,
    caps_from_config,
    safe_hub_view,
    safe_session_view,
)
from ..render import render_page

router = APIRouter(tags=["web"])

logger = logging.getLogger(__name__)

HUB_PATH: Final[str] = "/app/personalized"
SESSION_PATH_PREFIX: Final[str] = HUB_PATH + "/"
SESSION_TITLE: Final[str] = "Personalized session"
HUB_TITLE: Final[str] = "Personalized learning"
SETTINGS_PATH: Final[str] = "/app/settings"
_FORM_EXPIRED_TEXT: Final[str] = (
    "Reload the page and submit again. If it happens again, check that this "
    "browser allows cookies for Zivon."
)

START_ERROR_COPY: Final[dict[str, str]] = {
    "missing_input": "Choose a chapter, or describe what's confusing in a few words.",
    "weakness_too_long": (
        f"Keep the weakness under {WEAKNESS_MAX_CHARS} characters — a sentence is enough."
    ),
    "chapter_unknown": "That chapter isn't available for teaching yet.",
    "concept_not_in_chapter": "That concept doesn't belong to the chosen chapter.",
    "chapter_required": (
        "We won't guess the chapter from those words. Pick the chapter below and "
        "keep your description."
    ),
    "parent_unknown": (
        "That session can no longer be continued. Start a new session instead."
    ),
}

QUOTA_SESSIONS_NOTICE: Final[str] = (
    "You've used today's new-session allowance. Your saved sessions are safe; "
    "teaching turns reset at 00:00 IST."
)

# -- shared helpers ------------------------------------------------------------


def _require_account(request: Request) -> PageAccount:
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    return account


def _db(request: Request) -> Any:
    return getattr(request.app.state, "db", None)


def _enabled(request: Request) -> bool:
    return bool(getattr(config_for(request), "personalized_enabled", False))


def _index_catalog(request: Request) -> Any:
    return getattr(request.app.state, "personalized_index_catalog", None)


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


def _not_found(request: Request) -> HTMLResponse:
    return render_error_page(
        request,
        status_code=404,
        title="Session not found",
        message=(
            "This session doesn't exist, or it belongs to another account. "
            "Saved sessions are private to the account that made them."
        ),
    )


def _unavailable(request: Request) -> HTMLResponse:
    return render_error_page(
        request,
        status_code=503,
        title="Personalized learning is unavailable",
        message=HUB_DATA_ERROR,
    )


def _user(account: PageAccount) -> str:
    return str(account.context.user["user_id"])


def _hub_page(
    request: Request,
    account: PageAccount,
    view: dict[str, Any],
    *,
    status_code: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    flash: tuple[Any, ...] = ()
    saved = (request.query_params.get("saved") or "").strip()
    if saved == "deleted":
        flash = (notice("Session deleted. It is removed for good."),)
    if (request.query_params.get("resume") or "").strip() == "cap":
        # The store refused the resume: this session used all 60 turns. The
        # copy is the honest start-new explanation (spec.md §2.6), never a
        # suggestion that the button "failed".
        flash = (
            notice(
                "That session used all 60 turns. Start a new session to "
                "continue the chapter — nothing carries over, and the old "
                "transcript stays here."
            ),
        )
    return render_page(
        request,
        "app/personalized_hub.html",
        shell=account_shell(request, account, HUB_TITLE, flash=flash, error=error),
        status_code=status_code,
        extra=view,
    )


# -- hub (SCR-PL-01) -----------------------------------------------------------


@router.get(HUB_PATH, response_class=HTMLResponse, include_in_schema=False)
def personalized_hub(request: Request) -> Response:
    account = _require_account(request)
    view = safe_hub_view(
        _db(request),
        user_id=_user(account),
        index_catalog=_index_catalog(request),
        enabled=_enabled(request),
        caps=caps_from_config(config_for(request)),
    )
    return _hub_page(request, account, view)


@router.post(HUB_PATH + "/start", response_class=HTMLResponse, include_in_schema=False)
async def personalized_start(request: Request) -> Response:
    """Start a session from the hub form (the API-PL-05 rules, no model call).

    Chapter or weakness (≤ 500 chars) is required; the free-text weakness is
    resolved by the store's deterministic lexical match — an ambiguous one is
    a 422 that asks for the chapter, never a guess (spec.md §2.2). The daily
    new-session allowance is checked before the row is created.
    """
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db(request)
    if db is None:
        return _unavailable(request)
    if not _enabled(request):
        view = safe_hub_view(
            db,
            user_id=_user(account),
            index_catalog=_index_catalog(request),
            enabled=False,
        )
        return _hub_page(
            request, account, view, status_code=503, error=KILL_SWITCH_NOTICE
        )

    chapter_id = (form.get("chapter_id") or "").strip()
    concept_id = (form.get("concept_id") or "").strip()
    weakness = (form.get("weakness") or "").strip()
    skip = (form.get("mode") or "").strip() == "beginning"
    # §2.6: resuming after the 60-turn cap starts a new session linked to the
    # old one (display-only — no state or mastery carries over).
    parent_session_id = (form.get("parent_session_id") or "").strip() or None

    field_errors: dict[str, str] = {}
    if not chapter_id and not weakness:
        field_errors["input"] = START_ERROR_COPY["missing_input"]
    elif len(weakness) > WEAKNESS_MAX_CHARS:
        field_errors["weakness"] = START_ERROR_COPY["weakness_too_long"]

    try:
        store = PersonalizedStore(db)
        if not field_errors and not chapter_id:
            matched, _candidates = store.match_chapter_by_weakness(weakness)
            if matched is None:
                field_errors["weakness"] = START_ERROR_COPY["chapter_required"]
            else:
                chapter_id = matched

        chapter = None
        if not field_errors:
            chapter = store.get_chapter(chapter_id)
            if chapter is None:
                field_errors["chapter"] = START_ERROR_COPY["chapter_unknown"]

        concept_ids: list[str] = []
        if not field_errors and concept_id:
            if concept_id not in set(store.concepts_of_chapter(chapter_id)):
                field_errors["concept"] = START_ERROR_COPY["concept_not_in_chapter"]
            else:
                concept_ids = [concept_id]

        if field_errors:
            view = safe_hub_view(
                db,
                user_id=_user(account),
                index_catalog=_index_catalog(request),
                enabled=True,
                caps=caps_from_config(config_for(request)),
            )
            view["field_errors"] = field_errors
            view["form"] = {
                "class_level": (form.get("class_level") or "").strip(),
                "chapter_id": chapter_id,
                "concept_id": concept_id,
                "weakness": weakness,
            }
            return _hub_page(
                request,
                account,
                view,
                status_code=422,
                error="Check the highlighted fields.",
            )

        if parent_session_id:
            parent = store.get_session(_user(account), parent_session_id)
            if parent is None:
                field_errors = {"parent": START_ERROR_COPY["parent_unknown"]}
                view = safe_hub_view(
                    db,
                    user_id=_user(account),
                    index_catalog=_index_catalog(request),
                    enabled=True,
                    caps=caps_from_config(config_for(request)),
                )
                view["field_errors"] = field_errors
                view["form"] = {
                    "class_level": "",
                    "chapter_id": "",
                    "concept_id": "",
                    "weakness": weakness,
                }
                return _hub_page(
                    request,
                    account,
                    view,
                    status_code=422,
                    error="Check the highlighted fields.",
                )

        sessions_cap = int(
            getattr(config_for(request), "personalized_sessions_per_user_per_day", 5)
        )
        if (
            sessions_cap <= 0
            or QuotaService(db).sessions_created_today(_user(account)) >= sessions_cap
        ):
            view = safe_hub_view(
                db,
                user_id=_user(account),
                index_catalog=_index_catalog(request),
                enabled=True,
            )
            return _hub_page(
                request, account, view, status_code=403, error=QUOTA_SESSIONS_NOTICE
            )

        assert chapter is not None
        # The shared server-generated title (GAP-PL2R-1: the concept's TITLE,
        # never the raw id — one helper with the JSON create route).
        title = store.session_title(chapter, concept_ids)
        session = store.create_session(
            user_id=_user(account),
            chapter_id=str(chapter["chapter_id"]),
            class_level=int(chapter["class_level"]),
            title=title,
            concept_ids=concept_ids,
            weakness_text=weakness or None,
            skip_diagnostic=skip,
            parent_session_id=parent_session_id,
        )
        return RedirectResponse(
            url=f"{SESSION_PATH_PREFIX}{session['session_id']}", status_code=303
        )
    except Exception:  # HTML routes render the honest 503 shell, never a JSON 500
        logger.exception("personalized session start failed")
        return _unavailable(request)


# -- session (SCR-PL-02) -------------------------------------------------------


@router.get(
    SESSION_PATH_PREFIX + "{session_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def personalized_session(request: Request, session_id: str) -> Response:
    account = _require_account(request)
    db = _db(request)
    if db is None:
        return _unavailable(request)
    view = safe_session_view(
        db,
        user_id=_user(account),
        session_id=session_id,
        enabled=_enabled(request),
        caps=caps_from_config(config_for(request)),
    )
    if view is None:
        return _not_found(request)
    flash: tuple[Any, ...] = ()
    if (request.query_params.get("ended") or "").strip():
        flash = (notice("Session ended. Your transcript is saved; you can resume it."),)
    if (request.query_params.get("resumed") or "").strip():
        flash = (notice("Session reopened. Pick up where you left off."),)
    return render_page(
        request,
        "app/personalized_session.html",
        shell=account_shell(request, account, SESSION_TITLE, flash=flash),
        extra=view,
    )


@router.post(
    SESSION_PATH_PREFIX + "{session_id}/end",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def personalized_end(request: Request, session_id: str) -> Response:
    """End the session (API-PL-11's store path; reversible by resuming)."""
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db(request)
    if db is None:
        return _unavailable(request)
    try:
        session = PersonalizedStore(db).end_session(_user(account), session_id)
    except APIError:
        return _not_found(request)
    except Exception:  # HTML routes render the honest 503 shell, never a JSON 500
        logger.exception("personalized session end failed")
        return _unavailable(request)
    return RedirectResponse(
        url=f"{SESSION_PATH_PREFIX}{session['session_id']}?ended=1", status_code=303
    )


@router.post(
    SESSION_PATH_PREFIX + "{session_id}/resume",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def personalized_resume(request: Request, session_id: str) -> Response:
    """Reopen a completed session (API-PL-16's store path) and go back to it.

    The hub's Resume button posts here and the redirect lands on the session
    screen, open again. The store refuses anything that is not a completed
    session: another owner's id is the branded 404, a cap-exhausted session
    lands back on the hub with the truthful start-new explanation (`?resume=cap`),
    and an already-active id simply shows the session (a double submit changed
    nothing, so no "reopened" flash).
    """
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db(request)
    if db is None:
        return _unavailable(request)
    try:
        PersonalizedStore(db).resume_session(_user(account), session_id)
    except APIError as exc:
        if exc.code == "E-NOT-FOUND":
            return _not_found(request)
        if exc.code == "E-PL-TURN-CAP":
            return RedirectResponse(url=f"{HUB_PATH}?resume=cap", status_code=303)
        # E-CONFLICT: already active (or abandoned) — the session screen is
        # the honest landing either way.
        return RedirectResponse(
            url=f"{SESSION_PATH_PREFIX}{session_id}", status_code=303
        )
    except Exception:  # HTML routes render the honest 503 shell, never a JSON 500
        logger.exception("personalized session resume failed")
        return _unavailable(request)
    return RedirectResponse(
        url=f"{SESSION_PATH_PREFIX}{session_id}?resumed=1", status_code=303
    )


@router.post(
    SESSION_PATH_PREFIX + "{session_id}/delete",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def personalized_delete(request: Request, session_id: str) -> Response:
    """Hard-delete the session after the hub's confirm step (API-PL-08)."""
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db(request)
    if db is None:
        return _unavailable(request)
    try:
        deleted = PersonalizedStore(db).delete_session(_user(account), session_id)
    except Exception:  # HTML routes render the honest 503 shell, never a JSON 500
        logger.exception("personalized session delete failed")
        return _unavailable(request)
    if not deleted:
        return _not_found(request)
    return RedirectResponse(url=f"{HUB_PATH}?saved=deleted", status_code=303)


# -- settings: personal instructions (SCR-PL-04) -------------------------------


@router.post(
    SETTINGS_PATH + "/instructions",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def settings_instructions_submit(request: Request) -> Response:
    """Save/clear the account personal instructions (API-PL-02/03 rules).

    The value is normalized + validated by the PL1 domain function before any
    write; a rejection redirects back with the stable reason so the PL4
    partial renders the honest copy with the previous value untouched. Saving
    emits the PL1 counts-only event (`personalized.prefs.saved`).
    """
    account = _require_account(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)
    db = _db(request)
    if db is None:
        return RedirectResponse(
            url=f"{SETTINGS_PATH}?instructions_error=unavailable", status_code=303
        )
    if not _enabled(request):
        return render_error_page(
            request,
            status_code=503,
            title="Personalized learning is paused",
            message=KILL_SWITCH_NOTICE,
        )

    intent = (form.get("intent") or "save").strip()
    if intent == "clear":
        try:
            await run_in_threadpool(partial(clear_preferences, db, _user(account)))
        except Exception:  # the honest unavailable redirect, not a JSON 500
            logger.exception("personalized preferences clear failed")
            return RedirectResponse(
                url=f"{SETTINGS_PATH}?instructions_error=unavailable", status_code=303
            )
        return RedirectResponse(
            url=f"{SETTINGS_PATH}?saved=instructions-cleared", status_code=303
        )

    raw_text = form.get("personal_instructions") or ""
    try:
        await run_in_threadpool(partial(save_preferences, db, _user(account), raw_text))
    except PreferencesRejected as exc:
        return RedirectResponse(
            url=f"{SETTINGS_PATH}?instructions_error={exc.reason}", status_code=303
        )
    except Exception:  # the honest unavailable redirect, not a JSON 500
        logger.exception("personalized preferences save failed")
        return RedirectResponse(
            url=f"{SETTINGS_PATH}?instructions_error=unavailable", status_code=303
        )
    return RedirectResponse(url=f"{SETTINGS_PATH}?saved=instructions", status_code=303)


__all__ = ["router"]
