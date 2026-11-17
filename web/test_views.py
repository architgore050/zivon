"""Template view models for the test hub, builder, player, review, and series pages (F7).

The domain rules live in `backend.test_engine`; the routes only add the shell
context. These builders turn store rows into plain template data: display
titles from the catalogue (falling back to a humanized id), relative dates, the
palette, answer shapes, review copy, and the honest series states.

Every `safe_*` wrapper catches a store failure and returns a page-level error
view instead of a 500, and it never invents a chapter, a question, a score, or a
paper to fill the gap.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections.abc import Mapping
from typing import Any

from backend.assessment import AssessmentError
from backend.progress import INDIA_TZ, CatalogueSnapshot, catalogue_snapshot, utc_now
from backend.test_engine import (
    CHAPTER_TEST_MAX,
    CUSTOM_COUNT_DEFAULT,
    DIFFICULTY_LABELS,
    DURATION_DEFAULT,
    LANGUAGE_LABELS,
    QUESTION_TYPE_LABELS,
    TestUser,
    attempt_state,
    chapter_options,
    duration_label,
    format_remaining,
    marks_label,
    review_state,
    series_catalogue,
    series_detail,
    test_user,
)
from backend.test_engine import (
    history as test_history,
)

logger = logging.getLogger(__name__)

CONTENT_MODE_ERROR = (
    "This paper carries a source that is not cleared for practice yet, so it "
    "cannot be opened."
)
DATA_ERROR = (
    "The test data could not be read just now. Saved answers and papers are "
    "not lost; this page will show them again on the next successful load."
)
CLASS_PREFIX = re.compile(r"^class-\d+-")
NUMBER_WORDS: dict[int, str] = {
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
    10: "Ten",
}
PRESETS: tuple[tuple[int, int], ...] = ((10, 10), (30, 20))
COUNT_CHOICES: tuple[int, ...] = (5, 10, 15, 20, 30)
MINUTE_CHOICES: tuple[int, ...] = (10, 20, 30, 45, 60)


def humanize_id(value: object) -> str:
    """Make a stable id readable without inventing content (a derived label)."""
    text = CLASS_PREFIX.sub("", str(value or "").strip())
    text = text.replace("-", " ").replace("_", " ").strip()
    if not text:
        return "Test"
    return text[:1].upper() + text[1:]


def concept_title(concept_id: object, chapter_id: object) -> str:
    """Humanize a concept id; the catalogue vocabulary is not reconciled yet."""
    value = str(concept_id or "").strip()
    chapter = str(chapter_id or "").strip()
    if chapter and value.startswith(chapter + "-"):
        value = value[len(chapter) + 1 :]
    return humanize_id(value)


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
    if days < 365:
        months = days // 30
        return "a month ago" if months == 1 else f"{months} months ago"
    return local.strftime("%d %b %Y")


def _parse_iso(value: object) -> datetime.datetime | None:
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


def _chapter_view(
    snapshot: CatalogueSnapshot, chapter_id: str
) -> dict[str, Any] | None:
    meta = snapshot.chapters.get(chapter_id)
    if meta is None:
        return None
    return {
        "chapter_id": chapter_id,
        "title": meta.title,
        "chapter_no": meta.chapter_no,
        "class_level": None,
        "lesson_url": meta.lesson_url,
    }


def _chapter_entry(
    snapshot: CatalogueSnapshot, chapter_id: str, class_level: int | None
) -> dict[str, Any]:
    if not chapter_id:
        return {
            "chapter_id": "",
            "title": "Unknown chapter",
            "chapter_no": None,
            "class_level": class_level,
            "lesson_url": None,
        }
    return _chapter_view(snapshot, chapter_id) or {
        "chapter_id": chapter_id,
        "title": humanize_id(chapter_id),
        "chapter_no": None,
        "class_level": class_level,
        "lesson_url": None,
    }


def _assessment_copy(exc: AssessmentError) -> str:
    return {
        "E-TEST-CONTENT-MODE": CONTENT_MODE_ERROR,
        "E-TEST-EXPIRED": "Time is up for this paper. Open the review to submit it.",
        "E-TEST-ATTEMPT-CLOSED": "This paper is already submitted.",
    }.get(exc.code, DATA_ERROR)


def _language_note(user: TestUser, language: str) -> str | None:
    if language == user.language:
        return None
    return (
        "This paper is in English because your saved language has no bank rows "
        "for it yet. Your language choice is saved."
    )


# --- hub --------------------------------------------------------------------


def build_hub_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return everything `/app/tests` renders (or raise; use `safe_*`)."""
    current = now or utc_now()
    user = test_user(user_row)
    snapshot = catalogue_snapshot(db, frontend_dir)
    options = chapter_options(db, user)
    chapters = []
    for row in options["chapters"]:
        chapter = _chapter_entry(snapshot, row["chapter_id"], row["class_level"])
        chapters.append(
            {
                **chapter,
                "question_count": row["question_count"],
                "class_level": row["class_level"],
                "start_count": min(CHAPTER_TEST_MAX, row["question_count"]),
                "duration_label": duration_label(
                    max(300, min(CHAPTER_TEST_MAX, row["question_count"]) * 90)
                ),
            }
        )
    catalogue = series_catalogue(db, user)
    recent = test_history(db, user)["items"][:5]
    for item in recent:
        chapter_titles = [
            _chapter_entry(snapshot, chapter_id, None)["title"]
            for chapter_id in item.get("chapter_ids") or []
        ]
        item["when"] = relative_day(_parse_iso(item.get("started_at")), current)
        item["chapters_label"] = ", ".join(chapter_titles[:2]) + (
            " +" + str(len(chapter_titles) - 2) if len(chapter_titles) > 2 else ""
        )
    return {
        "data_error": None,
        "class_level": user.class_level,
        "language": options["language"],
        "requested_language": options["requested_language"],
        "language_fallback": options["language_fallback"],
        "language_note": _language_note(user, options["language"]),
        "chapters": chapters,
        "has_bank": bool(chapters),
        "presets": [
            {
                "minutes": minutes,
                "count": count,
                "duration_s": minutes * 60,
                "label": f"{minutes}-minute test",
                "detail": f"{count} questions",
            }
            for minutes, count in PRESETS
        ],
        "series": catalogue["cards"],
        "series_notice": catalogue["notice"],
        "recent": recent,
        "history_href": "/app/tests/history",
        "builder_href": "/app/tests/new",
    }


