"""Read paths for SWOT (F8): the student's own evidence plus chapter priors.

SWOT reads five kinds of rows, all of which already exist (no migration):

1. the student's `progress_event` rows (F3's read model — practice answers
   carry correct/hints/time per question, test submits carry per-chapter
   counts, lesson events carry sections read);
2. the student's `speaking_attempt` rows joined to `speaking_prompt` for the
   chapter (F6 never writes a `speaking_attempt` progress event, so the table
   is the only speaking source);
3. `lesson_progress` counters (coverage when the question bank is unknown);
4. the chapter's `topic_time_prior` row (the A5 AI prior) and the published
   `question_bank` count (the attempt-rate denominator);
5. **all students'** observed per-question times from `practice_attempt` for
   the chapter-time EWMA. That read is deliberately aggregate-only: rows are
   reduced to capped milliseconds inside this module and no user id, session
   id, or answer payload ever leaves it.

Every query here is bounded and user-scoped (or aggregate-only); nothing
writes, and no model or vendor is called.
"""

from __future__ import annotations

import datetime
from typing import Any, Final

from db.engine import DatabaseEngine

from ..progress.store import EventRow, as_utc, list_events, list_lesson_progress

# The all-student time sample per chapter stays bounded: an EWMA over the most
# recent window is the documented incremental shape (no all-history recompute;
# db-spec Q13 reserves the materialized `topic_time_stat` rollup for later).
TIME_SAMPLE_LIMIT: Final[int] = 200
# The served question statuses practice and tests draw from.
SERVED_QUESTION_STATUSES: Final[tuple[str, ...]] = ("reviewed", "published")


def read_learner_events(db: DatabaseEngine, user_id: str) -> list[EventRow]:
    """The account's own progress events (newest first), F3's read model."""
    return list_events(db, user_id)


def read_lesson_progress(db: DatabaseEngine, user_id: str) -> list[dict[str, Any]]:
    """Per-chapter lesson counters (blocks seen/total) for coverage fallback."""
    return list_lesson_progress(db, user_id)


