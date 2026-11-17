"""Template view models for the dashboard, progress map, and bookmarks pages.

These functions are pure read paths over the progress domain; the route only
adds the shell context. Each `safe_*` wrapper catches a store failure and
returns a page-level error view so a broken study log never turns the whole
page into a 500 and never invents data to fill the gap.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.progress import (
    INDIA_TZ,
    STATE_LABELS,
    build_progress_map,
    build_summary,
    catalogue_snapshot,
    decorate_bookmarks,
    list_bookmarks,
    list_events,
    list_lesson_progress,
    utc_now,
)

logger = logging.getLogger(__name__)

ACTIVITY_LABELS: dict[str, str] = {
    "lesson_block_view": "Read a section",
    "lesson_complete": "Finished a chapter",
    "practice_answer": "Answered a practice question",
    "test_submit": "Submitted a test",
    "speaking_attempt": "Recorded an explain-back",
    "bookmark_add": "Saved a section",
    "bookmark_remove": "Removed a saved section",
}
DATA_ERROR = (
    "The study log could not be read just now. Your saved reading is not lost; "
    "this page will show it again on the next successful load."
)
NEXT_STEPS: dict[str, str] = {
    "not_started": "Open the chapter to start.",
    "learning": "Finish the section checks. Practice arrives with its own release.",
    "practising": "Keep practising: 5 answers at 80% or better marks the chapter Confident.",
    "confident": "Keep it warm: revisit a check now and then.",
    "needs_revision": "Re-read the sections and retry the checks in the chapter.",
}


def build_dashboard_view(
    db: Any,
    *,
    user_id: str,
    user_class: int | None,
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return the dashboard view model (or raise; callers use `safe_*`)."""
    current = now or utc_now()
    snapshot = catalogue_snapshot(db, frontend_dir)
    events = list_events(db, user_id)
    progress_rows = list_lesson_progress(db, user_id)
    bookmarks = list_bookmarks(db, user_id)
    summary = build_summary(
        events=events,
        progress_rows=progress_rows,
        bookmark_count=len(bookmarks),
        snapshot=snapshot,
        now=current,
    )
    class_chapters = list(snapshot.class_chapters(user_class))
    class_group = next(
        (group for group in summary["classes"] if group["class_level"] == user_class),
        None,
    )
    map_chapters = list(class_group["chapters"][:4]) if class_group else []
    first_chapter = _first_published(class_chapters)
    continue_item = summary["continue"]
    if continue_item:
        continue_item = dict(continue_item)
        continue_item["when"] = _relative_day(
            _parse_iso(continue_item.get("last_activity_at")), current
        )
        # The shared `progress_macros.section_progress` renders `blocks_*`; the
        # API names the same fact `sections_*` on the continue card.
        continue_item["blocks_seen"] = int(continue_item.get("sections_seen") or 0)
        continue_item["blocks_total"] = continue_item.get("sections_total")
    return {
        "greeting": _greeting(current),
        "is_new": summary["is_new"],
        "data_error": None,
        "continue_chapter": continue_item,
        "plan": _plan(summary, first_chapter, user_class),
        "weekly": summary["weekly"],
        "counts": summary["counts"],
        "recent": _recent(summary["recent"], current),
        "map_chapters": map_chapters,
        "map_class": user_class,
        "class_chapters_total": len(class_chapters),
        "first_chapter": first_chapter,
        "bookmark_count": len(bookmarks),
        "catalogue_source": snapshot.source,
        "catalogue_unavailable": snapshot.source == "fixture" and not snapshot.chapters,
    }


