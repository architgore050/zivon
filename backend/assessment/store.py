"""Persistence for the W4 practice, speaking, and test tables (db-spec §4.19).

One data layer shared by F5 (practice), F6 (speaking), and F7 (tests/series):
the pack importer writes `question_bank` / `speaking_prompt` /
`topic_time_prior`, and the feature routes read them and write learner rows
through the functions here. Routes, scoring *policy* (negative marking, section
rules, adaptive selection) and UI belong to the owning feature; this module
owns the SQL, the shape of a stored row, and the one answer grader both F5 and
F7 would otherwise re-implement.

Rules this module enforces (db-spec §4.19, REQUIREMENTS §8.3/§9.5):

- every learner read/write is scoped by `user_id`; a cross-account id reads as
  "not found", never as somebody else's row;
- `speaking_attempt` has no audio column at all, transcript text and the
  rubric/feedback/self-check JSON are bounded, and an attempt may only be
  recorded against a currently served prompt (a draft or retired prompt cannot
  become an answer-material oracle); raw audio is never persisted anywhere;
- question rows are served without the answer key (`Question.public()`); the
  review shape (`Question.review()`) is server-side only. A practice or test
  player must not ship the answer to the child before they answer.
"""

from __future__ import annotations

import datetime
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from db.engine import DatabaseEngine
from db.uuid7 import uuid7_str

from ..progress.store import as_utc, to_iso, utc_now

QUESTION_TYPES: Final[frozenset[str]] = frozenset(
    {"mcq", "numeric", "assertion_reason"}
)
DIFFICULTIES: Final[frozenset[str]] = frozenset({"easy", "medium", "hard"})
PACK_LANGUAGES: Final[frozenset[str]] = frozenset({"en", "hi", "hi-Latn"})
PRACTICE_MODES: Final[frozenset[str]] = frozenset(
    {"chapter", "daily", "weak_topic", "retry_mistakes"}
)
SERIES_KINDS: Final[frozenset[str]] = frozenset(
    {"ai_lesson", "pyq_pattern", "exact_pyq", "board_practice", "challenge", "loop"}
)
# A question is servable once its pack passed the deterministic gate ("reviewed")
# or a later review promoted it ("published"). `draft` and `retired` never serve.
SERVED_STATUSES: Final[tuple[str, str]] = ("reviewed", "published")

MAX_QUESTION_IDS: Final[int] = 200
MAX_TRANSCRIPT_CHARS: Final[int] = 4000
MAX_JSON_CHARS: Final[int] = 2000
HISTORY_LIMIT: Final[int] = 50

_NUMERIC_EPSILON: Final[float] = 1e-9


