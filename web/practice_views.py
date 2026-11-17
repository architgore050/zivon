"""Template view models for the practice hub, player, summary, and history (F5).

The domain rules live in `backend.practice`; the routes only add the shell
context. These builders turn store rows into plain template data: display
titles from the catalogue (falling back to a humanized id when a chapter is not
in the catalogue yet), relative dates, progress percentages, and the feedback
copy.

Every `safe_*` wrapper catches a store failure and returns a page-level error
view instead of a 500, and it never invents a chapter, a session, or a score to
fill the gap.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any

from backend.assessment import (
    Question,
    fetch_questions,
    list_missed_question_ids,
    list_practice_chapters,
)
from backend.practice import (
    CHAPTER_COUNT_DEFAULT,
    DAILY_COUNT,
    RETRY_COUNT,
    PracticeUser,
    history,
    practice_user,
    session_state,
    session_summary,
)
from backend.progress import (
    INDIA_TZ,
    CatalogueSnapshot,
    as_utc,
    catalogue_snapshot,
    utc_now,
)

logger = logging.getLogger(__name__)

MODE_LABELS: dict[str, str] = {
    "chapter": "Chapter drill",
    "daily": "Daily 5",
    "weak_topic": "Weak-topic drill",
    "retry_mistakes": "Retry mistakes",
}
QUESTION_TYPE_LABELS: dict[str, str] = {
    "mcq": "Multiple choice",
    "numeric": "Numeric answer",
    "assertion_reason": "Assertion–reason",
}
DIFFICULTY_LABELS: dict[str, str] = {
    "easy": "Easy",
    "medium": "Medium",
    "hard": "Hard",
}
DATA_ERROR = (
    "The practice set could not be read just now. Your answers are stored; "
    "this page will show them again on the next successful load."
)
CLASS_PREFIX = re.compile(r"^class-\d+-")


# --- small formatting helpers ----------------------------------------------


def humanize_id(value: object) -> str:
    """Make a stable id readable without inventing content (a derived label)."""
    text = CLASS_PREFIX.sub("", str(value or "").strip())
    text = text.replace("-", " ").replace("_", " ").strip()
    if not text:
        return "Practice"
    return text[:1].upper() + text[1:]


def concept_title(concept_id: object, chapter_id: object) -> str:
    """Humanize a concept id; the catalogue vocabulary is not reconciled yet."""
    value = str(concept_id or "").strip()
    chapter = str(chapter_id or "").strip()
    if chapter and value.startswith(chapter + "-"):
        value = value[len(chapter) + 1 :]
    return humanize_id(value)


def mode_label(mode: object) -> str:
    return MODE_LABELS.get(str(mode or ""), "Practice")


def relative_day(moment: datetime.datetime | None, now: datetime.datetime) -> str:
    """A calendar-day distance in IST; never a live ticking clock."""
    if moment is None:
        return ""
    local = moment.astimezone(INDIA_TZ)
    current = now.astimezone(INDIA_TZ)
    days = (current.date() - local.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return "a week ago" if weeks == 1 else f"{weeks} weeks ago"
    return local.strftime("%d %b %Y")


def _format_number(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    return str(value)


def _marks_label(marks: object) -> str:
    try:
        value = float(marks)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return f"{value:g} mark" if value == 1 else f"{value:g} marks"


def _expected_time_label(expected_ms: object) -> str:
    try:
        value = int(expected_ms)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value < 60_000:
        return f"about {round(value / 1000)} s"
    return f"about {round(value / 60_000)} min"


def _chapter_view(
    snapshot: CatalogueSnapshot, chapter_id: object
) -> dict[str, Any] | None:
    value = str(chapter_id or "").strip()
    if not value:
        return None
    meta = snapshot.chapters.get(value)
    return {
        "chapter_id": value,
        "title": meta.title if meta else humanize_id(value),
        "chapter_no": meta.chapter_no if meta else None,
        "class_level": meta.class_level if meta else None,
        "lesson_url": meta.lesson_url if meta else None,
    }


def _session_when(session: dict[str, Any], now: datetime.datetime) -> str:
    return relative_day(as_utc(session.get("started_at")), now)


def _completed(session: dict[str, Any]) -> bool:
    return session.get("completed_at") is not None


# --- hub --------------------------------------------------------------------


def _chapters_with_fallback(db: Any, user: PracticeUser) -> list[dict[str, Any]]:
    """Union of chapters with the saved language and the English fallback."""
    requested = {
        str(row["chapter_id"]): row
        for row in list_practice_chapters(db, language=user.language)
    }
    fallback = (
        {}
        if user.language == "en"
        else {
            str(row["chapter_id"]): row
            for row in list_practice_chapters(db, language="en")
        }
    )
    rows: list[dict[str, Any]] = []
    for chapter_id in sorted(set(requested) | set(fallback)):
        row = requested.get(chapter_id) or fallback.get(chapter_id)
        if row is None:
            continue
        rows.append(
            {
                "chapter_id": chapter_id,
                "class_level": int(row["class_level"]),
                "question_count": int(row["question_count"]),
                "language_fallback": chapter_id not in requested,
            }
        )
    return rows


def _missed_ids(db: Any, user: PracticeUser) -> list[str]:
    ids = list_missed_question_ids(db, user.user_id, language=user.language, limit=50)
    if not ids and user.language != "en":
        ids = list_missed_question_ids(db, user.user_id, language="en", limit=50)
    return ids


def _weak_chapters(
    missed_questions: list[Question],
    snapshot: CatalogueSnapshot,
    user: PracticeUser,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    fallback: dict[str, bool] = {}
    for question in missed_questions:
        counts[question.chapter_id] = counts.get(question.chapter_id, 0) + 1
        fallback[question.chapter_id] = fallback.get(question.chapter_id, False) or (
            question.language != user.language
        )
    entries: list[dict[str, Any]] = []
    for chapter_id, missed in counts.items():
        chapter = _chapter_view(snapshot, chapter_id) or {
            "chapter_id": chapter_id,
            "title": humanize_id(chapter_id),
            "chapter_no": None,
            "class_level": None,
            "lesson_url": None,
        }
        entries.append(
            {
                **chapter,
                "missed_count": missed,
                "count": min(RETRY_COUNT, missed),
                "language_fallback": fallback.get(chapter_id, False),
            }
        )
    entries.sort(key=lambda item: (-int(item["missed_count"]), str(item["title"])))
    return entries


def _recent_sessions(
    db: Any,
    user: PracticeUser,
    snapshot: CatalogueSnapshot,
    now: datetime.datetime,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for session in history(db, user.user_id, limit=5):
        chapter = _chapter_view(snapshot, session.get("chapter_id"))
        completed = _completed(session)
        score = session.get("score")
        items.append(
            {
                "session_id": session["session_id"],
                "href": (
                    f"/app/practice/{session['session_id']}/summary"
                    if completed
                    else f"/app/practice/{session['session_id']}"
                ),
                "title": chapter["title"] if chapter else "Practice set",
                "mode_label": mode_label(session["mode"]),
                "question_count": int(session["question_count"]),
                "score_label": f"{round(float(score))}%" if score is not None else None,
                "completed": completed,
                "when": _session_when(session, now),
            }
        )
    return items


def build_hub_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    frontend_dir: str,
    requested_chapter: str | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return everything `/app/practice` renders (or raise; use `safe_*`)."""
    current = now or utc_now()
    user = practice_user(user_row)
    snapshot = catalogue_snapshot(db, frontend_dir)
    rows = _chapters_with_fallback(db, user)
    chapters: list[dict[str, Any]] = []
    for row in rows:
        chapter = _chapter_view(snapshot, row["chapter_id"]) or {
            "chapter_id": row["chapter_id"],
            "title": humanize_id(row["chapter_id"]),
            "chapter_no": None,
            "class_level": row["class_level"],
            "lesson_url": None,
        }
        chapters.append(
            {
                **chapter,
                "class_level": row["class_level"],
                "question_count": row["question_count"],
                "language_fallback": row["language_fallback"],
                "start_count": (
                    CHAPTER_COUNT_DEFAULT
                    if row["question_count"] >= CHAPTER_COUNT_DEFAULT
                    else None
                ),
            }
        )
    chapters.sort(
        key=lambda item: (
            int(item["class_level"] or 0),
            int(item["chapter_no"] or 0),
            str(item["title"]).lower(),
        )
    )
    daily_class = [
        chapter for chapter in chapters if chapter["class_level"] == user.class_level
    ]
    # Daily 5 selects only chapters that have the saved language; if none do,
    # it falls back to English for the whole set. The advertised count must use
    # the same pool, or it would promise questions the selection cannot serve.
    requested_class = [
        chapter for chapter in daily_class if not chapter["language_fallback"]
    ]
    daily_pool = requested_class or daily_class
    daily_total = sum(int(chapter["question_count"]) for chapter in daily_pool)
    daily_available = user.class_level is not None and daily_total > 0
    if user.class_level is None:
        daily_reason = "Set your class in Settings to get a Daily 5."
    elif not daily_available:
        daily_reason = (
            f"No Class {user.class_level} practice set is imported yet. "
            "Chapter drills are listed below where a bank exists."
        )
    else:
        daily_reason = None
    daily = {
        "available": daily_available,
        "reason": daily_reason,
        "count": min(DAILY_COUNT, daily_total) if daily_available else 0,
        "class_level": user.class_level,
        "language_fallback": bool(daily_class) and not requested_class,
    }
    missed_questions = fetch_questions(db, _missed_ids(db, user))
    weak_chapters = _weak_chapters(missed_questions, snapshot, user)
    retry = {
        "available": bool(missed_questions),
        "count": min(RETRY_COUNT, len(missed_questions)),
        "language_fallback": any(
            question.language != user.language for question in missed_questions
        ),
    }
    focus = next(
        (chapter for chapter in chapters if chapter["chapter_id"] == requested_chapter),
        None,
    )
    return {
        "data_error": None,
        "chapters": chapters,
        "daily": daily,
        "weak_chapters": weak_chapters,
        "retry": retry,
        "recent": _recent_sessions(db, user, snapshot, current),
        "focus": focus,
        "language": user.language,
        "catalogue_source": snapshot.source,
    }


