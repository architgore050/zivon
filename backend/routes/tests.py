"""Test and series APIs (`/v1/tests/*`, `/v1/series/*`, REQUIREMENTS §9.6).

Authenticated, same-origin JSON under `/v1`. Auth is F0's account guard
(`require_context`) and CSRF is F0's `require_csrf`; this module adds no second
session path. The global `/v1/*` rate-limit family applies.

The answer key never leaves the server before submit: `GET` returns
`Question.public()` rows only, autosave stores no correctness verdict, and the
key/explanation appear only in the `POST .../submit` or `GET .../review`
response for an attempt the caller owns and already submitted. A route cannot
mark a child right or wrong.

Failure shape reuses the closed error envelope: unknown/foreign ids are
`404 E-NOT-FOUND`, a closed or expired attempt is `409 E-CONFLICT`, a chapter
with too small a bank is `409 E-CONTENT-UNAVAILABLE`, and a malformed builder
or answer is `422 E-VALIDATION`. A stored answer *key* that no longer parses is
a content fault (`500 E-INTERNAL`), never the child's error.
"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..assessment import AssessmentError
from ..errors import APIError
from ..logging_shim import Severity, log_event
from ..test_engine import (
    TestUser,
    attempt_state,
    create_chapter_test,
    create_custom_test,
    create_retry_test,
    history,
    review_state,
    save_answer,
    series_catalogue,
    series_detail,
    start_attempt,
    submit_attempt,
    test_user,
)
from .auth import require_context, require_csrf

router = APIRouter(tags=["tests"])

_CONTENT_CODES: frozenset[str] = frozenset(
    {"E-TEST-EMPTY", "E-TEST-NO-MISTAKES", "E-TEST-CONTENT-MODE"}
)
_CONFLICT_CODES: frozenset[str] = frozenset(
    {"E-TEST-ATTEMPT-CLOSED", "E-TEST-EXPIRED", "E-TEST-ATTEMPT-CONFLICT"}
)
_SERVER_FAULT_CODES: frozenset[str] = frozenset(
    {"E-ANSWER-KEY-INVALID", "E-QUESTION-TYPE", "E-TEST-STRUCTURE"}
)
_VALIDATION_CODES: frozenset[str] = frozenset(
    {
        "E-TEST-CHAPTERS",
        "E-TEST-CLASS",
        "E-TEST-COUNT",
        "E-TEST-DIFFICULTY",
        "E-TEST-DURATION",
        "E-TEST-QUESTIONS",
        "E-TEST-TIME",
        "E-TEST-TITLE",
        "E-ANSWER-INVALID",
        "E-LANGUAGE-INVALID",
    }
)


class CustomTestIn(BaseModel):
    """The builder's JSON shape; policy lives in `backend.test_engine`."""

    model_config = ConfigDict(extra="forbid")

    chapter_ids: list[str]
    count: int | None = None
    difficulty: str | None = None
    duration_s: int | None = None


class ChapterTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_id: str


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer: Any = None
    flagged: bool | None = None
    time_ms: int | None = None


@router.get("/v1/series")
def get_series_catalogue(request: Request) -> JSONResponse:
    """The six series with honest live/pending/disabled states."""
    ctx = require_context(request)
    db = _db(request)
    catalogue = series_catalogue(db, _user(ctx.user))
    return _json({"schema_version": 1, **catalogue})


@router.get("/v1/series/{slug}")
def get_series_detail(slug: str, request: Request) -> JSONResponse:
    """One series, its approved copy/notice, and its published papers."""
    ctx = require_context(request)
    db = _db(request)
    detail = series_detail(db, _user(ctx.user), slug=slug)
    if detail is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    return _json({"schema_version": 1, **detail})


@router.post("/v1/tests/custom", status_code=201)
def post_custom_test(body: CustomTestIn, request: Request) -> JSONResponse:
    """Create a student-composed paper from the imported question bank."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    user = _user(ctx.user)
    try:
        test = create_custom_test(
            db,
            user,
            chapter_ids=body.chapter_ids,
            count=body.count,
            difficulty=body.difficulty,
            duration_s=body.duration_s,
        )
    except AssessmentError as exc:
        _raise_api(exc)
    _log_created(test)
    return _json({"schema_version": 1, "test": test}, status_code=201)


@router.post("/v1/tests/chapter", status_code=201)
def post_chapter_test(body: ChapterTestIn, request: Request) -> JSONResponse:
    """Derive a chapter test from that chapter's bank."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    try:
        test = create_chapter_test(db, _user(ctx.user), chapter_id=body.chapter_id)
    except AssessmentError as exc:
        _raise_api(exc)
    _log_created(test)
    return _json({"schema_version": 1, "test": test}, status_code=201)


@router.post("/v1/tests/retry", status_code=201)
def post_retry_test(request: Request) -> JSONResponse:
    """Create a retry paper from the student's still-unresolved misses."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    try:
        test = create_retry_test(db, _user(ctx.user))
    except AssessmentError as exc:
        _raise_api(exc)
    _log_created(test)
    return _json({"schema_version": 1, "test": test}, status_code=201)


@router.post("/v1/tests/{test_id}/attempts", status_code=201)
def post_test_attempt(test_id: str, request: Request) -> JSONResponse:
    """Start a paper, or resume the student's one live attempt on it."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    try:
        started = start_attempt(db, _user(ctx.user), test_id=test_id)
    except AssessmentError as exc:
        _raise_api(exc)
    log_event(
        "test.attempt.started",
        {
            "resumed": bool(started["resumed"]),
            "question_count": int(
                (started["test"].get("structure") or {}).get("question_count") or 0
            ),
        },
        severity=Severity.INFO,
    )
    return _json({"schema_version": 1, **started}, status_code=201)


