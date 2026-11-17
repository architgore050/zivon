"""Test creation, the exam-paper player, grading review, and the series catalogue (F7).

This module is the F7 domain layer. It owns the policy the store deliberately
does not: which questions a paper draws, how a custom/chapter/retry test is
built, when an attempt's clock expires, how a submitted attempt is summarised,
and what the six-series catalogue may claim while P3's volume gate has not
passed.

Rules implemented here:

- **Server-side grading only.** Answers are autosaved with `correct = NULL`;
  the key is graded by `submit_test_attempt` from `question_bank`, and the
  review shape is only returned for a submitted attempt. No route can mark a
  child right or wrong, and no player payload carries the key.
- **No negative marking.** A correct answer earns its paper marks; a wrong or
  missing answer earns zero. `submit_test_attempt` is the one scorer.
- **One live attempt per paper** (`create_test_attempt`'s DB-enforced resume).
  The player resumes the same attempt id; it never forks a second clock.
- **The clock is server-derived** from `test_attempt.started_at` +
  `test.duration_s`. An expired attempt refuses autosave (`E-TEST-EXPIRED`) and
  the page offers submit only; a late submit is still graded and records the
  real time spent. The browser timer is a display, not the authority.
- **Language is honest.** A custom test is drawn from the student's saved pack
  language; if that language has no rows it is served in English and the
  paper's `structure` records `language_fallback`. Series languages are fixed
  by the series definition (CBSE-style series are EN + HI only).
- **Series are honest.** A series with no published DB rows is "content
  pending", the Exact PYQ series is dark under `DEC-COMP-001`, and no page
  invents a paper. Generated series carry the exact `N-01` notice text.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from db.engine import DatabaseEngine

from ..assessment import (
    AssessmentError,
    Question,
    check_answer,
    count_test_questions,
    create_test_attempt,
    create_test_with_questions,
    fetch_questions,
    find_live_test_attempt,
    get_series_by_id,
    get_test,
    get_test_attempt,
    list_missed_test_question_ids,
    list_test_answers,
    list_test_attempts,
    list_test_chapters,
    list_test_questions,
    save_test_answer,
    select_question_ids,
    submit_test_attempt,
)
from ..logging_shim import ErrorClass, Severity, log_event
from ..progress import EventInput, record_events, utc_now
from .series import (
    SERIES_DEFINITIONS,
    n01_notice,
    series_by_slug,
    series_copy,
    subject_label,
)

PACK_LANGUAGE_BY_LOCALE: Final[dict[str, str]] = {
    "en": "en",
    "en-IN": "en",
    "hi": "hi",
    "hi-IN": "hi",
    "hinglish": "hi-Latn",
    "hi-Latn": "hi-Latn",
}
DEFAULT_PACK_LANGUAGE: Final[str] = "en"
LANGUAGE_LABELS: Final[dict[str, str]] = {
    "en": "English",
    "hi": "Hindi",
    "hi-Latn": "Hinglish",
}

CUSTOM_COUNT_MIN: Final[int] = 5
CUSTOM_COUNT_MAX: Final[int] = 30
CUSTOM_COUNT_DEFAULT: Final[int] = 10
CUSTOM_CHAPTER_MAX: Final[int] = 4
CHAPTER_TEST_MAX: Final[int] = 10
RETRY_LIMIT: Final[int] = 10
DURATION_MIN: Final[int] = 300
DURATION_MAX: Final[int] = 3600
DURATION_DEFAULT: Final[int] = 600
SECONDS_PER_QUESTION: Final[int] = 90
MIN_PAPER_QUESTIONS: Final[int] = 3
HISTORY_LIMIT: Final[int] = 50

DIFFICULTY_CHOICES: Final[tuple[str, ...]] = ("mixed", "easy", "medium", "hard")
DIFFICULTY_LABELS: Final[dict[str, str]] = {
    "mixed": "Mixed difficulty",
    "easy": "Easy",
    "medium": "Medium",
    "hard": "Hard",
}
QUESTION_TYPE_LABELS: Final[dict[str, str]] = {
    "mcq": "Multiple choice",
    "numeric": "Numeric answer",
    "assertion_reason": "Assertion-reason",
}
STATUS_LABELS: Final[dict[str, str]] = {
    "in_progress": "In progress",
    "submitted": "Submitted",
    "expired": "Expired",
    "abandoned": "Abandoned",
}
TEST_KIND_LABELS: Final[dict[str, str]] = {
    "custom": "Custom test",
    "chapter": "Chapter test",
    "retry": "Retry mistakes",
    "series": "Series paper",
}
SERIES_STATUS_LABELS: Final[dict[str, str]] = {
    "live": "Ready",
    "pending": "Content pending",
    "disabled": "Not available yet",
    "not_open": "Opens for Class 10 and 12",
    "choose_class": "Choose your class",
}

_DIFFICULTY_ORDER: Final[tuple[str, ...]] = ("easy", "medium", "hard")
# DEC-COMP-001: verbatim CBSE items may not reach a student while the
# clearance register is empty. The import gates should already prevent these
# rows; this is the runtime belt-and-braces check, never a silent filter.
VERBATIM_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"past_paper", "sample_paper", "curated_pyq"}
)


@dataclass(frozen=True)
class TestUser:
    """The slice of a `users` row test selection needs."""

    user_id: str
    class_level: int | None
    language: str

    @classmethod
    def from_row(cls, user: Mapping[str, Any]) -> TestUser:
        return cls(
            user_id=str(user.get("user_id") or "").strip(),
            class_level=_class_level(user.get("class_level")),
            language=pack_language(user.get("language")),
        )


def pack_language(locale: object) -> str:
    """Map a stored locale (`en-IN`, `hinglish`, …) to a pack language."""
    value = str(locale or "").strip()
    return PACK_LANGUAGE_BY_LOCALE.get(value, DEFAULT_PACK_LANGUAGE)


def test_user(user: Mapping[str, Any]) -> TestUser:
    """Public helper: build the test user from a resolved account row."""
    resolved = TestUser.from_row(user)
    if not resolved.user_id:
        raise AssessmentError("E-AUTH-REQUIRED")
    return resolved


def _class_level(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        level = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return level if 6 <= level <= 12 else None


def _clean_chapter_ids(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise AssessmentError("E-TEST-CHAPTERS")
    chapters = list(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )
    if not chapters or len(chapters) > CUSTOM_CHAPTER_MAX:
        raise AssessmentError("E-TEST-CHAPTERS")
    if any(len(item) > 120 or "/" in item for item in chapters):
        raise AssessmentError("E-TEST-CHAPTERS")
    return chapters


def _count(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        count = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AssessmentError("E-TEST-COUNT") from exc
    if count < minimum or count > maximum:
        raise AssessmentError("E-TEST-COUNT")
    return count


def _duration(value: object, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AssessmentError("E-TEST-DURATION") from exc
    if seconds < DURATION_MIN or seconds > DURATION_MAX:
        raise AssessmentError("E-TEST-DURATION")
    return seconds


def _difficulty(value: object) -> str:
    cleaned = str(value or "mixed").strip()
    if cleaned not in DIFFICULTY_CHOICES:
        raise AssessmentError("E-TEST-DIFFICULTY")
    return cleaned


# --- selection --------------------------------------------------------------


def _interleave(questions: Sequence[Question]) -> list[str]:
    """One difficulty tier at a time, easy first; id-sorted inside a tier."""
    buckets: dict[str, list[str]] = {level: [] for level in _DIFFICULTY_ORDER}
    for question in sorted(questions, key=lambda item: item.question_id):
        if question.difficulty in buckets:
            buckets[question.difficulty].append(question.question_id)
    picked: list[str] = []
    while any(buckets.values()):
        for level in _DIFFICULTY_ORDER:
            if buckets[level]:
                picked.append(buckets[level].pop(0))
    return picked


def _candidate_ids(
    db: DatabaseEngine,
    chapter_id: str,
    language: str,
    difficulty: str,
) -> list[str]:
    difficulties = None if difficulty == "mixed" else [difficulty]
    ids = select_question_ids(
        db, chapter_id, language=language, difficulties=difficulties
    )
    if not ids:
        return []
    questions = [
        question
        for question in fetch_questions(db, ids)
        if question.source_type not in VERBATIM_SOURCE_TYPES
    ]
    if difficulty == "mixed":
        return _interleave(questions)
    return [question.question_id for question in questions]


def _pick_across_chapters(
    db: DatabaseEngine,
    chapters: Sequence[str],
    language: str,
    difficulty: str,
    count: int,
) -> list[str]:
    """Round-robin across chapters, then within a chapter by difficulty."""
    per_chapter = [
        _candidate_ids(db, chapter, language, difficulty) for chapter in chapters
    ]
    picked: list[str] = []
    depth = 0
    while len(picked) < count and any(
        depth < len(candidates) for candidates in per_chapter
    ):
        for candidates in per_chapter:
            if len(picked) >= count:
                break
            if depth < len(candidates):
                picked.append(candidates[depth])
        depth += 1
    return picked


def chapter_options(db: DatabaseEngine, user: TestUser) -> dict[str, Any]:
    """Return chapters with a servable bank, in the student's language if possible."""
    rows = list_test_chapters(db, class_level=user.class_level, language=user.language)
    served = user.language
    fallback = False
    if not rows and user.language != DEFAULT_PACK_LANGUAGE:
        rows = list_test_chapters(
            db, class_level=user.class_level, language=DEFAULT_PACK_LANGUAGE
        )
        served = DEFAULT_PACK_LANGUAGE
        fallback = True
    return {
        "chapters": rows,
        "language": served,
        "requested_language": user.language,
        "language_fallback": fallback,
        "has_bank": bool(rows),
    }