def safe_hub_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    frontend_dir: str,
    requested_chapter: str | None = None,
) -> dict[str, Any]:
    try:
        return build_hub_view(
            db,
            user_row=user_row,
            frontend_dir=frontend_dir,
            requested_chapter=requested_chapter,
        )
    except Exception:  # a page-level error is the designed state
        logger.exception("practice hub read failed")
        return {
            "data_error": DATA_ERROR,
            "chapters": [],
            "daily": {
                "available": False,
                "reason": None,
                "count": 0,
                "class_level": None,
                "language_fallback": False,
            },
            "weak_chapters": [],
            "retry": {"available": False, "count": 0, "language_fallback": False},
            "recent": [],
            "focus": None,
            "language": "en",
            "catalogue_source": "unavailable",
        }


# --- player -----------------------------------------------------------------


def _options(question: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"index": index, "text": str(text)}
        for index, text in enumerate(question.get("options") or [])
    ]


def _feedback_view(
    question: dict[str, Any], options: list[dict[str, Any]]
) -> dict[str, Any] | None:
    feedback = question.get("feedback")
    if not feedback:
        return None
    answer = feedback.get("answer") or {}
    chosen = feedback.get("chosen") or {}
    answer_text = ""
    chosen_text = ""
    if isinstance(answer.get("index"), int):
        index = int(answer["index"])
        if 0 <= index < len(options):
            answer_text = options[index]["text"]
    elif "value" in answer:
        answer_text = _format_number(answer["value"])
        unit = feedback.get("unit")
        if unit:
            answer_text = f"{answer_text} {unit}"
    if isinstance(chosen.get("index"), int):
        index = int(chosen["index"])
        if 0 <= index < len(options):
            chosen_text = options[index]["text"]
    elif "value" in chosen:
        chosen_text = _format_number(chosen["value"])
    correct = bool(feedback.get("correct"))
    return {
        "correct": correct,
        "verdict": "Correct." if correct else "Not quite.",
        "answer": answer,
        "chosen": chosen,
        "answer_text": answer_text,
        "chosen_text": chosen_text,
        "explanation": feedback.get("explanation") or "",
        "misconception": feedback.get("misconception"),
        "attempt_no": int(feedback.get("attempt_no") or 1),
    }