def safe_hub_view(
    db: Any, *, user_row: Mapping[str, Any], frontend_dir: str
) -> dict[str, Any]:
    try:
        return build_hub_view(db, user_row=user_row, frontend_dir=frontend_dir)
    except Exception:  # a page-level error is the designed state
        logger.exception("test hub read failed")
        return {
            "data_error": DATA_ERROR,
            "class_level": None,
            "language": "en",
            "requested_language": "en",
            "language_fallback": False,
            "language_note": None,
            "chapters": [],
            "has_bank": False,
            "presets": [],
            "series": [],
            "series_notice": None,
            "recent": [],
            "history_href": "/app/tests/history",
            "builder_href": "/app/tests/new",
        }


# --- builder ----------------------------------------------------------------


def build_builder_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    frontend_dir: str,
    selected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the builder form; on a validation miss, keep the student's picks."""
    user = test_user(user_row)
    snapshot = catalogue_snapshot(db, frontend_dir)
    options = chapter_options(db, user)
    chapters = []
    for row in options["chapters"]:
        chapter = _chapter_entry(snapshot, row["chapter_id"], row["class_level"])
        chapters.append(
            {
                **chapter,
                "question_count": row["question_count"],
                "class_level": row["class_level"],
            }
        )
    picks = selected or {}
    selected_ids = {
        str(item) for item in (picks.get("chapter_ids") or []) if str(item).strip()
    }
    count = _int_or(picks.get("count"), CUSTOM_COUNT_DEFAULT)
    difficulty = str(picks.get("difficulty") or "mixed")
    duration_s = _int_or(picks.get("duration_s"), DURATION_DEFAULT)
    return {
        "state": "ok" if chapters else "empty",
        "data_error": None,
        "class_level": user.class_level,
        "language": options["language"],
        "language_note": _language_note(user, options["language"]),
        "chapters": chapters,
        "has_bank": bool(chapters),
        "selected_ids": selected_ids,
        "count": count,
        "difficulty": difficulty if difficulty in DIFFICULTY_LABELS else "mixed",
        "duration_s": duration_s,
        "count_choices": COUNT_CHOICES,
        "minute_choices": MINUTE_CHOICES,
        "difficulties": [
            {"value": key, "label": label} for key, label in DIFFICULTY_LABELS.items()
        ],
        "estimated_marks": count,
        "estimated_marks_label": f"Up to {marks_label(count)}",
        "error": picks.get("error"),
    }


