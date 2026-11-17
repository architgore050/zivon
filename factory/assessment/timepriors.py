"""A5-time-priors: the expected-time prior every question and topic carries.

FEATURE-MAP #16 / CNT-11: a question's expected time starts as an AI prior and
is later updated from real attempts with a recency-weighted average. This stage
is the prior: deterministic, explainable, and stored WITH its basis (type,
difficulty, marks, language, word count, computation steps, formula version)
so an operator can recompute it and the SWOT pace metric can compare a
student's median time against it.

The formula is deliberately boring - reading time + arithmetic steps, scaled by
difficulty, marks and the learner's script. It is NOT a measurement; it is a
starting guess with an audit trail.
"""

from __future__ import annotations

from typing import Any

from . import DIFFICULTIES, ITEM_TYPES, LANGUAGES
from .config import AssessmentConfig
from .errors import AssessmentGateError
from .validators import (
    ItemGatePolicy,
    count_words,
    gate_report,
    issues_for_reasons,
    validate_time_priors,
)

STAGE_ID = "A5-time-priors"
FORMULA_VERSION = "tp-v1"

# Reading: ~260 ms per word (a Class 9/10 student reading a physics stem and
# skimming options, not a fluent adult).
_READING_MS_PER_WORD = 260
_STEP_MS = 12_000
_BASE_MS = {"mcq": 45_000, "numeric": 75_000, "assertion_reason": 60_000}
_DIFFICULTY_FACTOR = {"easy": 0.8, "medium": 1.0, "hard": 1.35}
_MARK_FACTOR_STEP = 0.15
# Devanagari reading is slower per word for most of this cohort; Hinglish is
# Latin script and only slightly slower than English.
_LANGUAGE_FACTOR = {"en": 1.0, "hi": 1.12, "hi-Latn": 1.05}


def _clamp(value: int, policy: ItemGatePolicy) -> int:
    return max(policy.time_prior_min_ms, min(policy.time_prior_max_ms, value))


def expected_time_ms(
    item: dict[str, Any], language: str, policy: ItemGatePolicy
) -> int:
    """One item variant's prior. Same inputs -> same value, always."""
    payload = item["locales"][language]
    text = " ".join([payload["prompt"], *payload.get("options", [])])
    words = count_words(text)
    steps = int(item["computation_steps"])
    raw: float = (
        _BASE_MS[item["type"]] + _READING_MS_PER_WORD * words + _STEP_MS * steps
    )
    raw *= _DIFFICULTY_FACTOR[item["difficulty"]]
    raw *= 1.0 + _MARK_FACTOR_STEP * (int(item["marks"]) - 1)
    raw *= _LANGUAGE_FACTOR[language]
    # Round to the nearest second: a prior with 43,712 ms of false precision
    # invites the reader to trust it more than it deserves.
    rounded = round(raw / 1000.0) * 1000
    return _clamp(rounded, policy)


def question_rows(
    items: list[dict[str, Any]], policy: ItemGatePolicy
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        for language in LANGUAGES:
            payload = item["locales"][language]
            text = " ".join([payload["prompt"], *payload.get("options", [])])
            rows.append(
                {
                    "question_id": f"{item['item_id']}-{language}",
                    "expected_time_ms": expected_time_ms(item, language, policy),
                    "basis": {
                        "type": item["type"],
                        "difficulty": item["difficulty"],
                        "marks": int(item["marks"]),
                        "language": language,
                        "word_count": count_words(text),
                        "computation_steps": int(item["computation_steps"]),
                        "formula_version": FORMULA_VERSION,
                    },
                }
            )
    return rows


def _weighted_mean(rows: list[dict[str, Any]]) -> int:
    """Mark-weighted mean of the English variants (the prior is content-level;
    the per-language rows exist for the DB and the SWOT pace comparison)."""
    total_weight = 0
    total = 0
    for row in rows:
        weight = max(1, int(row["basis"]["marks"]))
        total += int(row["expected_time_ms"]) * weight
        total_weight += weight
    return round(total / total_weight)


def topic_priors(
    chapter: dict[str, Any],
    rows: list[dict[str, Any]],
    item_concepts: dict[str, str],
) -> list[dict[str, Any]]:
    english = {
        row["question_id"][: -len("-en")]: row
        for row in rows
        if row["basis"]["language"] == "en"
    }
    topics = [
        {
            "chapter_id": chapter["chapter_id"],
            "scope": "chapter",
            "scope_id": chapter["chapter_id"],
            "expected_time_ms": _weighted_mean(list(english.values())),
            "questions": len(english),
        }
    ]
    for concept in chapter["concepts"]:
        concept_rows = [
            row
            for item_id, row in english.items()
            if item_concepts.get(item_id) == concept["concept_id"]
        ]
        if concept_rows:
            topics.append(
                {
                    "chapter_id": chapter["chapter_id"],
                    "scope": "concept",
                    "scope_id": concept["concept_id"],
                    "expected_time_ms": _weighted_mean(concept_rows),
                    "questions": len(concept_rows),
                }
            )
    return sorted(topics, key=lambda t: (t["scope"], t["scope_id"]))


def build(
    cfg: AssessmentConfig, chapter: dict[str, Any], items_output: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the priors payload (no gate) for one chapter."""
    items = items_output["items"]
    item_concepts = {i["item_id"]: i["concept_id"] for i in items}
    rows = question_rows(items, cfg.policy)
    topics = topic_priors(chapter, rows, item_concepts)
    return {
        "schema_version": 1,
        "formula_version": FORMULA_VERSION,
        "questions": rows,
        "topics": topics,
    }


def run_stage(
    cfg: AssessmentConfig, chapter: dict[str, Any], items_output: dict[str, Any]
) -> dict[str, Any]:
    payload = build(cfg, chapter, items_output)
    issues = validate_time_priors(payload, chapter, items_output["items"], cfg.policy)
    counts = {
        "question_rows": len(payload["questions"]),
        "topic_rows": len(payload["topics"]),
        "formula_version": FORMULA_VERSION,
    }
    report = gate_report(issues, counts=counts)
    output = {
        "schema_version": 1,
        "stage": STAGE_ID,
        **payload,
        "counts": counts,
        "gate": report,
    }
    if report["verdict"] == "fail":
        raise AssessmentGateError(
            "A5-time-priors failed: " + "; ".join(issues_for_reasons(report)),
            report=report,
            output=output,
        )
    return output


def formula_constants() -> dict[str, Any]:
    """The documented inputs, exposed for the docs test and the admin view."""
    return {
        "formula_version": FORMULA_VERSION,
        "base_ms": dict(_BASE_MS),
        "reading_ms_per_word": _READING_MS_PER_WORD,
        "step_ms": _STEP_MS,
        "difficulty_factor": dict(_DIFFICULTY_FACTOR),
        "mark_factor_step": _MARK_FACTOR_STEP,
        "language_factor": dict(_LANGUAGE_FACTOR),
        "type_values": list(ITEM_TYPES),
        "difficulty_values": list(DIFFICULTIES),
    }


__all__ = [
    "FORMULA_VERSION",
    "STAGE_ID",
    "build",
    "expected_time_ms",
    "formula_constants",
    "question_rows",
    "run_stage",
    "topic_priors",
]
