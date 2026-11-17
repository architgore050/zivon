"""A3-practice-items: generate (or load) the chapter's practice bank and gate it.

The deterministic gate is the deliverable: schema, one correct answer, an
explanation, a cited source, a known concept, all three languages, no
duplicate, the required 15-20 count, the type mix, the difficulty mix and
concept coverage. When the generator can improve a failing bank (the live
model path) the stage runs a bounded, progress-aware repair loop inside this
run; when it cannot (seed content), the stage fails with the full report
instead of pretending to loop.
"""

from __future__ import annotations

from typing import Any

from . import DIFFICULTIES, ITEM_TYPES
from .config import AssessmentConfig, catalog_book_ids
from .errors import AssessmentGateError
from .generator import ItemGenerator, make_generator
from .validators import (
    ItemGatePolicy,
    blocking_issues,
    gate_report,
    issues_for_reasons,
    validate_item_bank,
)

STAGE_ID = "A3-practice-items"


def bank_counts(bank: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in (bank.get("items") or []) if isinstance(item, dict)]
    by_concept: dict[str, int] = {}
    for item in items:
        concept_id = item.get("concept_id")
        if concept_id:
            by_concept[concept_id] = by_concept.get(concept_id, 0) + 1
    return {
        "items": len(items),
        "by_type": {t: sum(1 for i in items if i.get("type") == t) for t in ITEM_TYPES},
        "by_difficulty": {
            d: sum(1 for i in items if i.get("difficulty") == d) for d in DIFFICULTIES
        },
        "by_concept": dict(sorted(by_concept.items())),
    }


def _run_gate(
    bank: dict[str, Any],
    chapter: dict[str, Any],
    policy: ItemGatePolicy,
    book_ids: set[str],
) -> tuple[list[Any], dict[str, Any]]:
    issues = validate_item_bank(bank, chapter, policy, catalog_book_ids=book_ids)
    return issues, gate_report(issues, counts=bank_counts(bank))


def generate_with_repair(
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    generator: ItemGenerator,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Generate and gate one chapter's bank. Returns (bank, gate, repair log)."""
    book_ids = catalog_book_ids(cfg.catalog_path)
    result = generator.generate_items(chapter)
    bank = result.bank
    _issues, report = _run_gate(bank, chapter, cfg.policy, book_ids)
    history: list[dict[str, Any]] = [
        {
            "round": 0,
            "kind": "generate",
            "generator": result.generator,
            "error_count": report["error_count"],
            "rules": sorted({i["rule"] for i in blocking_issues(report)}),
        }
    ]
    previous_score = report["error_count"]
    rounds = 0
    while report["verdict"] == "fail" and rounds < cfg.repair_rounds:
        repaired = generator.repair_items(chapter, bank, report)
        if repaired is None:
            break
        rounds += 1
        bank = repaired.bank
        _issues, report = _run_gate(bank, chapter, cfg.policy, book_ids)
        history.append(
            {
                "round": rounds,
                "kind": "repair",
                "generator": repaired.generator,
                "error_count": report["error_count"],
                "rules": sorted({i["rule"] for i in blocking_issues(report)}),
            }
        )
        if report["error_count"] >= previous_score:
            # No progress: a second identical round would burn credits for
            # nothing (the catcher's stall rule, same as the lesson factory).
            break
        previous_score = report["error_count"]
    return bank, report, {"rounds": rounds, "history": history}


def run_stage(
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    *,
    generator: ItemGenerator | None = None,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    generator = generator or make_generator(cfg, chapter, llm_client=llm_client)
    bank, report, repair = generate_with_repair(cfg, chapter, generator)
    generator_label = repair["history"][-1]["generator"]
    output = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "chapter_id": chapter["chapter_id"],
        "class_level": chapter["class"],
        "generator": generator_label,
        "source": bank.get("source", {}),
        "items": bank.get("items") or [],
        "counts": report["counts"],
        "gate": report,
        "repair": repair,
    }
    if report["verdict"] == "fail":
        raise AssessmentGateError(
            "A3-practice-items failed: " + "; ".join(issues_for_reasons(report)),
            report=report,
            output=output,
        )
    return output


__all__ = ["STAGE_ID", "bank_counts", "generate_with_repair", "run_stage"]