def build_custom_test(
    db: DatabaseEngine,
    user: TestUser,
    *,
    source: str,
    chapter_ids: Sequence[str],
    count: int,
    difficulty: str,
    duration_s: int | None,
    title: str,
) -> dict[str, Any]:
    """Create one paper from the bank, falling back to English only when thin."""
    chapters = _clean_chapter_ids(list(chapter_ids))
    wanted = max(MIN_PAPER_QUESTIONS, min(int(count), CUSTOM_COUNT_MAX))
    served = user.language
    ids = _pick_across_chapters(db, chapters, served, difficulty, wanted)
    fallback = False
    if len(ids) < MIN_PAPER_QUESTIONS and served != DEFAULT_PACK_LANGUAGE:
        english = _pick_across_chapters(
            db, chapters, DEFAULT_PACK_LANGUAGE, difficulty, wanted
        )
        if len(english) > len(ids):
            ids = english
            served = DEFAULT_PACK_LANGUAGE
            fallback = True
    if len(ids) < MIN_PAPER_QUESTIONS:
        raise AssessmentError("E-TEST-EMPTY")
    questions = fetch_questions(db, ids)
    if duration_s is None:
        duration_s = max(DURATION_MIN, len(ids) * SECONDS_PER_QUESTION)
    entries = [
        {"question_id": question.question_id, "marks": question.marks}
        for question in questions
    ]
    structure = {
        "source": source,
        "difficulty": difficulty,
        "question_count": len(entries),
        "chapters": len(chapters),
        "requested_language": user.language,
        "language_fallback": fallback,
    }
    return create_test_with_questions(
        db,
        user.user_id,
        title=title,
        chapter_ids=chapters,
        language=served,
        duration_s=duration_s,
        questions=entries,
        structure=structure,
    )