def build_progress_view(
    db: Any,
    *,
    user_id: str,
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return the class -> chapter -> concept map for `/app/progress`."""
    current = now or utc_now()
    snapshot = catalogue_snapshot(db, frontend_dir)
    payload = build_progress_map(
        events=list_events(db, user_id),
        progress_rows=list_lesson_progress(db, user_id),
        snapshot=snapshot,
        now=current,
        include_concepts=True,
    )
    classes = payload["classes"]
    for group in classes:
        for chapter in group["chapters"]:
            chapter["next_step"] = NEXT_STEPS[chapter["state"]]
            for concept in chapter.get("concepts", []):
                concept["next_step"] = NEXT_STEPS[concept["state"]]
    return {
        "data_error": None,
        "is_new": payload["is_new"],
        "rules": payload["rules"],
        "classes": classes,
        "has_concepts": any(
            chapter.get("concepts_available")
            for group in classes
            for chapter in group["chapters"]
        ),
        "has_unmatched": any(
            chapter["status"] == "unmatched"
            for group in classes
            for chapter in group["chapters"]
        ),
        "catalogue_source": snapshot.source,
        "state_labels": STATE_LABELS,
    }


def build_bookmarks_view(
    db: Any,
    *,
    user_id: str,
    frontend_dir: str,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Return the saved-items view for `/app/bookmarks`."""
    current = now or utc_now()
    snapshot = catalogue_snapshot(db, frontend_dir)
    saved = decorate_bookmarks(list_bookmarks(db, user_id), snapshot)
    for item in saved:
        item["when"] = _relative_day(_parse_iso(item.get("created_at")), current)
    return {
        "data_error": None,
        "saved": saved,
        "count": len(saved),
        "catalogue_source": snapshot.source,
    }


def safe_dashboard_view(
    db: Any,
    *,
    user_id: str,
    user_class: int | None,
    frontend_dir: str,
) -> dict[str, Any]:
    now = utc_now()
    try:
        return build_dashboard_view(
            db,
            user_id=user_id,
            user_class=user_class,
            frontend_dir=frontend_dir,
            now=now,
        )
    except Exception:
        logger.exception("dashboard view failed")
        return {
            "greeting": _greeting(now),
            "is_new": False,
            "data_error": DATA_ERROR,
        }


def safe_progress_view(db: Any, *, user_id: str, frontend_dir: str) -> dict[str, Any]:
    now = utc_now()
    try:
        return build_progress_view(
            db, user_id=user_id, frontend_dir=frontend_dir, now=now
        )
    except Exception:
        logger.exception("progress view failed")
        return {"data_error": DATA_ERROR}


def safe_bookmarks_view(db: Any, *, user_id: str, frontend_dir: str) -> dict[str, Any]:
    now = utc_now()
    try:
        return build_bookmarks_view(
            db, user_id=user_id, frontend_dir=frontend_dir, now=now
        )
    except Exception:
        logger.exception("bookmarks view failed")
        return {"data_error": DATA_ERROR}


def _first_published(chapters: list[Any]) -> dict[str, Any] | None:
    for chapter in chapters:
        if chapter.lesson_url:
            return {
                "chapter_id": chapter.chapter_id,
                "title": chapter.title,
                "lesson_url": chapter.lesson_url,
            }
    return None


def _plan(
    summary: dict[str, Any],
    first_chapter: dict[str, Any] | None,
    user_class: int | None,
) -> dict[str, Any]:
    continue_item = summary["continue"]
    if continue_item and continue_item.get("lesson_url"):
        if summary["weekly"]["today_active"]:
            title = "You studied today."
            text = "When you are ready, pick up where you stopped."
        else:
            title = "Pick up where you left off."
            text = "A short read is enough for today."
        return {
            "title": title,
            "text": text,
            "chapter": continue_item["title"],
            "href": continue_item["lesson_url"],
            "action": "Continue the chapter",
        }
    if first_chapter:
        return {
            "title": "Start your first chapter.",
            "text": "Read a section, try its check, and come back.",
            "chapter": first_chapter["title"],
            "href": first_chapter["lesson_url"],
            "action": "Open the chapter",
        }
    if user_class is None:
        text = (
            "Your class is not set yet. Open the catalogue and choose a chapter "
            "to begin."
        )
    else:
        text = (
            f"No Class {user_class} chapter is published yet. The catalogue "
            "shows every chapter that is live."
        )
    return {
        "title": "Nothing to plan yet.",
        "text": text,
        "chapter": None,
        "href": "/courses",
        "action": "Open the catalogue",
    }


def _recent(
    items: list[dict[str, Any]], now: datetime.datetime
) -> list[dict[str, Any]]:
    recent = []
    for item in items:
        recent.append(
            {
                **item,
                "label": ACTIVITY_LABELS.get(item["kind"], "Activity"),
                "when": _relative_day(_parse_iso(item.get("created_at")), now),
            }
        )
    return recent


def _greeting(now: datetime.datetime) -> str:
    hour = now.astimezone(INDIA_TZ).hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


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


def _relative_day(value: datetime.datetime | None, now: datetime.datetime) -> str:
    if value is None:
        return ""
    local = value.astimezone(INDIA_TZ).date()
    today = now.astimezone(INDIA_TZ).date()
    delta = (today - local).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta < 7:
        return local.strftime("%a")
    return local.strftime("%d %b")


__all__ = [
    "ACTIVITY_LABELS",
    "DATA_ERROR",
    "build_bookmarks_view",
    "build_dashboard_view",
    "build_progress_view",
    "safe_bookmarks_view",
    "safe_dashboard_view",
    "safe_progress_view",
]