def safe_builder_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    frontend_dir: str,
    selected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return build_builder_view(
            db,
            user_row=user_row,
            frontend_dir=frontend_dir,
            selected=selected,
        )
    except Exception:
        logger.exception("test builder read failed")
        return {
            "state": "error",
            "data_error": DATA_ERROR,
            "class_level": None,
            "language": "en",
            "language_note": None,
            "chapters": [],
            "has_bank": False,
            "selected_ids": set(),
            "count": CUSTOM_COUNT_DEFAULT,
            "difficulty": "mixed",
            "duration_s": DURATION_DEFAULT,
            "count_choices": COUNT_CHOICES,
            "minute_choices": MINUTE_CHOICES,
            "difficulties": [
                {"value": key, "label": label}
                for key, label in DIFFICULTY_LABELS.items()
            ],
            "estimated_marks": 0,
            "estimated_marks_label": "",
            "error": None,
        }


def _int_or(value: object, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


# --- player -----------------------------------------------------------------


def _options(question: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"index": index, "text": str(text)}
        for index, text in enumerate(question.get("options") or [])
    ]


def _palette(
    questions: list[Mapping[str, Any]],
    answers: Mapping[str, Mapping[str, Any]],
    *,
    current: int | None,
    attempt_id: str,
) -> list[dict[str, Any]]:
    palette = []
    for index, question in enumerate(questions):
        saved = answers.get(str(question["question_id"])) or {}
        answered = bool(saved.get("answer"))
        flagged = bool(saved.get("flagged"))
        if answered and flagged:
            state, label = "answered-flagged", "Answered, marked"
        elif answered:
            state, label = "answered", "Answered"
        elif flagged:
            state, label = "flagged", "Marked for review"
        else:
            state, label = "unanswered", "Not answered"
        palette.append(
            {
                "number": index + 1,
                "question_id": str(question["question_id"]),
                "href": f"/app/tests/{attempt_id}?q={question['question_id']}",
                "state": state,
                "state_label": label,
                "current": index == current,
            }
        )
    return palette


def _answer_kind(question: Mapping[str, Any]) -> str:
    return "value" if question.get("type") == "numeric" else "index"


def _saved_choice(
    question: Mapping[str, Any], saved: Mapping[str, Any] | None
) -> dict[str, Any]:
    answer = (saved or {}).get("answer") or {}
    return {
        "index": answer.get("index"),
        "value": answer.get("value"),
    }