def create_custom_test(
    db: DatabaseEngine,
    user: TestUser,
    *,
    chapter_ids: object,
    count: object = None,
    difficulty: object = None,
    duration_s: object = None,
) -> dict[str, Any]:
    """Build a student-composed test (builder page / `POST /v1/tests/custom`)."""
    chapters = _clean_chapter_ids(chapter_ids)
    wanted = _count(
        count,
        default=CUSTOM_COUNT_DEFAULT,
        minimum=CUSTOM_COUNT_MIN,
        maximum=CUSTOM_COUNT_MAX,
    )
    level = _difficulty(difficulty)
    duration = _duration(duration_s)
    return build_custom_test(
        db,
        user,
        source="custom",
        chapter_ids=chapters,
        count=wanted,
        difficulty=level,
        duration_s=duration,
        title="Custom test",
    )


def create_chapter_test(
    db: DatabaseEngine, user: TestUser, *, chapter_id: object
) -> dict[str, Any]:
    """Derive a chapter test from that chapter's bank (one chapter, mixed)."""
    return build_custom_test(
        db,
        user,
        source="chapter",
        chapter_ids=_clean_chapter_ids([chapter_id]),
        count=CHAPTER_TEST_MAX,
        difficulty="mixed",
        duration_s=None,
        title="Chapter test",
    )