class AssessmentError(ValueError):
    """A stored-data or request defect the route turns into a coded 4xx/5xx.

    `code` is the stable string a route maps to `APIError` (e.g.
    `E-PRACTICE-NOT-FOUND`); it is never a message shown to a child.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Question:
    """One stored `question_bank` row (one item, one language)."""

    question_id: str
    base_item_id: str
    class_level: int
    chapter_id: str
    concept_id: str
    type: str
    difficulty: str
    marks: float
    language: str
    source_type: str
    source_ref: dict[str, Any]
    prompt: str
    options: list[Any]
    answer: dict[str, Any]
    explanation: str
    misconception: str | None
    expected_time_ms: int | None
    status: str
    version: int

    def public(self) -> dict[str, Any]:
        """The player shape: no answer, explanation, or distractor rationale."""
        return {
            "question_id": self.question_id,
            "chapter_id": self.chapter_id,
            "concept_id": self.concept_id,
            "type": self.type,
            "difficulty": self.difficulty,
            "marks": self.marks,
            "language": self.language,
            "prompt": self.prompt,
            "options": list(self.options),
            "expected_time_ms": self.expected_time_ms,
        }

    def review(self) -> dict[str, Any]:
        """The post-answer shape, including the key and the explanation."""
        return {
            **self.public(),
            "answer": dict(self.answer),
            "explanation": self.explanation,
            "misconception": self.misconception,
            "source_type": self.source_type,
            "source_ref": dict(self.source_ref),
            "version": self.version,
        }


@dataclass(frozen=True)
class AnswerCheck:
    """A stored answer plus its deterministic correctness verdict."""

    correct: bool
    stored: dict[str, Any]


# --- JSON / validation helpers ---------------------------------------------


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return default
        return parsed
    return default


def _json_object(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    loaded = _load(value, default if default is not None else {})
    return (
        loaded if isinstance(loaded, dict) else (default if default is not None else {})
    )


def _json_array(value: Any) -> list[Any]:
    loaded = _load(value, [])
    return loaded if isinstance(loaded, list) else []


def _language(value: object) -> str:
    cleaned = str(value or "").strip()
    if cleaned not in PACK_LANGUAGES:
        raise AssessmentError("E-LANGUAGE-INVALID")
    return cleaned


def _require_user(user_id: object) -> str:
    cleaned = str(user_id or "").strip()
    if not cleaned:
        raise AssessmentError("E-AUTH-REQUIRED")
    return cleaned


def _bounded_payload(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AssessmentError(code)
    payload = dict(value)
    if len(_dumps(payload)) > MAX_JSON_CHARS:
        raise AssessmentError(code)
    return payload


def _check_question_ids(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AssessmentError("E-PRACTICE-QUESTIONS")
    ids = [str(item).strip() for item in value]
    unique = list(dict.fromkeys(ids))
    if not all(unique) or len(unique) > MAX_QUESTION_IDS:
        raise AssessmentError("E-PRACTICE-QUESTIONS")
    return unique


def _unique_violation(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "unique constraint failed" in message
        or "duplicate key" in message
        or getattr(exc, "sqlstate", "") == "23505"
    )


# --- question bank ----------------------------------------------------------


def _question_from_row(row: Mapping[str, Any]) -> Question:
    expected = row.get("expected_time_ms")
    return Question(
        question_id=str(row["question_id"]),
        base_item_id=str(row["base_item_id"]),
        class_level=int(row["class_level"]),
        chapter_id=str(row["chapter_id"]),
        concept_id=str(row["concept_id"]),
        type=str(row["type"]),
        difficulty=str(row["difficulty"]),
        marks=float(row["marks"]),
        language=str(row["language"]),
        source_type=str(row["source_type"]),
        source_ref=_json_object(row.get("source_ref")),
        prompt=str(row["prompt"]),
        options=_json_array(row.get("options")),
        answer=_json_object(row.get("answer")),
        explanation=str(row.get("explanation") or ""),
        misconception=row.get("misconception"),
        expected_time_ms=int(expected) if expected is not None else None,
        status=str(row.get("status") or "draft"),
        version=int(row.get("version") or 1),
    )


def fetch_question(db: DatabaseEngine, question_id: str) -> Question | None:
    """Return one question row, or None when the id is unknown."""
    wanted = str(question_id or "").strip()
    if not wanted:
        return None
    row = db.fetchone("SELECT * FROM question_bank WHERE question_id = ?", (wanted,))
    return _question_from_row(row) if row else None


def fetch_questions(db: DatabaseEngine, question_ids: Sequence[str]) -> list[Question]:
    """Return the requested questions in request order; unknown ids are skipped."""
    wanted = [str(item) for item in question_ids][:MAX_QUESTION_IDS]
    if not wanted:
        return []
    placeholders = ", ".join("?" for _ in wanted)
    rows = db.fetchall(
        f"SELECT * FROM question_bank WHERE question_id IN ({placeholders})",
        tuple(wanted),
    )
    by_id = {str(row["question_id"]): _question_from_row(row) for row in rows}
    return [by_id[item] for item in wanted if item in by_id]


def select_question_ids(
    db: DatabaseEngine,
    chapter_id: str,
    *,
    language: str = "en",
    concept_ids: Iterable[str] | None = None,
    difficulties: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    """Return servable question ids for a chapter, ordered by question id.

    Selection *policy* (shuffle seed, difficulty mix, adaptive order) belongs to
    the practice route; this is the deterministic candidate set.
    """
    chapter = str(chapter_id or "").strip()
    if not chapter:
        raise AssessmentError("E-PRACTICE-CHAPTER")
    lang = _language(language)
    clauses = ["chapter_id = ?", "language = ?", "status IN (?, ?)"]
    params: list[Any] = [chapter, lang, *SERVED_STATUSES]
    concepts = list(
        dict.fromkeys(str(item) for item in (concept_ids or []) if str(item).strip())
    )
    if len(concepts) > MAX_QUESTION_IDS:
        raise AssessmentError("E-PRACTICE-CONCEPTS")
    if concepts:
        clauses.append(f"concept_id IN ({', '.join('?' for _ in concepts)})")
        params.extend(concepts)
    levels = list(
        dict.fromkeys(str(item) for item in (difficulties or []) if str(item).strip())
    )
    if levels:
        unknown = [level for level in levels if level not in DIFFICULTIES]
        if unknown:
            raise AssessmentError("E-DIFFICULTY-INVALID")
        clauses.append(f"difficulty IN ({', '.join('?' for _ in levels)})")
        params.extend(levels)
    sql = (
        "SELECT question_id FROM question_bank WHERE "
        + " AND ".join(clauses)
        + " ORDER BY question_id"
    )
    if limit is not None:
        if int(limit) <= 0:
            raise AssessmentError("E-PRACTICE-QUESTIONS")
        sql += " LIMIT ?"
        params.append(min(int(limit), MAX_QUESTION_IDS))
    return [str(row["question_id"]) for row in db.fetchall(sql, tuple(params))]


def check_answer(question: Question, raw_answer: Any) -> AnswerCheck:
    """Grade one answer deterministically; returns the canonical stored shape.

    MCQ and assertion-reason items are graded by option index; numeric items by
    value within the authored tolerance. Anything else is a malformed answer,
    not a wrong one: the route must reject it rather than mark the child wrong.
    """
    if question.type == "numeric":
        answer = (
            raw_answer.get("value") if isinstance(raw_answer, Mapping) else raw_answer
        )
        if isinstance(answer, bool) or not isinstance(answer, (int, float)):
            raise AssessmentError("E-ANSWER-INVALID")
        value = float(answer)
        if not math.isfinite(value):
            raise AssessmentError("E-ANSWER-INVALID")
        expected = question.answer.get("value")
        tolerance = question.answer.get("tolerance", 0)
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            raise AssessmentError("E-ANSWER-KEY-INVALID")
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
            raise AssessmentError("E-ANSWER-KEY-INVALID")
        correct = (
            abs(value - float(expected)) <= abs(float(tolerance)) + _NUMERIC_EPSILON
        )
        return AnswerCheck(correct=correct, stored={"value": value})

    if question.type in ("mcq", "assertion_reason"):
        answer = (
            raw_answer.get("index") if isinstance(raw_answer, Mapping) else raw_answer
        )
        if isinstance(answer, bool) or not isinstance(answer, int):
            raise AssessmentError("E-ANSWER-INVALID")
        if answer < 0 or answer >= len(question.options):
            raise AssessmentError("E-ANSWER-INVALID")
        expected_index = question.answer.get("index")
        if isinstance(expected_index, bool) or not isinstance(expected_index, int):
            raise AssessmentError("E-ANSWER-KEY-INVALID")
        return AnswerCheck(correct=answer == expected_index, stored={"index": answer})

    raise AssessmentError("E-QUESTION-TYPE")


# --- practice (F5) ----------------------------------------------------------


def _practice_session_public(row: Mapping[str, Any]) -> dict[str, Any]:
    completed = as_utc(row.get("completed_at"))
    score = row.get("score")
    return {
        "session_id": str(row["session_id"]),
        "mode": str(row["mode"]),
        "chapter_id": row.get("chapter_id"),
        "question_ids": [str(item) for item in _json_array(row.get("question_ids"))],
        "question_count": int(row.get("question_count") or 0),
        "config": _json_object(row.get("config")),
        "score": float(score) if score is not None else None,
        "started_at": to_iso(as_utc(row.get("started_at")) or utc_now()),
        "completed_at": to_iso(completed) if completed else None,
    }


def _practice_attempt_public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "attempt_id": str(row["attempt_id"]),
        "question_id": str(row["question_id"]),
        "answer": _json_object(row.get("answer")),
        "correct": bool(row["correct"]),
        "time_ms": int(row.get("time_ms") or 0),
        "hints_used": int(row.get("hints_used") or 0),
        "attempt_no": int(row.get("attempt_no") or 1),
        "created_at": to_iso(as_utc(row.get("created_at")) or utc_now()),
    }


def create_practice_session(
    db: DatabaseEngine,
    user_id: str,
    *,
    mode: str,
    question_ids: Sequence[str],
    chapter_id: str | None = None,
    config: Mapping[str, Any] | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Create a practice session over an immutable, ordered question set."""
    owner = _require_user(user_id)
    if mode not in PRACTICE_MODES:
        raise AssessmentError("E-PRACTICE-MODE")
    ids = _check_question_ids(list(question_ids))
    chapter = str(chapter_id or "").strip() or None
    payload = _bounded_payload(config or {}, "E-PRACTICE-CONFIG")
    session_id = uuid7_str()
    started = to_iso(now or utc_now())
    db.execute(
        """
        INSERT INTO practice_session (
            session_id, user_id, mode, chapter_id, question_ids,
            question_count, config, started_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            owner,
            mode,
            chapter,
            _dumps(ids),
            len(ids),
            _dumps(payload),
            started,
        ),
    )
    row = db.fetchone(
        "SELECT * FROM practice_session WHERE session_id = ?", (session_id,)
    )
    assert row is not None
    return _practice_session_public(row)


def get_practice_session(
    db: DatabaseEngine, user_id: str, session_id: str
) -> dict[str, Any] | None:
    """Return one session scoped to its owner, or None."""
    row = db.fetchone(
        "SELECT * FROM practice_session WHERE session_id = ? AND user_id = ?",
        (str(session_id), _require_user(user_id)),
    )
    return _practice_session_public(row) if row else None


def list_practice_attempts(
    db: DatabaseEngine, user_id: str, session_id: str
) -> list[dict[str, Any]]:
    """Return the answers recorded so far, oldest first (owner-scoped)."""
    rows = db.fetchall(
        """
        SELECT pa.* FROM practice_attempt pa
        JOIN practice_session ps ON ps.session_id = pa.session_id
        WHERE ps.session_id = ? AND ps.user_id = ?
        ORDER BY pa.created_at, pa.attempt_no
        """,
        (str(session_id), _require_user(user_id)),
    )
    return [_practice_attempt_public(row) for row in rows]


def record_practice_answer(
    db: DatabaseEngine,
    user_id: str,
    session_id: str,
    *,
    question_id: str,
    answer: Mapping[str, Any],
    time_ms: int = 0,
    hints_used: int = 0,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Grade and append one answer to a session the caller owns.

    The correctness verdict is computed here (`check_answer`) from the stored
    question, never accepted from the caller: a route must not be able to mark a
    child right or wrong, and F5/F7 do not each re-implement grading.
    """
    owner = _require_user(user_id)
    if not 0 <= int(time_ms) <= 3_600_000:
        raise AssessmentError("E-PRACTICE-TIME")
    if not 0 <= int(hints_used) <= 20:
        raise AssessmentError("E-PRACTICE-HINTS")
    payload = _bounded_payload(answer, "E-ANSWER-INVALID")
    with db.transaction() as tx:
        session = tx.fetchone(
            "SELECT session_id, question_ids, completed_at FROM practice_session "
            "WHERE session_id = ? AND user_id = ?",
            (str(session_id), owner),
        )
        if session is None:
            raise AssessmentError("E-PRACTICE-NOT-FOUND")
        if session.get("completed_at"):
            raise AssessmentError("E-PRACTICE-CLOSED")
        set_ids = [str(item) for item in _json_array(session.get("question_ids"))]
        if str(question_id) not in set_ids:
            raise AssessmentError("E-PRACTICE-QUESTION-UNKNOWN")
        question_row = tx.fetchone(
            "SELECT * FROM question_bank WHERE question_id = ?", (str(question_id),)
        )
        if question_row is None:
            raise AssessmentError("E-PRACTICE-QUESTION-UNKNOWN")
        check = check_answer(_question_from_row(question_row), payload)
        payload = check.stored
        previous = tx.fetchone(
            "SELECT COALESCE(MAX(attempt_no), 0) AS last FROM practice_attempt "
            "WHERE session_id = ? AND question_id = ?",
            (str(session_id), str(question_id)),
        )
        attempt_no = int((previous or {}).get("last") or 0) + 1
        attempt_id = uuid7_str()
        try:
            tx.execute(
                """
                INSERT INTO practice_attempt (
                    attempt_id, session_id, question_id, answer, correct,
                    time_ms, hints_used, attempt_no, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    str(session_id),
                    str(question_id),
                    _dumps(payload),
                    bool(check.correct),
                    int(time_ms),
                    int(hints_used),
                    attempt_no,
                    to_iso(now or utc_now()),
                ),
            )
        except Exception as exc:  # mapped below; never swallowed
            if _unique_violation(exc):
                raise AssessmentError("E-PRACTICE-CONFLICT") from exc
            raise
        row = tx.fetchone(
            "SELECT * FROM practice_attempt WHERE attempt_id = ?", (attempt_id,)
        )
    assert row is not None
    return _practice_attempt_public(row)


def complete_practice_session(
    db: DatabaseEngine,
    user_id: str,
    session_id: str,
    *,
    score: float | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Close a session once (idempotent); defaults to answered-question accuracy."""
    owner = _require_user(user_id)
    with db.transaction() as tx:
        session = tx.fetchone(
            "SELECT * FROM practice_session WHERE session_id = ? AND user_id = ?",
            (str(session_id), owner),
        )
        if session is None:
            return None
        if session.get("completed_at"):
            return _practice_session_public(session)
        if score is None:
            counted = tx.fetchone(
                "SELECT COUNT(*) AS answered, "
                "COALESCE(SUM(CASE WHEN correct THEN 1 ELSE 0 END), 0) AS correct "
                "FROM practice_attempt WHERE session_id = ?",
                (str(session_id),),
            )
            answered = int((counted or {}).get("answered") or 0)
            correct = int((counted or {}).get("correct") or 0)
            score = round(100.0 * correct / answered, 2) if answered else 0.0
        value = float(score)
        if not 0.0 <= value <= 100.0:
            raise AssessmentError("E-PRACTICE-SCORE")
        tx.execute(
            "UPDATE practice_session SET score = ?, completed_at = ? "
            "WHERE session_id = ? AND user_id = ?",
            (value, to_iso(now or utc_now()), str(session_id), owner),
        )
        row = tx.fetchone(
            "SELECT * FROM practice_session WHERE session_id = ?", (str(session_id),)
        )
    assert row is not None
    return _practice_session_public(row)


def list_practice_history(
    db: DatabaseEngine, user_id: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Return the owner's recent sessions, newest first."""
    rows = db.fetchall(
        "SELECT * FROM practice_session WHERE user_id = ? "
        "ORDER BY started_at DESC, session_id DESC LIMIT ?",
        (_require_user(user_id), _history_limit(limit)),
    )
    return [_practice_session_public(row) for row in rows]


def list_practice_chapters(
    db: DatabaseEngine, *, language: str = "en"
) -> list[dict[str, Any]]:
    """Return chapters that currently have servable questions, with counts.

    The practice hub lists what can actually be practised instead of every
    catalogue chapter: a chapter with no imported bank is absent here, never a
    dead Start button.
    """
    lang = _language(language)
    rows = db.fetchall(
        """
        SELECT chapter_id, MIN(class_level) AS class_level,
               COUNT(*) AS question_count
        FROM question_bank
        WHERE language = ? AND status IN (?, ?)
        GROUP BY chapter_id
        ORDER BY MIN(class_level), chapter_id
        """,
        (lang, *SERVED_STATUSES),
    )
    return [
        {
            "chapter_id": str(row["chapter_id"]),
            "class_level": int(row["class_level"]),
            "question_count": int(row["question_count"]),
        }
        for row in rows
    ]


def select_daily_question_ids(
    db: DatabaseEngine,
    class_level: int,
    *,
    language: str = "en",
    limit: int = 5,
) -> list[str]:
    """Return a class-level set spread across chapters, one per chapter a pass.

    A Daily 5 should not be five questions from the first chapter in id order;
    this round-robins the chapters so a class with two imported chapters gets
    both. Selection is deterministic for the same bank.
    """
    level = int(class_level)
    if level < 6 or level > 12:
        raise AssessmentError("E-PRACTICE-CLASS")
    lang = _language(language)
    wanted = int(limit)
    if wanted <= 0:
        raise AssessmentError("E-PRACTICE-QUESTIONS")
    rows = db.fetchall(
        """
        SELECT question_id, chapter_id FROM question_bank
        WHERE class_level = ? AND language = ? AND status IN (?, ?)
        ORDER BY chapter_id, question_id
        """,
        (level, lang, *SERVED_STATUSES),
    )
    by_chapter: dict[str, list[str]] = {}
    for row in rows:
        by_chapter.setdefault(str(row["chapter_id"]), []).append(
            str(row["question_id"])
        )
    picked: list[str] = []
    depth = 0
    while len(picked) < wanted:
        added = False
        for chapter_ids in by_chapter.values():
            if len(picked) >= wanted:
                break
            if depth < len(chapter_ids):
                picked.append(chapter_ids[depth])
                added = True
        if not added:
            break
        depth += 1
    return picked


def list_missed_question_ids(
    db: DatabaseEngine,
    user_id: str,
    *,
    language: str = "en",
    chapter_id: str | None = None,
    limit: int = 20,
) -> list[str]:
    """Return questions whose **latest** attempt is wrong, newest first.

    Retry means "still unresolved", not "was ever wrong": a question answered
    wrong once and then right does not come back. Ids are deduplicated across
    sessions so one item cannot fill a retry set twice. `chapter_id` filters on
    the question's own chapter, not on the session that carried the attempt: a
    retry/weak session stores no chapter, so a session-based filter would hide a
    miss the student made inside one.
    """
    owner = _require_user(user_id)
    lang = _language(language)
    params: list[Any] = [owner, False, lang, *SERVED_STATUSES]
    chapter = str(chapter_id or "").strip()
    chapter_clause = ""
    if chapter:
        chapter_clause = " AND q.chapter_id = ?"
        params.append(chapter)
    rows = db.fetchall(
        """
        SELECT q.question_id AS question_id
        FROM (
            SELECT pa.session_id AS session_id,
                   pa.question_id AS question_id,
                   pa.correct AS correct,
                   pa.created_at AS created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY pa.question_id
                       ORDER BY pa.created_at DESC, pa.attempt_id DESC
                   ) AS rn
            FROM practice_attempt pa
            JOIN practice_session session
              ON session.session_id = pa.session_id
            WHERE session.user_id = ?
        ) latest
        JOIN question_bank q ON q.question_id = latest.question_id
        WHERE latest.rn = 1 AND latest.correct = ?
          AND q.language = ? AND q.status IN (?, ?)"""
        + chapter_clause
        + " ORDER BY latest.created_at DESC",
        tuple(params),
    )
    wanted = _history_limit(limit)
    picked: list[str] = []
    seen: set[str] = set()
    for row in rows:
        question_id = str(row["question_id"])
        if question_id in seen:
            continue
        seen.add(question_id)
        picked.append(question_id)
        if len(picked) >= wanted:
            break
    return picked


def list_weak_concept_ids(
    db: DatabaseEngine,
    user_id: str,
    *,
    chapter_id: str,
    language: str = "en",
    limit: int = 10,
) -> list[str]:
    """Return the chapter's concepts with the most unresolved misses, worst first."""
    owner = _require_user(user_id)
    lang = _language(language)
    chapter = str(chapter_id or "").strip()
    if not chapter:
        raise AssessmentError("E-PRACTICE-CHAPTER")
    rows = db.fetchall(
        """
        SELECT q.concept_id AS concept_id, COUNT(*) AS missed
        FROM (
            SELECT pa.session_id AS session_id,
                   pa.question_id AS question_id,
                   pa.correct AS correct,
                   pa.created_at AS created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY pa.question_id
                       ORDER BY pa.created_at DESC, pa.attempt_id DESC
                   ) AS rn
            FROM practice_attempt pa
            JOIN practice_session session
              ON session.session_id = pa.session_id
            WHERE session.user_id = ?
        ) latest
        JOIN practice_session ps ON ps.session_id = latest.session_id
        JOIN question_bank q ON q.question_id = latest.question_id
        WHERE latest.rn = 1 AND latest.correct = ?
          AND q.language = ? AND q.status IN (?, ?)
          AND q.chapter_id = ?
        GROUP BY q.concept_id
        ORDER BY missed DESC, q.concept_id
        LIMIT ?
        """,
        (owner, False, lang, *SERVED_STATUSES, chapter, _history_limit(limit)),
    )
    return [str(row["concept_id"]) for row in rows]


# --- speaking (F6) ----------------------------------------------------------


def _speaking_prompt_public(
    row: Mapping[str, Any], *, include_answer: bool
) -> dict[str, Any]:
    key_ideas = _json_array(row.get("key_ideas"))
    payload: dict[str, Any] = {
        "prompt_id": str(row["prompt_id"]),
        "language": str(row["language"]),
        "chapter_id": str(row["chapter_id"]),
        "class_level": row.get("class_level"),
        "concept_ids": [str(item) for item in _json_array(row.get("concept_ids"))],
        "prompt": str(row["prompt"]),
        # The key ideas ARE the expected answer; the hub shows only how many
        # there are, and the recorder gets the text after the attempt.
        "key_idea_count": len(key_ideas),
        "rubric": _json_object(row.get("rubric")),
        "version": int(row.get("version") or 1),
    }
    if include_answer:
        payload["key_ideas"] = key_ideas
        payload["model_answer"] = str(row["model_answer"])
        payload["model_answer_source"] = _json_object(row.get("model_answer_source"))
    return payload


def list_speaking_prompts(
    db: DatabaseEngine,
    *,
    chapter_id: str | None = None,
    language: str = "en",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return servable prompts for a language; answer material is withheld."""
    lang = _language(language)
    clauses = ["language = ?", "status IN (?, ?)"]
    params: list[Any] = [lang, *SERVED_STATUSES]
    chapter = str(chapter_id or "").strip()
    if chapter:
        clauses.append("chapter_id = ?")
        params.append(chapter)
    params.append(_history_limit(limit))
    rows = db.fetchall(
        "SELECT * FROM speaking_prompt WHERE "
        + " AND ".join(clauses)
        + " ORDER BY chapter_id, prompt_id LIMIT ?",
        tuple(params),
    )
    return [_speaking_prompt_public(row, include_answer=False) for row in rows]


def fetch_speaking_prompt(
    db: DatabaseEngine,
    prompt_id: str,
    language: str,
    *,
    served_only: bool = False,
) -> dict[str, Any] | None:
    """Return one prompt with its key ideas + model answer (server-side use).

    `served_only` restricts the lookup to the statuses students may be served
    (`reviewed`/`published`). The API and the recorder use it so a draft or
    retired prompt can never be recorded against (or rendered as a page) — the
    answer-material gate must not depend on a later write-time check. The
    history surface keeps `served_only=False`: an attempt already made must
    stay readable.
    """
    if served_only:
        row = db.fetchone(
            "SELECT * FROM speaking_prompt WHERE prompt_id = ? AND language = ? "
            "AND status IN (?, ?)",
            (str(prompt_id), _language(language), *SERVED_STATUSES),
        )
    else:
        row = db.fetchone(
            "SELECT * FROM speaking_prompt WHERE prompt_id = ? AND language = ?",
            (str(prompt_id), _language(language)),
        )
    return _speaking_prompt_public(row, include_answer=True) if row else None


def _speaking_attempt_public(row: Mapping[str, Any]) -> dict[str, Any]:
    score = row.get("score")
    return {
        "attempt_id": str(row["attempt_id"]),
        "prompt_id": str(row["prompt_id"]),
        "language": str(row["language"]),
        "transcript": row.get("transcript"),
        "rubric_scores": _json_object(row.get("rubric_scores")),
        "feedback": _json_object(row.get("feedback")),
        "self_check": _json_object(row.get("self_check")),
        "score": float(score) if score is not None else None,
        "duration_ms": row.get("duration_ms"),
        "created_at": to_iso(as_utc(row.get("created_at")) or utc_now()),
    }


def save_speaking_attempt(
    db: DatabaseEngine,
    user_id: str,
    *,
    prompt_id: str,
    language: str,
    transcript: str | None,
    rubric_scores: Mapping[str, Any] | None = None,
    feedback: Mapping[str, Any] | None = None,
    self_check: Mapping[str, Any] | None = None,
    score: float | None = None,
    duration_ms: int | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Persist one explain-back attempt (transcript + bounded rubric/feedback only).

    The prompt must be served (`reviewed`/`published`): the attempt is the gate
    that unlocks `key_ideas` and `model_answer`, so a draft or retired prompt
    must not be attemptable by id.
    """
    owner = _require_user(user_id)
    lang = _language(language)
    text = None if transcript is None else str(transcript).strip()
    if text is not None and len(text) > MAX_TRANSCRIPT_CHARS:
        raise AssessmentError("E-SPEAKING-TRANSCRIPT")
    rubric_payload = _bounded_payload(rubric_scores or {}, "E-SPEAKING-PAYLOAD")
    feedback_payload = _bounded_payload(feedback or {}, "E-SPEAKING-PAYLOAD")
    self_check_payload = _bounded_payload(self_check or {}, "E-SPEAKING-PAYLOAD")
    if score is not None and not 0.0 <= float(score) <= 100.0:
        raise AssessmentError("E-SPEAKING-SCORE")
    if duration_ms is not None and not 0 <= int(duration_ms) <= 600_000:
        raise AssessmentError("E-SPEAKING-DURATION")
    # An attempt is the gate that unlocks key ideas + model answer, so it may
    # only be recorded against a prompt that is currently served; a draft or
    # retired prompt must not become an answer-material oracle by id.
    prompt = db.fetchone(
        "SELECT prompt_id FROM speaking_prompt WHERE prompt_id = ? AND language = ? "
        "AND status IN (?, ?)",
        (str(prompt_id), lang, *SERVED_STATUSES),
    )
    if prompt is None:
        raise AssessmentError("E-SPEAKING-PROMPT-UNKNOWN")
    attempt_id = uuid7_str()
    created = to_iso(now or utc_now())
    db.execute(
        """
        INSERT INTO speaking_attempt (
            attempt_id, user_id, prompt_id, language, transcript, rubric_scores,
            feedback, self_check, score, duration_ms, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            owner,
            str(prompt_id),
            lang,
            text,
            _dumps(rubric_payload),
            _dumps(feedback_payload),
            _dumps(self_check_payload),
            float(score) if score is not None else None,
            int(duration_ms) if duration_ms is not None else None,
            created,
        ),
    )
    row = db.fetchone(
        "SELECT * FROM speaking_attempt WHERE attempt_id = ?", (attempt_id,)
    )
    assert row is not None
    return _speaking_attempt_public(row)


def get_speaking_attempt(
    db: DatabaseEngine, user_id: str, attempt_id: str
) -> dict[str, Any] | None:
    """Return one attempt scoped to its owner, or None."""
    row = db.fetchone(
        "SELECT * FROM speaking_attempt WHERE attempt_id = ? AND user_id = ?",
        (str(attempt_id), _require_user(user_id)),
    )
    return _speaking_attempt_public(row) if row else None


def set_speaking_self_check(
    db: DatabaseEngine,
    user_id: str,
    attempt_id: str,
    *,
    self_check: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Store the student's own post-attempt note (owner-scoped, bounded).

    Self-check is the learner's reflection ("I explained it fully"), not a
    second grade: the route validates the closed choice set, the store only
    bounds the JSON. A missing or somebody else's attempt returns None.
    """
    owner = _require_user(user_id)
    payload = _bounded_payload(self_check, "E-SPEAKING-PAYLOAD")
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT attempt_id FROM speaking_attempt "
            "WHERE attempt_id = ? AND user_id = ?",
            (str(attempt_id), owner),
        )
        if row is None:
            return None
        tx.execute(
            "UPDATE speaking_attempt SET self_check = ? "
            "WHERE attempt_id = ? AND user_id = ?",
            (_dumps(payload), str(attempt_id), owner),
        )
        updated = tx.fetchone(
            "SELECT * FROM speaking_attempt WHERE attempt_id = ?", (str(attempt_id),)
        )
    if updated is None:
        # A concurrent owner delete between the check and the update: report a
        # miss, never a 500 from an assertion inside a request.
        return None
    return _speaking_attempt_public(updated)


def list_speaking_attempts(
    db: DatabaseEngine,
    user_id: str,
    *,
    prompt_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the owner's attempts, newest first."""
    clauses = ["user_id = ?"]
    params: list[Any] = [_require_user(user_id)]
    if prompt_id:
        clauses.append("prompt_id = ?")
        params.append(str(prompt_id))
    params.append(_history_limit(limit))
    rows = db.fetchall(
        "SELECT * FROM speaking_attempt WHERE "
        + " AND ".join(clauses)
        + " ORDER BY created_at DESC LIMIT ?",
        tuple(params),
    )
    return [_speaking_attempt_public(row) for row in rows]


def delete_speaking_attempt(db: DatabaseEngine, user_id: str, attempt_id: str) -> bool:
    """Hard-delete an attempt (owner-scoped): no transcript or feedback survives."""
    owner = _require_user(user_id)
    with db.transaction() as tx:
        row = tx.fetchone(
            "SELECT attempt_id FROM speaking_attempt WHERE attempt_id = ? AND user_id = ?",
            (str(attempt_id), owner),
        )
        if row is None:
            return False
        tx.execute(
            "DELETE FROM speaking_attempt WHERE attempt_id = ? AND user_id = ?",
            (str(attempt_id), owner),
        )
    return True


# --- tests and series (F7) --------------------------------------------------


def _series_public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "series_id": str(row["series_id"]),
        "slug": str(row["slug"]),
        "class_level": int(row["class_level"]),
        "kind": str(row["kind"]),
        "title": str(row["title"]),
        "description": row.get("description"),
        "language_set": [str(item) for item in _json_array(row.get("language_set"))],
        "status": str(row.get("status") or "draft"),
        "metadata": _json_object(row.get("metadata")),
    }


def list_series(
    db: DatabaseEngine,
    *,
    class_level: int | None = None,
    include_unpublished: bool = False,
) -> list[dict[str, Any]]:
    """Return the series catalogue, published only unless asked otherwise."""
    clauses: list[str] = []
    params: list[Any] = []
    if class_level is not None:
        clauses.append("class_level = ?")
        params.append(int(class_level))
    if not include_unpublished:
        clauses.append("status = 'published'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.fetchall(
        f"SELECT * FROM test_series {where} ORDER BY class_level, kind, title",
        tuple(params),
    )
    return [_series_public(row) for row in rows]


def get_series(
    db: DatabaseEngine, slug: str, *, include_unpublished: bool = False
) -> dict[str, Any] | None:
    """Return one published series by slug (or any status for an operator view)."""
    sql = "SELECT * FROM test_series WHERE slug = ?"
    if not include_unpublished:
        sql += " AND status = 'published'"
    row = db.fetchone(sql, (str(slug or "").strip(),))
    return _series_public(row) if row else None


def _test_public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "test_id": str(row["test_id"]),
        "series_id": row.get("series_id"),
        "chapter_ids": [str(item) for item in _json_array(row.get("chapter_ids"))],
        "title": str(row["title"]),
        "language": row.get("language"),
        "duration_s": int(row["duration_s"]),
        "total_marks": float(row["total_marks"]),
        "structure": _json_object(row.get("structure")),
        "status": str(row.get("status") or "draft"),
    }


def list_tests(
    db: DatabaseEngine,
    series_id: str,
    *,
    include_unpublished: bool = False,
) -> list[dict[str, Any]]:
    """Return a series' tests, published only unless asked otherwise."""
    sql = "SELECT * FROM test WHERE series_id = ?"
    if not include_unpublished:
        sql += " AND status = 'published'"
    rows = db.fetchall(sql + " ORDER BY title", (str(series_id),))
    return [_test_public(row) for row in rows]


def get_test(
    db: DatabaseEngine, test_id: str, *, user_id: str | None = None
) -> dict[str, Any] | None:
    """Return a test the caller may see: shared+published, or their own custom test."""
    row = db.fetchone("SELECT * FROM test WHERE test_id = ?", (str(test_id),))
    if row is None:
        return None
    if str(row.get("status")) == "published":
        return _test_public(row)
    owner = row.get("user_id")
    if owner is not None and user_id is not None and str(owner) == str(user_id):
        return _test_public(row)
    return None


def list_test_questions(
    db: DatabaseEngine, test_id: str, *, include_answers: bool = False
) -> list[dict[str, Any]]:
    """Return a paper's questions in order; the key is opt-in (review only)."""
    rows = db.fetchall(
        """
        SELECT tq.order_index AS paper_order, tq.section AS paper_section,
               tq.marks AS paper_marks, q.*
        FROM test_question tq
        JOIN question_bank q ON q.question_id = tq.question_id
        WHERE tq.test_id = ?
        ORDER BY tq.order_index
        """,
        (str(test_id),),
    )
    payload: list[dict[str, Any]] = []
    for row in rows:
        question = _question_from_row(row)
        entry = {
            "order_index": int(row["paper_order"]),
            "section": row.get("paper_section"),
            "marks": float(row["paper_marks"]),
            **(question.review() if include_answers else question.public()),
        }
        payload.append(entry)
    return payload


def _test_attempt_public(row: Mapping[str, Any]) -> dict[str, Any]:
    score = row.get("score")
    submitted = as_utc(row.get("submitted_at"))
    return {
        "attempt_id": str(row["attempt_id"]),
        "test_id": str(row["test_id"]),
        "status": str(row["status"]),
        "score": float(score) if score is not None else None,
        "time_spent_s": row.get("time_spent_s"),
        "started_at": to_iso(as_utc(row.get("started_at")) or utc_now()),
        "submitted_at": to_iso(submitted) if submitted else None,
    }


def create_test_attempt(
    db: DatabaseEngine,
    user_id: str,
    test_id: str,
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Start a test, or resume the student's one live attempt (DB-enforced)."""
    owner = _require_user(user_id)
    if get_test(db, test_id, user_id=owner) is None:
        raise AssessmentError("E-TEST-NOT-FOUND")
    existing = db.fetchone(
        "SELECT * FROM test_attempt WHERE test_id = ? AND user_id = ? "
        "AND status = 'in_progress'",
        (str(test_id), owner),
    )
    if existing:
        return _test_attempt_public(existing)
    attempt_id = uuid7_str()
    try:
        db.execute(
            """
            INSERT INTO test_attempt (attempt_id, test_id, user_id, status, started_at)
            VALUES (?, ?, ?, 'in_progress', ?)
            """,
            (attempt_id, str(test_id), owner, to_iso(now or utc_now())),
        )
    except Exception as exc:  # the partial unique index is the guard
        if not _unique_violation(exc):
            raise
        resumed = db.fetchone(
            "SELECT * FROM test_attempt WHERE test_id = ? AND user_id = ? "
            "AND status = 'in_progress'",
            (str(test_id), owner),
        )
        if resumed:
            return _test_attempt_public(resumed)
        raise AssessmentError("E-TEST-ATTEMPT-CONFLICT") from exc
    row = db.fetchone("SELECT * FROM test_attempt WHERE attempt_id = ?", (attempt_id,))
    assert row is not None
    return _test_attempt_public(row)


def get_test_attempt(
    db: DatabaseEngine, user_id: str, attempt_id: str
) -> dict[str, Any] | None:
    """Return one attempt scoped to its owner, or None."""
    row = db.fetchone(
        "SELECT * FROM test_attempt WHERE attempt_id = ? AND user_id = ?",
        (str(attempt_id), _require_user(user_id)),
    )
    return _test_attempt_public(row) if row else None


def list_test_attempts(
    db: DatabaseEngine, user_id: str, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Return the owner's attempts, newest first."""
    rows = db.fetchall(
        "SELECT * FROM test_attempt WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
        (_require_user(user_id), _history_limit(limit)),
    )
    return [_test_attempt_public(row) for row in rows]


def list_test_answers(
    db: DatabaseEngine, user_id: str, attempt_id: str
) -> list[dict[str, Any]]:
    """Return the answers saved for an attempt the caller owns."""
    rows = db.fetchall(
        """
        SELECT ta.answer, ta.correct, ta.marks_awarded, ta.time_ms, ta.flagged,
               ta.question_id, ta.updated_at
        FROM test_attempt_answer ta
        JOIN test_attempt t ON t.attempt_id = ta.attempt_id
        WHERE ta.attempt_id = ? AND t.user_id = ?
        ORDER BY ta.question_id
        """,
        (str(attempt_id), _require_user(user_id)),
    )
    return [
        {
            "question_id": str(row["question_id"]),
            "answer": _json_object(row.get("answer")),
            "correct": None if row.get("correct") is None else bool(row["correct"]),
            "marks_awarded": (
                float(row["marks_awarded"])
                if row.get("marks_awarded") is not None
                else None
            ),
            "time_ms": row.get("time_ms"),
            "flagged": bool(row.get("flagged")),
            "updated_at": to_iso(as_utc(row.get("updated_at")) or utc_now()),
        }
        for row in rows
    ]


def save_test_answer(
    db: DatabaseEngine,
    user_id: str,
    attempt_id: str,
    *,
    question_id: str,
    answer: Mapping[str, Any] | None = None,
    flagged: bool | None = None,
    time_ms: int | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Upsert one autosaved answer on a live attempt the caller owns."""
    owner = _require_user(user_id)
    payload = (
        _bounded_payload(answer, "E-ANSWER-INVALID") if answer is not None else None
    )
    if time_ms is not None and not 0 <= int(time_ms) <= 3_600_000:
        raise AssessmentError("E-TEST-TIME")
    with db.transaction() as tx:
        attempt = tx.fetchone(
            "SELECT attempt_id, status FROM test_attempt WHERE attempt_id = ? AND user_id = ?",
            (str(attempt_id), owner),
        )
        if attempt is None:
            raise AssessmentError("E-TEST-ATTEMPT-NOT-FOUND")
        if str(attempt["status"]) != "in_progress":
            raise AssessmentError("E-TEST-ATTEMPT-CLOSED")
        on_test = tx.fetchone(
            "SELECT question_id FROM test_question WHERE test_id = "
            "(SELECT test_id FROM test_attempt WHERE attempt_id = ?) AND question_id = ?",
            (str(attempt_id), str(question_id)),
        )
        if on_test is None:
            raise AssessmentError("E-TEST-QUESTION-UNKNOWN")
        stamp = to_iso(now or utc_now())
        existing = tx.fetchone(
            "SELECT * FROM test_attempt_answer WHERE attempt_id = ? AND question_id = ?",
            (str(attempt_id), str(question_id)),
        )
        if existing is None:
            tx.execute(
                """
                INSERT INTO test_attempt_answer (
                    attempt_id, question_id, answer, flagged, time_ms, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(attempt_id),
                    str(question_id),
                    _dumps(payload or {}),
                    bool(flagged),
                    int(time_ms) if time_ms is not None else None,
                    stamp,
                ),
            )
        else:
            merged = (
                _json_object(existing.get("answer")) if payload is None else payload
            )
            kept_flag = (
                bool(existing.get("flagged")) if flagged is None else bool(flagged)
            )
            kept_time = existing.get("time_ms") if time_ms is None else int(time_ms)
            tx.execute(
                """
                UPDATE test_attempt_answer
                SET answer = ?, flagged = ?, time_ms = ?, updated_at = ?
                WHERE attempt_id = ? AND question_id = ?
                """,
                (
                    _dumps(merged),
                    bool(kept_flag),
                    kept_time,
                    stamp,
                    str(attempt_id),
                    str(question_id),
                ),
            )
        row = tx.fetchone(
            "SELECT * FROM test_attempt_answer WHERE attempt_id = ? AND question_id = ?",
            (str(attempt_id), str(question_id)),
        )
    assert row is not None
    return {
        "question_id": str(row["question_id"]),
        "answer": _json_object(row.get("answer")),
        "correct": None if row.get("correct") is None else bool(row["correct"]),
        "marks_awarded": (
            float(row["marks_awarded"])
            if row.get("marks_awarded") is not None
            else None
        ),
        "flagged": bool(row.get("flagged")),
        "time_ms": row.get("time_ms"),
        "updated_at": to_iso(as_utc(row.get("updated_at")) or utc_now()),
    }


def submit_test_attempt(
    db: DatabaseEngine,
    user_id: str,
    attempt_id: str,
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """Grade every saved answer, mark the attempt submitted, and score it.

    Idempotent: a second submit returns the stored result. The marks and the
    answer key come from `question_bank`/`test_question`, so the score is
    reproducible; policy (negative marking, per-section rules) is F7's.
    """
    owner = _require_user(user_id)
    moment = now or utc_now()
    with db.transaction() as tx:
        attempt = tx.fetchone(
            "SELECT * FROM test_attempt WHERE attempt_id = ? AND user_id = ?",
            (str(attempt_id), owner),
        )
        if attempt is None:
            return None
        if str(attempt["status"]) != "in_progress":
            return _test_attempt_public(attempt)
        paper = tx.fetchall(
            """
            SELECT tq.question_id AS paper_question_id, tq.marks AS paper_marks, q.*
            FROM test_question tq
            JOIN question_bank q ON q.question_id = tq.question_id
            WHERE tq.test_id = ?
            ORDER BY tq.order_index
            """,
            (str(attempt["test_id"]),),
        )
        answers = {
            str(row["question_id"]): row
            for row in tx.fetchall(
                "SELECT * FROM test_attempt_answer WHERE attempt_id = ?",
                (str(attempt_id),),
            )
        }
        earned = 0.0
        possible = 0.0
        for entry in paper:
            question = _question_from_row(entry)
            marks = float(entry["paper_marks"])
            possible += marks
            saved = answers.get(question.question_id)
            if saved is None:
                continue
            try:
                check = check_answer(question, _json_object(saved.get("answer")))
            except AssessmentError as exc:
                # A stored answer that no longer parses scores zero rather than
                # blocking the submit; a bad answer KEY is a content bug and must
                # still fail loudly.
                if exc.code != "E-ANSWER-INVALID":
                    raise
                tx.execute(
                    "UPDATE test_attempt_answer SET correct = ?, marks_awarded = ? "
                    "WHERE attempt_id = ? AND question_id = ?",
                    (False, 0.0, str(attempt_id), question.question_id),
                )
                continue
            awarded = marks if check.correct else 0.0
            earned += awarded
            tx.execute(
                """
                UPDATE test_attempt_answer
                SET answer = ?, correct = ?, marks_awarded = ?
                WHERE attempt_id = ? AND question_id = ?
                """,
                (
                    _dumps(check.stored),
                    bool(check.correct),
                    awarded,
                    str(attempt_id),
                    question.question_id,
                ),
            )
        score = round(100.0 * earned / possible, 2) if possible > 0 else None
        started = as_utc(attempt.get("started_at"))
        spent = max(0, int((moment - started).total_seconds())) if started else None
        tx.execute(
            """
            UPDATE test_attempt
            SET status = 'submitted', submitted_at = ?, score = ?, time_spent_s = ?
            WHERE attempt_id = ? AND user_id = ?
            """,
            (to_iso(moment), score, spent, str(attempt_id), owner),
        )
        row = tx.fetchone(
            "SELECT * FROM test_attempt WHERE attempt_id = ?", (str(attempt_id),)
        )
    assert row is not None
    return _test_attempt_public(row)


def _history_limit(limit: int) -> int:
    return max(1, min(int(limit), HISTORY_LIMIT))


__all__ = [
    "DIFFICULTIES",
    "HISTORY_LIMIT",
    "MAX_QUESTION_IDS",
    "MAX_TRANSCRIPT_CHARS",
    "PACK_LANGUAGES",
    "PRACTICE_MODES",
    "QUESTION_TYPES",
    "SERIES_KINDS",
    "SERVED_STATUSES",
    "AnswerCheck",
    "AssessmentError",
    "Question",
    "check_answer",
    "complete_practice_session",
    "create_practice_session",
    "create_test_attempt",
    "delete_speaking_attempt",
    "fetch_question",
    "fetch_questions",
    "fetch_speaking_prompt",
    "get_practice_session",
    "get_series",
    "get_speaking_attempt",
    "get_test",
    "get_test_attempt",
    "list_missed_question_ids",
    "list_practice_attempts",
    "list_practice_chapters",
    "list_practice_history",
    "list_series",
    "list_speaking_attempts",
    "list_speaking_prompts",
    "list_test_answers",
    "list_test_attempts",
    "list_test_questions",
    "list_tests",
    "list_weak_concept_ids",
    "record_practice_answer",
    "save_speaking_attempt",
    "save_test_answer",
    "select_daily_question_ids",
    "select_question_ids",
    "set_speaking_self_check",
    "submit_test_attempt",
]