def _language_note(state: dict[str, Any], chapter: dict[str, Any] | None) -> str | None:
    if not state.get("language_fallback"):
        return None
    topic = chapter["title"] if chapter else "this chapter"
    return (
        f"Practice for {topic} is not in your saved language yet, so this set "
        "is in English."
    )


def build_player_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    session_id: str,
    frontend_dir: str,
    review_question_id: str | None = None,
) -> dict[str, Any]:
    """Return the player page model for one session (one question at a time)."""
    user = practice_user(user_row)
    state = session_state(
        db,
        user.user_id,
        session_id,
        review_question_id=review_question_id,
    )
    if state is None:
        return {"state": "missing"}
    snapshot = catalogue_snapshot(db, frontend_dir)
    session = state["session"]
    chapter = _chapter_view(snapshot, session.get("chapter_id"))
    question = state["question"]
    options = _options(question) if question else []
    feedback = _feedback_view(question, options) if question else None
    index = state["index"]
    count = int(state["question_count"])
    answered = int(state["answered_count"])
    return {
        "state": "ok",
        "session": session,
        "mode_label": mode_label(session["mode"]),
        "chapter": chapter,
        "question": question,
        "options": options,
        "question_type_label": (
            QUESTION_TYPE_LABELS.get(str(question["type"]), "Question")
            if question
            else ""
        ),
        "difficulty_label": (
            DIFFICULTY_LABELS.get(str(question["difficulty"]), "") if question else ""
        ),
        "marks_label": _marks_label(question["marks"]) if question else "",
        "expected_time_label": (
            _expected_time_label(question["expected_time_ms"]) if question else ""
        ),
        "feedback": feedback,
        "answer_kind": "index" if options else "value",
        "progress": {
            "position": (int(index) + 1) if index is not None else count,
            "count": count,
            "answered": answered,
            "percent": round(100 * answered / count) if count else 0,
        },
        "next_href": (
            f"/app/practice/{session['session_id']}"
            if state["next_index"] is not None
            else None
        ),
        "complete_available": bool(state["complete_available"]),
        "completed": bool(state["completed"]),
        "language_note": _language_note(state, chapter),
        "review": bool(feedback is not None and question is not None),
        "lesson_url": chapter["lesson_url"] if chapter else None,
        "hint_available": bool(question and question.get("hint_available")),
    }


