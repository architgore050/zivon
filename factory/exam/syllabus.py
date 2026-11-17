"""Read-only view of the P2 syllabus map (`sources/syllabus/syllabus.json`).

P3 consumes the syllabus; it does not own it. This is deliberately a small
reader rather than an import of `factory.assessment.syllabus`: that loader is
bound to the assessment config and validates assessment-specific rules, while
the exam pipeline needs three things only - the chapter universe per class, the
chapter-to-class relationship, and the concept ids per chapter.

Anything this module cannot find is returned as an empty collection; the
validators decide whether that is a gap (a blueprint with no chapters is fatal)
or a debt (a chapter with no item bank yet). Nothing here mutates the file or
touches the assessment entrypoint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ExamStageError


def load_syllabus(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ExamStageError(f"syllabus not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("classes"), list):
        raise ExamStageError(f"{path}: syllabus has no 'classes' list")
    return data


def chapters_for_class(
    syllabus: dict[str, Any], class_num: int
) -> list[dict[str, Any]]:
    for entry in syllabus.get("classes", []):
        if int(entry.get("class", -1)) == class_num:
            return list(entry.get("chapters", []))
    return []


def classes_in(syllabus: dict[str, Any]) -> list[int]:
    return sorted(int(entry["class"]) for entry in syllabus.get("classes", []))


def chapter_index(syllabus: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(chapter["chapter_id"]): chapter
        for entry in syllabus.get("classes", [])
        for chapter in entry.get("chapters", [])
    }


def concepts_of(chapter: dict[str, Any]) -> list[str]:
    return [str(concept["concept_id"]) for concept in chapter.get("concepts", [])]


__all__ = [
    "chapter_index",
    "chapters_for_class",
    "classes_in",
    "concepts_of",
    "load_syllabus",
]
