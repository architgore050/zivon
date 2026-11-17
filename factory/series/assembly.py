"""E3-series: assemble the six test series from the blueprint and the item pools.

Inputs are the E1 metadata, the E2 blueprint and the P2 assessment banks
(`sources/syllabus/chapters/<chapter>.items.json`). The banks are curated Zivon
questions - generated content, not CBSE text - so they can be reused as series
items in blueprint mode. Everything this stage emits is labelled with its
`source_type`, `pattern_ref` and a similarity record.

What the assembler does *not* do is pretend. A full paper has 27 (Class 10
Physics section) or 33 (Class 12) slots; the prototype's two item banks cannot
fill five papers. Empty slots stay `item_id: null` and are counted in
`delivered`/`gap`, so the volume gate refuses to publish and the admin view can
name exactly what is missing. Nothing is duplicated to make a number look right:
an item may appear in several series (allowed) but never twice inside one paper
or one set.

Series assembly is deterministic: chapter-to-slot assignment is a largest-
remainder allocation over blueprint shares, selection is ordered by item id, and
a rebuild from the same inputs produces the same pack hash.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factory.exam import SLOT_ITEM_TYPES
from factory.exam.config import ExamConfig
from factory.exam.errors import ExamStageError
from factory.exam.report import Issue, gate_report
from factory.exam.similarity import check_text
from factory.exam.validators import validate_item, validate_series_manifest

from . import minimum_volume, series_copy, series_spec

STAGE_ID = "E3-series"

_NATURAL_RE = re.compile(r"^([0-9]+)")


# ------------------------------------------------------------------- the pool
def _bank_path(cfg: ExamConfig, chapter_id: str) -> Path:
    return cfg.chapters_dir / f"{chapter_id}.items.json"


def _answer_for(item: Mapping[str, Any]) -> dict[str, Any]:
    answer = dict(item.get("answer") or {})
    if item["type"] in ("mcq", "assertion_reason"):
        return {"index": int(answer["index"])}
    if item["type"] == "numeric":
        return {
            "value": float(answer["value"]),
            "tolerance": float(answer["tolerance"]),
            "unit": str(answer["unit"]),
        }
    return {"kind": "open"}


def load_pool(
    cfg: ExamConfig,
    *,
    chapters: Sequence[Mapping[str, Any]],
    generated_at: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Read the P2 banks for this class and project them into series items.

    Returns `(items, gaps)` where `gaps` maps a chapter id to the reason it has
    no bank (recorded, never silently skipped).
    """
    chapter_ids = [str(chapter["chapter_id"]) for chapter in chapters]
    chapter_class = {str(c["chapter_id"]): int(c["class"]) for c in chapters}
    items: list[dict[str, Any]] = []
    gaps: dict[str, str] = {}
    seen: set[str] = set()
    for chapter_id in chapter_ids:
        path = _bank_path(cfg, chapter_id)
        if not path.is_file():
            gaps[chapter_id] = "no_assessment_bank"
            continue
        bank = json.loads(path.read_text(encoding="utf-8"))
        for raw in bank.get("items", []):
            base_id = str(raw["item_id"])
            if base_id in seen:
                raise ExamStageError(f"item id {base_id!r} appears in two banks")
            seen.add(base_id)
            item_id = f"exam-{base_id}"
            item: dict[str, Any] = {
                "item_id": item_id,
                "base_item_id": base_id,
                "origin": "assessment_bank",
                "class_level": int(chapter_class[chapter_id]),
                "chapter_id": chapter_id,
                "concept_id": str(raw["concept_id"]),
                "type": str(raw["type"]),
                "difficulty": str(raw["difficulty"]),
                "marks": int(raw["marks"]),
                "section": None,
                "languages": ["en", "hi", "hi-Latn"],
                "locales": {
                    language: {
                        key: value
                        for key, value in dict(locale).items()
                        if key
                        in (
                            "prompt",
                            "options",
                            "explanation",
                            "misconception",
                            "model_answer",
                        )
                    }
                    for language, locale in raw["locales"].items()
                },
                "answer": _answer_for(raw),
                "source_type": "generated_blueprint",
                "source_ref": None,
                "licence_basis": "none",
                "permission_ref": None,
                "pattern_ref": f"{chapter_id}:{raw['type']}:{int(raw['marks'])}",
                "similarity": check_text(
                    str((raw.get("locales") or {}).get("en", {}).get("prompt") or ""),
                    [],  # blueprint mode stores no source text (DEC-COMP-001)
                    ngram=cfg.similarity.ngram,
                    max_overlap=cfg.similarity.max_overlap,
                    checked_at=generated_at,
                ),
                "series_ids": [],
            }
            items.append(item)
    items.sort(
        key=lambda item: (item["chapter_id"], item["type"], item["base_item_id"])
    )
    return items, gaps