def safe_player_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    session_id: str,
    frontend_dir: str,
    review_question_id: str | None = None,
) -> dict[str, Any]:
    try:
        return build_player_view(
            db,
            user_row=user_row,
            session_id=session_id,
            frontend_dir=frontend_dir,
            review_question_id=review_question_id,
        )
    except Exception:  # a page-level error is the designed state
        logger.exception("practice player read failed")
        return {"state": "error", "message": DATA_ERROR}


# --- summary and history ----------------------------------------------------


def _next_chapter(
    snapshot: CatalogueSnapshot, chapter_id: object
) -> dict[str, Any] | None:
    value = str(chapter_id or "").strip()
    meta = snapshot.chapters.get(value)
    if meta is None:
        return None
    siblings = sorted(
        snapshot.class_chapters(meta.class_level),
        key=lambda item: (item.chapter_no, item.title.lower()),
    )
    for sibling in siblings:
        if sibling.chapter_no <= meta.chapter_no:
            continue
        if sibling.lesson_url:
            return {"title": sibling.title, "lesson_url": sibling.lesson_url}
    return None


def build_summary_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    session_id: str,
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return the score, accuracy, concept breakdown, and next actions."""
    current = now or utc_now()
    user = practice_user(user_row)
    payload = session_summary(db, user.user_id, session_id)
    if payload is None:
        return {"state": "missing"}
    snapshot = catalogue_snapshot(db, frontend_dir)
    session = payload["session"]
    chapter = _chapter_view(snapshot, session.get("chapter_id"))
    summary = payload["summary"]
    concepts = [
        {
            **entry,
            "title": concept_title(entry["concept_id"], session.get("chapter_id")),
        }
        for entry in summary["concepts"]
    ]
    completed = _completed(session)
    missed = _missed_ids(db, user) if completed else []
    return {
        "state": "ok",
        "session": session,
        "summary": {**summary, "concepts": concepts},
        "completed": completed,
        "mode_label": mode_label(session["mode"]),
        "chapter": chapter,
        "when": _session_when(session, current),
        "score_label": (
            f"{round(float(session['score']))}%"
            if session.get("score") is not None
            else None
        ),
        "retry": {
            "available": bool(missed) and completed,
            "count": min(RETRY_COUNT, len(missed)) if completed else 0,
            "language_fallback": any(
                question.language != user.language
                for question in fetch_questions(db, missed)
            ),
        },
        "next_chapter": _next_chapter(snapshot, session.get("chapter_id")),
        "lesson_url": chapter["lesson_url"] if chapter else None,
        "language_note": (
            "This set was served in English because your saved language was not "
            "available for the chapter yet."
            if (session.get("config") or {}).get("language_fallback")
            else None
        ),
    }


def safe_summary_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    session_id: str,
    frontend_dir: str,
) -> dict[str, Any]:
    try:
        return build_summary_view(
            db,
            user_row=user_row,
            session_id=session_id,
            frontend_dir=frontend_dir,
        )
    except Exception:  # a page-level error is the designed state
        logger.exception("practice summary read failed")
        return {"state": "error", "message": DATA_ERROR}


def build_history_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return every saved practice session, newest first (bounded by the store)."""
    current = now or utc_now()
    user = practice_user(user_row)
    snapshot = catalogue_snapshot(db, frontend_dir)
    sessions: list[dict[str, Any]] = []
    for session in history(db, user.user_id, limit=20):
        chapter = _chapter_view(snapshot, session.get("chapter_id"))
        completed = _completed(session)
        score = session.get("score")
        sessions.append(
            {
                "session_id": session["session_id"],
                "href": (
                    f"/app/practice/{session['session_id']}/summary"
                    if completed
                    else f"/app/practice/{session['session_id']}"
                ),
                "title": chapter["title"] if chapter else "Practice set",
                "mode_label": mode_label(session["mode"]),
                "question_count": int(session["question_count"]),
                "score_label": f"{round(float(score))}%" if score is not None else None,
                "completed": completed,
                "when": _session_when(session, current),
            }
        )
    return {"state": "ok", "sessions": sessions, "count": len(sessions)}


def safe_history_view(
    db: Any,
    *,
    user_row: dict[str, Any],
    frontend_dir: str,
) -> dict[str, Any]:
    try:
        return build_history_view(db, user_row=user_row, frontend_dir=frontend_dir)
    except Exception:  # a page-level error is the designed state
        logger.exception("practice history read failed")
        return {"state": "error", "message": DATA_ERROR}


__all__ = [
    "DATA_ERROR",
    "MODE_LABELS",
    "build_history_view",
    "build_hub_view",
    "build_player_view",
    "build_summary_view",
    "concept_title",
    "humanize_id",
    "mode_label",
    "relative_day",
    "safe_history_view",
    "safe_hub_view",
    "safe_player_view",
    "safe_summary_view",
]
