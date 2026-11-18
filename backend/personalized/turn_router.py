"""The teaching-turn endpoint (API-PL-10, SSE; agent-and-rag.md §3, data-and-api.md §4.6).

PL2 replaces PL1's honest 503 stub. Admission order (§4.6), all before any
model call:

1. session auth + CSRF (middleware and the shared helpers),
2. owner scope (`404` for another user's session),
3. engine availability (`503 E-PL-MODEL-DOWN` when the `TurnEngine` is not
   wired or the kill switch is off — the honest state PL1 shipped),
4. idempotency: a completed `client_turn_id` replays its stored result; a
   turn still in flight is `409 E-PL-TURN-OPEN`;
5. pre-admission state validation (`answer` requires an open check; a new
   teaching action cannot start while one is open) — these are 4xx JSON
   errors, never mid-stream;
6. quota reservation (user + global in one transaction; `retry_decide` after
   a decide failure does NOT reserve again — a retry cannot double-charge);
7. the engine (retrieval, model calls).

SSE responses stream the §3.2 catalogue with `Cache-Control: no-store` and
`X-Accel-Buffering: no`. A client sending `Accept: application/json` gets the
assembled turn object (the same events, one body). Quota: `turn.done` or a
decide-pending turn commits the reservation; any exception releases it; a
blocked reservation writes a `quota_blocked` usage row (§4.6).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from db.uuid7 import uuid7_str

from ..auth.service import AuthContext
from ..errors import APIError
from ..logging_shim import ErrorClass, log_event
from . import state as sm
from .agent import ACTIONS, TurnEvent
from .quota import QuotaService
from .store import PersonalizedStore

router = APIRouter(tags=["personalized"])

SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
}


class TurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_turn_id: str
    action: str = "continue"
    check_id: str | None = None
    answer: str | dict[str, Any] | None = None
    text: str | None = None


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return db


def _user_id(ctx: AuthContext) -> str:
    return str(ctx.user["user_id"])


def _sse(event: TurnEvent) -> str:
    return f"event: {event.name}\ndata: {json.dumps(event.payload, ensure_ascii=False)}\n\n"


def _error_event(exc: APIError) -> TurnEvent:
    return TurnEvent(
        "turn.error",
        {
            "code": exc.code,
            "message_key": exc.message_key or "error.pl.turn_failed",
            "retryable": bool(exc.retryable),
        },
    )


def _find_anchor(
    db: Any, session_id: str, client_turn_id: str
) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT message_id, turn_index, payload FROM personalized_message "
        "WHERE session_id = ? AND client_turn_id = ? ORDER BY turn_index ASC",
        (session_id, client_turn_id),
    )
    return dict(row) if row else None


def _replay_events(db: Any, session_id: str, anchor: dict[str, Any]) -> list[TurnEvent]:
    """Rebuild the §3.2 event stream from the stored rows (§3.4: a retry with
    the same id returns the stored turn result instead of re-calling)."""
    payload = anchor.get("payload")
    payload = json.loads(payload) if isinstance(payload, str) else payload or {}
    events: list[TurnEvent] = []
    stage = str(payload.get("stage") or "teach")
    events.append(TurnEvent("turn.stage", {"stage": stage}))
    text = ""
    row = db.fetchone(
        "SELECT text FROM personalized_message WHERE message_id = ?",
        (anchor["message_id"],),
    )
    if row and row.get("text"):
        text = str(row["text"])
    message_id = str(anchor["message_id"])
    events.append(TurnEvent("turn.teach.start", {"message_id": message_id}))
    for chunk_start in range(0, len(text), 240):
        events.append(
            TurnEvent(
                "turn.teach.delta", {"text": text[chunk_start : chunk_start + 240]}
            )
        )
    check_payload = payload.get("check")
    if isinstance(check_payload, dict):
        events.append(TurnEvent("turn.check", check_payload))
    feedback = db.fetchone(
        "SELECT payload FROM personalized_message WHERE session_id = ? AND kind = 'check_result' "
        "AND turn_index > ? ORDER BY turn_index ASC",
        (session_id, int(anchor["turn_index"])),
    )
    if feedback is not None:
        fpayload = feedback.get("payload")
        fpayload = json.loads(fpayload) if isinstance(fpayload, str) else fpayload or {}
        events.append(TurnEvent("turn.feedback", fpayload))
    events.append(
        TurnEvent(
            "turn.next",
            {
                "next_action": str(payload.get("next_action") or "ask_check"),
                "stage": stage,
                "concept_id": (check_payload or {}).get("concept_id"),
                "difficulty": None,
            },
        )
    )
    return events


def _prevalidate(
    request: Request, ctx: AuthContext, session: dict[str, Any], body: TurnBody
) -> None:
    """Admission validation that must keep honest 4xx statuses (never
    mid-stream): action enum, session status, the one-open-check rule."""
    if body.action not in ACTIONS:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_action"}
        )
    if not body.client_turn_id or len(body.client_turn_id) > 100:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_client_turn_id"}
        )
    if body.action != "end" and session["status"] != "active":
        raise APIError("E-CONFLICT", status_code=409)
    state = sm.state_from_session(session)
    open_check = sm.open_check(state)
    pending = state.get("last_decide_pending") or {}
    if body.action == "retry_decide":
        if pending.get("client_turn_id") != body.client_turn_id:
            raise APIError("E-CONFLICT", status_code=409)
        return
    if body.action == "answer" and open_check is None:
        raise APIError("E-CONFLICT", status_code=409)
    if body.action != "answer" and open_check is not None:
        raise APIError("E-PL-TURN-OPEN", status_code=409)
    if (
        body.action == "answer"
        and body.check_id
        and open_check is not None
        and str(body.check_id) != str(open_check.get("check_id"))
    ):
        raise APIError("E-CONFLICT", status_code=409)
    del request, ctx


def _blocked_response(decision: Any) -> APIError:
    """§4.10: user quota 403, global quota 503, same envelope."""
    if decision.reason.startswith("global"):
        return APIError(
            "E-QUOTA-EXHAUSTED",
            status_code=503,
            message_key="error.pl.quota_global",
            extra={"scope": "global"},
        )
    if decision.reason == "user_concurrency":
        return APIError(
            "E-PL-TURN-OPEN", status_code=409, message_key="error.pl.turn_open"
        )
    return APIError(
        "E-QUOTA-EXHAUSTED",
        status_code=403,
        message_key="error.pl.quota_user",
        extra={"scope": "user"},
    )


def _record_quota_block(db: Any, user_id: str, session_id: str) -> None:
    """§4.6: a quota/rate decision that blocked the turn writes one
    quota_blocked usage row (counts only, no text)."""
    from .store import _utc_now_iso

    db.execute(
        """
        INSERT INTO personalized_usage (
            usage_id, user_id, session_id, stage, model, outcome, created_at
        ) VALUES (?, ?, ?, NULL, NULL, 'quota_blocked', ?)
        """,
        (uuid7_str(), user_id, session_id, _utc_now_iso()),
    )


@router.post("/v1/personalized/sessions/{session_id}/turns")
def post_turn(request: Request, session_id: str, body: TurnBody) -> Any:
    from ..routes.auth import require_context, require_csrf

    ctx = require_context(request)
    require_csrf(request, ctx)
    user_id = _user_id(ctx)
    db = _db(request)
    store = PersonalizedStore(db)
    session = store.get_session(user_id, session_id)
    if session is None:
        raise APIError("E-NOT-FOUND", status_code=404)

    engine = getattr(request.app.state, "personalized_turn_engine", None)
    if engine is None:
        log_event(
            "personalized.turn.unavailable",
            {"reason_code": "engine_not_wired"},
            error_class=ErrorClass.INFRA_ERROR,
        )
        raise APIError("E-PL-MODEL-DOWN", status_code=503, retryable=True)

    state = sm.state_from_session(session)
    pending = state.get("last_decide_pending") or {}
    skip_reserve = (
        body.action == "retry_decide"
        and pending.get("client_turn_id") == body.client_turn_id
    )
    if not skip_reserve:
        # Idempotency (§3.4, admission order before state validation): a
        # completed client_turn_id replays its stored result, never re-calls.
        anchor = _find_anchor(db, session_id, body.client_turn_id)
        if anchor is not None:
            events = _replay_events(db, session_id, anchor)
            return _respond(request, events, replay=True)
        _prevalidate(request, ctx, session, body)

    quota = QuotaService(db)
    decision = None
    if not skip_reserve:
        decision = quota.reserve_turn(user_id)
        if not decision.allowed:
            _record_quota_block(db, user_id, session_id)
            raise _blocked_response(decision)

    from .agent import TurnContext

    turn_ctx = TurnContext(
        user_id=user_id,
        session_id=session_id,
        client_turn_id=body.client_turn_id,
        action=body.action,
        store=store,
        answer=body.answer,
        check_id=body.check_id,
        text=body.text,
        personal_instructions=_personal_instructions(request, user_id),
    )
    # A decide-pending retry took no reservation: nothing to commit or
    # release — the original turn was already charged (§3.4).
    return _respond(
        request,
        engine.run_turn(turn_ctx),
        quota=None if skip_reserve else quota,
        user_id=None if skip_reserve else user_id,
    )


def _personal_instructions(request: Request, user_id: str) -> str | None:
    """The account's personal instructions (C22), read fresh per turn — the
    500-char bounded block rides as the second system message (§4.2)."""
    from .preferences import get_preferences_row

    row = get_preferences_row(_db(request), user_id)
    if row is None:
        return None
    return row.get("personal_instructions") or None


def _respond(
    request: Request,
    events: Iterable[TurnEvent],
    *,
    replay: bool = False,
    quota: QuotaService | None = None,
    user_id: str | None = None,
) -> Any:
    wants_json = "application/json" in (request.headers.get("accept") or "")

    if wants_json:
        collected: list[TurnEvent] = []
        try:
            collected.extend(events)
        except APIError as exc:
            if not collected and quota is not None and user_id is not None:
                quota.release_turn(user_id)
            if not collected:
                raise
            collected.append(_error_event(exc))
        # An unexpected backend failure becomes an honest turn.error, never a
        # bare 500 mid-body.
        except Exception:
            if quota is not None and user_id is not None:
                quota.release_turn(user_id)
            if not collected:
                raise
            collected.append(
                TurnEvent(
                    "turn.error",
                    {
                        "code": "E-PL-MODEL-DOWN",
                        "message_key": "error.pl.model_down",
                        "retryable": True,
                    },
                )
            )
        _settle_quota(collected, quota, user_id)
        payload: dict[str, Any] = {
            "events": [{"event": e.name, "payload": e.payload} for e in collected],
        }
        for event in collected:
            if event.name == "turn.done":
                payload.update(event.payload)
        response = JSONResponse(content=payload)
        response.headers["Cache-Control"] = "no-store"
        return response

    def stream() -> Iterator[str]:
        emitted: list[TurnEvent] = []
        try:
            for event in events:
                emitted.append(event)
                yield _sse(event)
        except APIError as exc:
            if quota is not None and user_id is not None:
                quota.release_turn(user_id)
            yield _sse(_error_event(exc))
            return
        except Exception:  # noqa: BLE001 — same mapping on the SSE path
            if quota is not None and user_id is not None:
                quota.release_turn(user_id)
            yield _sse(
                TurnEvent(
                    "turn.error",
                    {
                        "code": "E-PL-MODEL-DOWN",
                        "message_key": "error.pl.model_down",
                        "retryable": True,
                    },
                )
            )
            return
        _settle_quota(emitted, quota, user_id)
        if replay:
            yield _sse(
                TurnEvent(
                    "turn.done",
                    {"message_id": None, "quota": None, "replayed": True},
                )
            )

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


def _settle_quota(
    emitted: list[TurnEvent], quota: QuotaService | None, user_id: str | None
) -> None:
    """`turn.done` or a decide-pending `turn.error` commits the reservation;
    the release path is the exception handlers above (§4.6)."""
    if quota is None or user_id is None:
        return
    done = any(e.name == "turn.done" for e in emitted)
    decide_pending = any(
        e.name == "turn.error" and e.payload.get("retry_action") == "retry_decide"
        for e in emitted
    )
    if done or decide_pending:
        quota.commit_turn(user_id)
