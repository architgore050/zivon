"""Catalogue read model for `/v1/catalog` (F0 stub, REQUIREMENTS §9.3).

Authoritative source is the database (`syllabus_chapter` + `concept`, written by
the P1/P2 import). Until that import lands, the endpoint serves the tracked
fixture next to this module so F1/F3/F4 can build against the real shape. The
fixture is honest about what is published: it carries the 7 live topics and
never invents chapter numbers or concepts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from db.engine import DatabaseEngine

FIXTURE_PATH: Final[Path] = Path(__file__).parent / "fixtures" / "catalogue.json"
RELEASE_CLASSES: Final[tuple[int, ...]] = (9, 10, 11, 12)


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError("catalogue fixture must be a JSON object")
    return data


def _languages(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _chapter_public(row: dict[str, Any], concepts_count: int = 0) -> dict[str, Any]:
    chapter_no = row.get("chapter_no")
    return {
        "chapter_id": str(row.get("chapter_id")),
        "chapter_no": int(chapter_no) if chapter_no is not None else 0,
        "slug": str(row.get("slug")),
        "title_en": str(row.get("title_en")),
        "title_hi": row.get("title_hi"),
        "status": str(row.get("status") or "in_development"),
        "languages": _languages(row.get("languages")),
        "lesson_url": row.get("lesson_url"),
        "concepts_count": concepts_count,
    }


def _chapters_from_db(db: DatabaseEngine) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT chapter_id, class_level, chapter_no, slug, title_en, title_hi,
               status, languages, lesson_url
        FROM syllabus_chapter
        WHERE subject = 'physics'
        ORDER BY class_level, chapter_no, title_en
        """
    )
    counts = {
        str(row["chapter_id"]): int(row["cnt"])
        for row in db.fetchall(
            "SELECT chapter_id, COUNT(*) AS cnt FROM concept GROUP BY chapter_id"
        )
    }
    return [
        {
            **_chapter_public(row, counts.get(str(row["chapter_id"]), 0)),
            "class_level": int(row["class_level"]),
        }
        for row in rows
    ]


def _chapters_from_fixture() -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for class_entry in _load_fixture().get("classes", []):
        class_level = int(class_entry["class_level"])
        for row in class_entry.get("chapters", []):
            concepts = row.get("concepts") or []
            chapters.append(
                {
                    **_chapter_public(row, len(concepts)),
                    "class_level": class_level,
                }
            )
    return chapters


def catalogue(db: DatabaseEngine | None) -> dict[str, Any]:
    """Return classes 9–12 with their chapters, ordered for the catalogue UI."""
    chapters = (
        _chapters_from_db(db)
        if db is not None and _db_has_chapters(db)
        else _chapters_from_fixture()
    )
    by_class: dict[int, list[dict[str, Any]]] = {level: [] for level in RELEASE_CLASSES}
    for chapter in chapters:
        by_class.setdefault(int(chapter["class_level"]), []).append(chapter)
    for entries in by_class.values():
        entries.sort(key=lambda item: (int(item["chapter_no"]), str(item["title_en"])))
    fixture = _load_fixture()
    return {
        "schema_version": 1,
        "subject": "physics",
        "languages": _languages(fixture.get("languages")),
        "classes": [
            {
                "class_level": level,
                "chapters": [
                    {
                        key: value
                        for key, value in chapter.items()
                        if key != "class_level"
                    }
                    for chapter in by_class.get(level, [])
                ],
            }
            for level in RELEASE_CLASSES
        ],
    }


def chapter_detail(db: DatabaseEngine | None, slug: str) -> dict[str, Any] | None:
    """Return one chapter with its concepts, or None when the slug is unknown."""
    wanted = (slug or "").strip()
    if not wanted:
        return None
    if db is not None and _db_has_chapters(db):
        row = db.fetchone(
            "SELECT * FROM syllabus_chapter WHERE slug = ? ORDER BY class_level LIMIT 1",
            (wanted,),
        )
        if row is None:
            return None
        concepts = [
            {
                "concept_id": str(item["concept_id"]),
                "slug": str(item["slug"]),
                "title_en": str(item["title_en"]),
                "title_hi": item.get("title_hi"),
                "description": item.get("description"),
                "order_index": int(item.get("order_index") or 0),
            }
            for item in db.fetchall(
                "SELECT * FROM concept WHERE chapter_id = ? ORDER BY order_index, title_en",
                (str(row["chapter_id"]),),
            )
        ]
        return {"chapter": _chapter_public(row, len(concepts)), "concepts": concepts}

    for class_entry in _load_fixture().get("classes", []):
        for item in class_entry.get("chapters", []):
            if str(item.get("slug")) == wanted:
                concepts = list(item.get("concepts") or [])
                return {
                    "chapter": _chapter_public(item, len(concepts)),
                    "concepts": concepts,
                }
    return None


def _db_has_chapters(db: DatabaseEngine) -> bool:
    row = db.fetchone("SELECT COUNT(*) AS cnt FROM syllabus_chapter")
    return bool(row and int(row["cnt"]) > 0)