def build_player_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    attempt_id: str,
    frontend_dir: str,
    question_id: str | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return one player screen: the clock, palette, and the key-free question."""
    user = test_user(user_row)
    state = attempt_state(
        db, user, attempt_id=attempt_id, question_id=question_id, now=now
    )
    if state is None:
        return {"state": "missing"}
    if state["submitted"]:
        return {
            "state": "submitted",
            "attempt": state["attempt"],
            "test": state["test"],
            "href": f"/app/tests/{attempt_id}/review",
        }
    snapshot = catalogue_snapshot(db, frontend_dir)
    question = state["question"]
    questions = state["questions"]
    palette = _palette(
        questions, state["answers"], current=state["index"], attempt_id=attempt_id
    )
    current = state["index"] + 1 if state["index"] is not None else 0
    saved = state["answers"].get(str(question["question_id"])) if question else None
    chapter = (
        _chapter_entry(snapshot, str(question["chapter_id"]), None)
        if question
        else None
    )
    structure = state["structure"]
    return {
        "state": "ok",
        "attempt": state["attempt"],
        "test": state["test"],
        "series": state["series"],
        "kind": str(
            structure.get("source")
            or ("series" if state["test"].get("series_id") else "custom")
        ),
        "kind_label": (
            "Series paper"
            if state["test"].get("series_id")
            else {
                "chapter": "Chapter test",
                "custom": "Custom test",
                "retry": "Retry mistakes",
            }.get(str(structure.get("source")), "Test")
        ),
        "question": question,
        "options": _options(question) if question else [],
        "answer_kind": _answer_kind(question) if question else "index",
        "saved": _saved_choice(question, saved) if question else {},
        "flagged": bool((saved or {}).get("flagged")),
        "saved_time_ms": int((saved or {}).get("time_ms") or 0),
        "index": current,
        "count": len(questions),
        "counts": state["counts"],
        "palette": palette,
        "prev_href": (
            palette[state["index"] - 1]["href"]
            if state["index"] is not None and state["index"] > 0
            else None
        ),
        "next_href": (
            palette[state["index"] + 1]["href"]
            if state["index"] is not None and state["index"] + 1 < len(palette)
            else None
        ),
        "timer": {
            "remaining_s": state["remaining_s"],
            "label": format_remaining(state["remaining_s"]),
            "deadline": state["deadline"].isoformat(),
            "expired": state["expired"],
        },
        "expired": state["expired"],
        "section": (question or {}).get("section"),
        "marks_label": marks_label((question or {}).get("marks")),
        "type_label": _question_type_label(question),
        "chapter": chapter,
        "lesson_url": (chapter or {}).get("lesson_url"),
        "language": state["language"],
        "language_note": _language_note(user, state["language"]),
        "structure": structure,
        "submit_href": f"/app/tests/{attempt_id}/submit",
        "answer_action": f"/app/tests/{attempt_id}/answer",
        "review_href": f"/app/tests/{attempt_id}/review",
        "attempt_id": attempt_id,
        "title": str(state["test"].get("title") or "Test"),
        "total_marks": state["test"].get("total_marks"),
        "duration_label": duration_label(int(state["test"].get("duration_s") or 0)),
    }


def _question_type_label(question: Mapping[str, Any] | None) -> str:
    if not question:
        return ""
    return QUESTION_TYPE_LABELS.get(str(question.get("type")), "Question")


def safe_player_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    attempt_id: str,
    frontend_dir: str,
    question_id: str | None = None,
) -> dict[str, Any]:
    try:
        return build_player_view(
            db,
            user_row=user_row,
            attempt_id=attempt_id,
            frontend_dir=frontend_dir,
            question_id=question_id,
        )
    except AssessmentError as exc:
        logger.warning("test player refused: %s", exc.code)
        return {
            "state": "error",
            "message": _assessment_copy(exc),
            "attempt_id": attempt_id,
            "status_code": 409,
        }
    except Exception:
        logger.exception("test player read failed")
        return {"state": "error", "message": DATA_ERROR, "attempt_id": attempt_id}


# --- submit confirmation ----------------------------------------------------


def build_confirm_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    attempt_id: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    user = test_user(user_row)
    state = attempt_state(db, user, attempt_id=attempt_id, now=now)
    if state is None:
        return {"state": "missing"}
    if state["submitted"]:
        return {"state": "submitted", "href": f"/app/tests/{attempt_id}/review"}
    questions = state["questions"]
    answers = state["answers"]
    unanswered = [
        index + 1
        for index, question in enumerate(questions)
        if not (answers.get(str(question["question_id"])) or {}).get("answer")
    ]
    flagged = [
        index + 1
        for index, question in enumerate(questions)
        if (answers.get(str(question["question_id"])) or {}).get("flagged")
    ]
    return {
        "state": "ok",
        "attempt_id": attempt_id,
        "title": str(state["test"].get("title") or "Test"),
        "counts": state["counts"],
        "unanswered_numbers": unanswered,
        "flagged_numbers": flagged,
        "expired": state["expired"],
        "remaining_label": format_remaining(state["remaining_s"]),
        "submit_href": f"/app/tests/{attempt_id}/submit",
        "back_href": f"/app/tests/{attempt_id}",
        "series": state["series"],
    }


def safe_confirm_view(
    db: Any, *, user_row: Mapping[str, Any], attempt_id: str
) -> dict[str, Any]:
    try:
        return build_confirm_view(db, user_row=user_row, attempt_id=attempt_id)
    except AssessmentError as exc:
        logger.warning("test submit confirmation refused: %s", exc.code)
        return {"state": "error", "message": _assessment_copy(exc), "status_code": 409}
    except Exception:
        logger.exception("test submit confirmation read failed")
        return {"state": "error", "message": DATA_ERROR}


# --- review -----------------------------------------------------------------


def build_review_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    attempt_id: str,
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return the post-submit review; the key is allowed only here."""
    user = test_user(user_row)
    review = review_state(db, user, attempt_id=attempt_id)
    if review is None:
        return {"state": "missing"}
    if review.get("state") == "not_submitted":
        return {"state": "not_submitted", "attempt_id": attempt_id}
    current = now or utc_now()
    snapshot = catalogue_snapshot(db, frontend_dir)
    questions = []
    for entry in review["questions"]:
        chapter = _chapter_entry(snapshot, str(entry.get("chapter_id") or ""), None)
        answered = bool(entry.get("answered"))
        correct = entry.get("correct")
        if not answered:
            result, result_label = "unanswered", "Not answered"
        elif correct:
            result, result_label = "correct", "Correct"
        else:
            result, result_label = "wrong", "Incorrect"
        if entry.get("flagged") and not answered:
            result_label = "Not answered, marked"
        questions.append(
            {
                **entry,
                "number": int(entry.get("order_index") or 0),
                "chapter_title": chapter["title"],
                "lesson_url": chapter["lesson_url"],
                "concept_title": concept_title(
                    entry.get("concept_id"), entry.get("chapter_id")
                ),
                "result": result,
                "result_label": result_label,
                "marks_label": marks_label(entry.get("marks")),
                "awarded_label": marks_label(entry.get("marks_awarded") or 0),
            }
        )
    concepts = [
        {
            **entry,
            "title": concept_title(entry.get("concept_id"), None),
        }
        for entry in review["concepts"]
    ]
    chapters = [
        {
            **entry,
            "title": _chapter_entry(snapshot, str(entry.get("chapter_id") or ""), None)[
                "title"
            ],
        }
        for entry in review["chapters"]
    ]
    summary = dict(review["summary"])
    summary["earned_label"] = _mark_text(summary.get("earned"))
    summary["possible_label"] = _mark_text(summary.get("possible"))
    summary["score_label"] = (
        f"{float(summary['score']):g}%"
        if isinstance(summary.get("score"), (int, float))
        else None
    )
    summary["accuracy_label"] = (
        f"{float(summary['accuracy_pct']):g}%"
        if isinstance(summary.get("accuracy_pct"), (int, float))
        else None
    )
    summary["time_label"] = _time_text(summary.get("time_spent_s"))
    return {
        "state": "review",
        "attempt": review["attempt"],
        "test": review["test"],
        "series": review["series"],
        "title": str(review["test"].get("title") or "Test"),
        "summary": summary,
        "counts": review["counts"],
        "concepts": concepts,
        "chapters": chapters,
        "questions": questions,
        "notice": (review["series"] or {}).get("notice"),
        "series_blurb": (review["series"] or {}).get("blurb"),
        "language": review["language"],
        "language_note": _language_note(user, review["language"]),
        "when": relative_day(
            _parse_iso(review["attempt"].get("submitted_at")), current
        ),
        "retry_available": bool(review["missed_question_ids"]),
        "missed_count": len(review["missed_question_ids"]),
        "attempt_id": attempt_id,
    }


