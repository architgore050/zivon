"""Progress domain for the dashboard and progress map (F3, REQUIREMENTS §8.4/§9.3).

The public entry points are re-exported here so the route and web-layer code
depend on one small surface. Nothing in this package talks to a model or a
vendor: it is deterministic SQL + local catalogue reads.
"""

from __future__ import annotations

from .catalog import CatalogueSnapshot, ChapterMeta, ConceptMeta, catalogue_snapshot
from .stats import (
    INDIA_TZ,
    RULES,
    RULES_VERSION,
    STATE_LABELS,
    WEEKLY_GOAL_DAYS,
    build_chapter_detail,
    build_progress_map,
    build_summary,
    decorate_bookmarks,
)
from .store import (
    BOOKMARK_TARGET_TYPES,
    EVENT_KINDS,
    EVENTS_BATCH_MAX,
    EventInput,
    EventRow,
    ProgressValidationError,
    add_bookmark,
    as_utc,
    list_bookmarks,
    list_events,
    list_lesson_progress,
    record_events,
    remove_bookmark,
    to_iso,
    utc_now,
    validate_bookmark_target,
    validate_chapter_id,
    validate_event,
)

__all__ = [
    "BOOKMARK_TARGET_TYPES",
    "EVENTS_BATCH_MAX",
    "EVENT_KINDS",
    "INDIA_TZ",
    "RULES",
    "RULES_VERSION",
    "STATE_LABELS",
    "WEEKLY_GOAL_DAYS",
    "CatalogueSnapshot",
    "ChapterMeta",
    "ConceptMeta",
    "EventInput",
    "EventRow",
    "ProgressValidationError",
    "add_bookmark",
    "as_utc",
    "build_chapter_detail",
    "build_progress_map",
    "build_summary",
    "catalogue_snapshot",
    "decorate_bookmarks",
    "list_bookmarks",
    "list_events",
    "list_lesson_progress",
    "record_events",
    "remove_bookmark",
    "to_iso",
    "utc_now",
    "validate_bookmark_target",
    "validate_chapter_id",
    "validate_event",
]