@router.get("/v1/tests/attempts/{attempt_id}")
def get_test_attempt_state(attempt_id: str, request: Request) -> JSONResponse:
    """Attempt clock, saved answers, and the current public question."""
    ctx = require_context(request)
    db = _db(request)
    try:
        state = attempt_state(db, _user(ctx.user), attempt_id=attempt_id)
    except AssessmentError as exc:
        _raise_api(exc)
    if state is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    return _json({"schema_version": 1, **_jsonable_state(state)})


@router.patch("/v1/tests/attempts/{attempt_id}/answers")
def patch_test_answer(
    attempt_id: str, body: AnswerIn, request: Request
) -> JSONResponse:
    """Autosave one answer or flag; never grades and never returns the key."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    try:
        result = save_answer(
            db,
            _user(ctx.user),
            attempt_id=attempt_id,
            question_id=body.question_id,
            answer=body.answer,
            flagged=body.flagged,
            time_ms=body.time_ms,
        )
    except AssessmentError as exc:
        _raise_api(exc)
    log_event(
        "test.answer.saved",
        {
            "flagged": bool(result["saved"].get("flagged")),
            "answered": result["counts"]["answered"],
            "question_count": result["counts"]["question_count"],
        },
        severity=Severity.INFO,
    )
    return _json({"schema_version": 1, **result})


@router.post("/v1/tests/attempts/{attempt_id}/submit")
def post_test_submit(attempt_id: str, request: Request) -> JSONResponse:
    """Grade every saved answer and return the owner's review."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    review = submit_attempt(db, _user(ctx.user), attempt_id=attempt_id)
    if review is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    return _json({"schema_version": 1, "review": _jsonable_review(review)})


@router.get("/v1/tests/attempts/{attempt_id}/review")
def get_test_review(attempt_id: str, request: Request) -> JSONResponse:
    """The graded review; withheld until the attempt is submitted."""
    ctx = require_context(request)
    db = _db(request)
    try:
        review = review_state(db, _user(ctx.user), attempt_id=attempt_id)
    except AssessmentError as exc:
        _raise_api(exc)
    if review is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    if review.get("state") == "not_submitted":
        raise APIError("E-CONFLICT", status_code=409)
    return _json({"schema_version": 1, "review": _jsonable_review(review)})


@router.get("/v1/tests/history")
def get_test_history(
    request: Request,
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
) -> JSONResponse:
    """The owner's attempts, newest first, with status/kind filters."""
    ctx = require_context(request)
    db = _db(request)
    payload = history(db, _user(ctx.user), status=status, kind=kind)
    return _json({"schema_version": 1, **payload})


# --- mapping helpers --------------------------------------------------------


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503, retryable=False)
    return db


def _user(user_row: Any) -> TestUser:
    try:
        return test_user(dict(user_row))
    except AssessmentError as exc:
        raise APIError("E-AUTH-REQUIRED", status_code=401) from exc


def _json(content: Any, *, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(content=content, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    return response


def _log_created(test: dict[str, Any]) -> None:
    structure = test.get("structure") or {}
    log_event(
        "test.session.created",
        {
            "source": structure.get("source"),
            "question_count": int(structure.get("question_count") or 0),
            "chapters": int(structure.get("chapters") or 0),
            "language": test.get("language"),
            "language_fallback": bool(structure.get("language_fallback")),
        },
        severity=Severity.INFO,
    )


def _jsonable_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = dict(state)
    deadline = payload.get("deadline")
    if deadline is not None:
        payload["deadline"] = deadline.isoformat()
    return payload


def _jsonable_review(review: dict[str, Any]) -> dict[str, Any]:
    payload = dict(review)
    for key in ("test", "attempt"):
        value = payload.get(key)
        if isinstance(value, dict):
            payload[key] = {
                name: item.isoformat() if hasattr(item, "isoformat") else item
                for name, item in value.items()
            }
    return payload


def _raise_api(exc: AssessmentError, *, server_fault: bool = False) -> NoReturn:
    code = exc.code
    if server_fault or code in _SERVER_FAULT_CODES:
        raise APIError("E-INTERNAL", status_code=500, retryable=True) from exc
    if code in _CONTENT_CODES:
        raise APIError("E-CONTENT-UNAVAILABLE", status_code=409) from exc
    if code in _CONFLICT_CODES:
        raise APIError("E-CONFLICT", status_code=409) from exc
    if code in _VALIDATION_CODES:
        raise APIError("E-VALIDATION", status_code=422) from exc
    if code in {"E-TEST-NOT-FOUND", "E-TEST-ATTEMPT-NOT-FOUND"}:
        raise APIError("E-NOT-FOUND", status_code=404) from exc
    if code == "E-AUTH-REQUIRED":
        raise APIError("E-AUTH-REQUIRED", status_code=401) from exc
    raise APIError("E-VALIDATION", status_code=422) from exc


__all__ = ["router"]
