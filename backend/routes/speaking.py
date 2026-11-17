"""Explain-back APIs (F6, REQUIREMENTS §9.5/§10.9/§10.10).

Authenticated, same-origin JSON under `/v1`; auth is F0's account guard and
CSRF is F0's `require_csrf`. The one vendor path is `backend/speaking/` over
the shipped `voice/` clients — this module only maps request → pipeline →
store.

Privacy shape (binding, `docs/specs/frontend/speaking.md`):

- the upload is transient: bounded in memory, streamed to Prisma, and dropped;
- no audio column exists in `speaking_attempt` and no file is written;
- the persisted attempt is transcript + rubric/feedback JSON + self-check,
  owner-scoped and hard-deletable;
- logs carry ids, counts, bands, and latency only — never transcript text,
  audio, or prompt text.

Consent is the existing device-scoped voice gate: the browser sends the same
device pseudo id it uses for `/v1/consent`, and the server re-checks the stored
`granted` row (current notice version) before a single frame moves. Quota is
the existing `guard.CreditGuard` on the same device scope.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Final

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..assessment import (
    AssessmentError,
    delete_speaking_attempt,
    fetch_speaking_prompt,
    get_speaking_attempt,
    list_speaking_attempts,
    list_speaking_prompts,
    save_speaking_attempt,
    set_speaking_self_check,
)
from ..config import BackendConfig
from ..errors import APIError
from ..logging_shim import ErrorClass, Severity, log_event
from ..speaking import (
    MAX_UPLOAD_BYTES,
    AudioError,
    Evaluation,
    SpeakingEvaluationError,
    SpeakingUnavailableError,
    TranscriptError,
    parse_wav,
    pipeline_for,
    stt_credit_points,
    thresholds,
)
from .auth import _config, require_context, require_csrf

router = APIRouter(tags=["speaking"])

_UUID4_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ACCEPTED_AUDIO_TYPES: Final[frozenset[str]] = frozenset(
    {"audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"}
)
_SELF_CHECK_CHOICES: Final[frozenset[str]] = frozenset(
    {"explained_fully", "missed_a_part", "practise_again"}
)
_ASSESSMENT_STATUS: Final[dict[str, int]] = {
    "E-AUTH-REQUIRED": 401,
    "E-LANGUAGE-INVALID": 422,
    "E-SPEAKING-PROMPT-UNKNOWN": 404,
    "E-SPEAKING-TRANSCRIPT": 422,
    "E-SPEAKING-PAYLOAD": 422,
    "E-SPEAKING-SCORE": 422,
    "E-SPEAKING-DURATION": 422,
}
EVALUATION_UNAVAILABLE_NOTICE = (
    "Your explanation was saved as text, but the AI feedback could not be "
    "generated just now. Try the prompt again to get feedback."
)


class SelfCheckIn(BaseModel):
    """The student's own reflection; a closed choice, never free text."""

    model_config = ConfigDict(extra="forbid")

    choice: str


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return db


def _store_error(exc: AssessmentError) -> APIError:
    status = _ASSESSMENT_STATUS.get(exc.code, 422)
    return APIError(exc.code, status_code=status)


def _device_id(request: Request) -> str:
    raw = request.headers.get("X-Device-Id", "").strip().lower()
    if not _UUID4_RE.match(raw):
        raise APIError("E-VALIDATION", status_code=422)
    return raw


def _consent_state(db: Any, config: BackendConfig, device_pseudo_id: str) -> str | None:
    """None when the voice consent gate is open, else the blocked reason."""
    row = db.get_latest_consent(device_pseudo_id)
    if row is None or row.get("action") != "granted":
        return "consent_missing"
    if row.get("notice_version") != config.current_notice_version:
        return "consent_stale"
    return None


