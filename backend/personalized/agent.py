"""The personalized teaching agent (agent-and-rag.md §3/§4/§7/§8; PL2).

The `TurnEngine` PL1's turn stub waits for. One turn = one student interaction
= deterministic scoring + the state machine + up to two model calls:

1. **Teach call** — streamed prose (the visible teaching slice), no JSON.
2. **Decide call** — JSON mode: the check selection, advisory mastery signal,
   advisory next action, citations.

The model never decides correctness: answers are scored server-side
(`state.score_answer`); the check is **bank-first** — when a P2 bank item fits
the concept/level, the server arms the bank item with its **stored** key (the
model only selects which item fits); a model-generated check is used only when
the bank has no candidate, and its key is stored server-side
(`personalized_message.answer_key`, set NULL once scored) and never
serialized. The model's `next_action`/`mastery_signal` are advisory; the state
machine owns every transition.

Model route (D-PL-07, ADR-0030): DeepSeek V4.1 Flash via the OpenCode
OpenAI-format API through the **in-process** `llm_manager` library, with its
own `ZIVON_PERSONALIZED_*` secret/config — separate from the voice tutor and
the factory. The `x-opencode-session` affinity header carries the hashed
session id (not a credential). No `max_tokens` is ever sent (repo law); the
deadline and the format contract bound the output.

Injection defense (§8): student weakness/follow-up text and RAG excerpts are
delimited DATA blocks; personal instructions are the second system message
(`messages[1]`); citations are resolved server-side against the retrieved set;
unknown ids are dropped; zero resolved citations ⇒ `ungrounded=true`.

Usage rows go to `personalized_usage` (counts/latency only, never text).
Events are emitted through `logging_manager.log_event` only.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from ..config import BackendConfig
from ..errors import APIError
from ..logging_shim import log_event
from . import state as sm
from .prompts import PROMPT_VERSION, decide_messages, teach_messages
from .rag import Embedder, EmbedderUnavailable, RagIndex, resolve_citations
from .store import PersonalizedStore

if TYPE_CHECKING:
    from db.engine import DatabaseEngine

TEACH_STAGES: Final[tuple[str, ...]] = (
    "teach",
    "adapt",
    "worked_example",
    "harder",
    "board",
)
DECIDE_TIMEOUT_S: Final[float] = 20.0
DECIDE_VALIDATION_ROUNDS: Final[int] = 2
BANK_CANDIDATES_LIMIT: Final[int] = 6
BANK_STATUSES: Final[tuple[str, ...]] = ("reviewed", "published")
TEACH_RETRY_EXCERPTS: Final[int] = 4  # §7.5.2: one retry with a shorter set
DIAGNOSTIC_ITEMS_MAX: Final[int] = 3
DECIDE_PENDING_KEY: Final[str] = "last_decide_pending"

ACTIONS: Final[tuple[str, ...]] = (
    "answer",
    "continue",
    "retry_decide",
    "hint",
    "skip_concept",
    "end",
    "explain_directly",
    "message",
)

# The decide object's wire contract (§4.4): top-level keys and types. Field
# subtleties (bank item ids, option counts, citation ids) are validated where
# they are consumed — the schema is the parse-level contract.
DECIDE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "check": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "kind": {"enum": ["mcq", "numeric"]},
                        "question": {"type": "string"},
                        "explanation": {"type": "string"},
                        "concept_id": {"type": "string"},
                    },
                    "required": ["kind", "question"],
                },
            ]
        },
        "mastery_signal": {"type": "object"},
        "next_action": {"type": "string"},
        "citations": {"type": "array"},
        "ungrounded": {"type": "boolean"},
    },
    "required": ["check", "next_action"],
}


class TurnModelDown(APIError):
    """The model route is unavailable (§4.10 `E-PL-MODEL-DOWN`, 503)."""

    def __init__(self) -> None:
        super().__init__("E-PL-MODEL-DOWN", status_code=503, retryable=True)


class DecidePending(RuntimeError):
    """The decide call failed after the teaching slice persisted (§3.4).

    The teaching text stays; only the decide call is retried via
    `action: "retry_decide"` with the same `client_turn_id`. The reservation
    is committed (the teach call already spent tokens) and the retry does not
    reserve again — a retry cannot double-charge (§3.4).
    """

    def __init__(self, client_turn_id: str, teaching_message_id: str) -> None:
        super().__init__("decide_pending")
        self.client_turn_id = client_turn_id
        self.teaching_message_id = teaching_message_id


@dataclass(frozen=True)
class TurnEvent:
    """One SSE event of the §3.2 catalogue (`name` is the literal name)."""

    name: str
    payload: dict[str, Any]


@dataclass
class TurnUsage:
    """Token/latency counters for the usage ledger (no text, §7.4)."""

    stage: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    first_token_ms: int | None = None
    latency_ms: int | None = None
    outcome: str = "ok"


class ModelClient(Protocol):
    """The model-call seam (§6 test table): fakes in tests, `llm_manager` in
    production. Never hand-rolled HTTP anywhere."""

    @property
    def model_id(self) -> str: ...

    def stream(
        self, messages: list[dict[str, str]], *, session_id: str
    ) -> Iterator[str]:
        """Stream teach-call content deltas."""
        ...

    def complete_json(
        self, messages: list[dict[str, str]], *, session_id: str
    ) -> dict[str, Any]:
        """One JSON-mode decide call, validated, parsed to a dict."""
        ...

    def drain_usage(self) -> list[TurnUsage]:
        """Usage rows for the calls made since the last drain."""
        ...


class BankSource(Protocol):
    """The P2 question-bank seam (bank-first checks; read-only)."""

    def candidates(
        self, concept_ids: list[str], level: int, *, limit: int = BANK_CANDIDATES_LIMIT
    ) -> list[dict[str, Any]]: ...

    def item(self, item_id: str) -> dict[str, Any] | None: ...


@dataclass
class RetrievalPorts:
    """Everything retrieval needs; a `None` index ⇒ `E-CONTENT-UNAVAILABLE`."""

    index: RagIndex | None = None
    embedder: Embedder | None = None
    last_mode: str = "n/a"
    last_ungrounded: bool = False


@dataclass
class TurnContext:
    """Everything one turn may touch (the engine takes no other inputs)."""

    user_id: str
    session_id: str
    client_turn_id: str
    action: str
    store: PersonalizedStore
    answer: Any = None
    given_unit: str | None = None
    check_id: str | None = None
    text: str | None = None
    personal_instructions: str | None = None


# --- model route (D-PL-07) -----------------------------------------------------


def build_llm_config(cfg: BackendConfig, *, json_mode: bool, session_hash: str) -> Any:
    """One `llm_manager.LLMConfig` per call kind (§4.6 settings table).

    The teach call streams (JSON mode off), the decide call is a
    JSON-mode call; both carry the per-session affinity header. No
    `max_tokens` (repo law).
    """
    from llm_manager import LLMConfig

    headers = dict(cfg.personalized_model_extra_headers or {})
    headers["x-opencode-session"] = session_hash
    return LLMConfig(
        base_url=str(cfg.personalized_model_base_url),
        model=cfg.personalized_model,
        api_key=cfg.personalized_model_api_key,
        json_mode=json_mode,
        reasoning_effort=cfg.personalized_model_reasoning_effort or None,
        timeout_s=cfg.personalized_model_timeout_s,
        call_deadline_s=cfg.personalized_model_deadline_s,
        stream=not json_mode,
        extra_headers=headers,
        user_agent=cfg.personalized_model_user_agent,
    )


def session_affinity_hash(session_id: str) -> str:
    """The `x-opencode-session` value: a stable per-session id, hashed —
    an opaque routing key, never a secret (§7.3)."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