def create_retry_test(db: DatabaseEngine, user: TestUser) -> dict[str, Any]:
    """Build a test from questions whose latest submitted answer was wrong."""
    ids = _retry_question_ids(db, user)
    if len(ids) < 1:
        raise AssessmentError("E-TEST-NO-MISTAKES")
    questions = [
        question
        for question in fetch_questions(db, ids)
        if question.source_type not in VERBATIM_SOURCE_TYPES
    ]
    language = user.language
    if not questions:
        raise AssessmentError("E-TEST-NO-MISTAKES")
    if all(question.language != user.language for question in questions):
        language = DEFAULT_PACK_LANGUAGE
    entries = [
        {"question_id": question.question_id, "marks": question.marks}
        for question in questions
    ]
    chapters = list(dict.fromkeys(question.chapter_id for question in questions))
    return create_test_with_questions(
        db,
        user.user_id,
        title="Retry mistakes",
        chapter_ids=chapters,
        language=language,
        duration_s=max(DURATION_MIN, len(entries) * SECONDS_PER_QUESTION),
        questions=entries,
        structure={
            "source": "retry",
            "difficulty": "mixed",
            "question_count": len(entries),
            "chapters": len(chapters),
            "requested_language": user.language,
            "language_fallback": language != user.language,
        },
    )


def _retry_question_ids(db: DatabaseEngine, user: TestUser) -> list[str]:
    ids = list_missed_test_question_ids(
        db,
        user.user_id,
        class_level=user.class_level,
        language=user.language,
        limit=RETRY_LIMIT,
    )
    if not ids and user.language != DEFAULT_PACK_LANGUAGE:
        ids = list_missed_test_question_ids(
            db,
            user.user_id,
            class_level=user.class_level,
            language=DEFAULT_PACK_LANGUAGE,
            limit=RETRY_LIMIT,
        )
    return ids


# --- attempts and the clock -------------------------------------------------


def _parse_timestamp(value: object) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _deadline(attempt: Mapping[str, Any], test: Mapping[str, Any]) -> datetime.datetime:
    started = _parse_timestamp(attempt.get("started_at")) or utc_now()
    return started + datetime.timedelta(seconds=int(test["duration_s"]))


def _remaining_s(deadline: datetime.datetime, now: datetime.datetime) -> int:
    return max(0, int((deadline - now).total_seconds()))