def _mark_text(value: object) -> str:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return "0"
    return f"{number:g}"


def _time_text(value: object) -> str:
    if not isinstance(value, int) or value < 0:
        return "—"
    return f"{value // 60} min {value % 60} s"


def safe_review_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    attempt_id: str,
    frontend_dir: str,
) -> dict[str, Any]:
    try:
        return build_review_view(
            db,
            user_row=user_row,
            attempt_id=attempt_id,
            frontend_dir=frontend_dir,
        )
    except AssessmentError as exc:
        logger.warning("test review refused: %s", exc.code)
        return {
            "state": "error",
            "message": _assessment_copy(exc),
            "attempt_id": attempt_id,
            "status_code": 409,
        }
    except Exception:
        logger.exception("test review read failed")
        return {"state": "error", "message": DATA_ERROR, "attempt_id": attempt_id}


# --- history ----------------------------------------------------------------


def build_history_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    frontend_dir: str,
    status: str | None = None,
    kind: str | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    user = test_user(user_row)
    snapshot = catalogue_snapshot(db, frontend_dir)
    payload = test_history(db, user, status=status, kind=kind)
    items = []
    for item in payload["items"]:
        chapters = [
            _chapter_entry(snapshot, chapter_id, None)["title"]
            for chapter_id in item.get("chapter_ids") or []
        ]
        score = item.get("score")
        items.append(
            {
                **item,
                "when": relative_day(_parse_iso(item.get("started_at")), current),
                "score_label": f"{score:g}%"
                if isinstance(score, (int, float))
                else None,
                "href": (
                    f"/app/tests/{item['attempt_id']}"
                    if item["status"] == "in_progress"
                    else f"/app/tests/{item['attempt_id']}/review"
                ),
                "chapters_label": ", ".join(chapters[:2])
                + (" +" + str(len(chapters) - 2) if len(chapters) > 2 else ""),
                "can_resume": item["status"] == "in_progress",
            }
        )
    return {
        "data_error": None,
        "attempts": items,
        "count": payload["count"],
        "status_filter": payload["status_filter"],
        "kind_filter": payload["kind_filter"],
        "filters": payload["filters"],
        "retry": payload["retry"],
    }