class LLMManagerClient:
    """The production `ModelClient` over the in-process `llm_manager` library
    (D-PL-07). Transport retries, inactivity timeout, deadline and validation
    rounds are `llm_manager`'s; this adapter owns only the mapping."""

    def __init__(self, cfg: BackendConfig) -> None:
        self._cfg = cfg
        self._pending_usage: list[TurnUsage] = []

    @property
    def model_id(self) -> str:
        return self._cfg.personalized_model

    def stream(
        self, messages: list[dict[str, str]], *, session_id: str
    ) -> Iterator[str]:
        from llm_manager import LLMManager

        manager = LLMManager(
            build_llm_config(
                self._cfg,
                json_mode=False,
                session_hash=session_affinity_hash(session_id),
            )
        )
        started = time.monotonic()
        first_token: float | None = None
        usage_row = TurnUsage(stage="teach", model=self.model_id)
        try:
            for event in manager.stream_events(messages):
                if event.delta is not None:
                    if first_token is None:
                        first_token = time.monotonic()
                        usage_row.first_token_ms = int((first_token - started) * 1000)
                    yield event.delta
                if event.usage:
                    usage_row.input_tokens = int(
                        event.usage.get("prompt_tokens", 0) or 0
                    )
                    usage_row.output_tokens = int(
                        event.usage.get("completion_tokens", 0) or 0
                    )
                    details = event.usage.get("prompt_tokens_details") or {}
                    usage_row.cached_tokens = int(details.get("cached_tokens", 0) or 0)
            usage_row.latency_ms = int((time.monotonic() - started) * 1000)
            self._pending_usage.append(usage_row)
        except Exception:
            usage_row.outcome = "model_error"
            usage_row.latency_ms = int((time.monotonic() - started) * 1000)
            self._pending_usage.append(usage_row)
            raise

    def complete_json(
        self, messages: list[dict[str, str]], *, session_id: str
    ) -> dict[str, Any]:
        from llm_manager import LLMManager, run_validation_rounds

        manager = LLMManager(
            build_llm_config(
                self._cfg,
                json_mode=True,
                session_hash=session_affinity_hash(session_id),
            )
        )
        started = time.monotonic()
        usage_row = TurnUsage(stage="decide", model=self.model_id)

        def call_fn(
            round_no: int, transcript: list[dict[str, str]]
        ) -> tuple[str, str | None]:
            result = manager.complete(transcript)
            return result.text, result.finish_reason

        try:
            parsed = run_validation_rounds(
                call_fn,
                messages,
                DECIDE_SCHEMA,
                "personalized.decide",
                rounds=DECIDE_VALIDATION_ROUNDS,
            )
            usage_row.latency_ms = int((time.monotonic() - started) * 1000)
            usage_row.output_tokens = max(1, len(json.dumps(parsed)) // 4)
            self._pending_usage.append(usage_row)
            return parsed
        except Exception:
            usage_row.outcome = "model_error"
            usage_row.latency_ms = int((time.monotonic() - started) * 1000)
            self._pending_usage.append(usage_row)
            raise

    def drain_usage(self) -> list[TurnUsage]:
        rows = self._pending_usage
        self._pending_usage = []
        return rows


# --- the engine -----------------------------------------------------------------


class PersonalizedAgent:
    """The teaching loop. Synchronous by design (`llm_manager` is sync); the
    router wraps it in SSE / JSON responses."""

    def __init__(
        self,
        *,
        store: PersonalizedStore,
        config: BackendConfig,
        retrieval: RetrievalPorts | None = None,
        model_client: ModelClient | None = None,
        bank: BankSource | None = None,
    ) -> None:
        self._store = store
        self._db: DatabaseEngine = store.db
        self._config = config
        self._retrieval = retrieval or RetrievalPorts()
        self._model = model_client
        self._bank = bank

    # --- public API ------------------------------------------------------------

    def run_turn(self, ctx: TurnContext) -> Iterator[TurnEvent]:
        """Yield the §3.2 event stream for one admitted turn.

        The router owns auth/CSRF/owner-scope/quota/idempotency; this method
        starts after admission. The final event is `turn.done` (the router
        commits the quota reservation), `turn.error` after a decide failure
        (§3.4: committed, retry-decide), or an exception (the router releases
        the reservation and maps the error).
        """
        session = self._require_session(ctx)
        state = sm.state_from_session(session)
        if not state.get("concepts"):
            # concept_ids is optional at create (§4.4): coverage defaults to
            # the chapter's full concept list, in syllabus order.
            chapter_concepts = self._store.concepts_of_chapter(
                str(session["chapter_id"])
            )
            state = sm.initial_state(
                chapter_concepts,
                skip_diagnostic=str(session.get("stage")) == "teach",
            )
        if ctx.action != "end" and session["status"] != "active":
            raise APIError("E-CONFLICT", status_code=409)
        started = time.monotonic()
        teaching_message_id: str | None = None
        try:
            if ctx.action == "end":
                yield from self._end_session(ctx, session, state)
                return
            if ctx.action == "answer":
                events = self._handle_answer(ctx, session, state)
            elif ctx.action == "skip_concept":
                events = self._handle_skip(ctx, state)
            elif ctx.action == "message":
                events = self._handle_message(ctx, state)
            elif ctx.action in ("continue", "hint", "explain_directly", "retry_decide"):
                events = self._handle_continue(ctx, session, state)
            else:
                raise APIError(
                    "E-VALIDATION", status_code=422, extra={"reason": "invalid_action"}
                )

            sm.bump_turn(state)
            streamed_phase: dict[str, Any] | None = None
            streamed_concept: dict[str, Any] | None = None
            if sm.turn_cap_reached(state):
                events.extend(self._finish_mastery(ctx, session, state))
            else:
                plan = self._plan_next_stage(ctx, session, state)
                events.extend(plan["events"])
                session["stage"] = plan["stage"]
                if plan["diagnostic"]:
                    events.extend(plan["diagnostic_events"])
                elif plan["teach_phase"] and (
                    plan["teach_phase"].get("run") or plan["teach_phase"].get("decide")
                ):
                    if self._model is None:
                        raise TurnModelDown()
                    # Deterministic events first, then the live teach stream.
                    yield from events
                    events = []
                    streamed_phase = plan["teach_phase"]
                    streamed_concept = plan["concept"]
            if streamed_phase is not None and streamed_concept is not None:
                yield from self._teach_phase(
                    ctx, session, state, streamed_phase, concept=streamed_concept
                )
                phase_teaching_id = streamed_phase.get("teaching_message_id")
                if phase_teaching_id:
                    teaching_message_id = str(phase_teaching_id)
            if teaching_message_id is None:
                teaching_message_id = self._last_teaching_message_id(ctx)
            events.append(self._next_action_event(session, state))
            self._persist_session_state(ctx, session, state)
            usage = self._drain_usage()
            self._write_usage_rows(ctx, usage)
            yield from events
            latency_ms = int((time.monotonic() - started) * 1000)
            yield TurnEvent(
                "turn.done",
                {
                    "message_id": teaching_message_id,
                    "quota": self._quota_snapshot(ctx),
                    "turn_no": int(state["turn_count"]),
                    "latency_ms": latency_ms,
                },
            )
            log_event(
                "personalized.turn.complete",
                {
                    "stage": str(session["stage"]),
                    "turn_no": int(state["turn_count"]),
                    "latency_ms": latency_ms,
                    "retrieval": self._retrieval.last_mode,
                    "ungrounded": self._retrieval.last_ungrounded,
                    "outcome": "ok",
                    "input_tokens": sum(u.input_tokens for u in usage),
                    "output_tokens": sum(u.output_tokens for u in usage),
                    "cached_tokens": sum(u.cached_tokens for u in usage),
                },
            )
        except DecidePending as pending:
            self._persist_session_state(ctx, session, state, pending=pending)
            self._write_usage_rows(ctx, self._drain_usage())
            yield from events
            yield TurnEvent(
                "turn.error",
                {
                    "code": "E-PL-MODEL-DOWN",
                    "message_key": "error.pl.decide_retry",
                    "retryable": True,
                    "retry_action": "retry_decide",
                },
            )
        except APIError:
            self._write_usage_rows(ctx, self._drain_usage())
            raise
        except Exception:
            self._write_usage_rows(ctx, self._drain_usage())
            raise

    # --- session / persistence ---------------------------------------------------

    def _require_session(self, ctx: TurnContext) -> dict[str, Any]:
        session = self._store.get_session(ctx.user_id, ctx.session_id)
        if session is None:
            raise APIError("E-NOT-FOUND", status_code=404)
        return session

    def _persist_session_state(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        *,
        pending: DecidePending | None = None,
    ) -> None:
        now_iso = _utc_now_iso()
        state.pop(DECIDE_PENDING_KEY, None)
        if pending is not None:
            state[DECIDE_PENDING_KEY] = {
                "client_turn_id": pending.client_turn_id,
                "teaching_message_id": pending.teaching_message_id,
            }
        stage = str(session["stage"])
        done = stage == "done"
        self._db.execute(
            """
            UPDATE personalized_session
            SET stage = ?, difficulty_level = ?, state = ?, rag_index_version = ?,
                prompt_version = ?, model = ?, updated_at = ?, last_turn_at = ?,
                completed_at = CASE WHEN ? THEN COALESCE(completed_at, ?) ELSE completed_at END,
                status = CASE WHEN ? THEN 'completed' ELSE status END
            WHERE session_id = ? AND user_id = ?
            """,
            (
                stage,
                sm.difficulty_level(state),
                json.dumps(sm.normalized_state(state)),
                self._index_version(),
                PROMPT_VERSION,
                self._model.model_id if self._model else None,
                now_iso,
                now_iso,
                done,
                now_iso,
                done,
                ctx.session_id,
                ctx.user_id,
            ),
        )

    def _index_version(self) -> str | None:
        return self._retrieval.index.version if self._retrieval.index else None

    def _quota_snapshot(self, ctx: TurnContext) -> dict[str, Any]:
        from .quota import QuotaService

        usage = QuotaService(self._db).get_usage(ctx.user_id, enabled=True)
        return {"remaining": usage["turns"]["remaining"], "reset_at": usage["reset_at"]}

    def _drain_usage(self) -> list[TurnUsage]:
        if self._model is None:
            return []
        return self._model.drain_usage()

    def _write_usage_rows(self, ctx: TurnContext, usage: list[TurnUsage]) -> None:
        for row in usage:
            self._db.execute(
                """
                INSERT INTO personalized_usage (
                    usage_id, user_id, session_id, stage, model, input_tokens,
                    output_tokens, cached_tokens, first_token_ms, latency_ms,
                    outcome, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _uuid7_str(),
                    ctx.user_id,
                    ctx.session_id,
                    row.stage,
                    row.model,
                    row.input_tokens or None,
                    row.output_tokens or None,
                    row.cached_tokens or None,
                    row.first_token_ms,
                    row.latency_ms,
                    row.outcome,
                    _utc_now_iso(),
                ),
            )

    def _emit_stage_change(
        self,
        events: list[TurnEvent],
        session: dict[str, Any],
        state: dict[str, Any],
        to_stage: str,
    ) -> None:
        """The stage chip event always updates; the EVT-PL-04 audit row and
        log fire only on an actual transition (§2.3.7)."""
        from_stage = str(session.get("stage") or "diagnose")
        events.append(TurnEvent("turn.stage", {"stage": to_stage}))
        if from_stage == to_stage:
            return
        concept_id = str(state.get("current_concept_id") or "")
        level = sm.difficulty_level(state)
        self._store.append_message(
            session_id=ctx_session_id(session),
            role="system_event",
            kind="stage_change",
            payload={
                "from": from_stage,
                "to": to_stage,
                "concept_id": concept_id,
                "level": level,
            },
        )
        log_event(
            "personalized.stage.change",
            {
                "from": from_stage,
                "to": to_stage,
                "concept_id": concept_id,
                "level": level,
            },
        )

    # --- action handlers ------------------------------------------------------------

    def _handle_answer(
        self, ctx: TurnContext, session: dict[str, Any], state: dict[str, Any]
    ) -> list[TurnEvent]:
        """Score the open check deterministically; no model verdict (§3.3)."""
        open_check = sm.open_check(state)
        if open_check is None:
            raise APIError("E-PL-TURN-OPEN", status_code=409)
        if ctx.check_id and ctx.check_id != open_check["check_id"]:
            raise APIError("E-CONFLICT", status_code=409)
        check_row = self._load_scoring_check(ctx, str(open_check["check_id"]))
        scoring = check_row
        raw_answer = ctx.answer
        if isinstance(raw_answer, dict):
            # numeric answers may arrive as {"value": "12.5", "unit": "cm"}
            raw_answer = str(raw_answer.get("value", ""))
        score = sm.score_answer(scoring["check"], raw_answer)
        self._store.append_message(
            session_id=ctx.session_id,
            role="student",
            kind="text",
            text=str(ctx.answer),
        )
        result = sm.record_check_result(state, correct=score.correct)
        if str(state.get("started_at_stage")) == "diagnose":
            item_key = str(
                (check_row.get("source") or {}).get("item_id") or open_check["check_id"]
            )
            sm.record_diagnostic(state, item_key, score.correct)
        self._clear_answer_key(str(open_check["check_id"]))
        self._store.append_message(
            session_id=ctx.session_id,
            role="tutor",
            kind="check_result",
            payload={
                "check_id": open_check["check_id"],
                "concept_id": open_check["concept_id"],
                "level": open_check["level"],
                "correct": score.correct,
                "expected": score.expected_display,
                "unit_hint": score.unit_hint,
                "explanation": scoring["explanation"],
                "misconception": scoring["misconception"],
                "attempt_no": int(result["attempt_no"]),
            },
        )
        log_event(
            "personalized.check.answer",
            {
                "kind": str(open_check["kind"]),
                "level": int(open_check["level"]),
                "correct": score.correct,
                "attempt_no": int(result["attempt_no"]),
                "concept_id": str(open_check["concept_id"]),
            },
        )
        return [
            TurnEvent(
                "turn.feedback",
                {
                    "check_id": open_check["check_id"],
                    "correct": score.correct,
                    "expected": score.expected_display,
                    "unit_hint": score.unit_hint,
                    "explanation": scoring["explanation"],
                    "misconception": scoring["misconception"],
                },
            )
        ]

    def _handle_continue(
        self, ctx: TurnContext, session: dict[str, Any], state: dict[str, Any]
    ) -> list[TurnEvent]:
        if ctx.action != "retry_decide" and sm.open_check(state) is not None:
            # Exactly one open check at a time; submit it first (§2.3.2).
            raise APIError("E-PL-TURN-OPEN", status_code=409)
        if ctx.action == "retry_decide":
            pending = state.get(DECIDE_PENDING_KEY)
            if (
                not isinstance(pending, dict)
                or pending.get("client_turn_id") != ctx.client_turn_id
            ):
                raise APIError("E-CONFLICT", status_code=409)
        return []

    def _handle_skip(self, ctx: TurnContext, state: dict[str, Any]) -> list[TurnEvent]:
        current = state.get("current_concept_id")
        if not current:
            raise APIError("E-CONFLICT", status_code=409)
        if sm.open_check(state) is not None:
            raise APIError("E-PL-TURN-OPEN", status_code=409)
        sm.skip_concept(state, str(current))
        return []

    def _handle_message(
        self, ctx: TurnContext, state: dict[str, Any]
    ) -> list[TurnEvent]:
        """Free text is never graded (PL-C-014): a follow-up teaching request."""
        text = (ctx.text or "").strip()
        if not text:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "empty_message"}
            )
        if len(text) > 2000:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "message_too_long"}
            )
        self._store.append_message(
            session_id=ctx.session_id, role="student", kind="text", text=text
        )
        return []

    def _end_session(
        self, ctx: TurnContext, session: dict[str, Any], state: dict[str, Any]
    ) -> Iterator[TurnEvent]:
        """Student ends: mastery summary still written (transition table)."""
        events: list[TurnEvent] = []
        self._emit_stage_change(events, session, state, "mastery")
        summary = sm.mastery_summary(state)
        self._store.append_message(
            session_id=ctx.session_id,
            role="tutor",
            kind="summary",
            payload={"mastery": summary, "turn_count": int(state["turn_count"])},
        )
        session["stage"] = "done"
        self._emit_stage_change(events, session, state, "done")
        self._persist_session_state(ctx, session, state)
        yield TurnEvent(
            "turn.next",
            {
                "next_action": "finish",
                "stage": "done",
                "difficulty": sm.difficulty_level(state),
            },
        )
        yield TurnEvent(
            "turn.done",
            {
                "message_id": None,
                "quota": self._quota_snapshot(ctx),
                "turn_no": int(state["turn_count"]),
                "latency_ms": 0,
            },
        )

    # --- state-machine progression (the transition table, §2.2) -------------------

    def _plan_next_stage(
        self, ctx: TurnContext, session: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate the transition table after the action's effects. Returns
        `{"events", "stage", "teach_phase", "diagnostic", "diagnostic_events",
        "concept", "teaching_message_id"}`. The model's advisory next_action
        is never consulted here."""
        events: list[TurnEvent] = []
        last = sm.open_check(state) or state.get("last_check") or {}
        concept_id = str(state.get("current_concept_id") or "")

        if ctx.action == "retry_decide":
            concept = self._concept(concept_id)
            pending = state.get(DECIDE_PENDING_KEY) or {}
            teaching_text = self._teaching_text(
                ctx, str(pending.get("teaching_message_id") or "")
            )
            return self._teach_plan(
                ctx,
                session,
                state,
                "teach",
                concept,
                events,
                decide=True,
                run_teach=False,
                teaching_text=teaching_text,
            )

        if ctx.action == "answer" and last.get("correct") is not None:
            if str(state.get("started_at_stage")) == "diagnose" and last.get(
                "diagnostic"
            ):
                # Diagnostic answers (right or wrong) continue the diagnostic
                # until its ≤3 items are done, then teaching starts (§4.5).
                answered = len(state["diagnostic"].get("answers", {}))
                if answered < DIAGNOSTIC_ITEMS_MAX:
                    diag_events = self._diagnostic_phase(ctx, state)
                    if diag_events:
                        return {
                            "events": events,
                            "stage": "diagnose",
                            "teach_phase": None,
                            "diagnostic": True,
                            "diagnostic_events": diag_events,
                            "concept": None,
                            "teaching_message_id": None,
                        }
                sm.finish_diagnostic(state)
                return self._teach_plan(
                    ctx,
                    session,
                    state,
                    "teach",
                    self._concept(str(state.get("current_concept_id") or "")),
                    events,
                )
            if last["correct"]:
                return self._plan_after_correct(ctx, session, state, events)
            attempts = _concept_attempts(state, concept_id)
            if attempts >= sm.MAX_ATTEMPTS_PER_CONCEPT:
                sm.worked_example_fallback(state)
                return self._teach_plan(
                    ctx,
                    session,
                    state,
                    "worked_example",
                    self._concept(concept_id),
                    events,
                )
            return self._teach_plan(
                ctx, session, state, "adapt", self._concept(concept_id), events
            )

        if ctx.action == "skip_concept":
            if sm.coverage_complete(state):
                return self._teach_plan(
                    ctx,
                    session,
                    state,
                    "harder",
                    self._concept(concept_id or ""),
                    events,
                )
            return self._plan_advance(ctx, session, state, events)

        # continue / hint / explain_directly / message
        if str(state.get("started_at_stage")) == "diagnose" and ctx.action in (
            "continue",
            "explain_directly",
        ):
            answered = len(state["diagnostic"].get("answers", {}))
            if answered < DIAGNOSTIC_ITEMS_MAX:
                diag_events = self._diagnostic_phase(ctx, state)
                if diag_events:
                    return {
                        "events": events,
                        "stage": "diagnose",
                        "teach_phase": None,
                        "diagnostic": True,
                        "diagnostic_events": diag_events,
                        "concept": None,
                        "teaching_message_id": None,
                    }
            sm.finish_diagnostic(state)
        if ctx.action == "hint":
            # Extra help while the SAME open check stays armed: teach only,
            # no decide (a second check could not be armed anyway).
            return self._teach_plan(
                ctx,
                session,
                state,
                "teach",
                self._concept(concept_id),
                events,
                decide=False,
            )
        return self._teach_plan(
            ctx, session, state, "teach", self._concept(concept_id), events
        )

    def _plan_after_correct(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        events: list[TurnEvent],
    ) -> dict[str, Any]:
        last = state.get("last_check") or {}
        concept_id = str(state.get("current_concept_id") or "")
        if self._all_concepts_have_l3(state):
            return self._teach_plan(
                ctx, session, state, "board", self._concept(concept_id), events
            )
        if sm.coverage_complete(state):
            level = min(int(last.get("level", 1)) + 1, sm.BOARD_LEVEL)
            sm.set_difficulty(state, level)
            return self._teach_plan(
                ctx, session, state, "harder", self._concept(concept_id), events
            )
        return self._plan_advance(ctx, session, state, events)

    def _plan_advance(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        events: list[TurnEvent],
    ) -> dict[str, Any]:
        next_id = sm.next_concept(state)
        if next_id is None:
            return self._teach_plan(
                ctx,
                session,
                state,
                "harder",
                self._concept(str(state.get("current_concept_id") or "")),
                events,
            )
        state["current_concept_id"] = next_id
        return self._teach_plan(
            ctx, session, state, "teach", self._concept(next_id), events
        )

    def _teach_plan(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        stage: str,
        concept: dict[str, Any],
        events: list[TurnEvent],
        *,
        decide: bool = True,
        run_teach: bool = True,
        teaching_text: str = "",
    ) -> dict[str, Any]:
        """The common plan shape: a stage transition plus a teach phase."""
        self._emit_stage_change(events, session, state, stage)
        return {
            "events": events,
            "stage": stage,
            "teach_phase": {
                "run": run_teach,
                "stage": stage,
                "decide": decide,
                "concept_id": concept.get("concept_id"),
                "teaching_text": teaching_text,
            },
            "diagnostic": False,
            "diagnostic_events": [],
            "concept": concept,
            "teaching_message_id": None,
        }

    def _finish_mastery(
        self, ctx: TurnContext, session: dict[str, Any], state: dict[str, Any]
    ) -> list[TurnEvent]:
        """Turn cap (60) or the coverage+L3 ceiling: mastery, summary, done."""
        events: list[TurnEvent] = []
        self._emit_stage_change(events, session, state, "mastery")
        summary = sm.mastery_summary(state)
        self._store.append_message(
            session_id=ctx.session_id,
            role="tutor",
            kind="summary",
            payload={"mastery": summary, "turn_count": int(state["turn_count"])},
        )
        session["stage"] = "done"
        self._emit_stage_change(events, session, state, "done")
        events.append(
            TurnEvent(
                "turn.next",
                {
                    "next_action": "finish",
                    "stage": "done",
                    "difficulty": sm.difficulty_level(state),
                },
            )
        )
        return events

    def _next_action_event(
        self, session: dict[str, Any], state: dict[str, Any]
    ) -> TurnEvent:
        """One `turn.next` meta line per turn, derived from the machine (§3.2) —
        never from the model's advisory field."""
        stage = str(session["stage"])
        if stage == "done":
            next_action = "finish"
        elif sm.open_check(state) is not None:
            next_action = "ask_check"
        else:
            next_action = {
                "harder": "raise_difficulty",
                "board": "board_level",
                "worked_example": "worked_example",
                "mastery": "finish",
            }.get(stage, "teach_more")
        return TurnEvent(
            "turn.next",
            {
                "next_action": next_action,
                "stage": stage,
                "concept_id": state.get("current_concept_id"),
                "difficulty": sm.difficulty_level(state),
            },
        )

    def _all_concepts_have_l3(self, state: dict[str, Any]) -> bool:
        concepts = state.get("concepts", {})
        targets = [c for c in concepts.values() if not c.get("skipped")]
        return bool(targets) and all(3 in c.get("levels_passed", []) for c in targets)

    # --- diagnostic phase (§4.5: bank-only, ≤ 3 items, no teach call) ------------

    def _diagnostic_phase(
        self, ctx: TurnContext, state: dict[str, Any]
    ) -> list[TurnEvent]:
        """Arm the next bank diagnostic item (≤ 3, no teach call, §4.5);
        generated diagnostics would need a model call and the bank covers the
        tracked packs, so an exhausted bank simply ends the diagnostic."""
        armed = state["diagnostic"].setdefault("item_ids", [])
        candidates = (
            self._bank.candidates(self._diagnostic_concepts(state), 1, limit=8)
            if self._bank
            else []
        )
        fresh = [c for c in candidates if str(c.get("base_item_id")) not in armed]
        if not fresh:
            return []
        item = fresh[0]
        check = self._arm_bank_check(ctx, state, item, level=1, diagnostic=True)
        if check is None:
            return []
        armed.append(str(item.get("base_item_id")))
        return [TurnEvent("turn.check", check["client"])]

    def _diagnostic_concepts(self, state: dict[str, Any]) -> list[str]:
        concepts = state.get("concepts", {})
        ordered = sorted(concepts.items(), key=lambda kv: int(kv[1].get("order", 0)))
        ids = [cid for cid, _ in ordered]
        prerequisites: list[str] = []
        for cid in ids:
            concept = self._concept(cid)
            prerequisites.extend(str(p) for p in concept.get("prerequisites", []))
        return list(dict.fromkeys(prerequisites + ids))

    # --- teach + decide phases ---------------------------------------------------

    def _teach_phase(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        phase: dict[str, Any],
        *,
        concept: dict[str, Any],
    ) -> Iterator[TurnEvent]:
        """The streaming phase: `turn.teach.start` (with the pre-generated
        anchor id) + live deltas + the decide outcome. Events are yielded as
        they happen so the student reads the slice in seconds (§3.1)."""
        stage = str(phase.get("stage", "teach"))
        with_decide = bool(phase.get("decide", True))
        run_teach = bool(phase.get("run", True))
        retrieval = self._retrieve(ctx, session, state, concept)

        def build_messages(excerpts: list[dict[str, Any]]) -> list[dict[str, str]]:
            return teach_messages(
                concept_title=str(concept.get("title", "Physics")),
                concept_description=str(concept.get("description", "")),
                stage_context=_stage_context(stage, state),
                excerpts=excerpts,
                ungrounded=retrieval["ungrounded"],
                weakness_text=session.get("weakness_text"),
                follow_up=ctx.text if ctx.action == "message" else None,
                personal_instructions=ctx.personal_instructions,
            )

        text = str(phase.get("teaching_text") or "")
        teaching_message_id = ""
        if run_teach:
            # The anchor id exists before the stream so turn.teach.start can
            # carry it; the row itself is appended once (append-only store).
            teaching_message_id = f"msg-{_uuid7_str()}"
            phase["teaching_message_id"] = teaching_message_id
            yield TurnEvent("turn.teach.start", {"message_id": teaching_message_id})
            text = yield from self._stream_teach_wrapper(ctx, build_messages, retrieval)
        paragraphs, key_statement = _split_teaching(text)
        citations, ungrounded = resolve_citations(
            _citation_ids(text), retrieval["excerpts"]
        )
        ungrounded = ungrounded or retrieval["ungrounded"]
        if concept.get("concept_id"):
            sm.record_teach_slice(state, str(concept["concept_id"]))
            if stage == "adapt":
                sm.record_adapt_variant(state, str(concept["concept_id"]))

        turn_no = int(state["turn_count"])
        payload: dict[str, Any] = {
            "schema_version": 1,
            "stage": stage,
            "turn_no": turn_no,
            "teaching": {
                "paragraphs": paragraphs,
                "key_statement": key_statement,
                "worked_example": None,
            },
            "citations": citations,
            "ungrounded": ungrounded,
            "check": None,
            "mastery": None,
            "next_action": "ask_check",
            "model": {
                "teach": self._model.model_id if self._model else None,
                "decide": self._model.model_id if self._model else None,
            },
            "rag_index_version": self._index_version(),
            "prompt_version": PROMPT_VERSION,
            "retrieval": retrieval["mode"],
        }
        client_check: dict[str, Any] | None = None
        if run_teach:
            self._store.append_message(
                session_id=ctx.session_id,
                role="tutor",
                kind="text",
                text=text,
                payload=payload,
                client_turn_id=ctx.client_turn_id,
                message_id=teaching_message_id,
            )
        if with_decide and self._model is not None:
            try:
                decide = self._decide_phase(
                    ctx, session, state, stage, concept, text, retrieval, turn_no
                )
            except DecidePending:
                raise
            except Exception as exc:
                raise DecidePending(ctx.client_turn_id, teaching_message_id) from exc
            payload["mastery"] = decide.get("mastery_payload")
            payload["next_action"] = decide.get("next_action", "ask_check")
            client_check = decide.get("client_check")
            if client_check:
                payload["check"] = {
                    k: v for k, v in client_check.items() if k != "message_event"
                }
                if run_teach:
                    # The teaching row is already persisted; keep its payload
                    # authoritative for replay by appending the check event.
                    pass
        if client_check:
            yield client_check["message_event"]
        if run_teach and client_check:
            # Same-turn payload enrichment: the assembled turn record (§5) is
            # completed before turn.done; role/kind/text/created_at never
            # change, so the append-only history semantics hold.
            self._db.execute(
                "UPDATE personalized_message SET payload = ? WHERE message_id = ?",
                (json.dumps(payload), teaching_message_id),
            )

    def _stream_teach(
        self,
        ctx: TurnContext,
        build_messages: Callable[[list[dict[str, Any]]], list[dict[str, str]]],
        retrieval: dict[str, Any],
    ) -> Iterator[str]:
        """Stream the teach call, yielding `turn.teach.delta` events live;
        one retry with a shorter excerpt set before first text (§7.5.2); after
        first text a failure fails the turn. Returns the full text."""
        assert self._model is not None
        pieces: list[str] = []
        try:
            for delta in self._model.stream(
                build_messages(retrieval["excerpts"]), session_id=ctx.session_id
            ):
                pieces.append(delta)
                yield delta
        except APIError:
            raise
        except Exception:
            if pieces:
                raise TurnModelDown() from None
            try:
                for delta in self._model.stream(
                    build_messages(retrieval["excerpts"][:TEACH_RETRY_EXCERPTS]),
                    session_id=ctx.session_id,
                ):
                    pieces.append(delta)
                    yield delta
            except APIError:
                raise
            except Exception as exc:
                raise TurnModelDown() from exc
        text = "".join(pieces).strip()
        if not text:
            raise TurnModelDown()
        return text

    def _stream_teach_wrapper(
        self,
        ctx: TurnContext,
        build_messages: Callable[[list[dict[str, Any]]], list[dict[str, str]]],
        retrieval: dict[str, Any],
    ) -> Iterator[TurnEvent]:
        """Yield deltas as `turn.teach.delta` events while delegating the
        stream/retry logic to `_stream_teach`; returns the joined text."""
        pieces: list[str] = []
        for delta in self._stream_teach(ctx, build_messages, retrieval):
            pieces.append(delta)
            yield TurnEvent("turn.teach.delta", {"text": delta})
        return "".join(pieces).strip()

    def _decide_phase(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        stage: str,
        concept: dict[str, Any],
        teaching_text: str,
        retrieval: dict[str, Any],
        turn_no: int,
    ) -> dict[str, Any]:
        assert self._model is not None
        concept_id = str(concept.get("concept_id", ""))
        level = sm.difficulty_level(state)
        candidates = self._bank.candidates([concept_id], level) if self._bank else []
        messages = decide_messages(
            concept_title=str(concept.get("title", "Physics")),
            stage_context=_stage_context(stage, state),
            teaching_text=teaching_text,
            excerpts=retrieval["excerpts"],
            ungrounded=retrieval["ungrounded"],
            bank_candidates=candidates,
            weakness_text=session.get("weakness_text"),
        )
        raw = self._model.complete_json(messages, session_id=ctx.session_id)
        client_check = self._arm_check(
            ctx, state, concept_id, level, raw.get("check"), candidates
        )
        mastery_payload = {
            "concept_id": concept_id,
            "status": _concept_status(state.get("concepts", {}).get(concept_id, {})),
            "evidence": _evidence_key(state, concept_id),
        }
        return {
            "client_check": client_check,
            "mastery_payload": mastery_payload,
            "next_action": "ask_check" if client_check else "teach_more",
        }

    # --- check arming (bank-first, §3.3/§4.4) -----------------------------------

    def _arm_check(
        self,
        ctx: TurnContext,
        state: dict[str, Any],
        concept_id: str,
        level: int,
        check_spec: dict[str, Any] | None,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Bank-first: the model picks the bank item; the server owns the key.

        - `source.kind="bank"` with a real candidate id → that bank row (its
          stored key; the model's own answer text is ignored).
        - No honored selection but candidates exist → the first candidate
          (deterministic).
        - No bank candidate → the model's generated check, shape-validated;
          its key is stored server-side only.
        - Nothing valid (or a check is already open) → None (`teach_more`).
        """
        if sm.open_check(state) is not None:
            return None
        source = (check_spec or {}).get("source") or {}
        wanted_id = source.get("item_id")
        bank_item: dict[str, Any] | None = None
        if source.get("kind") == "bank" and wanted_id and self._bank is not None:
            item = self._bank.item(str(wanted_id))
            if item is not None and str(item.get("concept_id")) == concept_id:
                bank_item = item
        if bank_item is None and candidates:
            bank_item = candidates[0]
        if bank_item is not None:
            return self._arm_bank_check(ctx, state, bank_item, level)
        if check_spec and check_spec.get("kind") in sm.CHECK_KINDS:
            return self._arm_model_check(ctx, state, concept_id, level, check_spec)
        return None

    def _arm_bank_check(
        self,
        ctx: TurnContext,
        state: dict[str, Any],
        item: dict[str, Any],
        level: int,
        *,
        diagnostic: bool = False,
    ) -> dict[str, Any] | None:
        """Arm a check from a P2 bank row; the key comes from the row."""
        kind = str(item.get("type"))
        options = [str(o) for o in (item.get("options") or [])]
        answer = item.get("answer") or {}
        check_id = f"chk-{_uuid7_str()}"
        client_payload: dict[str, Any] = {
            "check_id": check_id,
            "kind": "mcq",
            "question": str(item.get("prompt", "")),
            "level": int(level),
            "concept_id": str(item.get("concept_id", "")),
            "source": {"kind": "bank", "item_id": str(item.get("base_item_id"))},
        }
        key: dict[str, Any]
        expected: str
        if kind == "mcq":
            index = int(answer.get("index", 0))
            letter = "ABCDEFGHIJ"[index] if 0 <= index < len(options) else "A"
            client_payload["options"] = [
                {"id": "ABCDEFGHIJ"[i], "text": text} for i, text in enumerate(options)
            ]
            key = {"kind": "mcq", "option": letter}
        elif kind == "numeric":
            client_payload["kind"] = "numeric"
            unit = answer.get("unit")
            client_payload["unit"] = unit
            key = {
                "kind": "numeric",
                "value": answer.get("value", 0.0),
                "unit": unit,
                "explanation": str(item.get("explanation", "")),
                "misconception": item.get("misconception"),
            }
            f"{answer.get('value', 0.0):g} {unit or ''}".strip()
        else:
            # assertion_reason: served as the standard four-option shape
            client_payload["options"] = [
                {"id": "A", "text": "Both true; the reason explains the assertion"},
                {"id": "B", "text": "Both true; the reason does not explain it"},
                {"id": "C", "text": "Assertion false; reason true"},
                {"id": "D", "text": "Both false"},
            ]
            index = int(answer.get("index", 0))
            letter = "ABCD"[index] if 0 <= index < 4 else "A"
            key = {"kind": "mcq", "option": letter}
        key.setdefault("explanation", str(item.get("explanation", "")))
        key.setdefault("misconception", item.get("misconception"))
        sm.set_open_check(
            state,
            check_id=check_id,
            concept_id=str(item.get("concept_id", "")),
            level=int(level),
            kind=str(client_payload["kind"]),
            diagnostic=diagnostic,
        )
        self._store.append_message(
            session_id=ctx.session_id,
            role="tutor",
            kind="check",
            payload=client_payload,
            answer_key=json.dumps(key),
        )
        return {
            "client": client_payload,
            "message_event": TurnEvent("turn.check", client_payload),
        }

    def _arm_model_check(
        self,
        ctx: TurnContext,
        state: dict[str, Any],
        concept_id: str,
        level: int,
        check_spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Arm a model-generated check (only when the bank has no candidate).

        The key rides in the server-only `answer_key` column, never in the
        client payload (§2.3.3); the explanation reaches the student only in
        the post-scoring feedback.
        """
        kind = str(check_spec.get("kind"))
        question = str(check_spec.get("question", "")).strip()
        if not question or len(question) > 800:
            return None
        check_id = f"chk-{_uuid7_str()}"
        client_payload: dict[str, Any] = {
            "check_id": check_id,
            "kind": kind,
            "question": question,
            "level": int(check_spec.get("level") or level),
            "concept_id": str(check_spec.get("concept_id") or concept_id),
            "source": {"kind": "generated", "item_id": None},
        }
        key: dict[str, Any]
        if kind == "mcq":
            raw_options = check_spec.get("options") or []
            if not (2 <= len(raw_options) <= 6):
                return None
            client_payload["options"] = [
                {"id": "ABCDEFGHIJ"[i], "text": str(option.get("text", option))}
                for i, option in enumerate(raw_options)
            ]
            answer_letter = str(check_spec.get("answer", "")).strip().upper()[:1]
            if answer_letter not in [o["id"] for o in client_payload["options"]]:
                return None
            key = {"kind": "mcq", "option": answer_letter}
        else:
            value = _normalize_model_number(check_spec.get("answer"))
            if value is None:
                return None
            unit = check_spec.get("unit")
            client_payload["unit"] = unit
            key = {"kind": "numeric", "value": value, "unit": unit}
        key["explanation"] = str(check_spec.get("explanation", ""))
        key["misconception"] = check_spec.get("misconception")
        sm.set_open_check(
            state,
            check_id=check_id,
            concept_id=str(client_payload["concept_id"]),
            level=int(client_payload["level"]),
            kind=kind,
        )
        self._store.append_message(
            session_id=ctx.session_id,
            role="tutor",
            kind="check",
            payload=client_payload,
            answer_key=json.dumps(key),
        )
        return {
            "client": client_payload,
            "message_event": TurnEvent("turn.check", client_payload),
        }

    def _load_scoring_check(self, ctx: TurnContext, check_id: str) -> dict[str, Any]:
        """The open check's server-side key + explanation (never serialized)."""
        row = self._db.fetchone(
            "SELECT payload, answer_key FROM personalized_message "
            "WHERE session_id = ? AND kind = 'check' AND payload LIKE ? "
            "ORDER BY turn_index DESC",
            (ctx.session_id, f'%"{check_id}"%'),
        )
        if row is None:
            raise APIError("E-CONFLICT", status_code=409)
        payload = row.get("payload")
        payload = json.loads(payload) if isinstance(payload, str) else payload or {}
        key_raw = row.get("answer_key")
        key = json.loads(key_raw) if isinstance(key_raw, str) and key_raw else None
        if not key:
            raise APIError("E-CONFLICT", status_code=409)
        check: dict[str, Any] = {"kind": str(key["kind"])}
        if key["kind"] == "mcq":
            check["answer_key"] = str(key["option"])
        else:
            check["answer_value"] = float(key["value"])
            check["answer_unit"] = key.get("unit")
        if isinstance(ctx.answer, dict) and ctx.answer.get("unit"):
            check["given_unit"] = str(ctx.answer["unit"])
        return {
            "check": check,
            "explanation": key.get("explanation"),
            "misconception": key.get("misconception"),
            "source": payload.get("source") or {},
        }

    def _clear_answer_key(self, check_id: str) -> None:
        """Scored: the key moves into the result payload's `expected` and the
        column is set NULL (§2.3)."""
        self._db.execute(
            "UPDATE personalized_message SET answer_key = NULL "
            "WHERE kind = 'check' AND payload LIKE ?",
            (f'%"{check_id}"%',),
        )

    # --- retrieval ---------------------------------------------------------------

    def _retrieve(
        self,
        ctx: TurnContext,
        session: dict[str, Any],
        state: dict[str, Any],
        concept: dict[str, Any],
    ) -> dict[str, Any]:
        if self._retrieval.index is None:
            raise APIError("E-CONTENT-UNAVAILABLE", status_code=503, retryable=True)
        concept_id = str(concept.get("concept_id", ""))
        scope = [concept_id] + [str(p) for p in (concept.get("prerequisites") or [])]
        last = state.get("last_check") or {}
        last_wrong = ""
        if last.get("correct") is False:
            last_wrong = self._last_check_stem(ctx, str(last.get("check_id", "")))
        try:
            result = self._retrieval.index.retrieve(
                concept_title=str(concept.get("title", "Physics")),
                concept_description=str(concept.get("description", "")),
                scope_concept_ids=scope,
                chapter_id=None,
                embedder=self._retrieval.embedder,
                weakness_text=str(session.get("weakness_text") or ""),
                last_wrong_stem=last_wrong,
            )
        except EmbedderUnavailable:
            result = self._retrieval.index.retrieve(
                concept_title=str(concept.get("title", "Physics")),
                concept_description=str(concept.get("description", "")),
                scope_concept_ids=scope,
                chapter_id=None,
                embedder=None,
                weakness_text=str(session.get("weakness_text") or ""),
                last_wrong_stem=last_wrong,
            )
        self._retrieval.last_mode = result["mode"]
        self._retrieval.last_ungrounded = result["ungrounded"]
        return result

    def _last_check_stem(self, ctx: TurnContext, check_id: str) -> str:
        row = self._db.fetchone(
            "SELECT payload FROM personalized_message WHERE session_id = ? "
            "AND kind = 'check' AND payload LIKE ? ORDER BY turn_index DESC",
            (ctx.session_id, f'%"{check_id}"%'),
        )
        if row is None:
            return ""
        payload = row.get("payload")
        payload = json.loads(payload) if isinstance(payload, str) else payload or {}
        return str(payload.get("question", ""))[:200]

    def _concept(self, concept_id: str | None) -> dict[str, Any]:
        if not concept_id:
            raise APIError("E-CONFLICT", status_code=409)
        row = self._db.fetchone(
            "SELECT concept_id, title_en, description, prerequisites FROM concept "
            "WHERE concept_id = ?",
            (concept_id,),
        )
        if row is None:
            raise APIError("E-CONTENT-UNAVAILABLE", status_code=503, retryable=True)
        prerequisites = row.get("prerequisites")
        return {
            "concept_id": str(row["concept_id"]),
            "title": str(row.get("title_en") or row.get("title") or "Physics"),
            "description": str(row.get("description") or ""),
            "prerequisites": (
                json.loads(prerequisites)
                if isinstance(prerequisites, str)
                else (prerequisites or [])
            ),
        }

    def _teaching_text(self, ctx: TurnContext, message_id: str) -> str:
        if not message_id:
            return ""
        row = self._db.fetchone(
            "SELECT text FROM personalized_message WHERE session_id = ? AND message_id = ?",
            (ctx.session_id, message_id),
        )
        return str((row or {}).get("text") or "")

    def _last_teaching_message_id(self, ctx: TurnContext) -> str | None:
        row = self._db.fetchone(
            "SELECT message_id FROM personalized_message WHERE session_id = ? "
            "AND role = 'tutor' AND kind = 'text' ORDER BY turn_index DESC",
            (ctx.session_id,),
        )
        return str(row["message_id"]) if row else None


def ctx_session_id(session: dict[str, Any]) -> str:
    return str(session.get("session_id", ""))


# --- helpers ---------------------------------------------------------------------


def _stage_context(stage: str, state: dict[str, Any]) -> str:
    concepts = state.get("concepts", {})
    taught = sum(1 for c in concepts.values() if int(c.get("taught_slices", 0)) > 0)
    remaining = len(state.get("coverage", {}).get("remaining", []))
    level = sm.difficulty_level(state)
    if stage == "adapt":
        return (
            "the student missed the last check: re-teach the SAME concept with a "
            "DIFFERENT representation (a new analogy, a diagram-in-words, or a "
            "worked example), not the same wording"
        )
    if stage == "worked_example":
        return (
            "three checks were missed: show the FULL worked solution step by step; "
            "the concept is marked not-yet and the next concept follows"
        )
    if stage == "harder":
        return (
            f"coverage is complete; the student passed level {max(1, level - 1)}: give a "
            f"brief bridge (≤ 2 paragraphs) and prepare a level-{level} check"
        )
    if stage == "board":
        return (
            "board-exam style: prepare a multi-step Class 9–12 board-style item "
            "(Zivon's own, never official CBSE)"
        )
    return f"concept slices taught so far: {taught}; concepts remaining: {remaining}"


def _split_teaching(text: str) -> tuple[list[str], str | None]:
    """Paragraph split + the marked key statement (the teach ask contract)."""
    paragraphs: list[str] = []
    key_statement: str | None = None
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        if cleaned.lower().startswith("key statement:"):
            key_statement = cleaned.split(":", 1)[1].strip() or key_statement
            continue
        paragraphs.append(cleaned)
    return paragraphs, key_statement


_CITATION_RE = re.compile(r"\[(S\d+)\]")


def _citation_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in _CITATION_RE.finditer(text):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def _concept_status(concept: dict[str, Any]) -> str:
    return sm.concept_mastery_status(concept)


def _evidence_key(state: dict[str, Any], concept_id: str) -> str:
    concept = state.get("concepts", {}).get(concept_id, {})
    if int(concept.get("first_try_correct", 0)) > 0:
        return "first_try_correct"
    if int(concept.get("attempts", 0)) > 1:
        return "second_try"
    if int(concept.get("taught_slices", 0)) > 1:
        return "explained"
    return "none"


def _concept_attempts(state: dict[str, Any], concept_id: str | None) -> int:
    if not concept_id:
        return 0
    concept = state.get("concepts", {}).get(concept_id, {})
    return int(concept.get("attempts", 0))


def _normalize_model_number(raw: Any) -> float | None:
    from .state import _normalize_number

    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, str):
        return _normalize_number(raw)
    return None


def _utc_now_iso() -> str:
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _uuid7_str() -> str:
    from db.uuid7 import uuid7_str

    return uuid7_str()