def _attempt_counts(
    questions: Sequence[Mapping[str, Any]],
    answers: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    answered = 0
    correct = 0
    flagged = 0
    for question in questions:
        saved = answers.get(str(question["question_id"]))
        if saved is None:
            continue
        if saved.get("flagged"):
            flagged += 1
        if saved.get("answer"):
            answered += 1
            if saved.get("correct") is True:
                correct += 1
    return {
        "question_count": len(questions),
        "answered": answered,
        "unanswered": len(questions) - answered,
        "correct": correct,
        "flagged": flagged,
    }


def _answer_map(answers: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(answer["question_id"]): answer for answer in answers}


def start_attempt(
    db: DatabaseEngine, user: TestUser, *, test_id: object
) -> dict[str, Any]:
    """Start a paper, or resume the student's one live attempt on it."""
    wanted = str(test_id or "").strip()
    test = get_test(db, wanted, user_id=user.user_id)
    if test is None:
        raise AssessmentError("E-TEST-NOT-FOUND")
    _require_published_series(db, test)
    existing = find_live_test_attempt(db, user.user_id, wanted)
    attempt = create_test_attempt(db, user.user_id, wanted)
    return {"attempt": attempt, "test": test, "resumed": existing is not None}


def _require_published_series(db: DatabaseEngine, test: Mapping[str, Any]) -> None:
    """A series paper is startable only under its own published series.

    A retired/draft series must not leak a published paper by id, and the
    verbatim Exact PYQ series stays dark under DEC-COMP-001 even if a row was
    published by mistake.
    """
    series_id = test.get("series_id")
    if not series_id:
        return
    series = get_series_by_id(db, str(series_id))
    if series is None:
        raise AssessmentError("E-TEST-NOT-FOUND")
    definition = SERIES_DEFINITIONS.get(str(series.get("kind") or ""))
    if definition is not None and definition.requires_verbatim:
        raise AssessmentError("E-TEST-CONTENT-MODE")


def start_series_paper(
    db: DatabaseEngine, user: TestUser, *, slug: str, test_id: object
) -> dict[str, Any]:
    """Start a paper only when it belongs to the series the URL names."""
    definition = series_by_slug(slug)
    if definition is None:
        raise AssessmentError("E-TEST-NOT-FOUND")
    test = get_test(db, str(test_id or "").strip(), user_id=user.user_id)
    if test is None or not test.get("series_id"):
        raise AssessmentError("E-TEST-NOT-FOUND")
    series = get_series_by_id(db, str(test["series_id"]), include_unpublished=True)
    if series is None or str(series.get("kind")) != definition.kind:
        raise AssessmentError("E-TEST-NOT-FOUND")
    return start_attempt(db, user, test_id=test["test_id"])


def attempt_state(
    db: DatabaseEngine,
    user: TestUser,
    *,
    attempt_id: str,
    question_id: str | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Return the player state; the key stays in the server's review shape only."""
    attempt = get_test_attempt(db, user.user_id, attempt_id)
    if attempt is None:
        return None
    test = get_test(
        db, attempt["test_id"], user_id=user.user_id, include_unpublished=True
    )
    if test is None:
        return None
    questions = list_test_questions(db, test["test_id"])
    if any(
        str(question.get("source_type")) in VERBATIM_SOURCE_TYPES
        for question in questions
    ):
        raise AssessmentError("E-TEST-CONTENT-MODE")
    answers = list_test_answers(db, user.user_id, attempt_id)
    by_id = _answer_map(answers)
    current = _current_index(questions, by_id, question_id)
    deadline = _deadline(attempt, test)
    moment = now or utc_now()
    remaining = _remaining_s(deadline, moment)
    submitted = attempt["status"] != "in_progress"
    return {
        "attempt": attempt,
        "test": test,
        "questions": questions,
        "answers": by_id,
        "index": current,
        "question": questions[current] if current is not None else None,
        "counts": _attempt_counts(questions, by_id),
        "deadline": deadline,
        "remaining_s": remaining,
        "expired": not submitted and remaining <= 0,
        "submitted": submitted,
        "language": test.get("language") or DEFAULT_PACK_LANGUAGE,
        "structure": test.get("structure") or {},
        "series": _series_for_test(db, test),
    }


def _current_index(
    questions: Sequence[Mapping[str, Any]],
    answers: Mapping[str, Mapping[str, Any]],
    requested: str | None,
) -> int | None:
    if not questions:
        return None
    if requested:
        for index, question in enumerate(questions):
            if str(question["question_id"]) == requested:
                return index
    for index, question in enumerate(questions):
        saved = answers.get(str(question["question_id"]))
        if saved is None or not saved.get("answer"):
            return index
    return len(questions) - 1


def _series_for_test(
    db: DatabaseEngine, test: Mapping[str, Any]
) -> dict[str, Any] | None:
    series_id = test.get("series_id")
    if not series_id:
        return None
    row = get_series_by_id(db, str(series_id), include_unpublished=True)
    if row is None:
        return None
    definition = SERIES_DEFINITIONS.get(str(row.get("kind") or ""))
    class_num = int(row.get("class_level") or 0)
    return {
        **row,
        "label": str(
            row.get("title") or (definition.label if definition else "Series")
        ),
        "slug": definition.slug if definition else None,
        "blurb": (
            series_copy(
                definition, class_num=class_num, subject=subject_label(class_num)
            )
            if definition
            else ""
        ),
        "notice": (
            n01_notice(class_num)
            if definition is not None and definition.notice_id == "N-01"
            else None
        ),
    }


def save_answer(
    db: DatabaseEngine,
    user: TestUser,
    *,
    attempt_id: str,
    question_id: object,
    answer: object = None,
    flagged: object = None,
    time_ms: object = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Autosave one answer or flag on a live, unexpired attempt."""
    state = attempt_state(db, user, attempt_id=attempt_id, now=now)
    if state is None:
        raise AssessmentError("E-TEST-ATTEMPT-NOT-FOUND")
    if state["submitted"]:
        raise AssessmentError("E-TEST-ATTEMPT-CLOSED")
    if state["expired"]:
        raise AssessmentError("E-TEST-EXPIRED")
    wanted = str(question_id or "").strip()
    question = next(
        (item for item in state["questions"] if item["question_id"] == wanted), None
    )
    if question is None:
        raise AssessmentError("E-TEST-QUESTION-UNKNOWN")
    payload = None
    if answer is not None:
        stored_question = _stored_question(db, wanted)
        check = check_answer(stored_question, _answer_object(answer))
        payload = check.stored
    flag_value = None if flagged is None else bool(flagged)
    time_value = _time_ms(time_ms)
    if payload is None and flag_value is None and time_value is None:
        raise AssessmentError("E-ANSWER-INVALID")
    saved = save_test_answer(
        db,
        user.user_id,
        attempt_id,
        question_id=wanted,
        answer=payload,
        flagged=flag_value,
        time_ms=time_value,
        now=now,
    )
    refreshed = attempt_state(db, user, attempt_id=attempt_id, now=now)
    assert refreshed is not None
    return {
        "saved": saved,
        "counts": refreshed["counts"],
        "remaining_s": refreshed["remaining_s"],
    }


def _answer_object(value: object) -> object:
    """The HTTP layer hands JSON; accept the two authored answer shapes."""
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _stored_question(db: DatabaseEngine, question_id: str) -> Question:
    questions = fetch_questions(db, [question_id])
    if not questions:
        raise AssessmentError("E-TEST-QUESTION-UNKNOWN")
    return questions[0]


def _time_ms(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        millis = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AssessmentError("E-TEST-TIME") from exc
    if millis < 0 or millis > 3_600_000:
        raise AssessmentError("E-TEST-TIME")
    return millis


def submit_attempt(
    db: DatabaseEngine,
    user: TestUser,
    *,
    attempt_id: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Grade every saved answer, close the attempt, and return its review."""
    state = attempt_state(db, user, attempt_id=attempt_id, now=now)
    if state is None:
        return None
    if not state["submitted"]:
        result = submit_test_attempt(db, user.user_id, attempt_id, now=now or utc_now())
        if result is None:
            return None
        # The graded verdicts were written by submit_test_attempt's transaction;
        # state's answer snapshot was read before grading and cannot show them.
        graded = _answer_map(list_test_answers(db, user.user_id, attempt_id))
        _record_progress(db, user, state["questions"], result, graded)
        log_event(
            "test.attempt.submitted",
            {
                "question_count": len(state["questions"]),
                "answered": state["counts"]["answered"],
                "score": result.get("score"),
                "expired": bool(state["expired"]),
            },
            severity=Severity.INFO,
        )
    return review_state(db, user, attempt_id=attempt_id)


def _record_progress(
    db: DatabaseEngine,
    user: TestUser,
    questions: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
    answers: Mapping[str, Mapping[str, Any]],
) -> None:
    """Feed F3 with one `test_submit` event per chapter (counts, never answers)."""
    by_chapter: dict[str, dict[str, int]] = {}
    for question in questions:
        chapter = str(question.get("chapter_id") or "").strip()
        if not chapter:
            continue
        entry = by_chapter.setdefault(
            chapter, {"answered": 0, "correct": 0, "total": 0}
        )
        entry["total"] += 1
        saved = answers.get(str(question["question_id"]))
        if saved is None or not saved.get("answer"):
            continue
        entry["answered"] += 1
        if saved.get("correct") is True:
            entry["correct"] += 1
    events = [
        EventInput(
            kind="test_submit",
            chapter_id=chapter,
            concept_id=None,
            question_id=None,
            payload={
                "correct": counts["correct"],
                "answered": counts["answered"],
                "total": counts["total"],
                "score": float(result.get("score") or 0.0),
            },
            occurred_at=utc_now(),
        )
        for chapter, counts in by_chapter.items()
        if counts["total"] > 0
    ]
    if not events:
        return
    try:
        record_events(db, user.user_id, events)
    except Exception:  # noqa: BLE001 - the submit is committed; the rollup is derivative
        log_event(
            "test.attempt.progress_sync_failed",
            {"reason_code": "progress_event"},
            severity=Severity.WARNING,
            error_class=ErrorClass.STORE_ERROR,
        )


# --- review -----------------------------------------------------------------


def _answer_text(question: Mapping[str, Any]) -> str:
    answer = question.get("answer") or {}
    if question.get("type") == "numeric":
        value = answer.get("value")
        unit = answer.get("unit")
        text = _number_text(value)
        return f"{text} {unit}".strip() if unit else text
    index = answer.get("index")
    options = question.get("options") or []
    if isinstance(index, int) and 0 <= index < len(options):
        return str(options[index])
    return ""


def _number_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f"{float(value):g}"


def _chosen_text(question: Mapping[str, Any], saved: Mapping[str, Any]) -> str:
    answer = saved.get("answer") or {}
    if question.get("type") == "numeric":
        value = answer.get("value")
        unit = (question.get("answer") or {}).get("unit")
        text = _number_text(value)
        if not text:
            return ""
        return f"{text} {unit}".strip() if unit else text
    index = answer.get("index")
    options = question.get("options") or []
    if isinstance(index, int) and 0 <= index < len(options):
        return str(options[index])
    return ""


def _concept_breakdown(
    questions: Sequence[Mapping[str, Any]],
    answers: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    concepts: dict[str, dict[str, Any]] = {}
    for question in questions:
        concept = str(question.get("concept_id") or "")
        entry = concepts.setdefault(
            concept, {"concept_id": concept, "answered": 0, "correct": 0, "total": 0}
        )
        entry["total"] += 1
        saved = answers.get(str(question["question_id"]))
        if saved is None or not saved.get("answer"):
            continue
        entry["answered"] += 1
        if saved.get("correct") is True:
            entry["correct"] += 1
    for entry in concepts.values():
        answered = int(entry["answered"])
        entry["accuracy_pct"] = (
            round(100.0 * int(entry["correct"]) / answered, 1) if answered else None
        )
    return sorted(concepts.values(), key=lambda item: item["concept_id"])


def _chapter_breakdown(
    questions: Sequence[Mapping[str, Any]],
    answers: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    chapters: dict[str, dict[str, Any]] = {}
    for question in questions:
        chapter = str(question.get("chapter_id") or "")
        entry = chapters.setdefault(
            chapter, {"chapter_id": chapter, "answered": 0, "correct": 0, "total": 0}
        )
        entry["total"] += 1
        saved = answers.get(str(question["question_id"]))
        if saved is None or not saved.get("answer"):
            continue
        entry["answered"] += 1
        if saved.get("correct") is True:
            entry["correct"] += 1
    for entry in chapters.values():
        answered = int(entry["answered"])
        entry["accuracy_pct"] = (
            round(100.0 * int(entry["correct"]) / answered, 1) if answered else None
        )
    return sorted(chapters.values(), key=lambda item: item["chapter_id"])


def review_state(
    db: DatabaseEngine, user: TestUser, *, attempt_id: str
) -> dict[str, Any] | None:
    """Return the graded review for a submitted attempt, or a not-submitted state."""
    attempt = get_test_attempt(db, user.user_id, attempt_id)
    if attempt is None:
        return None
    test = get_test(
        db, attempt["test_id"], user_id=user.user_id, include_unpublished=True
    )
    if test is None:
        return None
    if attempt["status"] == "in_progress":
        return {"state": "not_submitted", "attempt": attempt, "test": test}
    questions = list_test_questions(db, test["test_id"], include_answers=True)
    if any(
        str(question.get("source_type")) in VERBATIM_SOURCE_TYPES
        for question in questions
    ):
        raise AssessmentError("E-TEST-CONTENT-MODE")
    answers = _answer_map(list_test_answers(db, user.user_id, attempt_id))
    entries: list[dict[str, Any]] = []
    earned = 0.0
    possible = 0.0
    missed: list[str] = []
    time_ms = 0
    for question in questions:
        saved = answers.get(str(question["question_id"]))
        answered = bool(saved and saved.get("answer"))
        correct = bool(saved and saved.get("correct")) if answered else None
        awarded = float(saved.get("marks_awarded") or 0.0) if saved else 0.0
        possible += float(question.get("marks") or 0.0)
        earned += awarded if answered else 0.0
        if saved and saved.get("time_ms"):
            time_ms += int(saved["time_ms"])
        if answered and not correct:
            missed.append(str(question["question_id"]))
        entries.append(
            {
                **question,
                "type_label": QUESTION_TYPE_LABELS.get(
                    str(question.get("type")), "Question"
                ),
                "source_note": (
                    "Source recorded with this item."
                    if str(question.get("source_type")) in VERBATIM_SOURCE_TYPES
                    else "Written by Zivon for practice."
                ),
                "answered": answered,
                "correct": correct,
                "flagged": bool(saved.get("flagged")) if saved else False,
                "chosen": (saved or {}).get("answer") or {},
                "chosen_text": _chosen_text(question, saved or {}),
                "answer_text": _answer_text(question),
                "marks_awarded": awarded if answered else 0.0,
                "time_ms": int((saved or {}).get("time_ms") or 0),
            }
        )
    counts = _attempt_counts(questions, answers)
    accuracy = (
        round(100.0 * counts["correct"] / counts["answered"], 1)
        if counts["answered"]
        else None
    )
    return {
        "state": "review",
        "attempt": attempt,
        "test": test,
        "questions": entries,
        "counts": counts,
        "summary": {
            "score": attempt.get("score"),
            "earned": round(earned, 2),
            "possible": round(possible, 2),
            "accuracy_pct": accuracy,
            "answered": counts["answered"],
            "unanswered": counts["unanswered"],
            "correct": counts["correct"],
            "flagged": counts["flagged"],
            "time_spent_s": attempt.get("time_spent_s"),
            "answer_time_ms": time_ms,
            "missed": len(missed),
        },
        "concepts": _concept_breakdown(questions, answers),
        "chapters": _chapter_breakdown(questions, answers),
        "missed_question_ids": missed,
        "language": test.get("language") or DEFAULT_PACK_LANGUAGE,
        "series": _series_for_test(db, test),
    }


# --- history ----------------------------------------------------------------


def _test_kind(test: Mapping[str, Any] | None) -> str:
    if test is None:
        return "series"
    if test.get("series_id"):
        return "series"
    source = str((test.get("structure") or {}).get("source") or "custom")
    return source if source in TEST_KIND_LABELS else "custom"


def history(
    db: DatabaseEngine,
    user: TestUser,
    *,
    status: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Return the student's attempts, newest first, with honest filters."""
    status_filter = str(status or "").strip() or None
    kind_filter = str(kind or "").strip() or None
    if status_filter and status_filter not in STATUS_LABELS:
        status_filter = None
    if kind_filter and kind_filter not in TEST_KIND_LABELS:
        kind_filter = None
    cache: dict[str, Mapping[str, Any] | None] = {}
    items: list[dict[str, Any]] = []
    for attempt in list_test_attempts(db, user.user_id, limit=HISTORY_LIMIT):
        test_id = str(attempt["test_id"])
        if test_id not in cache:
            cache[test_id] = get_test(
                db, test_id, user_id=user.user_id, include_unpublished=True
            )
        test = cache[test_id]
        item_kind = _test_kind(test)
        item_status = str(attempt["status"])
        if status_filter and item_status != status_filter:
            continue
        if kind_filter and item_kind != kind_filter:
            continue
        series = _series_for_test(db, test) if test else None
        items.append(
            {
                **attempt,
                "title": str(test.get("title") if test else "Test"),
                "kind": item_kind,
                "kind_label": TEST_KIND_LABELS[item_kind],
                "status_label": STATUS_LABELS.get(item_status, item_status.title()),
                "series_label": (series or {}).get("label"),
                "series_slug": (series or {}).get("slug"),
                "chapter_ids": list((test or {}).get("chapter_ids") or []),
                "total_marks": (test or {}).get("total_marks"),
                "question_count": int(
                    ((test or {}).get("structure") or {}).get("question_count")
                    or count_test_questions(db, test_id)
                ),
                "notice": (series or {}).get("notice"),
            }
        )
    missed = _retry_question_ids(db, user)
    return {
        "items": items,
        "count": len(items),
        "status_filter": status_filter,
        "kind_filter": kind_filter,
        "retry": {"available": bool(missed), "count": len(missed)},
        "filters": {
            "statuses": [
                ("", "All tests"),
                ("in_progress", STATUS_LABELS["in_progress"]),
                ("submitted", STATUS_LABELS["submitted"]),
            ],
            "kinds": [
                ("", "Every kind"),
                ("chapter", TEST_KIND_LABELS["chapter"]),
                ("custom", TEST_KIND_LABELS["custom"]),
                ("series", TEST_KIND_LABELS["series"]),
                ("retry", TEST_KIND_LABELS["retry"]),
            ],
        },
    }


def format_remaining(seconds: int) -> str:
    """`mm:ss` for the timer (hours are not expected inside a 60-minute cap)."""
    value = max(0, int(seconds))
    return f"{value // 60:02d}:{value % 60:02d}"


def duration_label(seconds: int) -> str:
    minutes = max(1, int(seconds) // 60)
    return f"{minutes} min"


def marks_label(marks: object) -> str:
    try:
        value = float(str(marks))
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value):
        return ""
    whole = int(value)
    return f"{whole} mark" if whole == 1 and value == whole else f"{value:g} marks"


__all__ = [
    "CHAPTER_TEST_MAX",
    "CUSTOM_CHAPTER_MAX",
    "CUSTOM_COUNT_DEFAULT",
    "CUSTOM_COUNT_MAX",
    "CUSTOM_COUNT_MIN",
    "DIFFICULTY_CHOICES",
    "DIFFICULTY_LABELS",
    "DURATION_DEFAULT",
    "DURATION_MAX",
    "DURATION_MIN",
    "HISTORY_LIMIT",
    "LANGUAGE_LABELS",
    "PACK_LANGUAGE_BY_LOCALE",
    "QUESTION_TYPE_LABELS",
    "RETRY_LIMIT",
    "SERIES_STATUS_LABELS",
    "STATUS_LABELS",
    "TEST_KIND_LABELS",
    "VERBATIM_SOURCE_TYPES",
    "TestUser",
    "attempt_state",
    "chapter_options",
    "create_chapter_test",
    "create_custom_test",
    "create_retry_test",
    "duration_label",
    "format_remaining",
    "history",
    "marks_label",
    "pack_language",
    "review_state",
    "save_answer",
    "start_attempt",
    "start_series_paper",
    "submit_attempt",
    "test_user",
]