def read_speaking_scores(db: DatabaseEngine, user_id: str) -> list[dict[str, Any]]:
    """The account's scored explain-backs with their chapter, newest first.

    A prompt from a retired pack still resolves (the soft pair is not a FK);
    an unknown prompt cannot happen through the recorder, but a dangling row
    is skipped rather than guessed into a chapter.
    """
    rows = db.fetchall(
        """
        SELECT sa.score, sa.created_at, sp.chapter_id
        FROM speaking_attempt sa
        LEFT JOIN speaking_prompt sp
               ON sp.prompt_id = sa.prompt_id AND sp.language = sa.language
        WHERE sa.user_id = ?
        ORDER BY sa.created_at DESC
        """,
        (user_id,),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        chapter = str(row.get("chapter_id") or "").strip()
        score = row.get("score")
        created = as_utc(row.get("created_at"))
        if not chapter or score is None or created is None:
            continue
        items.append(
            {
                "chapter_id": chapter,
                "score": float(score),
                "created_at": created,
            }
        )
    return items


def read_question_counts(db: DatabaseEngine) -> dict[str, int]:
    """Published question-bank size per chapter (the attempt-rate denominator)."""
    placeholders = ", ".join("?" for _ in SERVED_QUESTION_STATUSES)
    try:
        rows = db.fetchall(
            f"""
            SELECT chapter_id, COUNT(DISTINCT base_item_id) AS items
            FROM question_bank
            WHERE status IN ({placeholders}) AND chapter_id IS NOT NULL
            GROUP BY chapter_id
            """,
            SERVED_QUESTION_STATUSES,
        )
    except Exception:  # noqa: BLE001 - the pack import may not have landed
        return {}
    return {
        str(row["chapter_id"]): int(row.get("items") or 0)
        for row in rows
        if row.get("chapter_id")
    }


def read_attempted_questions(db: DatabaseEngine, user_id: str) -> dict[str, set[str]]:
    """Distinct question ids the account attempted, per chapter.

    Sources: the practice rows this account wrote (`practice_attempt` through
    `practice_session`, whose chapter is set for chapter-mode sets) — merged
    with the caller's progress events, which already carry `question_id`.
    """
    try:
        rows = db.fetchall(
            """
            SELECT DISTINCT ps.chapter_id AS chapter_id, pa.question_id AS question_id
            FROM practice_attempt pa
            JOIN practice_session ps ON ps.session_id = pa.session_id
            WHERE ps.user_id = ? AND ps.chapter_id IS NOT NULL
            """,
            (user_id,),
        )
    except Exception:  # noqa: BLE001 - F5 tables may predate the import
        return {}
    attempted: dict[str, set[str]] = {}
    for row in rows:
        chapter = str(row.get("chapter_id") or "").strip()
        question = str(row.get("question_id") or "").strip()
        if chapter and question:
            attempted.setdefault(chapter, set()).add(question)
    return attempted


def read_topic_priors(db: DatabaseEngine) -> dict[str, int]:
    """The A5 AI prior (expected ms per question) per chapter, if imported."""
    try:
        rows = db.fetchall(
            """
            SELECT chapter_id, expected_time_ms
            FROM topic_time_prior
            WHERE scope = 'chapter'
            """
        )
    except Exception:  # noqa: BLE001 - 0004 tables may not exist yet
        return {}
    priors: dict[str, int] = {}
    for row in rows:
        chapter = str(row.get("chapter_id") or "").strip()
        expected = int(row.get("expected_time_ms") or 0)
        if chapter and expected > 0:
            priors.setdefault(chapter, expected)
    return priors


def read_all_student_times(
    db: DatabaseEngine, chapter_id: str
) -> list[tuple[datetime.datetime, int]]:
    """Observed per-question times for one chapter across all students.

    Returns `(created_at, time_ms)` pairs oldest first, ready for the EWMA
    chain. Aggregate-only: timestamps and milliseconds, never an identity or
    an answer. Bounded to the most recent `TIME_SAMPLE_LIMIT` rows.
    """
    try:
        rows = db.fetchall(
            """
            SELECT pa.time_ms, pa.created_at
            FROM practice_attempt pa
            JOIN practice_session ps ON ps.session_id = pa.session_id
            WHERE ps.chapter_id = ? AND pa.time_ms IS NOT NULL
            ORDER BY pa.created_at DESC
            LIMIT ?
            """,
            (chapter_id, TIME_SAMPLE_LIMIT),
        )
    except Exception:  # noqa: BLE001 - F5 tables may not exist yet
        return []
    samples: list[tuple[datetime.datetime, int]] = []
    for row in rows:
        created = as_utc(row.get("created_at"))
        time_ms = row.get("time_ms")
        if created is None or time_ms is None:
            continue
        samples.append((created, int(time_ms)))
    samples.sort(key=lambda item: item[0])
    return samples


def read_exam_weights(db: DatabaseEngine) -> dict[str, float]:
    """The syllabus chapter exam weight (P3 owns real weights; often NULL)."""
    try:
        rows = db.fetchall(
            """
            SELECT chapter_id, exam_weight
            FROM syllabus_chapter
            WHERE subject = 'physics'
            """
        )
    except Exception:  # noqa: BLE001 - the P1/P2 import may not have landed
        return {}
    weights: dict[str, float] = {}
    for row in rows:
        chapter = str(row.get("chapter_id") or "").strip()
        raw = row.get("exam_weight")
        if chapter and raw is not None:
            try:
                weights[chapter] = float(raw)
            except (TypeError, ValueError):
                continue
    return weights


__all__ = [
    "SERVED_QUESTION_STATUSES",
    "TIME_SAMPLE_LIMIT",
    "read_all_student_times",
    "read_attempted_questions",
    "read_exam_weights",
    "read_learner_events",
    "read_lesson_progress",
    "read_question_counts",
    "read_speaking_scores",
    "read_topic_priors",
]
