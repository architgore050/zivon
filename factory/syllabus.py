"""Reads and writes the tracked syllabus the lesson pipeline consumes for the
section -> curated-concept map.

The map is `sources/syllabus/chapters/<chapter_id>.concept-map.json` - a tracked
file, consumed by A2 (`factory/assessment/concepts.py`) and the offline verifier
(`scripts/verify_magnetic_manifest.py`). Since 2026-11-25 the lesson pipeline
has a PRODUCER for it: 02-generate emits the map (prompted by this module's
helpers) and 09-review verifies it; `write_tracked_map` persists the verified
map after the final review passes (called from `factory/stages.py`), and a
resume retries the persistence from the saved passing report (issue #118).

The map's keys are LESSON manifest section ids (`sec-01`..., the shape from
`factory/schemas.py` LESSON.sections); its values are curated syllabus concept
ids (`sources/syllabus/syllabus.json` chapter["concepts"][].concept_id).

Chapter resolution is CANONICAL (issue #118, 2026-11-27): the renderer's
`chapter_id` truncates its slug at 40 characters, but curated chapter ids are
not capped (`class-9-sound-waves-characteristics-and-applications`,
`class-11-system-of-particles-and-rotational-motion`, ...). Every consumer of
the curated vocabulary (`factory/agents.py`, `factory/review.py`,
`factory/reviewfix.py`, `write_tracked_map`) resolves the chapter by class +
FULL normalized title (or an explicit `aliases` list on the syllabus record)
via `resolve_chapter` - never by the truncated renderer key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import identity
from .artifacts import slugify
from .config import Config
from .errors import PersistenceError

DEFAULT_SYLLABUS_REL = Path("sources/syllabus/syllabus.json")

# The pipeline stage that owns concept-map persistence (StageError tag for
# durable-write failures - issue #118: a persistence failure must fail the
# stage loudly, never silently resume without a map).
PERSISTENCE_STAGE = "09-review"


def _syllabus_path(cfg: Config) -> Path:
    return cfg.repo_path(str(DEFAULT_SYLLABUS_REL))


def load_syllabus(cfg: Config) -> dict[str, Any] | None:
    path = _syllabus_path(cfg)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def syllabus_state(cfg: Config) -> str:
    """`ok` | `missing` | `corrupt` - distinct states, never conflated
    (issue #118): a chapter with zero curated concepts is a FOUND chapter and
    must not be mistaken for a syllabus that cannot be read at all. Consumers
    print the degraded mode loudly instead of silently skipping the gate."""
    path = _syllabus_path(cfg)
    if not path.is_file():
        return "missing"
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "corrupt"
    return "ok"


def _iter_chapters(cfg: Config) -> list[tuple[str | None, dict[str, Any]]]:
    syllabus = load_syllabus(cfg) or {}
    out: list[tuple[str | None, dict[str, Any]]] = []
    for entry in syllabus.get("classes", []):
        for ch in entry.get("chapters", []):
            if isinstance(ch, dict) and ch.get("chapter_id"):
                out.append((entry.get("class"), ch))
    return out


def load_chapter(cfg: Config, chapter_id: str) -> dict[str, Any] | None:
    """The syllabus record for a chapter_id, or None when unknown."""
    if not chapter_id:
        return None
    for _, ch in _iter_chapters(cfg):
        if ch.get("chapter_id") == chapter_id:
            return ch
    return None


def canonical_chapter_id(
    cfg: Config, title: str, class_level: int | str | None
) -> str | None:
    """The CURATED chapter id for a located chapter, or None when unresolvable.

    Resolution order (issue #118): (1) the exact canonical id the renderer's
    key WOULD have if it never truncated - `class-<class>-<full slug of the
    display title>`; (2) a full-slug title match within the class; (3) an
    explicit `aliases` list on the syllabus record (slug or direct id);
    (4) None - callers must treat that as 'chapter not in the tracked
    syllabus', never as 'no curated concepts'."""
    from .render import chapter_display_title

    display = chapter_display_title(str(title or ""))
    full = slugify(display, max_len=None)
    # (1) the canonical id itself
    if class_level is not None:
        candidate = identity.chapter_id(class_level, full)
        if load_chapter(cfg, candidate) is not None:
            return candidate
    # (2) + (3) scan: full-title slug equality, then recorded aliases
    for entry_class, ch in _iter_chapters(cfg):
        if (
            class_level is not None
            and entry_class is not None
            and str(entry_class) != str(class_level)
        ):
            continue
        if slugify(ch.get("title") or "", max_len=None) == full:
            return str(ch["chapter_id"])
        for alias in ch.get("aliases") or []:
            if slugify(str(alias), max_len=None) == full or str(alias) == ch.get(
                "chapter_id"
            ):
                return str(ch["chapter_id"])
    return None


def resolve_chapter(
    cfg: Config, title: str, class_level: int | str | None
) -> dict[str, Any] | None:
    """The syllabus chapter record for a located chapter (canonical
    resolution, see `canonical_chapter_id`), or None when the tracked syllabus
    has no such chapter. A found chapter with ZERO curated concepts is a
    found chapter - callers branch on `concepts`, not on `None`."""
    chapter_id = canonical_chapter_id(cfg, title, class_level)
    if chapter_id is None:
        return None
    return load_chapter(cfg, chapter_id)


def curated_concepts(cfg: Config, chapter_id: str) -> list[dict[str, Any]]:
    """The curated concept records (id, title, description) of a chapter,
    sorted by concept_id - reviewer context (issue #118: the facts reviewer
    judges whether a mapped section actually TEACHES its concept, so it needs
    the concepts, not just their ids)."""
    ch = load_chapter(cfg, chapter_id)
    if not ch:
        return []
    return sorted(
        (
            {
                "concept_id": c["concept_id"],
                "title": str(c.get("title") or ""),
                "description": str(c.get("description") or ""),
            }
            for c in ch.get("concepts", [])
            if c.get("concept_id")
        ),
        key=lambda c: c["concept_id"],
    )


def curated_concept_ids(cfg: Config, chapter_id: str) -> list[str]:
    """The curated concept ids the map's values must be drawn from (sorted)."""
    return [c["concept_id"] for c in curated_concepts(cfg, chapter_id)]


def located_chapter_id(title: str, class_level: int | str) -> str:
    """The A2 chapter key for a chapter as 01-locate/render compute it:
    class + slugified display title (`identity.chapter_id`). NOTE (issue
    #118): this is the RENDERER's truncated key, not the curated id - the
    syllabus consumers use `canonical_chapter_id`/`resolve_chapter` instead."""
    from .render import chapter_display_title

    return identity.chapter_id(
        class_level, slugify(chapter_display_title(str(title or "")))
    )


def tracked_map_path(cfg: Config, chapter_id: str) -> Path:
    return cfg.repo_path("sources/syllabus/chapters") / f"{chapter_id}.concept-map.json"


def tracked_map_payload(
    *,
    chapter_id: str,
    section_concept_map: dict[str, Any],
    lesson_topic_slug: str | None,
    lesson_manifest: str | None,
    notes: str,
) -> dict[str, Any]:
    """The exact tracked-file payload (also the durable run artifact and the
    resume-comparison form - issue #118)."""
    return {
        "chapter_id": chapter_id,
        "lesson_topic_slug": lesson_topic_slug or "",
        "lesson_manifest": lesson_manifest or "",
        "section_concept_map": {
            str(k): str(v) for k, v in sorted(section_concept_map.items())
        },
        "notes": notes,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically (issue #118): a killed process must never leave a
    half-written tracked map (or durable artifact) behind - the temp file is
    written in the same directory and `os.replace`d over the target."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


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
    payload = tracked_map_payload(
        chapter_id=chapter_id,
        section_concept_map=section_concept_map,
        lesson_topic_slug=lesson_topic_slug,
        lesson_manifest=lesson_manifest,
        notes=notes,
    )
    _atomic_write_json(path, payload)
    return path


def concept_map_artifact_path(run_ctx: Any) -> Path:
    """The durable, PVC-backed run artifact that carries the verified map
    (issue #118): written BEFORE 09-review is marked ok, so a cluster run can
    always export/commit the map from `runs/<run_id>/09-review/` even when the
    tracked-sources write itself could not succeed in that pod."""
    return run_ctx.stage_dir(PERSISTENCE_STAGE) / "concept-map.json"


def write_run_artifact(run_ctx: Any, payload: dict[str, Any]) -> Path:
    """Write the verified-map payload as the durable run artifact (atomic)."""
    path = concept_map_artifact_path(run_ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, payload)
    return path


def tracked_map_payload_for_run(
    cfg: Config,
    run_ctx: Any,
    render_out: dict[str, Any],
    concept_map: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The tracked-file payload for this run's VERIFIED map, or None when
    there is nothing to persist (no resolvable chapter, or no map in effect).
    The chapter id is CANONICAL (issue #118); the effective map falls back to
    02-generate's emitted map when the caller passes none."""
    manifest = (render_out or {}).get("manifest") or {}
    chapter_id = canonical_chapter_id(
        cfg,
        str((manifest.get("chapter") or {}).get("title") or ""),
        manifest.get("class"),
    )
    if not chapter_id:
        print(
            "[09-review] chapter not resolvable in the tracked syllabus "
            f"(manifest key: {manifest.get('chapter_id')!r}); tracked concept "
            "map not updated"
        )
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
            "[09-review] no concept_map in effect; tracked concept map left untouched"
        )
        return None
    frontend_rel = str(Path(cfg.paths["frontend"]))
    return tracked_map_payload(
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


def write_tracked_map(
    cfg: Config,
    run_ctx: Any,
    render_out: dict[str, Any],
    concept_map: dict[str, Any] | None = None,
) -> Path | None:
    """Persist the VERIFIED map to the tracked path (09-review passed, so
    nothing the map claims was contradicted; the deterministic concept-coverage
    gate re-derived coverage on the current blocks + manifest + this map).

    `concept_map` is the EFFECTIVE map (the latest 10-reviewfix `concept_map`
    if present, else 02-generate's emitted map); when omitted, 02-generate's
    emitted map is used. The file is keyed by the CANONICAL chapter id
    (issue #118), never the renderer's truncated key, and the write is atomic.
    Tolerant by design: without a produced map there is nothing to persist,
    and a missing 02-generate output is a partial-run state, not an error.
    Called ONLY on a final verdict=pass. A write failure raises StageError -
    the run must fail loudly (and resume-retry), never mark the stage ok
    without a map."""
    payload = tracked_map_payload_for_run(cfg, run_ctx, render_out, concept_map)
    if payload is None:
        return None
    path = tracked_map_path(cfg, payload["chapter_id"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, payload)
    except OSError as exc:
        raise PersistenceError(
            PERSISTENCE_STAGE,
            f"tracked concept map persistence failed ({exc}); the run must not "
            "mark 09-review ok without a persisted map - fix the tracked-sources "
            "mount (k8s/20 bridge) and re-trigger to RESUME: the passing report "
            "already carries the verified map",
            artifacts_dir=str(run_ctx.stage_dir(PERSISTENCE_STAGE)),
        ) from exc
    print(
        f"[09-review] concept map written to tracked file: "
        f"{path.relative_to(cfg.root)} ({len(payload['section_concept_map'])} sections)"
    )
    return path


__all__ = [
    "canonical_chapter_id",
    "concept_map_artifact_path",
    "curated_concept_ids",
    "curated_concepts",
    "load_chapter",
    "load_syllabus",
    "located_chapter_id",
    "resolve_chapter",
    "syllabus_state",
    "tracked_map_path",
    "tracked_map_payload",
    "tracked_map_payload_for_run",
    "write_concept_map",
    "write_run_artifact",
    "write_tracked_map",
]
