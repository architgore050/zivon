"""Practice selection, state, grading hand-off, and summary (F5).

One question-bank row is one item in one language (`question_bank.question_id`
ends in the language). A session stores an immutable ordered id list, so the
player never re-selects mid-set and the answer key can only be revealed by
committing an answer through `record_practice_answer`.

Rules implemented here:

- **Selection is deterministic** for the same bank: difficulty is interleaved
  easy → medium → hard so a drill is not ten easy items in id order; Daily 5
  round-robins chapters; retry/weak drills come from the student's *unresolved*
  latest-wrong attempts only.
- **No answer key before commit.** `session_state` returns `Question.public()`
  and adds `feedback` only for a question the student already answered.
- **Language is the student's saved language** when the bank has it. When it
  does not, the set is served in English and the session config says so; the
  player tells the student instead of silently pretending.
- **First attempts feed progress.** One `practice_answer` progress event is
  written per question on its first committed attempt (not on retries), so a
  guess-until-right loop cannot inflate the dashboard's accuracy figure.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from db.engine import DatabaseEngine

from ..assessment import (
    PRACTICE_MODES,
    AssessmentError,
    Question,
    complete_practice_session,
    create_practice_session,
    fetch_question,
    fetch_questions,
    get_practice_session,
    list_missed_question_ids,
    list_practice_attempts,
    list_practice_history,
    list_weak_concept_ids,
    record_practice_answer,
    select_daily_question_ids,
    select_question_ids,
)
from ..logging_shim import ErrorClass, Severity, log_event
from ..progress import EventInput, record_events, utc_now

PACK_LANGUAGE_BY_LOCALE: Final[dict[str, str]] = {
    "en": "en",
    "en-IN": "en",
    "hi": "hi",
    "hi-IN": "hi",
    "hinglish": "hi-Latn",
    "hi-Latn": "hi-Latn",
}
DEFAULT_PACK_LANGUAGE: Final[str] = "en"

# A chapter drill is 10 items by default and never more than 20; a thinner
# chapter serves what it has and the hub shows the true count.
CHAPTER_COUNT_DEFAULT: Final[int] = 10
CHAPTER_COUNT_MIN: Final[int] = 10
CHAPTER_COUNT_MAX: Final[int] = 20
DAILY_COUNT: Final[int] = 5
RETRY_COUNT: Final[int] = 10

_DIFFICULTY_ORDER: Final[tuple[str, ...]] = ("easy", "medium", "hard")
_HISTORY_LIMIT: Final[int] = 20


@dataclass(frozen=True)
class PracticeUser:
    """The slice of a `users` row practice selection needs."""

    user_id: str
    class_level: int | None
    language: str

    @classmethod
    def from_row(cls, user: Mapping[str, Any]) -> PracticeUser:
        return cls(
            user_id=str(user.get("user_id") or "").strip(),
            class_level=_class_level(user.get("class_level")),
            language=pack_language(user.get("language")),
        )


def pack_language(locale: object) -> str:
    """Map a stored locale (`en-IN`, `hinglish`, …) to a pack language."""
    value = str(locale or "").strip()
    return PACK_LANGUAGE_BY_LOCALE.get(value, DEFAULT_PACK_LANGUAGE)


def practice_user(user: Mapping[str, Any]) -> PracticeUser:
    """Public helper: build the practice user from a resolved account row."""
    resolved = PracticeUser.from_row(user)
    if not resolved.user_id:
        raise AssessmentError("E-AUTH-REQUIRED")
    return resolved


# --- selection --------------------------------------------------------------


def _class_level(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        level = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return level if 6 <= level <= 12 else None


def _interleave(questions: Sequence[Question], count: int) -> list[str]:
    """Take up to `count` ids, one difficulty tier at a time, easy first."""
    buckets: dict[str, list[str]] = {level: [] for level in _DIFFICULTY_ORDER}
    for question in sorted(questions, key=lambda item: item.question_id):
        if question.difficulty in buckets:
            buckets[question.difficulty].append(question.question_id)
    picked: list[str] = []
    while len(picked) < count and any(buckets.values()):
        for level in _DIFFICULTY_ORDER:
            if len(picked) >= count:
                break
            if buckets[level]:
                picked.append(buckets[level].pop(0))
    return picked


def _chapter_questions(
    db: DatabaseEngine,
    chapter_id: str,
    language: str,
    *,
    concept_ids: Iterable[str] | None = None,
) -> list[Question]:
    ids = select_question_ids(
        db, chapter_id, language=language, concept_ids=concept_ids
    )
    return fetch_questions(db, ids)


def _count_for_mode(mode: str, count: int | None) -> int:
    if mode == "daily":
        if count is not None:
            raise AssessmentError("E-PRACTICE-COUNT")
        return DAILY_COUNT
    if mode == "retry_mistakes":
        if count is None:
            return RETRY_COUNT
        if not 1 <= int(count) <= RETRY_COUNT:
            raise AssessmentError("E-PRACTICE-COUNT")
        return int(count)
    if count is None:
        return CHAPTER_COUNT_DEFAULT
    if not CHAPTER_COUNT_MIN <= int(count) <= CHAPTER_COUNT_MAX:
        raise AssessmentError("E-PRACTICE-COUNT")
    return int(count)


def _chapter_id(value: object) -> str:
    chapter = str(value or "").strip()
    if not chapter:
        raise AssessmentError("E-PRACTICE-CHAPTER")
    if len(chapter) > 120:
        raise AssessmentError("E-PRACTICE-CHAPTER")
    return chapter


def _select_ids(
    db: DatabaseEngine,
    user: PracticeUser,
    mode: str,
    *,
    chapter_id: str | None,
    count: int,
) -> tuple[list[str], str, bool]:
    """Return `(ordered ids, served language, language_fallback)`."""
    requested = user.language
    if mode == "daily":
        if user.class_level is None:
            raise AssessmentError("E-PRACTICE-CLASS")
        questions = _daily_questions(db, user.class_level, requested)
        served = requested
        if not questions and requested != DEFAULT_PACK_LANGUAGE:
            questions = _daily_questions(db, user.class_level, DEFAULT_PACK_LANGUAGE)
            served = DEFAULT_PACK_LANGUAGE
        if not questions:
            raise AssessmentError("E-PRACTICE-EMPTY")
        return (
            [question.question_id for question in questions[:count]],
            served,
            served != requested,
        )

    if mode == "retry_mistakes":
        ids = list_missed_question_ids(
            db, user.user_id, language=requested, limit=RETRY_COUNT
        )
        served = requested
        if not ids and requested != DEFAULT_PACK_LANGUAGE:
            ids = list_missed_question_ids(
                db, user.user_id, language=DEFAULT_PACK_LANGUAGE, limit=RETRY_COUNT
            )
            served = DEFAULT_PACK_LANGUAGE
        if not ids:
            raise AssessmentError("E-PRACTICE-NO-MISTAKES")
        questions = fetch_questions(db, ids)
        if not questions:
            raise AssessmentError("E-PRACTICE-NO-MISTAKES")
        return (
            [question.question_id for question in questions[:count]],
            served,
            served != requested,
        )

    chapter = _chapter_id(chapter_id)
    concept_ids: list[str] | None = None
    if mode == "weak_topic":
        # Concept ids are language-independent. A student who practised in
        # English before switching the UI language must still get a weak drill.
        concept_ids = list_weak_concept_ids(
            db, user.user_id, chapter_id=chapter, language=requested
        )
        if not concept_ids and requested != DEFAULT_PACK_LANGUAGE:
            concept_ids = list_weak_concept_ids(
                db,
                user.user_id,
                chapter_id=chapter,
                language=DEFAULT_PACK_LANGUAGE,
            )
        if not concept_ids:
            raise AssessmentError("E-PRACTICE-NO-WEAK")
    questions = _chapter_questions(db, chapter, requested, concept_ids=concept_ids)
    served = requested
    if not questions and requested != DEFAULT_PACK_LANGUAGE:
        questions = _chapter_questions(
            db,
            chapter,
            DEFAULT_PACK_LANGUAGE,
            concept_ids=concept_ids,
        )
        served = DEFAULT_PACK_LANGUAGE
    if not questions:
        raise AssessmentError("E-PRACTICE-EMPTY")
    return _interleave(questions, count), served, served != requested


def _daily_questions(
    db: DatabaseEngine, class_level: int, language: str
) -> list[Question]:
    ids = select_daily_question_ids(
        db, class_level, language=language, limit=DAILY_COUNT
    )
    return fetch_questions(db, ids)


def create_session(
    db: DatabaseEngine,
    user: PracticeUser,
    *,
    mode: str,
    chapter_id: str | None = None,
    count: int | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Create one practice session over a deterministic, graded question set."""
    if mode not in PRACTICE_MODES:
        raise AssessmentError("E-PRACTICE-MODE")
    if mode in ("chapter", "weak_topic"):
        chapter = _chapter_id(chapter_id)
    else:
        chapter = None
    wanted = _count_for_mode(mode, count)
    question_ids, served, fallback = _select_ids(
        db, user, mode, chapter_id=chapter, count=wanted
    )
    config = {
        "language": served,
        "requested_language": user.language,
        "language_fallback": fallback,
    }
    return create_practice_session(
        db,
        user.user_id,
        mode=mode,
        question_ids=question_ids,
        chapter_id=chapter,
        config=config,
        now=now,
    )


