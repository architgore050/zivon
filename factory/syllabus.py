"""Reads and writes the tracked syllabus the lesson pipeline consumes for the
section -> curated-concept map.

The map is `sources/syllabus/chapters/<chapter_id>.concept-map.json` - a tracked
file, consumed by A2 (`factory/assessment/concepts.py`) and the offline verifier
(`scripts/verify_magnetic_manifest.py`). Since 2026-11-25 the lesson pipeline
has a PRODUCER for it: 02-generate emits the map (prompted by this module's
helpers) and 09-review verifies it; `write_tracked_map` persists the verified
map after the final review passes (called from `factory/stages.py`).

The map's keys are LESSON manifest section ids (`sec-01`..., the shape from
`factory/schemas.py` LESSON.sections); its values are curated syllabus concept
ids (`sources/syllabus/syllabus.json` chapter["concepts"][].concept_id).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import identity
from .artifacts import slugify
from .config import Config

DEFAULT_SYLLABUS_REL = Path("sources/syllabus/syllabus.json")


def _syllabus_path(cfg: Config) -> Path:
    return cfg.repo_path(DEFAULT_SYLLABUS_REL)


def load_syllabus(cfg: Config) -> dict[str, Any] | None:
    path = _syllabus_path(cfg)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_chapter(cfg: Config, chapter_id: str) -> dict[str, Any] | None:
    """The syllabus record for a chapter_id, or None when unknown."""
    if not chapter_id:
        return None
    syllabus = load_syllabus(cfg) or {}
    for entry in syllabus.get("classes", []):
        for ch in entry.get("chapters", []):
            if ch.get("chapter_id") == chapter_id:
                return ch
    return None


def curated_concept_ids(cfg: Config, chapter_id: str) -> list[str]:
    """The curated concept ids the map's values must be drawn from (sorted)."""
    ch = load_chapter(cfg, chapter_id)
    if not ch:
        return []
    return sorted(
        c["concept_id"] for c in ch.get("concepts", []) if c.get("concept_id")
    )


def located_chapter_id(title: str, class_level: int | str) -> str:
    """The A2 chapter key for a chapter as 01-locate/render compute it:
    class + slugified display title (`identity.chapter_id`)."""
    from .render import chapter_display_title

    return identity.chapter_id(
        class_level, slugify(chapter_display_title(str(title or "")))
    )


def tracked_map_path(cfg: Config, chapter_id: str) -> Path:
    return cfg.repo_path("sources/syllabus/chapters") / f"{chapter_id}.concept-map.json"


def write_concept_map(
    cfg: Config,
    *,
    chapter_id: str,
    section_concept_map: dict[str, Any],
    lesson_topic_slug: str | None,
    lesson_manifest: str | None,
    notes: str,
) -> Path:
    path = tracked_map_path(cfg, chapter_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chapter_id": chapter_id,
        "lesson_topic_slug": lesson_topic_slug or "",
        "lesson_manifest": lesson_manifest or "",
        "section_concept_map": {
            str(k): str(v) for k, v in sorted(section_concept_map.items())
        },
        "notes": notes,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def write_tracked_map(
    cfg: Config,
    run_ctx: Any,
    source_pack: dict[str, Any] | None,
    render_out: dict[str, Any],
    concept_map: dict[str, Any] | None = None,
) -> Path | None:
    """Persist the VERIFIED map to the tracked path (09-review passed, so
    nothing the map claims was contradicted; the deterministic concept-coverage
    gate re-derived coverage on the current blocks + manifest + this map).

    `concept_map` is the EFFECTIVE map (the latest 10-reviewfix `concept_map`
    if present, else 02-generate's emitted map); when omitted, 02-generate's
    emitted map is used. Tolerant by design: without a produced map there is
    nothing to persist, and a missing 02-generate output is a partial-run
    state, not an error. Called ONLY on a final verdict=pass.
    """
    manifest = (render_out or {}).get("manifest") or {}
    chapter_id = manifest.get("chapter_id")
    if not chapter_id:
        print("[09-review] no manifest chapter_id; tracked concept map not updated")
        return None
    if concept_map is not None:
        map_data = concept_map
    else:
        try:
            gen = run_ctx.load_stage_output("02-generate")
        except Exception:  # noqa: BLE001 - partial run without 02-generate is normal
            gen = None
        map_data = (gen or {}).get("concept_map") or {}
    map_data = {str(k): str(v) for k, v in (map_data or {}).items() if v is not None}
    if not map_data:
        print(
            "[09-review] no concept_map in effect; tracked concept "
            "map left untouched"
        )
        return None
    frontend_rel = str(Path(cfg.paths["frontend"]))
    path = write_concept_map(
        cfg,
        chapter_id=chapter_id,
        section_concept_map=map_data,
        lesson_topic_slug=manifest.get("topic_slug"),
        lesson_manifest=str(
            Path(frontend_rel)
            / "courses"
            / str(manifest.get("course_id"))
            / str(manifest.get("topic_slug"))
            / "manifest.json"
        ),
        notes=(
            f"Pipeline-produced: the map was emitted by the 02-generate stage of "
            f"run {run_ctx.run_id} and verified by the 09-review gate of the same "
            "run. Keys are the lesson manifest section ids; values are the "
            "curated syllabus concept ids of sources/syllabus/syllabus.json. "
            "Review before committing: A2 fails the bank on any unmapped section "
            "or orphan concept."
        ),
    )
    print(
        f"[09-review] concept map written to tracked file: "
        f"{path.relative_to(cfg.root)} ({len(map_data)} sections)"
    )
    return path


__all__ = [
    "curated_concept_ids",
    "located_chapter_id",
    "load_chapter",
    "load_syllabus",
    "tracked_map_path",
    "write_concept_map",
    "write_tracked_map",
]
