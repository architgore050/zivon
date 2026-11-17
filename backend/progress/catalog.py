"""Catalogue read model for the progress surfaces (F3).

The progress pages need chapter titles, lesson links, chapter numbers, and the
concept list (section id -> concept id) for the class -> chapter -> concept
map and for the guest-sync mapping. Three sources exist today, in precedence
order:

1. the database (`syllabus_chapter` + `concept`), the moment the P1/P2 import
   populates it — this is the production path;
2. the published catalogue (`frontend/catalogue.json`, written by P5) when the
   backend can see the frontend tree (local development and compose);
3. F0's tracked fixture (`backend/catalog/fixtures/catalogue.json`), the
   honest fallback that ships inside the backend image.

The snapshot is read-only. Nothing here writes the catalogue, and no surface
invents a chapter: a chapter with progress but no catalogue entry is shown
under its humanized id and marked as unmatched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from db.engine import DatabaseEngine

from ..catalog.store import FIXTURE_PATH

RELEASE_CLASSES: Final[tuple[int, ...]] = (9, 10, 11, 12)


@dataclass(frozen=True)
class ConceptMeta:
    """One catalogue concept and the lesson section that carries it."""

    concept_id: str
    title: str
    section_id: str | None = None
    order_index: int = 0


@dataclass(frozen=True)
class ChapterMeta:
    """One Physics chapter as the progress surfaces may display it."""

    chapter_id: str
    class_level: int
    chapter_no: int
    slug: str
    title: str
    lesson_url: str | None
    status: str = "lesson_only"
    concepts: tuple[ConceptMeta, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CatalogueSnapshot:
    """The chapters grouped by class, plus an id lookup."""

    classes: tuple[tuple[int, tuple[ChapterMeta, ...]], ...]
    chapters: dict[str, ChapterMeta]
    source: str

    def class_chapters(self, class_level: int | None) -> tuple[ChapterMeta, ...]:
        """Return the chapters for one class (empty when nothing is published)."""
        if class_level is None:
            return ()
        for level, chapters in self.classes:
            if level == class_level:
                return chapters
        return ()


def catalogue_snapshot(
    db: DatabaseEngine | None, frontend_dir: str = "frontend"
) -> CatalogueSnapshot:
    """Return the best available catalogue snapshot for progress display."""
    from_db = _from_database(db)
    if from_db is not None:
        return from_db
    from_published = _from_published(frontend_dir)
    if from_published is not None:
        return from_published
    return _from_fixture()


def _from_database(db: DatabaseEngine | None) -> CatalogueSnapshot | None:
    if db is None:
        return None
    try:
        rows = db.fetchall(
            """
            SELECT chapter_id, class_level, chapter_no, slug, title_en,
                   status, lesson_url
            FROM syllabus_chapter
            WHERE subject = 'physics'
            ORDER BY class_level, chapter_no, title_en
            """
        )
    except Exception:  # noqa: BLE001 - a missing table is the fixture path
        return None
    if not rows:
        return None
    concepts: dict[str, list[ConceptMeta]] = {}
    try:
        concept_rows = db.fetchall(
            """
            SELECT concept_id, chapter_id, title_en, order_index
            FROM concept
            ORDER BY chapter_id, order_index, title_en
            """
        )
    except Exception:  # noqa: BLE001 - additive table may predate 0003
        concept_rows = []
    for row in concept_rows:
        concepts.setdefault(str(row["chapter_id"]), []).append(
            ConceptMeta(
                concept_id=str(row["concept_id"]),
                title=str(row["title_en"]),
                order_index=int(row.get("order_index") or 0),
            )
        )
    chapters = [
        _chapter(
            chapter_id=str(row["chapter_id"]),
            class_level=int(row["class_level"]),
            chapter_no=int(row.get("chapter_no") or 0),
            slug=str(row.get("slug") or ""),
            title=str(row["title_en"]),
            lesson_url=row.get("lesson_url"),
            status=str(row.get("status") or "lesson_only"),
            concepts=tuple(concepts.get(str(row["chapter_id"]), [])),
        )
        for row in rows
    ]
    return _snapshot(chapters, "database")


def _from_published(frontend_dir: str) -> CatalogueSnapshot | None:
    path = Path(frontend_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    catalogue_path = path / "catalogue.json"
    if not catalogue_path.is_file():
        return None
    try:
        data = json.loads(catalogue_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    topics = data.get("topics")
    if not isinstance(topics, list) or not topics:
        return None
    chapters: list[ChapterMeta] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        chapter_id = str(topic.get("chapter_id") or "").strip()
        if not chapter_id:
            continue
        raw_chapter = topic.get("chapter")
        chapter: dict[str, Any] = raw_chapter if isinstance(raw_chapter, dict) else {}
        raw_concepts = topic.get("concepts")
        concept_rows: list[Any] = raw_concepts if isinstance(raw_concepts, list) else []
        concepts: list[ConceptMeta] = []
        for index, concept in enumerate(concept_rows):
            if not isinstance(concept, dict):
                continue
            concept_id = str(concept.get("concept_id") or "").strip()
            if not concept_id:
                continue
            concepts.append(
                ConceptMeta(
                    concept_id=concept_id,
                    title=str(concept.get("title") or concept_id),
                    section_id=(
                        str(concept["section_id"])
                        if concept.get("section_id")
                        else None
                    ),
                    order_index=index,
                )
            )
        chapters.append(
            _chapter(
                chapter_id=chapter_id,
                class_level=int(topic.get("class") or 0),
                chapter_no=int(chapter.get("number") or 0),
                slug=_published_slug(topic),
                title=str(
                    topic.get("title") or topic.get("lesson_title") or chapter_id
                ),
                lesson_url=_published_lesson_url(topic.get("href")),
                status=str(topic.get("status") or "lesson_only"),
                concepts=tuple(concepts),
            )
        )
    return _snapshot(chapters, "published") if chapters else None


def _published_slug(topic: dict[str, Any]) -> str:
    """The topic slug: the catalogue carries it as `href`, not as its own key."""
    explicit = str(topic.get("topic_slug") or "").strip()
    if explicit:
        return explicit
    raw = str(topic.get("href") or "").strip().strip("/")
    raw = raw.removesuffix("index.html").strip("/")
    return raw.split("/")[-1] if raw else ""


def _published_lesson_url(href: object) -> str | None:
    raw = str(href or "").strip()
    if not raw:
        return None
    cleaned = raw.lstrip("/")
    cleaned = cleaned.removesuffix("index.html")
    if not cleaned.endswith("/"):
        cleaned += "/"
    return "/" + cleaned


def _from_fixture() -> CatalogueSnapshot:
    try:
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _snapshot([], "fixture")
    chapters: list[ChapterMeta] = []
    classes = data.get("classes") if isinstance(data, dict) else None
    for class_entry in classes or []:
        if not isinstance(class_entry, dict):
            continue
        class_level = int(class_entry.get("class_level") or 0)
        for row in class_entry.get("chapters") or []:
            if not isinstance(row, dict):
                continue
            chapters.append(
                _chapter(
                    chapter_id=str(row.get("chapter_id") or ""),
                    class_level=class_level,
                    chapter_no=int(row.get("chapter_no") or 0),
                    slug=str(row.get("slug") or ""),
                    title=str(row.get("title_en") or row.get("chapter_id") or ""),
                    lesson_url=row.get("lesson_url"),
                    status=str(row.get("status") or "lesson_only"),
                    concepts=(),
                )
            )
    return _snapshot(chapters, "fixture")


def _chapter(
    *,
    chapter_id: str,
    class_level: int,
    chapter_no: int,
    slug: str,
    title: str,
    lesson_url: object,
    status: str,
    concepts: tuple[ConceptMeta, ...],
) -> ChapterMeta:
    return ChapterMeta(
        chapter_id=chapter_id,
        class_level=class_level,
        chapter_no=chapter_no,
        slug=slug,
        title=title,
        lesson_url=str(lesson_url) if lesson_url else None,
        status=status,
        concepts=concepts,
    )


def _snapshot(chapters: list[ChapterMeta], source: str) -> CatalogueSnapshot:
    by_id: dict[str, ChapterMeta] = {}
    grouped: dict[int, list[ChapterMeta]] = {level: [] for level in RELEASE_CLASSES}
    for chapter in chapters:
        if not chapter.chapter_id or chapter.chapter_id in by_id:
            continue
        by_id[chapter.chapter_id] = chapter
        grouped.setdefault(chapter.class_level, []).append(chapter)
    for entries in grouped.values():
        entries.sort(key=lambda item: (item.chapter_no, item.title.lower()))
    classes: list[tuple[int, tuple[ChapterMeta, ...]]] = []
    for level in RELEASE_CLASSES:
        classes.append((level, tuple(grouped.get(level, ()))))
    other_levels = sorted(
        level for level in grouped if level not in RELEASE_CLASSES and grouped[level]
    )
    for level in other_levels:
        classes.append((level, tuple(grouped[level])))
    return CatalogueSnapshot(
        classes=tuple(classes),
        chapters=by_id,
        source=source,
    )


__all__ = [
    "RELEASE_CLASSES",
    "CatalogueSnapshot",
    "ChapterMeta",
    "ConceptMeta",
    "catalogue_snapshot",
]
