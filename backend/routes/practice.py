"""Practice session APIs (`/v1/practice/*`, REQUIREMENTS §9.4, §10.6–§10.8).

Authenticated, same-origin JSON under `/v1`. Auth is F0's account guard
(`require_context`) and CSRF is F0's `require_csrf`; this module adds no second
session path. The global `/v1/*` rate-limit family applies (30 requests/min per
IP hash by default), so a drill is a handful of requests, not a request per
keystroke.

The answer key never leaves the server before the student commits an answer:
`GET` returns `Question.public()` only, and the key/explanation appear in the
`POST .../answers` response after `record_practice_answer` graded the attempt
from the stored key. The route cannot mark a child right or wrong.

Failure-shaped responses reuse the closed error envelope: unknown session is
`404 E-NOT-FOUND`, a closed set is `409 E-CONFLICT`, a chapter with no imported
questions is `409 E-CONTENT-UNAVAILABLE`, and a malformed request/answer is
`422 E-VALIDATION`. A stored answer *key* that no longer parses is a content
fault (`500 E-INTERNAL`), never the child's error.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..assessment import AssessmentError
from ..errors import APIError
from ..logging_shim import Severity, log_event
from ..practice import (
    PracticeUser,
    complete_session,
    create_session,
    history,
    practice_user,
    session_state,
    submit_answer,
)
from .auth import require_context, require_csrf

router = APIRouter(tags=["practice"])

_CONTENT_CODES: frozenset[str] = frozenset(
    {
        "E-PRACTICE-EMPTY",
        "E-PRACTICE-NO-MISTAKES",
        "E-PRACTICE-NO-WEAK",
    }
)
_SERVER_FAULT_CODES: frozenset[str] = frozenset(
    {"E-ANSWER-KEY-INVALID", "E-PRACTICE-QUESTIONS"}
)


class SessionCreateIn(BaseModel):
    """One practice-set request; policy lives in `backend.practice`."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    chapter_id: str | None = None
    count: int | None = None


class AnswerIn(BaseModel):
    """A committed answer; the grader rejects a malformed shape (never 'wrong')."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer: Any = None
    time_ms: int = 0
    hints_used: int = 0


@router.post("/v1/practice/sessions", status_code=201)
def post_practice_session(body: SessionCreateIn, request: Request) -> JSONResponse:
    """Create a chapter drill, Daily 5, weak-topic drill, or retry set."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    user = _user(ctx.user)
    try:
        session = create_session(
            db,
            user,
            mode=body.mode,
            chapter_id=body.chapter_id,
            count=body.count,
        )
    except AssessmentError as exc:
        _raise_api(exc)
    log_event(
        "practice.session.created",
        {
            "mode": session["mode"],
            "question_count": session["question_count"],
            "chapter_id": session["chapter_id"],
            "language": session["config"].get("language"),
            "language_fallback": bool(
                session["config"].get("language_fallback") or False
            ),
        },
        severity=Severity.INFO,
    )
    return _json({"schema_version": 1, "session": session}, status_code=201)


@router.get("/v1/practice/sessions/{session_id}")
def get_practice_session_state(session_id: str, request: Request) -> JSONResponse:
    """Session progress plus the current question, with the key withheld."""
    ctx = require_context(request)
    db = _db(request)
    try:
        state = session_state(db, str(ctx.user["user_id"]), session_id)
    except AssessmentError as exc:
        _raise_api(exc, server_fault=True)
    if state is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    return _json({"schema_version": 1, **state})


@router.post("/v1/practice/sessions/{session_id}/answers")
def post_practice_answer(
    session_id: str, body: AnswerIn, request: Request
) -> JSONResponse:
    """Grade one answer from the stored key and return feedback plus the next."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    user = _user(ctx.user)
    try:
        result = submit_answer(
            db,
            user,
            session_id,
            question_id=body.question_id,
            answer=body.answer,
            time_ms=body.time_ms,
            hints_used=body.hints_used,
        )
    except AssessmentError as exc:
        _raise_api(exc, server_fault=exc.code in _SERVER_FAULT_CODES)
    if result is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    attempt = result["attempt"]
    log_event(
        "practice.answer.recorded",
        {
            "correct": bool(attempt["correct"]),
            "attempt_no": int(attempt["attempt_no"]),
            "time_ms": int(attempt["time_ms"]),
            "hints_used": int(attempt["hints_used"]),
            "answered_count": int(result["answered_count"]),
            "question_count": int(result["question_count"]),
        },
        severity=Severity.INFO,
    )
    return _json({"schema_version": 1, **result})


@router.post("/v1/practice/sessions/{session_id}/complete")
def post_practice_complete(session_id: str, request: Request) -> JSONResponse:
    """Close the set once (idempotent) and return its summary."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    user = _user(ctx.user)
    try:
        summary = complete_session(db, user, session_id)
    except AssessmentError as exc:
        _raise_api(exc, server_fault=True)
    if summary is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    payload = summary["summary"]
    log_event(
        "practice.session.completed",
        {
            "answered": int(payload["answered_count"]),
            "question_count": int(payload["question_count"]),
            "unanswered": int(payload["unanswered_count"]),
            "score": payload["score"],
        },
        severity=Severity.INFO,
    )
    return _json({"schema_version": 1, **summary})


@router.get("/v1/practice/history")
def get_practice_history(request: Request) -> JSONResponse:
    """Return the account's recent practice sessions, newest first."""
    ctx = require_context(request)
    db = _db(request)
    items = history(db, str(ctx.user["user_id"]))
    return _json({"schema_version": 1, "items": items, "count": len(items)})


def _user(row: Any) -> PracticeUser:
    try:
        return practice_user(row)
    except AssessmentError as exc:  # a resolved account always has a user id
        _raise_api(exc, server_fault=True)


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return db


def _json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(content=payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    return response


def _raise_api(exc: AssessmentError, *, server_fault: bool = False) -> NoReturn:
    """Map a store/policy code onto the closed API error envelope."""
    code = exc.code
    if code == "E-PRACTICE-NOT-FOUND":
        raise APIError("E-NOT-FOUND", status_code=404) from exc
    if code in ("E-PRACTICE-CLOSED", "E-PRACTICE-CONFLICT"):
        raise APIError("E-CONFLICT", status_code=409) from exc
    if code in _CONTENT_CODES:
        raise APIError("E-CONTENT-UNAVAILABLE", status_code=409) from exc
    if server_fault and code in _SERVER_FAULT_CODES:
        raise APIError("E-INTERNAL", status_code=500) from exc
    raise APIError("E-VALIDATION", status_code=422) from exc


__all__ = ["router"]
