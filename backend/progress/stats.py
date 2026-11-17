"""Aggregation for the dashboard, progress map, and chapter evidence (F3).

Five states, computed only from the student's own events. The rules are
deterministic, published on `/app/progress`, and versioned here so a copy
change never silently changes a verdict:

- **Not started**: no event for the chapter/concept.
- **Learning**: lesson activity only (sections read, chapter opened/finished).
- **Practising**: at least one practice answer, test, or explain-back, but not
  yet confident.
- **Confident**: 5+ practice answers, 80%+ correct, and at least 2 of the last
  3 correct.
- **Needs revision**: 3+ practice answers and under 50% correct.

There is no ability score, no ranking, and no comparison with another student.
Tests and explain-backs count as practice activity but do not move the
accuracy figure; only practice answers carry a correct/incorrect bit today.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any, Final

from .catalog import CatalogueSnapshot, ChapterMeta
from .store import EventRow, as_utc, to_iso

RULES_VERSION: Final[int] = 1
WEEKLY_GOAL_DAYS: Final[int] = 4
INDIA_TZ: Final[datetime.tzinfo] = datetime.timezone(
    datetime.timedelta(hours=5, minutes=30), "IST"
)
CONFIDENT_MIN_ANSWERS: Final[int] = 5
CONFIDENT_MIN_ACCURACY_PCT: Final[int] = 80
CONFIDENT_RECENT_WINDOW: Final[int] = 3
CONFIDENT_RECENT_MIN_CORRECT: Final[int] = 2
REVISION_MIN_ANSWERS: Final[int] = 3
REVISION_MAX_ACCURACY_PCT: Final[int] = 50

STATE_LABELS: Final[dict[str, str]] = {
    "not_started": "Not started",
    "learning": "Learning",
    "practising": "Practising",
    "confident": "Confident",
    "needs_revision": "Needs revision",
}
RULES: Final[dict[str, int]] = {
    "version": RULES_VERSION,
    "confident_min_answers": CONFIDENT_MIN_ANSWERS,
    "confident_min_accuracy_pct": CONFIDENT_MIN_ACCURACY_PCT,
    "confident_recent_window": CONFIDENT_RECENT_WINDOW,
    "confident_recent_min_correct": CONFIDENT_RECENT_MIN_CORRECT,
    "revision_min_answers": REVISION_MIN_ANSWERS,
    "revision_max_accuracy_pct": REVISION_MAX_ACCURACY_PCT,
    "weekly_goal_days": WEEKLY_GOAL_DAYS,
}

_PRACTICE_KINDS: Final[frozenset[str]] = frozenset(
    {"practice_answer", "test_submit", "speaking_attempt"}
)


def build_summary(
    *,
    events: list[EventRow],
    progress_rows: list[dict[str, Any]],
    bookmark_count: int,
    snapshot: CatalogueSnapshot,
    now: datetime.datetime,
) -> dict[str, Any]:
    """Return the `/v1/progress/summary` payload."""
    counters = _counters(progress_rows)
    events_by_chapter = _events_by_chapter(events)
    classes = _map_entries(events_by_chapter, snapshot, counters, now)
    continue_chapter = _continue_chapter(events, progress_rows, snapshot, now)
    weekly = _weekly(events, now)
    counts = _counts(events, weekly, bookmark_count)
    recent = [_recent_item(event, snapshot) for event in events[:8]]
    return {
        "schema_version": 1,
        "rules_version": RULES_VERSION,
        "rules": RULES,
        "generated_at": to_iso(now),
        "is_new": not events,
        "weekly": weekly,
        "counts": counts,
        "continue": continue_chapter,
        "classes": classes,
        "recent": recent,
    }


def build_progress_map(
    *,
    events: list[EventRow],
    progress_rows: list[dict[str, Any]],
    snapshot: CatalogueSnapshot,
    now: datetime.datetime,
    include_concepts: bool = False,
) -> dict[str, Any]:
    """Return the class -> chapter entries for `/app/progress`."""
    counters = _counters(progress_rows)
    events_by_chapter = _events_by_chapter(events)
    return {
        "schema_version": 1,
        "rules_version": RULES_VERSION,
        "rules": RULES,
        "generated_at": to_iso(now),
        "is_new": not events,
        "classes": _map_entries(
            events_by_chapter,
            snapshot,
            counters,
            now,
            include_concepts=include_concepts,
        ),
    }


def build_chapter_detail(
    *,
    chapter_id: str,
    events: list[EventRow],
    progress_rows: list[dict[str, Any]],
    snapshot: CatalogueSnapshot,
    now: datetime.datetime,
) -> dict[str, Any] | None:
    """Return one chapter with per-concept states, or None when unknown."""
    meta = snapshot.chapters.get(chapter_id)
    chapter_events = [event for event in events if event.chapter_id == chapter_id]
    if meta is None and not chapter_events:
        return None
    counters = _counters(progress_rows)
    concepts, concepts_available = _concepts(meta, chapter_events)
    chapter = _chapter_entry(
        chapter_id,
        meta,
        chapter_events,
        counters.get(chapter_id),
        now,
    )
    chapter["concept_count"] = len(concepts)
    chapter["concepts_available"] = concepts_available
    chapter["catalogue_source"] = snapshot.source
    return {
        "schema_version": 1,
        "rules_version": RULES_VERSION,
        "rules": RULES,
        "generated_at": to_iso(now),
        "chapter": chapter,
        "concepts": concepts,
        "concepts_available": concepts_available,
    }


def decorate_bookmarks(
    rows: list[dict[str, Any]], snapshot: CatalogueSnapshot
) -> list[dict[str, Any]]:
    """Add chapter titles, lesson links, and type labels to bookmark rows."""
    items: list[dict[str, Any]] = []
    for row in rows:
        target_type = str(row["target_type"])
        target_id = str(row["target_id"])
        chapter_id, rest = _split_target(target_type, target_id)
        meta = snapshot.chapters.get(chapter_id)
        lesson_url = meta.lesson_url if meta else None
        if target_type == "block" and rest and lesson_url:
            lesson_url = f"{lesson_url}#{rest}"
        items.append(
            {
                **row,
                "chapter_id": chapter_id,
                "chapter_title": meta.title if meta else _humanize(chapter_id),
                "section_id": rest if target_type == "block" else None,
                "lesson_url": lesson_url,
                "label": {
                    "chapter": "Chapter",
                    "concept": "Concept",
                    "block": "Section",
                    "question": "Question",
                }[target_type],
            }
        )
    return items


def _map_entries(
    events_by_chapter: dict[str, list[EventRow]],
    snapshot: CatalogueSnapshot,
    counters: dict[str, dict[str, Any]],
    now: datetime.datetime,
    *,
    include_concepts: bool = False,
) -> list[dict[str, Any]]:
    classes: list[dict[str, Any]] = []
    listed: set[str] = set()
    for class_level, chapters in snapshot.classes:
        entries = []
        for meta in chapters:
            listed.add(meta.chapter_id)
            entries.append(
                _chapter_entry(
                    meta.chapter_id,
                    meta,
                    events_by_chapter.get(meta.chapter_id, []),
                    counters.get(meta.chapter_id),
                    now,
                    include_concepts=include_concepts,
                )
            )
        classes.append({"class_level": class_level, "chapters": entries})
    extras = sorted(
        chapter_id for chapter_id in events_by_chapter if chapter_id not in listed
    )
    if extras:
        classes.append(
            {
                "class_level": None,
                "chapters": [
                    _chapter_entry(
                        chapter_id,
                        None,
                        events_by_chapter[chapter_id],
                        counters.get(chapter_id),
                        now,
                        include_concepts=include_concepts,
                    )
                    for chapter_id in extras
                ],
            }
        )
    return classes


def _chapter_entry(
    chapter_id: str,
    meta: ChapterMeta | None,
    events: list[EventRow],
    counter: dict[str, Any] | None,
    now: datetime.datetime,
    *,
    include_concepts: bool = False,
) -> dict[str, Any]:
    del now  # the entry is a pure function of the stored times
    state, evidence = _state(events)
    blocks_seen = int(counter.get("blocks_seen") or 0) if counter else 0
    blocks_total = (
        int(counter["blocks_total"])
        if counter and counter.get("blocks_total") is not None
        else None
    )
    if blocks_seen == 0 and meta:
        blocks_seen = evidence["sections_seen"]
    entry: dict[str, Any] = {
        "chapter_id": chapter_id,
        "title": meta.title if meta else _humanize(chapter_id),
        "class_level": meta.class_level if meta else None,
        "chapter_no": meta.chapter_no if meta else 0,
        "slug": meta.slug if meta else "",
        "lesson_url": meta.lesson_url if meta else None,
        "status": meta.status if meta else "unmatched",
        "state": state,
        "state_label": STATE_LABELS[state],
        "blocks_seen": blocks_seen,
        "blocks_total": blocks_total,
        "evidence": evidence,
    }
    if include_concepts:
        concepts, concepts_available = _concepts(meta, events)
        entry["concepts"] = concepts
        entry["concepts_available"] = concepts_available
        entry["concept_count"] = len(concepts)
    return entry


def _concepts(
    meta: ChapterMeta | None, chapter_events: list[EventRow]
) -> tuple[list[dict[str, Any]], bool]:
    concept_events: dict[str, list[EventRow]] = defaultdict(list)
    for event in chapter_events:
        if event.concept_id:
            concept_events[event.concept_id].append(event)
    concepts: list[dict[str, Any]] = []
    listed: set[str] = set()
    for concept in meta.concepts if meta else ():
        listed.add(concept.concept_id)
        state, evidence = _state(concept_events.get(concept.concept_id, []))
        concepts.append(
            {
                "concept_id": concept.concept_id,
                "title": concept.title,
                "section_id": concept.section_id,
                "state": state,
                "state_label": STATE_LABELS[state],
                "evidence": evidence,
            }
        )
    for concept_id in sorted(concept_events):
        if concept_id in listed:
            continue
        state, evidence = _state(concept_events[concept_id])
        concepts.append(
            {
                "concept_id": concept_id,
                "title": _humanize(concept_id),
                "section_id": None,
                "state": state,
                "state_label": STATE_LABELS[state],
                "evidence": evidence,
            }
        )
    return concepts, bool(meta and meta.concepts)


def _state(events: list[EventRow]) -> tuple[str, dict[str, Any]]:
    if not events:
        return "not_started", _evidence([], [])
    ordered = sorted(events, key=lambda event: (event.created_at, event.event_id))
    answers = [
        bool(event.payload.get("correct"))
        for event in ordered
        if event.kind == "practice_answer"
        and isinstance(event.payload.get("correct"), bool)
    ]
    lesson_events = [
        event
        for event in ordered
        if event.kind in ("lesson_block_view", "lesson_complete")
    ]
    practice_activity = any(event.kind in _PRACTICE_KINDS for event in ordered)
    sections = {
        str(event.payload["section_id"])
        for event in lesson_events
        if event.payload.get("section_id")
    }
    sections_seen = max(
        [len(sections)]
        + [
            int(event.payload["blocks_seen"])
            for event in lesson_events
            if isinstance(event.payload.get("blocks_seen"), int)
        ]
    )
    answers_count = len(answers)
    correct = sum(1 for value in answers if value)
    accuracy = round(correct * 100 / answers_count) if answers_count else None
    recent = answers[-CONFIDENT_RECENT_WINDOW:]
    state = "learning"
    if answers_count >= REVISION_MIN_ANSWERS and (
        accuracy is not None and accuracy < REVISION_MAX_ACCURACY_PCT
    ):
        state = "needs_revision"
    elif (
        answers_count >= CONFIDENT_MIN_ANSWERS
        and accuracy is not None
        and accuracy >= CONFIDENT_MIN_ACCURACY_PCT
        and sum(1 for value in recent if value) >= CONFIDENT_RECENT_MIN_CORRECT
    ):
        state = "confident"
    elif practice_activity or answers_count:
        state = "practising"
    return state, _evidence(ordered, answers, sections_seen=sections_seen)


def _evidence(
    events: list[EventRow],
    answers: list[bool],
    *,
    sections_seen: int = 0,
) -> dict[str, Any]:
    answers_count = len(answers)
    correct = sum(1 for value in answers if value)
    concepts = {event.concept_id for event in events if event.concept_id}
    last = events[-1].created_at if events else None
    return {
        "events": len(events),
        "sections_seen": sections_seen,
        "practice_answers": answers_count,
        "practice_correct": correct,
        "accuracy_pct": (
            round(correct * 100 / answers_count) if answers_count else None
        ),
        "concepts_touched": len(concepts),
        "last_activity_at": to_iso(last) if last else None,
    }


def _events_by_chapter(events: list[EventRow]) -> dict[str, list[EventRow]]:
    grouped: dict[str, list[EventRow]] = defaultdict(list)
    for event in events:
        if event.chapter_id:
            grouped[str(event.chapter_id)].append(event)
    return grouped


def _counters(progress_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["chapter_id"]): row for row in progress_rows}


def _continue_chapter(
    events: list[EventRow],
    progress_rows: list[dict[str, Any]],
    snapshot: CatalogueSnapshot,
    now: datetime.datetime,
) -> dict[str, Any] | None:
    del now
    latest_by_chapter: dict[str, datetime.datetime] = {}
    sections_by_chapter: dict[str, set[str]] = defaultdict(set)
    for event in events:  # newest first
        if not event.chapter_id:
            continue
        # A saved section is engagement, not reading: it must not create a
        # "continue reading" card on a chapter the student never opened.
        if event.kind not in ("lesson_block_view", "lesson_complete"):
            continue
        chapter_id = str(event.chapter_id)
        latest_by_chapter.setdefault(chapter_id, event.created_at)
        if event.payload.get("section_id"):
            sections_by_chapter[chapter_id].add(str(event.payload["section_id"]))
    for row in progress_rows:
        if str(row.get("status")) == "completed":
            continue
        chapter_id = str(row["chapter_id"])
        meta = snapshot.chapters.get(chapter_id)
        updated = as_utc(row.get("updated_at"))
        return {
            "chapter_id": chapter_id,
            "title": meta.title if meta else _humanize(chapter_id),
            "lesson_url": meta.lesson_url if meta else None,
            "class_level": meta.class_level if meta else None,
            "sections_seen": (
                int(row.get("blocks_seen") or 0)
                or len(sections_by_chapter.get(chapter_id, ()))
            ),
            "sections_total": (
                int(row["blocks_total"])
                if row.get("blocks_total") is not None
                else None
            ),
            "last_activity_at": (
                to_iso(updated)
                if updated
                else (
                    to_iso(latest_by_chapter[chapter_id])
                    if chapter_id in latest_by_chapter
                    else None
                )
            ),
        }
    completed = {
        str(row["chapter_id"])
        for row in progress_rows
        if str(row.get("status")) == "completed"
    }
    for chapter_id, latest in latest_by_chapter.items():
        if chapter_id in completed:
            continue
        meta = snapshot.chapters.get(chapter_id)
        return {
            "chapter_id": chapter_id,
            "title": meta.title if meta else _humanize(chapter_id),
            "lesson_url": meta.lesson_url if meta else None,
            "class_level": meta.class_level if meta else None,
            "sections_seen": len(sections_by_chapter.get(chapter_id, ())),
            "sections_total": None,
            "last_activity_at": to_iso(latest),
        }
    return None


def _weekly(events: list[EventRow], now: datetime.datetime) -> dict[str, Any]:
    today = now.astimezone(INDIA_TZ).date()
    start = today - datetime.timedelta(days=6)
    active_dates = {event.created_at.astimezone(INDIA_TZ).date() for event in events}
    days = []
    for offset in range(7):
        day = start + datetime.timedelta(days=offset)
        days.append(
            {
                "date": day.isoformat(),
                "weekday": day.strftime("%a"),
                "initial": day.strftime("%a")[0],
                "active": day in active_dates,
                "is_today": day == today,
            }
        )
    return {
        "goal_days": WEEKLY_GOAL_DAYS,
        "days_active": sum(1 for day in days if day["active"]),
        "today_active": today in active_dates,
        "days": days,
    }


def _counts(
    events: list[EventRow], weekly: dict[str, Any], bookmark_count: int
) -> dict[str, Any]:
    started = {str(event.chapter_id) for event in events if event.chapter_id}
    completed = {
        str(event.chapter_id)
        for event in events
        if event.chapter_id and event.kind == "lesson_complete"
    }
    practice_7d = 0
    start_dates = {day["date"] for day in weekly["days"]}
    for event in events:
        if event.kind != "practice_answer":
            continue
        if event.created_at.astimezone(INDIA_TZ).date().isoformat() in start_dates:
            practice_7d += 1
    return {
        "chapters_started": len(started),
        "chapters_completed": len(completed),
        "practice_answers_7d": practice_7d,
        "active_days_7d": weekly["days_active"],
        "bookmarks": bookmark_count,
    }


def _recent_item(event: EventRow, snapshot: CatalogueSnapshot) -> dict[str, Any]:
    chapter_id = str(event.chapter_id) if event.chapter_id else None
    meta = snapshot.chapters.get(chapter_id) if chapter_id else None
    return {
        "kind": event.kind,
        "chapter_id": chapter_id,
        "chapter_title": (
            meta.title if meta else (_humanize(chapter_id) if chapter_id else None)
        ),
        "concept_id": event.concept_id,
        "created_at": to_iso(event.created_at),
    }


def _split_target(target_type: str, target_id: str) -> tuple[str, str | None]:
    if target_type == "chapter":
        return target_id, None
    chapter_id, _, rest = target_id.partition(":")
    return chapter_id, rest or None


def _humanize(chapter_id: str | None) -> str:
    raw = str(chapter_id or "").strip()
    if not raw:
        return "Untitled chapter"
    tail = raw.replace(":", "/").rstrip("/").split("/")[-1]
    words = tail.replace("-", " ").replace("_", " ").strip()
    if not words:
        return raw
    text = " ".join(words.split())
    return text[:1].upper() + text[1:]
