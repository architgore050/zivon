"""The series volume and coverage gate (FEATURE-MAP SER-13 / CNT-12).

The approved minimums are product decisions (`factory/series/__init__.py`), not
targets to round towards. This gate is the honest counter: it compares what the
assembler actually delivered against the approved table, and it reports gaps in
named units - series, chapter, paper - so the admin view and the next content
batch can act on them.

The prototype has banks for two chapters. That means several rules fire on real
data today. That is the point: the gate is built and tested against a
full-syllabus fixture (`evals/goldens/exam/volume/`) so it is proven to pass
when the volume is real, and it names the real shortfall instead of hiding it
behind a token sample.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from factory.exam.report import Issue

from . import SERIES_ORDER, minimum_volume, series_spec

FULL_PAPER_SERIES = ("pyq_pattern", "board_practice")


def _active(series: Mapping[str, Any]) -> bool:
    return bool(series.get("enabled"))


def check_minimums(class_num: int, series: Sequence[Mapping[str, Any]]) -> list[Issue]:
    issues: list[Issue] = []
    for manifest in series:
        if not _active(manifest):
            continue
        series_id = str(manifest["series_id"])
        minimum = minimum_volume(class_num, series_id)
        delivered = manifest.get("delivered") or {}
        shortfalls: list[str] = []
        for key, required in minimum.items():
            actual = _delivered_value(delivered, key)
            if actual < int(required):
                shortfalls.append(f"{key} {actual}/{required}")
        if shortfalls:
            issues.append(
                Issue(
                    rule=f"series.minimum.{series_id}",
                    severity="major",
                    message=(
                        f"{series_id}: below the approved minimum ("
                        + "; ".join(shortfalls)
                        + ")"
                    ),
                    series_id=series_id,
                )
            )
    return issues


def _delivered_value(delivered: Mapping[str, Any], key: str) -> int:
    value = delivered.get(key, 0)
    if isinstance(value, Mapping):
        # `questions_per_chapter` is a per-chapter map; the gate's number is
        # "how many chapters reached the target", which the manifest records
        # separately. Fall back to the smallest chapter count so a single empty
        # chapter cannot hide behind a healthy total.
        return min((int(v) for v in value.values()), default=0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def check_chapter_coverage(
    *,
    chapters: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    items_by_id: Mapping[str, Mapping[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    chapter_ids = [str(chapter["chapter_id"]) for chapter in chapters]
    for manifest in series:
        if not _active(manifest) or manifest["series_id"] not in FULL_PAPER_SERIES:
            continue
        series_id = str(manifest["series_id"])
        for paper in manifest["papers"]:
            present = set()
            for slot in paper["sections"]:
                item = items_by_id.get(str(slot["item_id"]))
                if item is not None:
                    present.add(str(item["chapter_id"]))
            missing = [cid for cid in chapter_ids if cid not in present]
            if missing:
                preview = ", ".join(missing[:4])
                more = f" (+{len(missing) - 4} more)" if len(missing) > 4 else ""
                issues.append(
                    Issue(
                        rule="series.chapter_coverage",
                        severity="major",
                        message=(
                            f"{series_id}/{paper['paper_id']}: {len(missing)} chapter(s) "
                            f"have no question: {preview}{more}"
                        ),
                        paper_id=str(paper["paper_id"]),
                        series_id=series_id,
                    )
                )
    return issues


def check_chapter_floor(
    *,
    class_num: int,
    chapters: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    items_by_id: Mapping[str, Mapping[str, Any]],
    floor: int,
) -> list[Issue]:
    counts: dict[str, set[str]] = defaultdict(set)
    for manifest in series:
        if not _active(manifest):
            continue
        for item_id in manifest["item_ids"]:
            item = items_by_id.get(item_id)
            if item is not None:
                counts[str(item["chapter_id"])].add(str(item["base_item_id"]))
    issues: list[Issue] = []
    for chapter in chapters:
        chapter_id = str(chapter["chapter_id"])
        count = len(counts.get(chapter_id, set()))
        if count < floor:
            issues.append(
                Issue(
                    rule="series.chapter_floor",
                    severity="major",
                    message=(
                        f"chapter {chapter_id}: {count} distinct question(s) across "
                        f"all series, floor is {floor}"
                    ),
                    chapter_id=chapter_id,
                )
            )
    return issues


def check_concept_coverage(
    *,
    chapters: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    items_by_id: Mapping[str, Mapping[str, Any]],
) -> list[Issue]:
    """Every concept in AI Lesson, and in at least one of Challenge/Loop."""
    by_series: dict[str, set[str]] = defaultdict(set)
    for manifest in series:
        if not _active(manifest):
            continue
        for item_id in manifest["item_ids"]:
            item = items_by_id.get(item_id)
            if item is not None:
                by_series[str(manifest["series_id"])].add(str(item["concept_id"]))
    issues: list[Issue] = []
    for chapter in chapters:
        chapter_id = str(chapter["chapter_id"])
        concepts = [
            str(concept["concept_id"]) for concept in chapter.get("concepts", [])
        ]
        if not concepts:
            continue
        lesson_missing = [c for c in concepts if c not in by_series["ai_lesson"]]
        drill_missing = [
            c
            for c in concepts
            if c not in by_series["challenge"] and c not in by_series["loop"]
        ]
        if lesson_missing:
            issues.append(
                Issue(
                    rule="series.concept_coverage",
                    severity="major",
                    message=(
                        f"AI lesson series misses {len(lesson_missing)} of "
                        f"{len(concepts)} concept(s) in {chapter_id}"
                    ),
                    chapter_id=chapter_id,
                    series_id="ai_lesson",
                )
            )
        if drill_missing:
            issues.append(
                Issue(
                    rule="series.concept_coverage",
                    severity="major",
                    message=(
                        f"Challenge/Loop miss {len(drill_missing)} of "
                        f"{len(concepts)} concept(s) in {chapter_id}"
                    ),
                    chapter_id=chapter_id,
                    series_id="challenge",
                )
            )
    return issues


def check_paper_structure(
    *,
    blueprint: Mapping[str, Any],
    series: Sequence[Mapping[str, Any]],
) -> list[Issue]:
    template: list[dict[str, Any]] = [
        {
            "id": str(row["id"]),
            "marks_each": int(row["marks_each"]),
            "question_count": int(row["question_count"]),
        }
        for row in blueprint["section_template"]
    ]
    template_marks = sum(row["marks_each"] * row["question_count"] for row in template)
    issues: list[Issue] = []
    for manifest in series:
        if not _active(manifest) or manifest["series_id"] not in FULL_PAPER_SERIES:
            continue
        for paper in manifest["papers"]:
            observed: dict[str, list[int]] = defaultdict(list)
            for slot in paper["sections"]:
                observed[str(slot["section"])].append(int(slot["marks"]))
            observed_ids = list(observed)
            template_ids = [row["id"] for row in template]
            if observed_ids != template_ids:
                issues.append(
                    Issue(
                        rule="series.paper_structure",
                        severity="fatal",
                        message=(
                            f"{manifest['series_id']}/{paper['paper_id']}: sections "
                            f"{observed_ids} do not match the blueprint template "
                            f"{template_ids}"
                        ),
                        paper_id=str(paper["paper_id"]),
                        series_id=str(manifest["series_id"]),
                    )
                )
                continue
            for row in template:
                marks = observed[row["id"]]
                if len(marks) != row["question_count"]:
                    issues.append(
                        Issue(
                            rule="series.paper_structure",
                            severity="fatal",
                            message=(
                                f"{manifest['series_id']}/{paper['paper_id']}: "
                                f"section {row['id']} has {len(marks)} slots, "
                                f"template has {row['question_count']}"
                            ),
                            paper_id=str(paper["paper_id"]),
                            series_id=str(manifest["series_id"]),
                        )
                    )
                elif any(value != row["marks_each"] for value in marks):
                    issues.append(
                        Issue(
                            rule="series.paper_structure",
                            severity="fatal",
                            message=(
                                f"{manifest['series_id']}/{paper['paper_id']}: "
                                f"section {row['id']} slot marks disagree with "
                                f"{row['marks_each']}"
                            ),
                            paper_id=str(paper["paper_id"]),
                            series_id=str(manifest["series_id"]),
                        )
                    )
            if int(paper["marks_total"]) != template_marks:
                issues.append(
                    Issue(
                        rule="series.paper_structure",
                        severity="fatal",
                        message=(
                            f"{manifest['series_id']}/{paper['paper_id']}: paper is "
                            f"{paper['marks_total']} marks, template is "
                            f"{template_marks}"
                        ),
                        paper_id=str(paper["paper_id"]),
                        series_id=str(manifest["series_id"]),
                    )
                )
    return issues


def check_series_languages(
    *,
    series: Sequence[Mapping[str, Any]],
    items_by_id: Mapping[str, Mapping[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    for manifest in series:
        if not _active(manifest):
            continue
        policy = set(manifest["language_policy"])
        for item_id in manifest["item_ids"]:
            item = items_by_id.get(item_id)
            if item is None:
                continue
            missing = policy - set(item.get("languages") or [])
            if missing:
                issues.append(
                    Issue(
                        rule="series.language",
                        severity="fatal",
                        message=(
                            f"{manifest['series_id']}: item {item_id} is missing "
                            f"{sorted(missing)}"
                        ),
                        item_id=str(item_id),
                        series_id=str(manifest["series_id"]),
                    )
                )
    return issues


def check_volume(
    *,
    class_num: int,
    blueprint: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    series: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    chapter_floor: int,
) -> dict[str, Any]:
    """Every volume/coverage rule, in one report the admin view can read."""
    items_by_id = {str(item["item_id"]): item for item in items}
    issues: list[Issue] = []
    issues.extend(check_minimums(class_num, series))
    issues.extend(
        check_chapter_coverage(
            chapters=chapters,
            series=series,
            items_by_id=items_by_id,
        )
    )
    issues.extend(
        check_chapter_floor(
            class_num=class_num,
            chapters=chapters,
            series=series,
            items_by_id=items_by_id,
            floor=chapter_floor,
        )
    )
    issues.extend(
        check_concept_coverage(
            chapters=chapters, series=series, items_by_id=items_by_id
        )
    )
    issues.extend(check_paper_structure(blueprint=blueprint, series=series))
    issues.extend(check_series_languages(series=series, items_by_id=items_by_id))
    by_series: dict[str, dict[str, Any]] = {}
    for spec_id in SERIES_ORDER:
        manifest = next((s for s in series if s["series_id"] == spec_id), None)
        if manifest is None:
            continue
        spec = series_spec(spec_id)
        by_series[spec_id] = {
            "status": manifest["status"],
            "minimum": manifest["minimum"],
            "delivered": manifest["delivered"],
            "gap": manifest["gap"],
            "feature_id": spec.feature_id,
        }
    return {
        "issues": issues,
        "by_series": by_series,
        "counts": {
            "series": len(series),
            "active_series": sum(1 for s in series if _active(s)),
            "items": len(items),
        },
    }


__all__ = [
    "FULL_PAPER_SERIES",
    "check_chapter_coverage",
    "check_chapter_floor",
    "check_concept_coverage",
    "check_minimums",
    "check_paper_structure",
    "check_series_languages",
    "check_volume",
]