async def _read_bounded_body(request: Request) -> bytes:
    """Read the upload with a hard cap; never trust Content-Length alone."""
    declared = request.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise APIError("E-SPEAKING-AUDIO-SIZE", status_code=413)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise APIError("E-SPEAKING-AUDIO-SIZE", status_code=413)
        chunks.append(chunk)
    if total == 0:
        raise APIError("E-SPEAKING-AUDIO", status_code=422)
    return b"".join(chunks)


def _prompt_for(db: Any, prompt_id: str, language: str) -> dict[str, Any]:
    try:
        prompt = fetch_speaking_prompt(db, prompt_id, language, served_only=True)
    except AssessmentError as exc:
        raise _store_error(exc) from exc
    if prompt is None:
        raise APIError("E-SPEAKING-PROMPT-UNKNOWN", status_code=404)
    return prompt


def _attempt_response(
    *,
    attempt: dict[str, Any],
    prompt: dict[str, Any],
    evaluation: Evaluation | None,
    mock: bool,
) -> JSONResponse:
    content: dict[str, Any] = {
        "mock": mock,
        "attempt": attempt,
        "prompt": prompt,
        "evaluation": evaluation.public() if evaluation is not None else None,
        "evaluation_error": (
            None
            if evaluation is not None
            else {"code": "E-SPEAKING-EVALUATION", "retryable": True}
        ),
        "notice": None if evaluation is not None else EVALUATION_UNAVAILABLE_NOTICE,
    }
    response = JSONResponse(content=content)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/speaking/prompts")
