"""A2-concept-tag: turn the syllabus concepts into a graph and tag lesson blocks.

The P1 renderer already gives every published block a stable `b-NN` id, a
`section_id` and a section-scoped `concept_id` (`...-sec-03`). Those keys are
a *grouping* key, not a curated syllabus concept. This stage owns the
translation: a tracked, reviewable `section -> curated concept` map per
chapter (`sources/syllabus/chapters/<chapter_id>.concept-map.json`), so every
block ends up tagged with a real curriculum concept and the practice bank
uses the same ids.

Honest gap: a chapter whose lesson is not published yet (Class 10 Light in
this wave) has no block ids to tag. The stage records
`block_tagging: pending_lesson` and a minor `concept.manifest_missing` issue
instead of inventing blocks; question tagging is still enforced. That is
content-quality debt, not a technical gate (Q-6).
"""

from __future__ import annotations

import json
from typing import Any

from .config import AssessmentConfig
from .errors import AssessmentGateError, AssessmentStageError
from .validators import Issue, gate_report, issues_for_reasons, validate_concept_graph

STAGE_ID = "A2-concept-tag"


def concept_map_path(cfg: AssessmentConfig, chapter_id: str):
    return cfg.chapters_dir / f"{chapter_id}.concept-map.json"


def load_concept_map(
    cfg: AssessmentConfig, chapter: dict[str, Any]
) -> dict[str, Any] | None:
    path = concept_map_path(cfg, chapter["chapter_id"])
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssessmentStageError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AssessmentStageError(f"{path} must contain a JSON object")
    if data.get("chapter_id") != chapter["chapter_id"]:
        raise AssessmentStageError(
            f"{path}: chapter_id {data.get('chapter_id')!r} != {chapter['chapter_id']!r}"
        )
    mapping = data.get("section_concept_map")
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise AssessmentStageError(
            f"{path}: section_concept_map must map strings to strings"
        )
    return data


def _lesson_manifest_path(cfg: AssessmentConfig, chapter: dict[str, Any]):
    slug = chapter.get("lesson_topic_slug")
    if not slug:
        return None
    course_id = f"class-{chapter['class']}-physics"
    return cfg.frontend_dir / "courses" / course_id / slug / "manifest.json"


def load_lesson_manifest(
    cfg: AssessmentConfig, chapter: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None, list[Issue]]:
    """Return (manifest, repo-relative path, issues). A manifest from before
    the P1 hooks (no sections/blocks map) is reported, never guessed at."""
    issues: list[Issue] = []
    path = _lesson_manifest_path(cfg, chapter)
    if path is None or not path.is_file():
        return None, None, issues
    rel = str(path.relative_to(cfg.repo_root))
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            None,
            rel,
            [
                Issue(
                    "concept.manifest_invalid",
                    "fatal",
                    f"{rel} is not valid JSON: {exc}",
                )
            ],
        )
    if manifest.get("chapter_id") != chapter["chapter_id"]:
        issues.append(
            Issue(
                "concept.manifest_mismatch",
                "fatal",
                f"{rel}: chapter_id {manifest.get('chapter_id')!r} != "
                f"{chapter['chapter_id']!r}; the lesson belongs to another chapter",
            )
        )
    if manifest.get("class") != chapter["class"]:
        issues.append(
            Issue(
                "concept.manifest_mismatch",
                "fatal",
                f"{rel}: class {manifest.get('class')!r} != {chapter['class']}",
            )
        )
    if not manifest.get("sections") or not manifest.get("blocks"):
        issues.append(
            Issue(
                "concept.hooks_missing",
                "minor",
                f"{rel}: manifest carries no sections/blocks map (pre-P1 page); "
                "block tagging is pending a re-render",
            )
        )
        return None, rel, issues
    return manifest, rel, issues


def prerequisite_edges(concepts: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for concept in concepts:
        for prereq in concept["prerequisites"]:
            edges.append(
                {
                    "from": prereq,
                    "to": concept["concept_id"],
                    "kind": "prerequisite",
                }
            )
    return sorted(edges, key=lambda e: (e["from"], e["to"]))


def build_graph(
    cfg: AssessmentConfig, chapter: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the A2 payload for one chapter. Returns (payload, gate report)."""
    concepts = chapter["concepts"]
    known = {c["concept_id"] for c in concepts}
    issues: list[Issue] = []

    concept_map = load_concept_map(cfg, chapter)
    mapping: dict[str, str] = dict((concept_map or {}).get("section_concept_map") or {})
    manifest, manifest_rel, manifest_issues = load_lesson_manifest(cfg, chapter)
    issues.extend(manifest_issues)

    if manifest is not None and concept_map is None:
        issues.append(
            Issue(
                "concept.map_missing",
                "fatal",
                f"{manifest_rel} exists but {concept_map_path(cfg, chapter['chapter_id']).name} "
                "does not; every lesson section needs a curated concept",
            )
        )

    lesson: dict[str, Any] | None = None
    blocks: dict[str, Any] = {}
    if manifest is not None:
        lesson = {
            "manifest_path": manifest_rel,
            "lesson_id": manifest.get("lesson_id"),
            "title": manifest.get("title"),
            "sections": [
                {
                    "id": section.get("id"),
                    "title": section.get("title"),
                    "p1_concept_id": section.get("concept_id"),
                }
                for section in manifest.get("sections", [])
            ],
        }
        for block_id, block in (manifest.get("blocks") or {}).items():
            section_id = block.get("section_id")
            blocks[block_id] = {
                "type": block.get("type"),
                "section_id": section_id,
                "p1_concept_id": block.get("concept_id"),
                "concept_id": mapping.get(section_id),
            }
        if concept_map is not None:
            for section in lesson["sections"]:
                section["concept_id"] = mapping.get(section["id"])

    graph = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "chapter_id": chapter["chapter_id"],
        "class_level": chapter["class"],
        "concepts": concepts,
        "edges": prerequisite_edges(concepts),
        "section_concept_map": mapping,
        "lesson": lesson,
        "blocks": blocks,
        "block_tagging": "complete"
        if lesson is not None and mapping
        else "pending_lesson",
    }
    issues.extend(validate_concept_graph(graph, chapter))

    counts = {
        "concepts": len(known),
        "edges": len(graph["edges"]),
        "lesson_sections": len(lesson["sections"]) if lesson else 0,
        "blocks": len(blocks),
        "blocks_tagged": sum(1 for b in blocks.values() if b.get("concept_id")),
    }
    report = gate_report(issues, counts=counts)
    payload = {**graph, "counts": counts, "gate": report}
    return payload, report


def run_stage(cfg: AssessmentConfig, chapter: dict[str, Any]) -> dict[str, Any]:
    payload, report = build_graph(cfg, chapter)
    if report["verdict"] == "fail":
        raise AssessmentGateError(
            "A2-concept-tag failed: " + "; ".join(issues_for_reasons(report)),
            report=report,
            output=payload,
        )
    return payload


__all__ = [
    "STAGE_ID",
    "build_graph",
    "concept_map_path",
    "load_concept_map",
    "load_lesson_manifest",
    "prerequisite_edges",
    "run_stage",
]
