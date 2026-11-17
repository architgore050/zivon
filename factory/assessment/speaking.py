"""A4-speaking-rubrics: the voice explain-back prompts and their rubric data.

One prompt per chapter/concept cluster: a student speaks for ~45 s, the
assessor looks for 3-5 key ideas (not exact wording), and a model answer plus
self-check is shown afterwards (SPK-04/SPK-05). Every key idea and model
answer carries the NCERT section that justifies it, and every prompt exists in
EN/HI/Hinglish.
"""

from __future__ import annotations

from typing import Any

from . import LANGUAGES
from .config import AssessmentConfig, catalog_book_ids
from .errors import AssessmentGateError
from .generator import ItemGenerator, make_generator
from .validators import (
    blocking_issues,
    gate_report,
    issues_for_reasons,
    validate_speaking_bank,
)

STAGE_ID = "A4-speaking-rubrics"


def run_stage(
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    *,
    generator: ItemGenerator | None = None,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    generator = generator or make_generator(cfg, chapter, llm_client=llm_client)
    result = generator.generate_speaking(chapter)
    bank = result.bank
    issues = validate_speaking_bank(
        bank,
        chapter,
        cfg.policy,
        catalog_book_ids=catalog_book_ids(cfg.catalog_path),
    )
    by_concept: dict[str, int] = {}
    for prompt in bank.get("prompts", []):
        for concept_id in prompt.get("concept_ids", []):
            by_concept[concept_id] = by_concept.get(concept_id, 0) + 1
    counts = {
        "prompts": len(bank.get("prompts", [])),
        "by_concept": dict(sorted(by_concept.items())),
        "languages": list(LANGUAGES),
    }
    report = gate_report(issues, counts=counts)
    output = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "chapter_id": chapter["chapter_id"],
        "class_level": chapter["class"],
        "generator": result.generator,
        "prompts": bank.get("prompts", []),
        "counts": counts,
        "gate": report,
    }
    if report["verdict"] == "fail":
        raise AssessmentGateError(
            "A4-speaking-rubrics failed: "
            + "; ".join(issues_for_reasons(report))
            + f" ({len(blocking_issues(report))} blocking findings)",
            report=report,
            output=output,
        )
    return output


__all__ = ["STAGE_ID", "run_stage"]