def list_prompts(
    request: Request,
    chapter: str | None = Query(default=None, max_length=120),
    language: str = Query(default="en", max_length=8),
) -> JSONResponse:
    """Servable prompts for one language; answer material is withheld."""
    require_context(request)
    db = _db(request)
    try:
        items = list_speaking_prompts(db, chapter_id=chapter, language=language)
    except AssessmentError as exc:
        raise _store_error(exc) from exc
    log_event(
        "speaking.prompts.listed",
        {"count": len(items), "language": language, "chapter_filtered": bool(chapter)},
        severity=Severity.INFO,
    )
    response = JSONResponse(
        content={
            "schema_version": 1,
            "language": language,
            "count": len(items),
            "items": items,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/v1/speaking/attempts")
async def create_attempt(
    request: Request,
    prompt_id: str = Query(..., min_length=1, max_length=120),
    language: str = Query(default="en", max_length=8),
) -> JSONResponse:
    """Transcribe one transient upload, evaluate it, and save text only."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    config: BackendConfig = _config(request)
    user_id = str(ctx.user["user_id"])
    prompt = await asyncio.to_thread(_prompt_for, db, prompt_id, language)
    device = _device_id(request)
    blocked = await asyncio.to_thread(_consent_state, db, config, device)
    if blocked is not None:
        log_event(
            "speaking.consent.blocked",
            {"prompt_id": prompt_id, "reason_code": blocked},
            severity=Severity.WARNING,
            error_class=ErrorClass.AUTH_ERROR,
        )
        raise APIError(
            "E-CONSENT-REQUIRED" if blocked == "consent_missing" else "E-CONSENT-STALE",
            status_code=403,
        )
    pipeline = pipeline_for(request.app)
    if not pipeline.available:
        raise APIError("E-SPEAKING-UNAVAILABLE", status_code=503)
    guard = getattr(request.app.state, "guard", None)
    if guard is None:
        # Fail closed: STT costs real credits, so an unmetered deployment must
        # not transcribe. A missing guard is a deployment defect, not a quota
        # state, so this is the honest retryable 503 (nothing was read).
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503, retryable=True)
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type not in _ACCEPTED_AUDIO_TYPES:
        raise APIError("E-SPEAKING-AUDIO", status_code=415)
    body = await _read_bounded_body(request)
    try:
        audio = parse_wav(body)
    except AudioError as exc:
        raise APIError(exc.code, status_code=422) from exc
    max_ms = int(thresholds(prompt)["max_duration_s"] * 1000) + 5_000
    if audio.duration_ms > max_ms:
        raise APIError("E-SPEAKING-AUDIO", status_code=422)

    settings = getattr(pipeline, "settings", None)
    seconds_per_point = int(getattr(settings, "credit_stt_seconds_per_point", 30) or 30)
    points = stt_credit_points(audio.duration_ms, seconds_per_point)
    decision = await asyncio.to_thread(guard.check_and_reserve, device, points)
    if not decision.allowed:
        log_event(
            "speaking.quota.blocked",
            {
                "prompt_id": prompt_id,
                "requested": points,
                "remaining": decision.status.global_remaining,
                "reason": decision.reason,
            },
            severity=Severity.WARNING,
            error_class=ErrorClass.QUOTA_ERROR,
        )
        raise APIError(
            "E-QUOTA-EXHAUSTED",
            status_code=429,
            retryable=True,
            retry_after=3600,
        )
    # Logged after the quota decision: "started" counts attempts that will
    # actually reach a vendor, never a refused request.
    log_event(
        "speaking.attempt.started",
        {
            "prompt_id": prompt_id,
            "language": language,
            "duration_ms": audio.duration_ms,
            "upload_bytes": len(body),
            "mock": bool(pipeline.mock_mode),
        },
        severity=Severity.INFO,
    )

    try:
        transcript = await pipeline.transcribe(audio.pcm, language=language)
    except SpeakingUnavailableError as exc:
        log_event(
            "speaking.attempt.failed",
            {"prompt_id": prompt_id, "stage": "stt", "reason_code": "unconfigured"},
            severity=Severity.ERROR,
            error_class=ErrorClass.INFRA_ERROR,
        )
        raise APIError("E-SPEAKING-UNAVAILABLE", status_code=503) from exc
    except TranscriptError as exc:
        log_event(
            "speaking.attempt.failed",
            {"prompt_id": prompt_id, "stage": "stt", "reason_code": "transport"},
            severity=Severity.ERROR,
            error_class=ErrorClass.TRANSPORT_ERROR,
        )
        raise APIError(
            "E-SERVICE-UNAVAILABLE", status_code=503, retryable=True
        ) from exc
    log_event(
        "speaking.attempt.transcribed",
        {
            "prompt_id": prompt_id,
            "language": transcript.language,
            "char_count": len(transcript.text),
            "mock": transcript.mock,
        },
        severity=Severity.INFO,
        latency_ms=transcript.stt_ms,
    )
    if not transcript.text.strip():
        log_event(
            "speaking.attempt.no_speech",
            {"prompt_id": prompt_id, "duration_ms": audio.duration_ms},
            severity=Severity.WARNING,
            error_class=ErrorClass.CLIENT_ERROR,
        )
        raise APIError("E-SPEAKING-NO-SPEECH", status_code=422, retryable=True)

    evaluation: Evaluation | None
    eval_started = time.monotonic()
    try:
        evaluation = await pipeline.evaluate(prompt, transcript.text)
    except (SpeakingEvaluationError, SpeakingUnavailableError):
        log_event(
            "speaking.attempt.evaluation_unavailable",
            {"prompt_id": prompt_id, "reason_code": "model_unavailable"},
            severity=Severity.WARNING,
            error_class=ErrorClass.TRANSPORT_ERROR,
        )
        evaluation = None
    eval_ms = int((time.monotonic() - eval_started) * 1000)
    if evaluation is not None:
        log_event(
            "speaking.attempt.evaluated",
            {
                "prompt_id": prompt_id,
                "band": evaluation.band,
                "ideas_present": evaluation.ideas_present,
                "ideas_total": evaluation.ideas_total,
                "mock": evaluation.mock,
            },
            severity=Severity.INFO,
            latency_ms=eval_ms,
        )

    try:
        attempt = await asyncio.to_thread(
            save_speaking_attempt,
            db,
            user_id,
            prompt_id=prompt_id,
            language=language,
            transcript=transcript.text,
            rubric_scores=(evaluation.rubric_scores() if evaluation else None),
            feedback=(evaluation.feedback() if evaluation else None),
            score=(evaluation.score if evaluation else None),
            duration_ms=audio.duration_ms,
        )
    except AssessmentError as exc:
        raise _store_error(exc) from exc
    try:
        await asyncio.to_thread(
            guard.record_ledger_entry,
            device_pseudo_id=device,
            model="prisma",
            units="seconds",
            amount=audio.duration_ms / 1000.0,
            cost_credits=points,
        )
    except Exception:  # noqa: BLE001 — the attempt is saved; accounting is not
        log_event(
            "speaking.attempt.ledger_failed",
            {"prompt_id": prompt_id, "points": points},
            severity=Severity.WARNING,
            error_class=ErrorClass.STORE_ERROR,
        )
    log_event(
        "speaking.attempt.saved",
        {
            "prompt_id": prompt_id,
            "attempt_id": str(attempt["attempt_id"]),
            "band": evaluation.band if evaluation else None,
            "evaluation_available": evaluation is not None,
        },
        severity=Severity.INFO,
    )
    return _attempt_response(
        attempt=attempt,
        prompt=prompt,
        evaluation=evaluation,
        mock=transcript.mock or pipeline.mock_mode,
    )


@router.get("/v1/speaking/attempts")
def list_attempts(
    request: Request,
    prompt_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
) -> JSONResponse:
    """The owner's attempts, newest first (text only; no prompt join)."""
    ctx = require_context(request)
    db = _db(request)
    try:
        items = list_speaking_attempts(
            db, str(ctx.user["user_id"]), prompt_id=prompt_id, limit=limit
        )
    except AssessmentError as exc:
        raise _store_error(exc) from exc
    response = JSONResponse(
        content={"schema_version": 1, "count": len(items), "items": items}
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/speaking/attempts/{attempt_id}")
def get_attempt(attempt_id: str, request: Request) -> JSONResponse:
    """One saved attempt plus the prompt material the attempt unlocks."""
    ctx = require_context(request)
    db = _db(request)
    attempt = get_speaking_attempt(db, str(ctx.user["user_id"]), attempt_id)
    if attempt is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    prompt = fetch_speaking_prompt(
        db, str(attempt["prompt_id"]), str(attempt["language"])
    )
    response = JSONResponse(content={"attempt": attempt, "prompt": prompt})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.patch("/v1/speaking/attempts/{attempt_id}")
def patch_attempt(attempt_id: str, body: SelfCheckIn, request: Request) -> JSONResponse:
    """Save the student's own reflection on one attempt (closed choice)."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    if body.choice not in _SELF_CHECK_CHOICES:
        raise APIError("E-VALIDATION", status_code=422)
    db = _db(request)
    attempt = set_speaking_self_check(
        db,
        str(ctx.user["user_id"]),
        attempt_id,
        self_check={"choice": body.choice},
    )
    if attempt is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    log_event(
        "speaking.attempt.self_check",
        {"prompt_id": str(attempt["prompt_id"]), "choice": body.choice},
        severity=Severity.INFO,
    )
    response = JSONResponse(content={"attempt": attempt})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.delete("/v1/speaking/attempts/{attempt_id}")
def delete_attempt(attempt_id: str, request: Request) -> JSONResponse:
    """Hard-delete the transcript and feedback; a missing id is a 404."""
    ctx = require_context(request)
    require_csrf(request, ctx)
    db = _db(request)
    removed = delete_speaking_attempt(db, str(ctx.user["user_id"]), attempt_id)
    if not removed:
        raise APIError("E-NOT-FOUND", status_code=404)
    log_event(
        "speaking.attempt.deleted",
        {"attempt_id": attempt_id},
        severity=Severity.INFO,
    )
    response = JSONResponse(content={"ok": True, "removed": True})
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ["router"]
