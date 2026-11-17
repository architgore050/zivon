"""A1-syllabus: validate the four-class Physics map and freeze its digest.

The manifest is tracked data (`sources/syllabus/syllabus.json`), not model
output: classes 9-12, NCERT chapter identity, and curated concepts for the
classes whose practice banks are in R1 (9/10). Chapter titles were derived
from the cached NCERT PDFs in `sources/pdfs/` (see the manifest's
`source_basis`); concepts, prerequisites and section references are curated
and reviewed here. Classes 11/12 carry chapter identity only and say so
(`concepts_status: pending_r1_5`) - R1.5 owns their practice banks.

`exam_weight` stays `null` with `exam_weight_status: pending_p3_blueprint`:
P3's CBSE blueprint (SER-02) is the only place a real mark weight comes from,
and an invented number would be worse than an absent one (the repo's
"unknown = absent" rule).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import AssessmentConfig, catalog_book_ids
from .errors import AssessmentGateError, AssessmentStageError
from .validators import (
    Issue,
    chapter_by_id,
    gate_report,
    issues_for_reasons,
    validate_syllabus,
)

STAGE_ID = "A1-syllabus"


def load_syllabus(cfg: AssessmentConfig) -> dict[str, Any]:
    path = cfg.syllabus_path
    if not path.is_file():
        raise AssessmentStageError(
            f"assessment syllabus not found at {path}. It is tracked data; "
            "restore sources/syllabus/syllabus.json (see docs/content-factory/assessment.md)."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssessmentStageError(f"{path} is not valid JSON: {exc}") from exc


def syllabus_sha256(syllabus: dict[str, Any]) -> str:
    payload = json.dumps(syllabus, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_counts(syllabus: dict[str, Any]) -> dict[str, Any]:
    chapters = [c for entry in syllabus["classes"] for c in entry["chapters"]]
    curated = [c for c in chapters if c["concepts_status"] == "curated"]
    return {
        "classes": len(syllabus["classes"]),
        "chapters": len(chapters),
        "concepts": sum(len(c["concepts"]) for c in chapters),
        "curated_chapters": len(curated),
        "pending_chapters": len(chapters) - len(curated),
    }


def chapter_index(syllabus: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        chapter["chapter_id"]: chapter
        for entry in syllabus["classes"]
        for chapter in entry["chapters"]
    }


def run_stage(cfg: AssessmentConfig) -> dict[str, Any]:
    """Validate the syllabus and return the A1 output payload."""
    syllabus = load_syllabus(cfg)
    issues: list[Issue] = validate_syllabus(
        syllabus, catalog_book_ids=catalog_book_ids(cfg.catalog_path)
    )
    report = gate_report(issues, counts=collect_counts(syllabus))
    output = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "syllabus_path": str(cfg.syllabus_path.relative_to(cfg.repo_root)),
        "syllabus_sha256": syllabus_sha256(syllabus),
        "syllabus": syllabus,
        "counts": report["counts"],
        "gate": report,
    }
    if report["verdict"] == "fail":
        raise AssessmentGateError(
            "A1-syllabus failed: " + "; ".join(issues_for_reasons(report)),
            report=report,
            output=output,
        )
    return output


def require_chapter(syllabus: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    """Resolve a chapter or stop with the valid ids (operator typo protection)."""
    chapter = chapter_by_id(syllabus, chapter_id)
    if chapter is not None:
        return chapter
    valid = ", ".join(sorted(chapter_index(syllabus)))
    raise AssessmentStageError(f"unknown chapter_id {chapter_id!r}. Known ids: {valid}")


def require_curated(chapter: dict[str, Any]) -> None:
    if chapter["concepts_status"] != "curated":
        raise AssessmentStageError(
            f"{chapter['chapter_id']}: concepts are {chapter['concepts_status']}; "
            "the practice/speaking stages need a curated concept list (R1.5 owns "
            "Class 11/12 practice banks)."
        )


__all__ = [
    "STAGE_ID",
    "chapter_index",
    "collect_counts",
    "file_sha256",
    "load_syllabus",
    "require_chapter",
    "require_curated",
    "run_stage",
    "syllabus_sha256",
]
