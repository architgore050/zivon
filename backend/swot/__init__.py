"""SWOT domain (F8): relative placement of the student's own chapters.

The public entry points are re-exported here so the route and web-layer code
depend on one small surface. Nothing in this package talks to a model or a
vendor: it is deterministic SQL + local catalogue reads, and the all-student
time read is aggregate-only (no identity leaves `store.read_all_student_times`).

`gather_input` is the single seam that assembles `SwotInput` from the
database; routes and SSR views call it, tests can build `SwotInput` directly
for hermetic unit coverage.
"""

from __future__ import annotations

from typing import Any

from db.engine import DatabaseEngine

from ..progress.catalog import catalogue_snapshot
from . import store as swot_store
from .stats import (
    QUADRANT_BLURBS,
    QUADRANT_LABELS,
    SwotInput,
    SwotModeError,
    build_swot,
    build_swot_explain,
    resolve_mode,
    rules,
)

# The all-student time EWMA is only worth reading for chapters the student
# actually has time observations in (their own practice rows bound the set).
ALL_STUDENT_TIME_CHAPTER_CAP = 12


def gather_input(
    db: DatabaseEngine,
    *,
    user_id: str,
    frontend_dir: str,
    mode: str,
    now: Any | None = None,
) -> SwotInput:
    """Pre-fetch every read SWOT needs for one account (no writes, no model)."""
    snapshot = catalogue_snapshot(db, frontend_dir)
    events = swot_store.read_learner_events(db, user_id)
    speaking = swot_store.read_speaking_scores(db, user_id)
    # Time evidence exists only where the student practised; cap the
    # all-student reads to those chapters (prototype scale: years of activity
    # are far below the cap, and the cap keeps a pathological account honest).
    own_chapters: set[str] = set()
    for event in events:
        if event.kind == "practice_answer" and event.chapter_id:
            own_chapters.add(str(event.chapter_id))
    times = {
        chapter_id: swot_store.read_all_student_times(db, chapter_id)
        for chapter_id in sorted(own_chapters)[:ALL_STUDENT_TIME_CHAPTER_CAP]
    }
    return SwotInput(
        events=events,
        speaking=speaking,
        lesson_progress=swot_store.read_lesson_progress(db, user_id),
        question_counts=swot_store.read_question_counts(db),
        attempted=swot_store.read_attempted_questions(db, user_id),
        priors=swot_store.read_topic_priors(db),
        exam_weights=swot_store.read_exam_weights(db),
        catalogue=snapshot,
        all_student_times=times,
        mode=resolve_mode(mode),
        now=now,
    )


__all__ = [
    "ALL_STUDENT_TIME_CHAPTER_CAP",
    "QUADRANT_BLURBS",
    "QUADRANT_LABELS",
    "SwotInput",
    "SwotModeError",
    "build_swot",
    "build_swot_explain",
    "gather_input",
    "resolve_mode",
    "rules",
]