def item_languages(item: Mapping[str, Any]) -> list[str]:
    return list(item.get("languages") or [])


# --------------------------------------------------------------- slot plans
def _natural_key(value: str) -> tuple[int, str]:
    match = _NATURAL_RE.match(str(value))
    return (int(match.group(1)) if match else 999, str(value))


def _latest_paper(
    ingest: Mapping[str, Any], blueprint: Mapping[str, Any]
) -> Mapping[str, Any]:
    used = set(blueprint["papers_used"])
    candidates = [
        paper
        for paper in ingest["papers"]
        if paper["paper_id"] in used
        and int(paper["class_num"]) == blueprint["class_num"]
    ]
    if not candidates:
        raise ExamStageError("blueprint cites no ingested paper for this class")
    return max(candidates, key=lambda paper: (int(paper["year"]), paper["paper_id"]))


def build_slot_plan(
    ingest: Mapping[str, Any], blueprint: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """One slot per question of the latest paper: section, type, marks.

    The chapter is allocated separately (largest remainder) so a series covers
    every chapter the blueprint weighted, instead of copying one year's map.
    """
    latest = _latest_paper(ingest, blueprint)
    paper_id = str(latest["paper_id"])
    questions = [
        question for question in ingest["questions"] if question["paper_id"] == paper_id
    ]
    questions.sort(key=lambda question: _natural_key(question["question_no"]))
    return [
        {
            "section": str(question["section"]),
            "type": str(question["type"]),
            "marks": int(question["marks"]),
        }
        for question in questions
    ]


def allocate_chapters(
    slots: Sequence[Mapping[str, Any]], blueprint: Mapping[str, Any]
) -> list[str]:
    """Assign a chapter to every slot by largest-remainder over blueprint shares.

    A chapter with a positive share appears before any chapter exceeds its
    target; ties break on chapter id so the plan is reproducible.
    """
    rows = sorted(
        (row for row in blueprint["chapters"] if float(row["share"]) > 0),
        key=lambda row: (-float(row["share"]), row["chapter_id"]),
    )
    if not rows:
        raise ExamStageError("blueprint has no chapter with a positive share")
    total_marks = sum(int(slot["marks"]) for slot in slots)
    target = {str(row["chapter_id"]): float(row["share"]) * total_marks for row in rows}
    assigned: dict[str, float] = {chapter_id: 0.0 for chapter_id in target}
    order = {str(row["chapter_id"]): index for index, row in enumerate(rows)}
    allocation: list[str] = []
    for slot in slots:
        chapter_id = max(
            target,
            key=lambda cid: (
                target[cid] - assigned[cid],
                -order[cid],
            ),
        )
        assigned[chapter_id] += int(slot["marks"])
        allocation.append(chapter_id)
    return allocation


def slot_accepts(item: Mapping[str, Any], slot: Mapping[str, Any]) -> bool:
    accepted = SLOT_ITEM_TYPES.get(str(slot["type"]), ())
    return str(item["type"]) in accepted and int(item["marks"]) == int(slot["marks"])


def rotate_pool(
    pool: Sequence[Mapping[str, Any]], *, paper_index: int, paper_count: int
) -> list[Mapping[str, Any]]:
    """Rotate every chapter's items for paper `paper_index`.

    A single rotation of the whole pool only moves the one chapter whose block
    straddles the cut, so every paper still chooses the same first item per
    (chapter, type) and the "five papers" come out identical. Rotating inside
    each chapter - by a stride derived from the paper count - changes the first
    available item for every chapter, which is what makes the papers different.
    The result is deterministic: chapter order is first appearance in the pool,
    which `load_pool` sorts by chapter id.
    """
    blocks: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for item in pool:
        chapter_id = str(item["chapter_id"])
        if chapter_id not in blocks:
            order.append(chapter_id)
        blocks[chapter_id].append(item)
    rotated: list[Mapping[str, Any]] = []
    for chapter_id in order:
        block = blocks[chapter_id]
        stride = max(1, len(block) // max(1, paper_count))
        shift = (paper_index * stride) % len(block)
        rotated.extend(block[shift:] + block[:shift])
    return rotated


def fill_slots(
    slots: Sequence[Mapping[str, Any]],
    allocation: Sequence[str],
    pool: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any] | None]:
    """Greedy, deterministic slot filling. Unfillable slots stay `None`.

    A slot allocated to chapter X is filled only by an item from chapter X. A
    Light question standing in an Electricity slot would make the paper look
    more complete than it is and would let the coverage gate pass on a paper
    that never teaches the chapter; an empty slot is the honest answer.
    """
    used: set[str] = set()
    chosen: list[Mapping[str, Any] | None] = []
    for slot, chapter_id in zip(slots, allocation):
        candidates = [
            item
            for item in pool
            if item["item_id"] not in used
            and item["chapter_id"] == chapter_id
            and slot_accepts(item, slot)
        ]
        pick = candidates[0] if candidates else None
        if pick is not None:
            used.add(pick["item_id"])
        chosen.append(pick)
    return chosen


def build_paper(
    *,
    paper_id: str,
    slots: Sequence[Mapping[str, Any]],
    allocation: Sequence[str],
    chosen: Sequence[Mapping[str, Any] | None],
) -> dict[str, Any]:
    section_slots: list[dict[str, Any]] = []
    item_ids: list[str] = []
    for index, (slot, chapter_id, item) in enumerate(zip(slots, allocation, chosen)):
        item_id = item["item_id"] if item is not None else None
        if item_id is not None:
            item_ids.append(str(item_id))
        section_slots.append(
            {
                "slot_id": f"{paper_id}-q{index + 1:02d}",
                "section": str(slot["section"]),
                "type": str(slot["type"]),
                "marks": int(slot["marks"]),
                "chapter_id": str(chapter_id),
                "item_id": item_id,
            }
        )
    return {
        "paper_id": paper_id,
        "sections": section_slots,
        "item_ids": sorted(set(item_ids)),
        "filled_slots": len(item_ids),
        "total_slots": len(section_slots),
        "marks_total": sum(int(slot["marks"]) for slot in slots),
    }


# -------------------------------------------------------------- series builds
def _assign(items: Sequence[Mapping[str, Any]], series_id: str) -> None:
    for item in items:
        if series_id not in item["series_ids"]:
            item["series_ids"].append(series_id)


def _round_robin(
    chapter_items: Mapping[str, Sequence[Mapping[str, Any]]],
    chapters: Sequence[str],
    size: int,
    *,
    offset: int = 0,
) -> list[Mapping[str, Any]]:
    """Take `size` items cycling through chapters, deterministic order.

    `offset` rotates the starting chapter and the starting item inside each
    queue, so a second mixed test / unit test is a different paper rather than
    a copy of the first with the same questions in the same order.
    """
    queues = {chapter: list(chapter_items.get(chapter, [])) for chapter in chapters}
    for queue in queues.values():
        if queue:
            shift = offset % len(queue)
            queue[:] = queue[shift:] + queue[:shift]
    order = list(chapters)
    if order:
        shift = offset % len(order)
        order = order[shift:] + order[:shift]
    picked: list[Mapping[str, Any]] = []
    cursor = 0
    while len(picked) < size and any(queues.values()):
        chapter = order[cursor % len(order)]
        cursor += 1
        if queues[chapter]:
            picked.append(queues[chapter].pop(0))
    return picked


def _build_ai_lesson(
    *,
    cfg: ExamConfig,
    class_num: int,
    subject_en: str,
    chapters: Sequence[Mapping[str, Any]],
    pool: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    spec = series_spec("ai_lesson")
    chapter_ids = [str(chapter["chapter_id"]) for chapter in chapters]
    by_chapter: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in pool:
        by_chapter[item["chapter_id"]].append(item)
    per_chapter = int(minimum_volume(class_num, "ai_lesson")["questions_per_chapter"])
    selected: list[Mapping[str, Any]] = []
    chapter_counts: dict[str, int] = {}
    sets: list[dict[str, Any]] = []
    for chapter_id in chapter_ids:
        chapter_items = by_chapter.get(chapter_id, [])
        # Round-robin over the chapter's concepts, so "every concept appears in
        # the AI lesson series" (SER-13) is true by construction rather than by
        # luck of the pool's ordering.
        take = _spread(
            chapter_items,
            per_chapter,
            key_fn=lambda item: item["concept_id"],
        )
        chapter_counts[chapter_id] = len(take)
        selected.extend(take)
        if take:
            sets.append(
                {
                    "set_id": f"ai-lesson-{chapter_id}-test",
                    "kind": "chapter_test",
                    "chapter_id": chapter_id,
                    "item_ids": [
                        item["item_id"] for item in take[: cfg.series.chapter_test_size]
                    ],
                }
            )
    mixed_count = int(minimum_volume(class_num, "ai_lesson")["mixed_tests"])
    for index in range(mixed_count):
        mixed = _round_robin(
            by_chapter, chapter_ids, cfg.series.mixed_test_size, offset=index
        )
        if not mixed:
            continue
        sets.append(
            {
                "set_id": f"ai-lesson-mixed-{index + 1:02d}",
                "kind": "mixed_test",
                "chapter_id": None,
                "item_ids": [item["item_id"] for item in mixed],
            }
        )
    _assign(selected, "ai_lesson")
    tests_per_chapter = {
        chapter_id: 1 if chapter_counts.get(chapter_id, 0) else 0
        for chapter_id in chapter_ids
    }
    delivered: dict[str, Any] = {
        "questions_per_chapter": chapter_counts,
        "chapter_tests": sum(1 for entry in sets if entry["kind"] == "chapter_test"),
        "chapter_tests_per_chapter": tests_per_chapter,
        "mixed_tests": sum(1 for entry in sets if entry["kind"] == "mixed_test"),
        "questions": len(selected),
    }
    minimum = minimum_volume(class_num, "ai_lesson")
    gap = {
        "questions_per_chapter": {
            chapter_id: max(0, per_chapter - chapter_counts.get(chapter_id, 0))
            for chapter_id in chapter_ids
        },
        "chapter_tests": max(0, len(chapter_ids) - delivered["chapter_tests"]),
        "chapter_tests_per_chapter": {
            chapter_id: 0 if tests_per_chapter[chapter_id] else 1
            for chapter_id in chapter_ids
        },
        "mixed_tests": max(0, mixed_count - delivered["mixed_tests"]),
    }
    manifest = _manifest(
        spec,
        class_num=class_num,
        subject_en=subject_en,
        minimum=minimum,
        delivered=delivered,
        gap=gap,
        item_ids=sorted({item["item_id"] for item in selected}),
        papers=[],
        sets=sets,
        marks_total=None,
        duration_min=None,
    )
    return manifest, selected


def _build_paper_series(
    *,
    cfg: ExamConfig,
    ingest: Mapping[str, Any],
    blueprint: Mapping[str, Any],
    class_num: int,
    subject_en: str,
    pool: Sequence[Mapping[str, Any]],
    series_id: str,
    count: int,
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    spec = series_spec(series_id)
    slots = build_slot_plan(ingest, blueprint)
    allocation = allocate_chapters(slots, blueprint)
    papers: list[dict[str, Any]] = []
    used_items: list[Mapping[str, Any]] = []
    complete = 0
    for index in range(count):
        # Rotate each chapter's block so five papers are five different papers,
        # not the same questions in the same order (and a volume gate that
        # counts papers cannot pass on duplicate copies).
        rotated = rotate_pool(pool, paper_index=index, paper_count=count)
        chosen = fill_slots(slots, allocation, rotated)
        paper = build_paper(
            paper_id=f"{series_id.replace('_', '-')}-p{index + 1:02d}",
            slots=slots,
            allocation=allocation,
            chosen=chosen,
        )
        if paper["filled_slots"] == paper["total_slots"]:
            complete += 1
        papers.append(paper)
        used_items.extend(item for item in chosen if item is not None)
    unique_items = {item["item_id"]: item for item in used_items}
    _assign(list(unique_items.values()), series_id)
    template_marks = sum(int(slot["marks"]) for slot in slots)
    delivered_key = "full_papers"
    minimum = minimum_volume(class_num, series_id)
    delivered: dict[str, Any] = {
        delivered_key: complete,
        "papers": len(papers),
        "filled_slots": sum(paper["filled_slots"] for paper in papers),
        "total_slots": sum(paper["total_slots"] for paper in papers),
    }
    gap: dict[str, Any] = {
        delivered_key: max(0, int(minimum[delivered_key]) - complete),
        "filled_slots": max(0, delivered["total_slots"] - delivered["filled_slots"]),
    }
    sets: list[dict[str, Any]] = []
    if series_id == "pyq_pattern":
        units = int(minimum["chapter_or_unit_tests"])
        by_chapter: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for item in pool:
            by_chapter[item["chapter_id"]].append(item)
        chapters = [row["chapter_id"] for row in blueprint["chapters"]]
        for index in range(units):
            unit_items = _round_robin(
                by_chapter, chapters, cfg.series.unit_test_size, offset=index
            )
            if not unit_items:
                break
            _assign(unit_items, series_id)
            sets.append(
                {
                    "set_id": f"pyq-pattern-unit-{index + 1:02d}",
                    "kind": "unit_test",
                    "chapter_id": None,
                    "item_ids": [item["item_id"] for item in unit_items],
                }
            )
        delivered["chapter_or_unit_tests"] = len(sets)
        gap["chapter_or_unit_tests"] = max(0, units - len(sets))
    set_item_ids = {item_id for entry in sets for item_id in entry["item_ids"]}
    manifest = _manifest(
        spec,
        class_num=class_num,
        subject_en=subject_en,
        minimum=minimum,
        delivered=delivered,
        gap=gap,
        item_ids=sorted(set(unique_items) | set_item_ids),
        papers=papers,
        sets=sets,
        marks_total=template_marks,
        duration_min=180,
    )
    return manifest, list(unique_items.values())


def _spread(
    items: Sequence[Mapping[str, Any]],
    target: int,
    *,
    key_fn,
) -> list[Mapping[str, Any]]:
    """Take `target` items cycling through buckets, in the given order.

    A straight `items[:target]` slice of a chapter/type-sorted pool would hand
    every Challenge/Loop/Lesson slot to the first few buckets and leave the
    rest uncovered; the series gate requires every chapter and every concept to
    appear. Bucket order is first appearance, so a caller's ranking still
    decides which buckets are visited first.
    """
    queues: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    order: list[Any] = []
    for item in items:
        key = key_fn(item)
        if key not in queues:
            order.append(key)
        queues[key].append(item)
    picked: list[Mapping[str, Any]] = []
    cursor = 0
    while len(picked) < target and any(queues.values()):
        key = order[cursor % len(order)]
        cursor += 1
        if queues[key]:
            picked.append(queues[key].pop(0))
    return picked


def _spread_across_chapters(
    items: Sequence[Mapping[str, Any]], target: int
) -> list[Mapping[str, Any]]:
    return _spread(
        items, target, key_fn=lambda item: (item["chapter_id"], item["concept_id"])
    )


def _build_bank_series(
    *,
    cfg: ExamConfig,
    class_num: int,
    subject_en: str,
    pool: Sequence[Mapping[str, Any]],
    series_id: str,
    predicate,
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    spec = series_spec(series_id)
    minimum = minimum_volume(class_num, series_id)
    target = int(minimum["questions"])
    set_size = int(cfg.series.set_size)
    eligible = [item for item in pool if predicate(item)]
    selected = _spread_across_chapters(eligible, target)
    sets: list[dict[str, Any]] = []
    for index in range(0, len(selected), set_size):
        chunk = selected[index : index + set_size]
        sets.append(
            {
                "set_id": f"{series_id.replace('_', '-')}-set-{index // set_size + 1:02d}",
                "kind": "set",
                "chapter_id": None,
                "item_ids": [item["item_id"] for item in chunk],
            }
        )
    _assign(selected, series_id)
    delivered = {"questions": len(selected), "sets": len(sets)}
    gap = {
        "questions": max(0, target - delivered["questions"]),
        "sets": max(0, int(minimum["sets"]) - delivered["sets"]),
    }
    manifest = _manifest(
        spec,
        class_num=class_num,
        subject_en=subject_en,
        minimum=minimum,
        delivered=delivered,
        gap=gap,
        item_ids=sorted({item["item_id"] for item in selected}),
        papers=[],
        sets=sets,
        marks_total=None,
        duration_min=None,
    )
    return manifest, selected


def _build_loop(
    *,
    cfg: ExamConfig,
    blueprint: Mapping[str, Any],
    class_num: int,
    subject_en: str,
    pool: Sequence[Mapping[str, Any]],
    series_id: str = "loop",
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    """Loop drills the highest-frequency archetypes the blueprint measured."""
    archetypes = {
        (row["chapter_id"], row["type"], int(row["marks"])): float(row["share"])
        for row in blueprint["archetypes"]
    }
    ranked = sorted(
        pool,
        key=lambda item: (
            -archetypes.get(
                (item["chapter_id"], item["type"], int(item["marks"])), 0.0
            ),
            item["base_item_id"],
        ),
    )
    return _build_bank_series(
        cfg=cfg,
        class_num=class_num,
        subject_en=subject_en,
        pool=ranked,
        series_id=series_id,
        predicate=lambda item: True,
    )


def _build_exact_pyq(
    *,
    class_num: int,
    subject_en: str,
    pool: Sequence[Mapping[str, Any]],
    enabled: bool,
) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    spec = series_spec("exact_pyq")
    minimum = minimum_volume(class_num, "exact_pyq")
    if not enabled:
        manifest = _manifest(
            spec,
            class_num=class_num,
            subject_en=subject_en,
            minimum=minimum,
            delivered={"past_years": 0},
            gap={"past_years": int(minimum["past_years"])},
            item_ids=[],
            papers=[],
            sets=[],
            marks_total=None,
            duration_min=None,
            disabled_reason="no_verbatim_clearance",
        )
        return manifest, []
    verbatim = [item for item in pool if item["source_type"].startswith("verbatim_")]
    # Count real years only: an item without `source_ref.year` cannot make the
    # "5 years" minimum, and `str(None)` must never be counted as a year.
    years = sorted(
        {
            str((item.get("source_ref") or {}).get("year"))
            for item in verbatim
            if (item.get("source_ref") or {}).get("year") not in (None, "")
        }
    )
    delivered = {"past_years": len(years)}
    manifest = _manifest(
        spec,
        class_num=class_num,
        subject_en=subject_en,
        minimum=minimum,
        delivered=delivered,
        gap={"past_years": max(0, int(minimum["past_years"]) - len(years))},
        item_ids=sorted(item["item_id"] for item in verbatim),
        papers=[],
        sets=[],
        marks_total=None,
        duration_min=None,
    )
    manifest["notice_id"] = "N-03"
    manifest["copy"] = (
        f"{spec.label} uses questions from question papers published by CBSE."
    )
    return manifest, verbatim


def _manifest(
    spec,
    *,
    class_num: int,
    subject_en: str,
    minimum: Mapping[str, int],
    delivered: Mapping[str, Any],
    gap: Mapping[str, Any],
    item_ids: Sequence[str],
    papers: Sequence[Mapping[str, Any]],
    sets: Sequence[Mapping[str, Any]],
    marks_total: int | None,
    duration_min: int | None,
    disabled_reason: str | None = None,
) -> dict[str, Any]:
    enabled = disabled_reason is None
    return {
        "series_id": spec.series_id,
        "label": spec.label,
        "label_key": spec.label_key,
        "purpose": spec.purpose,
        "status": "active" if enabled else "disabled",
        "enabled": enabled,
        "disabled_reason": disabled_reason,
        "language_policy": list(spec.languages_for_pack()),
        "source_policy": spec.source_policy,
        "notice_id": spec.notice_id,
        "copy": series_copy(spec, class_num=class_num, subject_en=subject_en),
        "minimum": dict(minimum),
        "delivered": dict(delivered),
        "gap": dict(gap),
        "item_ids": list(item_ids),
        "papers": list(papers),
        "sets": list(sets),
        "marks_total": marks_total,
        "duration_min": duration_min,
    }


# -------------------------------------------------------------------- stage
def validate_pack_items(
    *,
    cfg: ExamConfig,
    series: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    chapters: Sequence[Mapping[str, Any]],
) -> list[Issue]:
    """Every manifest and item rule, against whatever is about to be published.

    E3 runs this to refuse an invalid assembly; E4 runs it again because the
    publish gate must validate the pack it is about to ship, not trust an
    upstream report (cbse-exam-content.md §7.3's two-stage gate). A seeded
    defect injected after E3 is therefore still caught at publish time.
    """
    items_by_id = {str(item["item_id"]): item for item in items}
    compliance = cfg.compliance.to_dict()
    issues: list[Issue] = []
    for manifest in series:
        issues.extend(
            validate_series_manifest(
                manifest, items_by_id=items_by_id, compliance=compliance
            )
        )
    for item in items:
        # Item rules are per series: the strictest language policy an item is
        # used by decides what it must carry.
        series_ids = item.get("series_ids") or []
        strict = max(
            (series_spec(sid) for sid in series_ids),
            key=lambda spec: len(spec.languages_for_pack()),
            default=series_spec("board_practice"),
        )
        issues.extend(
            validate_item(
                item,
                series={
                    "series_id": strict.series_id,
                    "language_policy": list(strict.languages_for_pack()),
                },
                chapters=chapters,
                similarity_max_overlap=cfg.similarity.max_overlap,
                compliance=compliance,
            )
        )
    return issues


def assemble_class(
    cfg: ExamConfig,
    *,
    blueprint: Mapping[str, Any],
    ingest: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    class_num = int(blueprint["class_num"])
    subject_en = str(blueprint["subject"])
    if class_num == 10:
        subject_en = "Science (Physics section)"
    pool, bank_gaps = load_pool(cfg, chapters=chapters, generated_at=generated_at)
    pool_by_id: dict[str, Any] = {item["item_id"]: item for item in pool}

    ai_lesson, ai_items = _build_ai_lesson(
        cfg=cfg,
        class_num=class_num,
        subject_en=subject_en,
        chapters=chapters,
        pool=pool,
    )
    pyq_pattern, pattern_items = _build_paper_series(
        cfg=cfg,
        ingest=ingest,
        blueprint=blueprint,
        class_num=class_num,
        subject_en=subject_en,
        pool=pool,
        series_id="pyq_pattern",
        count=int(minimum_volume(class_num, "pyq_pattern")["full_papers"]),
    )
    board_practice, board_items = _build_paper_series(
        cfg=cfg,
        ingest=ingest,
        blueprint=blueprint,
        class_num=class_num,
        subject_en=subject_en,
        pool=pool,
        series_id="board_practice",
        count=int(minimum_volume(class_num, "board_practice")["full_papers"]),
    )
    challenge, challenge_items = _build_bank_series(
        cfg=cfg,
        class_num=class_num,
        subject_en=subject_en,
        pool=pool,
        series_id="challenge",
        predicate=lambda item: item["difficulty"] == "hard",
    )
    loop, loop_items = _build_loop(
        cfg=cfg,
        blueprint=blueprint,
        class_num=class_num,
        subject_en=subject_en,
        pool=pool,
    )
    exact_pyq, exact_items = _build_exact_pyq(
        class_num=class_num,
        subject_en=subject_en,
        pool=pool,
        enabled=bool(cfg.compliance.exact_pyq_visible),
    )

    manifests = [ai_lesson, pyq_pattern, exact_pyq, board_practice, challenge, loop]
    used_ids = {item_id for manifest in manifests for item_id in manifest["item_ids"]}
    for series_items in (
        ai_items,
        pattern_items,
        board_items,
        challenge_items,
        loop_items,
        exact_items,
    ):
        for item in series_items:
            pool_by_id.setdefault(item["item_id"], item)
    items = [pool_by_id[item_id] for item_id in sorted(used_ids)]

    issues = validate_pack_items(
        cfg=cfg, series=manifests, items=items, chapters=chapters
    )

    report = gate_report(
        issues,
        counts={
            "items": len(items),
            "series": len(manifests),
            "chapters_with_bank": len(chapters) - len(bank_gaps),
            "chapters_without_bank": len(bank_gaps),
        },
    )
    return {
        "schema_version": 1,
        "class_num": class_num,
        "series": manifests,
        "items": items,
        "bank_gaps": bank_gaps,
        "gate": report,
    }


__all__ = [
    "STAGE_ID",
    "allocate_chapters",
    "assemble_class",
    "build_paper",
    "build_slot_plan",
    "fill_slots",
    "load_pool",
    "rotate_pool",
    "slot_accepts",
    "validate_pack_items",
]
