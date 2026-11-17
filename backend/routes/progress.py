"""Progress, bookmark, and dashboard summary APIs (F3, REQUIREMENTS §9.3/§9.7).

Authenticated, same-origin JSON under `/v1`. Auth is F0's account guard
(`require_context`) and CSRF is F0's `require_csrf`; this module adds no second
session path. The global API rate-limit family (`/v1/*` = 30/min) applies.

The batch endpoint is append-only and bounded: event kinds and payload keys are
allowlisted, ids are pattern-checked, and no free-text field exists. Bookmark
changes are the only way to write the two bookmark event kinds.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..config import BackendConfig
from ..errors import APIError
from ..logging_shim import ErrorClass, Severity, log_event
from ..progress import (
    EVENTS_BATCH_MAX,
    ProgressValidationError,
    add_bookmark,
    build_chapter_detail,
    build_summary,
    catalogue_snapshot,
    decorate_bookmarks,
    list_bookmarks,
    list_events,
    list_lesson_progress,
    record_events,
    remove_bookmark,
    utc_now,
    validate_bookmark_target,
    validate_chapter_id,
    validate_event,
)
from .auth import _config, require_context, require_csrf

logger = logging.getLogger(__name__)

router = APIRouter(tags=["progress"])


class EventIn(BaseModel):
    """One client event; field-level validation is `validate_event`."""

    model_config = ConfigDict(extra="forbid")

    kind: Any = None
    chapter_id: Any = None
    concept_id: Any = None
    question_id: Any = None
    payload: Any = None
    occurred_at: Any = None


class EventsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventIn]


class BookmarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str
    target_id: str


class BookmarkPost(BaseModel):
    """One bookmark, or a bounded batch from the device-merge island."""

    model_config = ConfigDict(extra="forbid")

    target_type: str | None = None
    target_id: str | None = None
    items: list[BookmarkIn] | None = None


@router.post("/v1/progress/events")
def post_progress_events(body: EventsIn, request: Request) -> JSONResponse:
    """Append a bounded batch of study events; reject bad items individually."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    if len(body.events) > EVENTS_BATCH_MAX:
        raise APIError("E-VALIDATION", status_code=422)
    now = utc_now()
    accepted_events = []
    rejected: list[dict[str, Any]] = []
    for index, item in enumerate(body.events):
        try:
            accepted_events.append(validate_event(item.model_dump(), now=now))
        except ProgressValidationError:
            rejected.append({"index": index, "code": "E-EVT-SCHEMA"})
    accepted = (
        record_events(db, str(ctx.user["user_id"]), accepted_events)
        if accepted_events
        else 0
    )
    if rejected:
        log_event(
            "progress.events.rejected",
            {"rejected": len(rejected), "reason_code": "event_schema"},
            severity=Severity.WARNING,
            error_class=ErrorClass.CLIENT_ERROR,
        )
    if accepted:
        log_event(
            "progress.events.ingested",
            {"accepted": accepted, "rejected": len(rejected)},
            severity=Severity.INFO,
        )
    response = JSONResponse(content={"accepted": accepted, "rejected": rejected})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/progress/summary")
def get_progress_summary(request: Request) -> JSONResponse:
    """Continue chapter, weekly rhythm, counts, chapter states, recent activity."""
    ctx = require_context(request)
    db = _db(request)
    config: BackendConfig = _config(request)
    user_id = str(ctx.user["user_id"])
    now = utc_now()
    snapshot = catalogue_snapshot(db, config.frontend_dir)
    payload = build_summary(
        events=list_events(db, user_id),
        progress_rows=list_lesson_progress(db, user_id),
        bookmark_count=len(list_bookmarks(db, user_id)),
        snapshot=snapshot,
        now=now,
    )
    payload["catalogue_source"] = snapshot.source
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/progress/chapters/{chapter_id:path}")
def get_progress_chapter(chapter_id: str, request: Request) -> JSONResponse:
    """Chapter and per-concept states derived from the student's events."""
    ctx = require_context(request)
    db = _db(request)
    config: BackendConfig = _config(request)
    try:
        cleaned = validate_chapter_id(chapter_id)
    except ProgressValidationError as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    user_id = str(ctx.user["user_id"])
    snapshot = catalogue_snapshot(db, config.frontend_dir)
    payload = build_chapter_detail(
        chapter_id=cleaned,
        events=list_events(db, user_id),
        progress_rows=list_lesson_progress(db, user_id),
        snapshot=snapshot,
        now=utc_now(),
    )
    if payload is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/bookmarks")
def get_bookmarks(request: Request) -> JSONResponse:
    """List the account's saved chapters, concepts, sections, and questions."""
    ctx = require_context(request)
    db = _db(request)
    config: BackendConfig = _config(request)
    snapshot = catalogue_snapshot(db, config.frontend_dir)
    items = decorate_bookmarks(list_bookmarks(db, str(ctx.user["user_id"])), snapshot)
    response = JSONResponse(
        content={"schema_version": 1, "items": items, "count": len(items)}
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/v1/bookmarks")
def post_bookmark(body: BookmarkPost, request: Request) -> JSONResponse:
    """Save one bookmark or a bounded batch (both idempotent)."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    user_id = str(ctx.user["user_id"])
    if body.items is not None:
        if body.target_type is not None or body.target_id is not None:
            raise APIError("E-VALIDATION", status_code=422)
        if not body.items or len(body.items) > 100:
            raise APIError("E-VALIDATION", status_code=422)
        items: list[dict[str, Any]] = []
        created_count = 0
        for item in body.items:
            try:
                validate_bookmark_target(item.target_type, item.target_id)
            except ProgressValidationError as exc:
                raise APIError("E-VALIDATION", status_code=422) from exc
        for item in body.items:
            saved, created = add_bookmark(
                db, user_id, item.target_type, item.target_id.strip()
            )
            items.append(saved)
            created_count += 1 if created else 0
        log_event(
            "progress.bookmark.changed",
            {
                "target_type": "batch",
                "added": True,
                "created": created_count,
            },
            severity=Severity.INFO,
        )
        response = JSONResponse(
            content={
                "items": items,
                "created": created_count,
                "existing": len(items) - created_count,
            },
            status_code=201 if created_count else 200,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    if not body.target_type or not body.target_id:
        raise APIError("E-VALIDATION", status_code=422)
    try:
        validate_bookmark_target(body.target_type, body.target_id)
    except ProgressValidationError as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    saved, created = add_bookmark(db, user_id, body.target_type, body.target_id.strip())
    log_event(
        "progress.bookmark.changed",
        {"target_type": body.target_type, "added": True, "created": created},
        severity=Severity.INFO,
    )
    response = JSONResponse(
        content={"item": saved, "created": created},
        status_code=201 if created else 200,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.delete("/v1/bookmarks")
def delete_bookmark(
    request: Request,
    target_type: str = Query(..., min_length=1, max_length=20),
    target_id: str = Query(..., min_length=1, max_length=160),
) -> JSONResponse:
    """Remove a bookmark by target; a repeat removal is a no-op, not an error."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    try:
        validate_bookmark_target(target_type, target_id)
    except ProgressValidationError as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    removed = remove_bookmark(
        db, str(ctx.user["user_id"]), target_type, target_id.strip()
    )
    if removed:
        log_event(
            "progress.bookmark.changed",
            {"target_type": target_type, "added": False, "created": False},
            severity=Severity.INFO,
        )
    response = JSONResponse(
        content={
            "ok": True,
            "removed": removed,
            "target_type": target_type,
            "target_id": target_id.strip(),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return db


__all__ = ["router"]
