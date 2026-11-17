"""E2-blueprint: derive the paper blueprint from ingested metadata.

`SER-02`: chapter weightage, question-type mix, section structure, recency-
weighted across years. All four are *derived facts about the papers' design*,
which is exactly what `cbse-exam-content.md` §5 permits in blueprint mode.

Recency weighting is explicit and auditable:

    weight(year) = recency_decay ** (latest_year - year)

so a paper from the latest year counts 1.0, the year before `decay`, and so on.
Every weighted number in the output can be recomputed from `papers_used`, the
question rows and `recency.weights`; the eval checker does exactly that.

The section template is taken from the latest included paper and then enforced
against every other included paper by the gate - a blueprint whose own years
disagree about the paper's shape is not a blueprint.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .config import BlueprintPolicy
from .errors import ExamGateError, ExamStageError
from .report import gate_report
from .validators import validate_blueprint

STAGE_ID = "E2-blueprint"


def _normalise_shares(values: Mapping[Any, float]) -> dict[Any, float]:
    """Shares that sum to exactly 1.0 (float) by construction.

    Rounding each share independently leaves a residual that trips an honest
    sum check. The residual goes to the largest bucket, so no share is
    fabricated and the total is exact.
    """
    total = sum(values.values())
    if total <= 0:
        return {key: 0.0 for key in values}
    shares = {key: round(value / total, 6) for key, value in values.items()}
    residual = round(1.0 - sum(shares.values()), 6)
    if residual and shares:
        largest = max(shares, key=lambda key: (shares[key], key))
        shares[largest] = round(shares[largest] + residual, 6)
    return shares


def recency_weights(
    years: Iterable[int], *, decay: float, latest_year: int
) -> dict[int, float]:
    return {
        int(year): round(float(decay) ** (int(latest_year) - int(year)), 6)
        for year in sorted({int(y) for y in years}, reverse=True)
    }


def _included_papers(
    papers: Sequence[Mapping[str, Any]], policy: BlueprintPolicy
) -> list[Mapping[str, Any]]:
    if not papers:
        return []
    latest = max(int(paper["year"]) for paper in papers)
    floor = latest - policy.years_window + 1
    return [
        paper
        for paper in papers
        if paper["paper_type"] in policy.include_paper_types
        and int(paper["year"]) >= floor
    ]


def build_blueprint(
    ingest: Mapping[str, Any],
    *,
    class_num: int,
    chapters: Sequence[Mapping[str, Any]],
    policy: BlueprintPolicy,
) -> dict[str, Any]:
    class_papers = [
        paper for paper in ingest["papers"] if int(paper["class_num"]) == class_num
    ]
    used = _included_papers(class_papers, policy)
    if not used:
        raise ExamStageError(
            f"class {class_num}: no papers of type {list(policy.include_paper_types)} "
            f"inside the {policy.years_window}-year window were ingested"
        )
    used_ids = {str(paper["paper_id"]) for paper in used}
    latest_year = max(int(paper["year"]) for paper in used)
    weights = recency_weights(
        (int(paper["year"]) for paper in used),
        decay=policy.recency_decay,
        latest_year=latest_year,
    )
    chapter_ids = [str(chapter["chapter_id"]) for chapter in chapters]
    questions = [
        question for question in ingest["questions"] if question["paper_id"] in used_ids
    ]
    by_paper: dict[str, list[Mapping[str, Any]]] = {pid: [] for pid in used_ids}
    for question in questions:
        by_paper[str(question["paper_id"])].append(question)

    chapter_marks: dict[str, float] = {cid: 0.0 for cid in chapter_ids}
    chapter_papers: dict[str, set[str]] = {cid: set() for cid in chapter_ids}
    type_marks: dict[str, float] = {}
    archetype_counts: dict[tuple[str, str, int], float] = {}
    for paper in used:
        paper_id = str(paper["paper_id"])
        weight = weights[int(paper["year"])]
        for question in by_paper.get(paper_id, []):
            chapter_id = str(question["chapter_id"])
            marks = int(question["marks"])
            if chapter_id in chapter_marks:
                chapter_marks[chapter_id] += marks * weight
                chapter_papers[chapter_id].add(paper_id)
            type_marks[str(question["type"])] = (
                type_marks.get(str(question["type"]), 0.0) + marks * weight
            )
            key = (chapter_id, str(question["type"]), marks)
            archetype_counts[key] = archetype_counts.get(key, 0.0) + weight

    chapter_shares = _normalise_shares(chapter_marks)
    type_shares = _normalise_shares(type_marks)
    archetype_shares = _normalise_shares(archetype_counts)
    latest_paper = max(
        used, key=lambda paper: (int(paper["year"]), str(paper["paper_id"]))
    )
    section_template = [
        {
            "id": str(section["id"]),
            "marks_each": int(section["marks_each"]),
            "question_count": int(section["question_count"]),
            "marks_total": int(section["marks_each"]) * int(section["question_count"]),
        }
        for section in latest_paper["sections"]
    ]
    subject = str(latest_paper["subject"])
    subject_code = latest_paper.get("subject_code")
    verified = sum(1 for paper in used if paper["provenance"].get("verified") is True)
    unverified = len(used) - verified
    question_map_basis = (
        "published_map"
        if unverified == 0
        and all(
            paper["provenance"].get("question_map_basis") == "published_map"
            for paper in used
        )
        else "authored_estimate"
    )
    blueprint = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "class_num": class_num,
        "subject": subject,
        "subject_code": subject_code,
        "papers_used": sorted(used_ids),
        "window": {
            "start_year": latest_year - policy.years_window + 1,
            "end_year": latest_year,
            "years": policy.years_window,
        },
        "recency": {
            "decay": policy.recency_decay,
            "weights": {str(year): weight for year, weight in weights.items()},
        },
        "chapters": [
            {
                "chapter_id": chapter_id,
                "weighted_marks": round(chapter_marks[chapter_id], 3),
                "share": chapter_shares[chapter_id],
                "papers_observed": len(chapter_papers[chapter_id]),
            }
            for chapter_id in chapter_ids
        ],
        "type_mix": [
            {
                "type": question_type,
                "weighted_marks": round(type_marks[question_type], 3),
                "share": type_shares[question_type],
            }
            for question_type in sorted(type_marks)
        ],
        "section_template": section_template,
        "archetypes": [
            {
                "archetype_id": f"{chapter_id}:{question_type}:{marks}",
                "chapter_id": chapter_id,
                "type": question_type,
                "marks": marks,
                "weighted_count": round(count, 3),
                "share": archetype_shares[(chapter_id, question_type, marks)],
            }
            for (chapter_id, question_type, marks), count in sorted(
                archetype_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "confidence": {
            "verified_papers": verified,
            "unverified_papers": unverified,
            "question_map_basis": question_map_basis,
        },
        "gate": {},
    }
    report = gate_report(
        validate_blueprint(
            blueprint,
            chapters=chapters,
            papers=[paper for paper in class_papers if paper["paper_id"] in used_ids],
        ),
        counts={
            "papers_used": len(used_ids),
            "chapters": len(chapter_ids),
            "archetypes": len(archetype_counts),
        },
    )
    blueprint["gate"] = report
    if report["verdict"] != "pass":
        raise ExamGateError(
            f"E2-blueprint refused for class {class_num}: "
            f"{report['error_count']} blocking finding(s)",
            report=report,
            output=blueprint,
        )
    return blueprint


__all__ = ["STAGE_ID", "build_blueprint", "recency_weights"]