def safe_history_view(
    db: Any,
    *,
    user_row: Mapping[str, Any],
    frontend_dir: str,
    status: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    try:
        return build_history_view(
            db,
            user_row=user_row,
            frontend_dir=frontend_dir,
            status=status,
            kind=kind,
        )
    except Exception:
        logger.exception("test history read failed")
        return {
            "data_error": DATA_ERROR,
            "attempts": [],
            "count": 0,
            "status_filter": status,
            "kind_filter": kind,
            "filters": {"statuses": [], "kinds": []},
            "retry": {"available": False, "count": 0},
        }


# --- series -----------------------------------------------------------------


def build_series_catalogue_view(
    db: Any, *, user_row: Mapping[str, Any]
) -> dict[str, Any]:
    user = test_user(user_row)
    catalogue = series_catalogue(db, user)
    for card in catalogue["cards"]:
        card["href"] = f"/app/series/{card['slug']}"
        card["language_label"] = " + ".join(
            LANGUAGE_LABELS.get(language, language) for language in card["languages"]
        )
    return {
        "data_error": None,
        **catalogue,
    }


def safe_series_catalogue_view(
    db: Any, *, user_row: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        return build_series_catalogue_view(db, user_row=user_row)
    except Exception:
        logger.exception("series catalogue read failed")
        return {
            "data_error": DATA_ERROR,
            "class_level": None,
            "cards": [],
            "chapter_count": 0,
            "notice": None,
            "status_counts": {"live": 0, "pending": 0},
        }


def build_series_detail_view(
    db: Any, *, user_row: Mapping[str, Any], slug: str
) -> dict[str, Any]:
    user = test_user(user_row)
    detail = series_detail(db, user, slug=slug)
    if detail is None:
        return {"state": "missing"}
    for paper in detail["papers"]:
        paper["marks_label"] = marks_label(paper.get("total_marks"))
        paper["duration_label"] = duration_label(int(paper.get("duration_s") or 0))
        paper["start_action"] = f"/app/series/{slug}/start"
        paper["resume_href"] = (
            f"/app/tests/{paper['live_attempt_id']}"
            if paper.get("live_attempt_id")
            else None
        )
    definition = detail["definition"]
    return {
        "state": "ok",
        "data_error": None,
        **detail,
        "slug": slug,
        "label": detail["label"],
        "definition": definition,
        "back_href": "/app/series",
        "tests_href": "/app/tests",
    }


def safe_series_detail_view(
    db: Any, *, user_row: Mapping[str, Any], slug: str
) -> dict[str, Any]:
    try:
        return build_series_detail_view(db, user_row=user_row, slug=slug)
    except Exception:
        logger.exception("series detail read failed")
        return {"state": "error", "message": DATA_ERROR, "slug": slug}


__all__ = [
    "COUNT_CHOICES",
    "DATA_ERROR",
    "MINUTE_CHOICES",
    "PRESETS",
    "build_builder_view",
    "build_confirm_view",
    "build_history_view",
    "build_hub_view",
    "build_player_view",
    "build_review_view",
    "build_series_catalogue_view",
    "build_series_detail_view",
    "concept_title",
    "humanize_id",
    "relative_day",
    "safe_builder_view",
    "safe_confirm_view",
    "safe_history_view",
    "safe_hub_view",
    "safe_player_view",
    "safe_review_view",
    "safe_series_catalogue_view",
    "safe_series_detail_view",
]
