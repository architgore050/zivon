"""Chapter list resolution for SWOT (F8) — a thin read over F3's catalogue.

SWOT needs the same chapter universe the dashboard maps: id, title, class,
number, and lesson link, with exam weight from the syllabus table when the
P1/P2 import has landed. Reusing `backend.progress.catalog` keeps one
catalogue truth (database → published → fixture) and keeps F8 from inventing
a second map — the debt F3's spec explicitly forbids.
"""

from __future__ import annotations

from typing import Any, Final

from ..progress.catalog import CatalogueSnapshot

# Chapters that are not live (in_development) carry no evidence and would
# render as forever-empty cards; SWOT keeps the catalogue order of live and
# lesson_only chapters (the same universe the progress map shows).
INCLUDED_STATUSES: Final[frozenset[str]] = frozenset({"live", "lesson_only"})


def resolve_chapters(snapshot: CatalogueSnapshot) -> dict[str, dict[str, Any]]:
    """Return the catalogue chapters SWOT may render, keyed by chapter id.

    Order follows the snapshot's class → chapter ordering (class levels in
    release order, chapters by number then title), which keeps the API stable
    between calls with identical data.
    """
    chapters: dict[str, dict[str, Any]] = {}
    for _level, class_chapters in snapshot.classes:
        for meta in class_chapters:
            if meta.chapter_id in chapters:
                continue
            if meta.status not in INCLUDED_STATUSES:
                continue
            chapters[meta.chapter_id] = {
                "title": meta.title,
                "class_level": meta.class_level,
                "chapter_no": meta.chapter_no,
                "lesson_url": meta.lesson_url,
            }
    return chapters


__all__ = ["INCLUDED_STATUSES", "resolve_chapters"]
