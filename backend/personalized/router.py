"""Personalized-learning JSON API (PL1, data-and-api.md §4).

Endpoints `API-PL-01…09`, `API-PL-12`, `API-PL-15` plus the honest `API-PL-10`
turn stub and `API-PL-04` catalog stub. Contract rules (§4.1):

- **Session auth** via the opaque `zivon_session` cookie resolved by
  `AuthService.resolve` (ADR-0029); guests get `401 E-AUTH-REQUIRED`.
- **CSRF** on every write via `X-CSRF-Token`; missing/invalid → `403
  E-AUTH-CSRF` and nothing changes.
- **Owner scoping**: `user_id` always comes from the validated session, never
  from the URL or body; another user's id is `404` (no existence oracle).
- **Rate-limit families** (§4.1, enforced by `backend/abuse.py` middleware):
  `personalized_turn` (6/min) on the turn stub, `personalized_create` (5/h) on
  session create, `personalized_read` (60/min) on the GETs, and
  `personalized_ip` (20/min) as the surface brake on the remaining writes
  (preferences save/clear, session delete/end — the per-endpoint hourly
  sub-caps of the endpoint table ride on PL2's turn-router work).
- **Body caps**: 8 KB preference/session bodies; 500-char preference and
  weakness values; 32 fields max (pydantic `extra="forbid"` models).

The turn endpoint reserves no quota and writes no usage row: PL1 makes no
model call, and §4.6 says a failure before the model calls with no quota/rate
decision writes nothing. It returns `503 E-PL-MODEL-DOWN` until PL2 wires the
injected `TurnEngine` (`app.state.personalized_turn_engine`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..auth.service import AuthContext
from ..config import BackendConfig
from ..errors import APIError
from ..logging_shim import ErrorClass, log_event
from ..routes.auth import require_context, require_csrf
from .personalization import PreferencesRejected
from .preferences import clear_preferences, get_preferences, save_preferences
from .quota import QuotaCaps, QuotaService
from .store import PersonalizedStore

router = APIRouter(tags=["personalized"])
preferences_router = APIRouter(prefix="/v1/me", tags=["personalized"])

MAX_BODY_BYTES = 8192


# --- request models (extra="forbid": 32-fields-max body cap) -----------------


class PreferencesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal_instructions: str


class SessionCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_id: str | None = None
    concept_ids: list[str] | None = None
    weakness_text: str | None = None
    skip_diagnostic: bool = False
    parent_session_id: str | None = None
    mode: str = "learning"


# --- shared helpers -----------------------------------------------------------


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return db


def _config(request: Request) -> BackendConfig:
    return request.app.state.config


def _store(request: Request) -> PersonalizedStore:
    return PersonalizedStore(_db(request))


def _quota(request: Request) -> QuotaService:
    cfg = _config(request)
    caps = QuotaCaps(
        turns_per_user_per_day=cfg.personalized_turns_per_user_per_day,
        turn_concurrency=cfg.personalized_turn_concurrency,
        sessions_per_user_per_day=cfg.personalized_sessions_per_user_per_day,
        artifacts_per_user_per_day=cfg.personalized_artifacts_per_user_per_day,
        turns_global_per_day=cfg.personalized_turns_global_per_day,
        artifacts_global_per_day=cfg.personalized_artifacts_global_per_day,
    )
    return QuotaService(_db(request), caps)


def _require_enabled(request: Request) -> None:
    """Kill switch (§4.8): `ZIVON_PERSONALIZED_ENABLED=false` is read-only."""
    if not _config(request).personalized_enabled:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503, retryable=False)


def _enforce_body_cap(request: Request) -> None:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "body_too_large"}
        )


def _user_id(ctx: AuthContext) -> str:
    return str(ctx.user["user_id"])


def _prefs_rejected(exc: PreferencesRejected) -> APIError:
    """The §4.3 rejection payload: previous value untouched, reason carried."""
    return APIError(
        "E-VALIDATION",
        status_code=422,
        message_key="error.preferences_rejected",
        extra={"field": "personal_instructions", "reason": exc.reason},
    )


def _no_store(payload: Any, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(content=payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    return response


# --- preferences (API-PL-01…03) -----------------------------------------------


@preferences_router.get("/preferences")
def get_preferences_endpoint(request: Request) -> JSONResponse:
    ctx = require_context(request)
    payload = get_preferences(
        _db(request),
        _user_id(ctx),
        available=_config(request).personalized_enabled,
    )
    return _no_store(payload)


@preferences_router.put("/preferences")
def put_preferences(body: PreferencesBody, request: Request) -> JSONResponse:
    ctx = require_context(request)
    require_csrf(request, ctx)
    _require_enabled(request)
    _enforce_body_cap(request)
    try:
        payload = save_preferences(
            _db(request), _user_id(ctx), body.personal_instructions
        )
    except PreferencesRejected as exc:
        raise _prefs_rejected(exc) from exc
    return _no_store(payload)


@preferences_router.delete("/preferences")
def delete_preferences(request: Request) -> JSONResponse:
    ctx = require_context(request)
    require_csrf(request, ctx)
    _require_enabled(request)
    clear_preferences(_db(request), _user_id(ctx))
    response = JSONResponse(status_code=204, content=None)
    response.headers["Cache-Control"] = "no-store"
    return response


# --- catalog (API-PL-04) --------------------------------------------------------


@router.get("/v1/personalized/catalog")
def personalized_catalog(request: Request) -> JSONResponse:
    """Chapters with RAG index coverage + tier (§4.2 API-PL-04).

    PL1 has no index: the honest answer is `503 E-CONTENT-UNAVAILABLE`
    ("index missing/stale"). PL2 installs the index-catalog callable on
    `app.state.personalized_index_catalog` to fill this in.
    """
    require_context(request)
    index_catalog = getattr(request.app.state, "personalized_index_catalog", None)
    if index_catalog is None:
        raise APIError("E-CONTENT-UNAVAILABLE", status_code=503, retryable=True)
    return _no_store(index_catalog())


# --- sessions (API-PL-05…09, 12) --------------------------------------------------


@router.post("/v1/personalized/sessions")
def create_session(body: SessionCreateBody, request: Request) -> JSONResponse:
    ctx = require_context(request)
    require_csrf(request, ctx)
    _require_enabled(request)
    _enforce_body_cap(request)
    store = _store(request)
    quota = _quota(request)
    user = _user_id(ctx)

    if (
        quota.sessions_created_today(user)
        >= _config(request).personalized_sessions_per_user_per_day
    ):
        raise APIError(
            "E-QUOTA-EXHAUSTED", status_code=403, message_key="error.pl.quota_user"
        )

    chapter_id = body.chapter_id
    if not chapter_id:
        weakness = body.weakness_text or ""
        matched, candidates = store.match_chapter_by_weakness(weakness)
        if matched is None:
            raise APIError(
                "E-VALIDATION",
                status_code=422,
                extra={
                    "reason": "chapter_required",
                    "hint": "chapter_picker" if candidates else "provide_chapter_id",
                },
            )
        chapter_id = matched
    chapter = store.get_chapter(chapter_id)
    if chapter is None:
        raise APIError("E-CONTENT-UNAVAILABLE", status_code=503, retryable=True)

    concept_ids = body.concept_ids or []
    valid_concepts = set(store.concepts_of_chapter(chapter_id))
    if concept_ids and not set(concept_ids).issubset(valid_concepts):
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "concept_not_in_chapter"}
        )

    parent_session_id = body.parent_session_id
    if parent_session_id:
        parent = store.get_session(user, parent_session_id)
        if parent is None:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "invalid_parent"}
            )

    first_concept = concept_ids[0] if concept_ids else None
    title_source = first_concept or chapter["slug"]
    title = f"{chapter['title_en']} · {title_source}"[:120]
    session = store.create_session(
        user_id=user,
        chapter_id=chapter_id,
        class_level=int(chapter["class_level"]),
        title=title,
        concept_ids=concept_ids,
        weakness_text=body.weakness_text,
        skip_diagnostic=body.skip_diagnostic,
        parent_session_id=parent_session_id,
        mode=body.mode,
    )
    usage = quota.get_usage(user, enabled=_config(request).personalized_enabled)
    return _no_store(
        {
            "session_id": session["session_id"],
            "title": session["title"],
            "stage": session["stage"],
            "class_level": session["class_level"],
            # PL1 has no diagnostic engine (PL2 wires the bank-first picker):
            # nothing remaining is the honest value, not a hidden feature.
            "diagnostic": {"remaining": 0, "first_question": None},
            "quota": {
                "turns_remaining": usage["turns"]["remaining"],
                "reset_at": usage["reset_at"],
            },
        },
        status_code=201,
    )


@router.get("/v1/personalized/sessions")
def list_sessions(
    request: Request,
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> JSONResponse:
    ctx = require_context(request)
    items, next_cursor = _store(request).list_sessions(
        _user_id(ctx), status=status, limit=limit, cursor=cursor
    )
    return _no_store({"items": items, "next": next_cursor})


def _owned_session(
    request: Request, ctx: AuthContext, session_id: str
) -> dict[str, Any]:
    session = _store(request).get_session(_user_id(ctx), session_id)
    if session is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    return session


@router.get("/v1/personalized/sessions/{session_id}")
def get_session_detail(request: Request, session_id: str) -> JSONResponse:
    ctx = require_context(request)
    session = _owned_session(request, ctx, session_id)
    store = _store(request)
    messages = store.last_messages(_user_id(ctx), session_id, limit=50)
    usage = _quota(request).get_usage(
        _user_id(ctx), enabled=_config(request).personalized_enabled
    )
    return _no_store(
        {
            "session": session,
            "quota": {
                "turns_remaining": usage["turns"]["remaining"],
                "reset_at": usage["reset_at"],
            },
            "messages": messages,
        }
    )


@router.delete("/v1/personalized/sessions/{session_id}")
def delete_session(request: Request, session_id: str) -> JSONResponse:
    ctx = require_context(request)
    require_csrf(request, ctx)
    deleted = _store(request).delete_session(_user_id(ctx), session_id)
    if not deleted:
        raise APIError("E-NOT-FOUND", status_code=404)
    response = JSONResponse(status_code=204, content=None)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/personalized/sessions/{session_id}/export")
def export_session(request: Request, session_id: str) -> JSONResponse:
    ctx = require_context(request)
    payload = _store(request).export_session(_user_id(ctx), session_id)
    if payload is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="zivon-session-{session_id}.json"'
    )
    return response


@router.get("/v1/personalized/sessions/{session_id}/messages")
def session_messages(
    request: Request, session_id: str, before: int | None = None, limit: int = 50
) -> JSONResponse:
    ctx = require_context(request)
    _owned_session(request, ctx, session_id)
    messages = _store(request).messages_page(
        _user_id(ctx), session_id, before=before, limit=limit
    )
    return _no_store({"items": messages})


@router.post("/v1/personalized/sessions/{session_id}/end")
def end_session(request: Request, session_id: str) -> JSONResponse:
    ctx = require_context(request)
    require_csrf(request, ctx)
    session = _store(request).end_session(_user_id(ctx), session_id)
    return _no_store(
        {
            "status": session["status"],
            "summary": {
                "turn_count": session["turn_count"],
                "concept_total": len(session["concept_ids"]),
                "stage": session["stage"],
            },
        }
    )


# --- turns (API-PL-10 stub) -------------------------------------------------------


@router.post("/v1/personalized/sessions/{session_id}/turns")
def next_turn(request: Request, session_id: str) -> JSONResponse:
    """The teaching turn: an honest 503 until PL2's TurnEngine exists (§4.6).

    Admission order stays contract-shaped: auth → CSRF → owner scope →
    engine availability. No quota reservation is taken and no usage row is
    written — §4.6 writes quota rows only when a quota/rate decision was made,
    and PL1 reaches no model call. PL2 replaces this body with the injected
    `TurnEngine` call (SSE + JSON fallback).
    """
    ctx = require_context(request)
    require_csrf(request, ctx)
    _owned_session(request, ctx, session_id)
    engine = getattr(request.app.state, "personalized_turn_engine", None)
    log_event(
        "personalized.turn.unavailable",
        {"reason_code": "engine_not_wired" if engine is None else "disabled"},
        error_class=ErrorClass.INFRA_ERROR,
    )
    raise APIError("E-PL-MODEL-DOWN", status_code=503, retryable=True)


# --- usage (API-PL-15) --------------------------------------------------------------


@router.get("/v1/personalized/usage")
def personalized_usage(request: Request) -> JSONResponse:
    ctx = require_context(request)
    payload = _quota(request).get_usage(
        _user_id(ctx), enabled=_config(request).personalized_enabled
    )
    return _no_store(payload)