# --- state ------------------------------------------------------------------


def _latest_attempts(
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for attempt in attempts:
        question_id = str(attempt["question_id"])
        current = latest.get(question_id)
        if current is None or int(attempt["attempt_no"]) >= int(current["attempt_no"]):
            latest[question_id] = attempt
    return latest


def _session_questions(
    db: DatabaseEngine, session: Mapping[str, Any]
) -> list[Question]:
    ids = [str(item) for item in session["question_ids"]]
    questions = fetch_questions(db, ids)
    if len(questions) != len(ids):
        # A session's question set is immutable and question rows are retired,
        # never deleted. A short read is a real integrity fault, not a state to
        # paper over by silently shifting the player's index.
        raise AssessmentError("E-PRACTICE-QUESTIONS")
    return questions


def _next_unanswered(
    questions: Sequence[Question],
    latest: Mapping[str, Mapping[str, Any]],
    *,
    after: int,
) -> int | None:
    for index in list(range(after + 1, len(questions))) + list(range(after + 1)):
        if questions[index].question_id not in latest:
            return index
    return None


def _question_entry(
    question: Question, latest: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    entry = question.public()
    attempt = latest.get(question.question_id)
    entry["answered"] = attempt is not None
    entry["feedback"] = (
        None
        if attempt is None
        else {
            "correct": bool(attempt["correct"]),
            "attempt_no": int(attempt["attempt_no"]),
            "chosen": dict(attempt["answer"]),
            "answer": dict(question.answer),
            "explanation": question.explanation,
            "misconception": question.misconception,
            "unit": question.answer.get("unit"),
        }
    )
    # The P2 bank has no authored hint field. Saying so is the honest state;
    # the player offers a generic, non-answer-revealing study nudge instead of
    # inventing content.
    entry["hint_available"] = False
    return entry


def session_state(
    db: DatabaseEngine,
    user_id: str,
    session_id: str,
    *,
    review_question_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the player state: progress, current question, and safe feedback."""
    session = get_practice_session(db, user_id, session_id)
    if session is None:
        return None
    questions = _session_questions(db, session)
    attempts = list_practice_attempts(db, user_id, session_id)
    latest = _latest_attempts(attempts)
    completed = session["completed_at"] is not None
    answered_count = sum(1 for question in questions if question.question_id in latest)
    index: int | None = None
    if questions and not completed:
        index = next(
            (
                position
                for position, question in enumerate(questions)
                if question.question_id not in latest
            ),
            len(questions) - 1,
        )
        review = str(review_question_id or "").strip()
        if review:
            for position, question in enumerate(questions):
                if question.question_id == review and review in latest:
                    index = position
                    break
    question_payload = (
        None
        if index is None or completed or not questions
        else _question_entry(questions[index], latest)
    )
    next_index = (
        None
        if completed or index is None
        else _next_unanswered(questions, latest, after=index)
    )
    config = session.get("config") or {}
    return {
        "session": session,
        "question_count": len(questions),
        "answered_count": answered_count,
        "correct_count": sum(
            1 for attempt in latest.values() if bool(attempt["correct"])
        ),
        "index": index,
        "question": question_payload,
        "next_index": next_index,
        "complete_available": bool(questions) and answered_count == len(questions),
        "completed": completed,
        "questions_language": str(config.get("language") or DEFAULT_PACK_LANGUAGE),
        "requested_language": str(
            config.get("requested_language") or DEFAULT_PACK_LANGUAGE
        ),
        "language_fallback": bool(config.get("language_fallback")),
    }


# --- answers ----------------------------------------------------------------


def _record_progress_event(
    db: DatabaseEngine,
    user: PracticeUser,
    question: Question,
    attempt: Mapping[str, Any],
    *,
    now: datetime.datetime,
) -> None:
    """Feed F3's mastery rules with the first attempt only (never a retry)."""
    try:
        record_events(
            db,
            user.user_id,
            [
                EventInput(
                    kind="practice_answer",
                    chapter_id=question.chapter_id,
                    concept_id=question.concept_id,
                    question_id=question.question_id,
                    payload={
                        "correct": bool(attempt["correct"]),
                        "hints_used": int(attempt["hints_used"]),
                        "time_ms": int(attempt["time_ms"]),
                    },
                    occurred_at=now,
                )
            ],
        )
    except Exception:  # noqa: BLE001 - the answer is committed; the rollup is derivative
        log_event(
            "practice.answer.progress_sync_failed",
            {"reason_code": "progress_event"},
            severity=Severity.WARNING,
            error_class=ErrorClass.STORE_ERROR,
        )


def submit_answer(
    db: DatabaseEngine,
    user: PracticeUser,
    session_id: str,
    *,
    question_id: str,
    answer: Any,
    time_ms: int = 0,
    hints_used: int = 0,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Grade and record one answer; return feedback plus the next pointer."""
    session = get_practice_session(db, user.user_id, session_id)
    if session is None:
        return None
    if session["completed_at"] is not None:
        raise AssessmentError("E-PRACTICE-CLOSED")
    attempt = record_practice_answer(
        db,
        user.user_id,
        session_id,
        question_id=question_id,
        answer=answer,
        time_ms=time_ms,
        hints_used=hints_used,
        now=now,
    )
    question = fetch_question(db, question_id)
    if question is None:
        raise AssessmentError("E-PRACTICE-QUESTION-UNKNOWN")
    moment = now or utc_now()
    if int(attempt["attempt_no"]) == 1:
        _record_progress_event(db, user, question, attempt, now=moment)
    state = session_state(db, user.user_id, session_id)
    assert state is not None  # the session was just read inside the same request
    next_index = (
        None
        if state["complete_available"] or state["index"] is None
        else int(state["index"])
    )
    return {
        "attempt": attempt,
        "feedback": {
            "question_id": question.question_id,
            "concept_id": question.concept_id,
            "correct": bool(attempt["correct"]),
            "answer": dict(question.answer),
            "explanation": question.explanation,
            "misconception": question.misconception,
            "unit": question.answer.get("unit"),
        },
        "answered_count": state["answered_count"],
        "correct_count": state["correct_count"],
        "question_count": state["question_count"],
        "next_index": next_index,
        "complete_available": state["complete_available"],
    }


def complete_session(
    db: DatabaseEngine,
    user: PracticeUser,
    session_id: str,
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Close the set once, scoring it by latest-attempt question accuracy."""
    session = get_practice_session(db, user.user_id, session_id)
    if session is None:
        return None
    if session["completed_at"] is None:
        attempts = list_practice_attempts(db, user.user_id, session_id)
        latest = _latest_attempts(attempts)
        answered = len(latest)
        correct = sum(1 for attempt in latest.values() if bool(attempt["correct"]))
        score = round(100.0 * correct / answered, 2) if answered else 0.0
        closed = complete_practice_session(
            db, user.user_id, session_id, score=score, now=now
        )
        if closed is None:
            return None
    return session_summary(db, user.user_id, session_id)


def session_summary(
    db: DatabaseEngine, user_id: str, session_id: str
) -> dict[str, Any] | None:
    """Return score, accuracy, time, hints, and a per-concept breakdown."""
    session = get_practice_session(db, user_id, session_id)
    if session is None:
        return None
    questions = _session_questions(db, session)
    attempts = list_practice_attempts(db, user_id, session_id)
    latest = _latest_attempts(attempts)
    first = {
        str(attempt["question_id"]): attempt
        for attempt in attempts
        if int(attempt["attempt_no"]) == 1
    }
    concepts: dict[str, dict[str, Any]] = {}
    for question in questions:
        entry = concepts.setdefault(
            question.concept_id,
            {
                "concept_id": question.concept_id,
                "answered": 0,
                "correct": 0,
                "accuracy_pct": None,
            },
        )
        attempt = latest.get(question.question_id)
        if attempt is None:
            continue
        entry["answered"] += 1
        entry["correct"] += 1 if bool(attempt["correct"]) else 0
    for entry in concepts.values():
        answered = int(entry["answered"])
        entry["accuracy_pct"] = (
            round(100.0 * int(entry["correct"]) / answered, 1) if answered else None
        )

    answered_count = len(latest)
    correct_count = sum(1 for attempt in latest.values() if bool(attempt["correct"]))
    first_correct = sum(1 for attempt in first.values() if bool(attempt["correct"]))
    return {
        "session": session,
        "summary": {
            "answered_count": answered_count,
            "question_count": len(questions),
            "unanswered_count": len(questions) - answered_count,
            "correct_count": correct_count,
            "accuracy_pct": (
                round(100.0 * correct_count / answered_count, 1)
                if answered_count
                else None
            ),
            "first_attempt_answered": len(first),
            "first_attempt_correct": first_correct,
            "first_attempt_accuracy_pct": (
                round(100.0 * first_correct / len(first), 1) if first else None
            ),
            "score": session["score"],
            "time_ms": sum(int(attempt["time_ms"]) for attempt in attempts),
            "hints_used": sum(int(attempt["hints_used"]) for attempt in attempts),
            "concepts": list(concepts.values()),
        },
    }


def history(
    db: DatabaseEngine, user_id: str, *, limit: int = _HISTORY_LIMIT
) -> list[dict[str, Any]]:
    """Return the student's recent sessions, newest first."""
    return list_practice_history(db, user_id, limit=limit)


__all__ = [
    "CHAPTER_COUNT_DEFAULT",
    "CHAPTER_COUNT_MAX",
    "CHAPTER_COUNT_MIN",
    "DAILY_COUNT",
    "PACK_LANGUAGE_BY_LOCALE",
    "RETRY_COUNT",
    "PracticeUser",
    "complete_session",
    "create_session",
    "history",
    "pack_language",
    "practice_user",
    "session_state",
    "session_summary",
    "submit_answer",
]
