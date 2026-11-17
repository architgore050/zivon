"""The six-series catalogue and detail view (F7, REQUIREMENTS §10.12–§10.13).

Reads published `test_series`/`test` rows and overlays the approved runtime
definitions in `backend.test_engine.series`. The catalogue never invents a
paper: no row is `content pending`, the verbatim Exact PYQ series is `disabled`
under `DEC-COMP-001`, and classes outside the approved launch volume are
`not_open`.

Split from `service.py` so the player/review policy and the catalogue policy
are reviewable on their own; both share `TestUser` and the store helpers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from db.engine import DatabaseEngine

from ..assessment import (
    count_test_questions,
    list_live_test_attempts,
    list_series,
    list_test_chapters,
    list_tests,
)
from .series import (
    APPROVED_CLASSES,
    SERIES_DEFINITIONS,
    SERIES_ORDER,
    minimum_label,
    n01_notice,
    series_by_slug,
    series_copy,
)
from .service import LANGUAGE_LABELS, SERIES_STATUS_LABELS, TestUser

# --- series catalogue -------------------------------------------------------


def _approved_series_rows(
    db: DatabaseEngine, class_num: int
) -> dict[str, Mapping[str, Any]]:
    rows = list_series(db, class_level=class_num)
    by_kind: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        kind = str(row.get("kind") or "")
        if kind and kind not in by_kind:
            by_kind[kind] = row
    return by_kind


def _series_status(
    definition_kind: str,
    *,
    class_num: int | None,
    row: Mapping[str, Any] | None,
    paper_count: int,
) -> tuple[str, str | None]:
    if class_num is None:
        return "choose_class", (
            "Set your class in Settings to see which series are open for it."
        )
    if class_num not in APPROVED_CLASSES:
        return "not_open", (
            "The six series open for Class 10 and Class 12 first. Chapter tests "
            "and custom tests work for your class now."
        )
    if definition_kind == "exact_pyq":
        return "disabled", (
            "Not available: the verbatim past-paper clearance has not been "
            "recorded (DEC-COMP-001). Zivon does not show past-paper text while "
            "that clearance is missing."
        )
    if row is None or paper_count == 0:
        return "pending", (
            "The series content has not passed its volume and coverage gate yet. "
            "Nothing is shown that is not ready."
        )
    return "live", None


def series_catalogue(db: DatabaseEngine, user: TestUser) -> dict[str, Any]:
    """Return the six-series catalogue, honest about what is not built yet."""
    class_num = user.class_level
    rows = _approved_series_rows(db, class_num) if class_num is not None else {}
    chapters = (
        list_test_chapters(db, class_level=class_num) if class_num is not None else []
    )
    chapter_count = len(chapters)
    cards: list[dict[str, Any]] = []
    for kind in SERIES_ORDER:
        definition = SERIES_DEFINITIONS[kind]
        row = rows.get(kind)
        papers = list_tests(db, str(row["series_id"])) if row else []
        status, reason = _series_status(
            kind, class_num=class_num, row=row, paper_count=len(papers)
        )
        subject = "Physics" if class_num in (11, 12) else "Science (Physics section)"
        label = str(row.get("title") or definition.label) if row else definition.label
        description = (
            str(row.get("description") or "").strip() if row else ""
        ) or definition.purpose
        cards.append(
            {
                "kind": kind,
                "slug": definition.slug,
                "label": label,
                "purpose": description,
                "blurb": (
                    series_copy(definition, class_num=class_num, subject=subject)
                    if class_num in APPROVED_CLASSES
                    else ""
                ),
                "coverage": definition.coverage,
                "length": definition.length,
                "languages": definition.languages,
                "language_label": _language_label(definition.languages),
                "notice_id": definition.notice_id,
                "status": status,
                "status_label": SERIES_STATUS_LABELS[status],
                "reason": reason,
                "paper_count": len(papers),
                "approved": class_num in APPROVED_CLASSES,
                "minimum": (
                    minimum_label(definition, class_num)
                    if class_num in APPROVED_CLASSES
                    else ""
                ),
            }
        )
    notice = n01_notice(class_num) if class_num in APPROVED_CLASSES else None
    return {
        "class_level": class_num,
        "cards": cards,
        "chapter_count": chapter_count,
        "notice": notice,
        "status_counts": {
            "live": sum(1 for card in cards if card["status"] == "live"),
            "pending": sum(1 for card in cards if card["status"] == "pending"),
        },
    }


def series_detail(
    db: DatabaseEngine, user: TestUser, *, slug: str
) -> dict[str, Any] | None:
    """Return one series with its published papers, or an honest pending page."""
    definition = series_by_slug(slug)
    if definition is None:
        return None
    class_num = user.class_level
    rows = _approved_series_rows(db, class_num) if class_num is not None else {}
    row = rows.get(definition.kind)
    tests = list_tests(db, str(row["series_id"])) if row else []
    status, reason = _series_status(
        definition.kind, class_num=class_num, row=row, paper_count=len(tests)
    )
    live = {
        str(attempt["test_id"]): attempt
        for attempt in (
            list_live_test_attempts(db, user.user_id) if user.user_id else []
        )
    }
    papers: list[dict[str, Any]] = []
    for index, test in enumerate(tests):
        live_attempt = live.get(str(test["test_id"]))
        papers.append(
            {
                **test,
                "question_count": count_test_questions(db, str(test["test_id"])),
                "duration_min": max(1, int(test["duration_s"]) // 60),
                "live_attempt_id": (live_attempt or {}).get("attempt_id"),
                "recommended": index == 0,
            }
        )
    subject = "Physics" if class_num in (11, 12) else "Science (Physics section)"
    languages = definition.languages
    language_note = None
    if class_num in APPROVED_CLASSES and user.language not in languages:
        language_note = (
            "This series is available in " + _language_label(languages) + " only."
        )
    return {
        "definition": definition,
        "label": str(row.get("title") or definition.label) if row else definition.label,
        "purpose": (str(row.get("description") or "").strip() if row else "")
        or definition.purpose,
        "blurb": (
            series_copy(definition, class_num=class_num, subject=subject)
            if class_num in APPROVED_CLASSES
            else ""
        ),
        "coverage": definition.coverage,
        "length": definition.length,
        "languages": languages,
        "language_label": _language_label(languages),
        "language_note": language_note,
        "status": status,
        "status_label": SERIES_STATUS_LABELS[status],
        "reason": reason,
        "papers": papers,
        "paper_count": len(papers),
        "minimum": (
            minimum_label(definition, class_num)
            if class_num in APPROVED_CLASSES
            else ""
        ),
        "notice": (
            n01_notice(class_num)
            if class_num in APPROVED_CLASSES and definition.notice_id == "N-01"
            else None
        ),
        "class_level": class_num,
    }


def _language_label(languages: Sequence[str]) -> str:
    return " + ".join(LANGUAGE_LABELS.get(language, language) for language in languages)
