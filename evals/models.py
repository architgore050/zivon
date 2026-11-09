"""Typed dataclasses and JSON Schemas for `evals/`.

Validates Eval Cards (`evals/cards/*.yaml`), Golden Topic expected properties
(`evals/goldens/topics/*/expected.json`), Seeded Defect samples
(`evals/goldens/defects/**/*.json`), Kid Session records, Human Edit records,
and versioned Eval Run / Diff reports.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

EVAL_RECORD_SCHEMA_VERSION = 1

# Exact schema from docs/specs/evals/card-template.md §1
EVAL_CARD_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ZivonEvalCard",
    "type": "object",
    "required": [
        "card_id",
        "version",
        "title",
        "stage",
        "agent_role",
        "suites",
        "golden_inputs",
        "deterministic_checks",
        "llm_judge",
        "thresholds",
        "cost_budget",
    ],
    "additionalProperties": False,
    "properties": {
        "card_id": {
            "type": "string",
            "pattern": "^EV-(CUR|SYN|VIS|PERF|REV|E2E|KID)-[0-9]{3}$",
        },
        "version": {"type": "integer", "minimum": 1},
        "title": {"type": "string", "minLength": 10},
        "stage": {
            "type": "string",
            "enum": [
                "00-ingest..02-generate.ground_truth",
                "02-generate.blocks..04-repair",
                "02-generate.lesson..02-generate.blocks",
                "05-interactive..06-render",
                "07-perf..08-fixloop",
                "03-check",
                "09-review",
                "00-ingest..11-link",
                "post-11-link-gate-b",
            ],
        },
        "agent_role": {
            "type": "string",
            "enum": [
                "Curator",
                "Synthesizer",
                "Visual Builder",
                "Performance Engineer",
                "Comprehension & Fact Reviewer",
                "Code Reviewer",
                "End-to-End Pipeline",
                "Kid-Comprehension Validator",
            ],
        },
        "suites": {
            "type": "array",
            "minItems": 1,
            "items": {"enum": ["smoke", "full", "calibrate"]},
        },
        "golden_inputs": {
            "type": "object",
            "required": ["topics", "seeded_defects", "source_catalog_ref"],
            "additionalProperties": False,
            "properties": {
                "topics": {"type": "array", "items": {"type": "string"}},
                "seeded_defects": {"type": "array", "items": {"type": "string"}},
                "source_catalog_ref": {"type": "string"},
                "profiles": {"type": "array", "items": {"type": "string"}},
            },
        },
        "deterministic_checks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "entrypoint", "severity_on_fail", "description"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^DET-[A-Z0-9-]+$"},
                    "entrypoint": {
                        "type": "string",
                        "description": "Dotted Python callable in evals.checkers or factory.{checks,lint}",
                    },
                    "severity_on_fail": {"enum": ["fatal", "major", "minor"]},
                    "reuses_factory_rule": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                },
            },
        },
        "llm_judge": {
            "type": ["object", "null"],
            "required": [
                "enabled_in_suites",
                "entrypoint",
                "reuses_prompt_from",
                "severity_ladder",
                "way_out_rule",
                "anchor_examples",
            ],
            "additionalProperties": False,
            "properties": {
                "enabled_in_suites": {
                    "type": "array",
                    "items": {"enum": ["full", "calibrate"]},
                },
                "entrypoint": {"type": "string"},
                "reuses_prompt_from": {
                    "type": "string",
                    "description": "Exact factory module and symbol reused (never a parallel rubric)",
                },
                "severity_ladder": {
                    "type": "object",
                    "required": ["fatal", "major", "minor"],
                    "properties": {
                        "fatal": {"type": "string"},
                        "major": {"type": "string"},
                        "minor": {"type": "string"},
                    },
                },
                "way_out_rule": {
                    "type": "string",
                    "const": "Report unverifiable suspicions as severity='minor' with message starting 'unverified:' — never as fatal or major.",
                },
                "anchor_examples": {
                    "type": "array",
                    "minItems": 2,
                    "items": {
                        "type": "object",
                        "required": ["label", "input_summary", "expected_issue"],
                        "properties": {
                            "label": {"type": "string"},
                            "input_summary": {"type": "string"},
                            "expected_issue": {"type": "object"},
                        },
                    },
                },
            },
        },
        "thresholds": {
            "type": "object",
            "required": [
                "deterministic_pass_rate_min",
                "fatal_issues_max",
                "major_issues_max",
                "regression_drop_tolerance",
            ],
            "additionalProperties": True,
            "properties": {
                "deterministic_pass_rate_min": {"type": "number", "const": 1.0},
                "fatal_issues_max": {"type": "integer", "const": 0},
                "major_issues_max": {"type": "integer", "minimum": 0},
                "recall_fatal_min": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "recall_blocking_min": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "specificity_clean_min": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "regression_drop_tolerance": {"type": "number", "const": 0.0},
            },
        },
        "cost_budget": {
            "type": "object",
            "required": [
                "smoke_model_calls",
                "full_model_calls_per_topic",
                "calibration_model_calls_total",
                "max_completion_tokens_per_call",
                "call_deadline_s",
            ],
            "additionalProperties": False,
            "properties": {
                "smoke_model_calls": {"type": "integer", "const": 0},
                "full_model_calls_per_topic": {"type": "integer", "minimum": 0},
                "calibration_model_calls_total": {"type": "integer", "minimum": 0},
                "max_completion_tokens_per_call": {"type": "integer", "minimum": 1000},
                "call_deadline_s": {"type": "integer", "minimum": 60},
            },
        },
    },
}

# Exact schema from docs/specs/evals/golden-sets.md §2
GOLDEN_EXPECTED_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "GoldenTopicExpectedProperties",
    "type": "object",
    "required": [
        "golden_id",
        "topic_slug",
        "course_id",
        "class_level",
        "pipeline_version_min",
        "source_provenance",
        "structure_bounds",
        "required_concepts_and_equations",
        "canonical_numerical_anchors",
        "visual_and_kit_invariants",
        "perf_budgets",
    ],
    "additionalProperties": False,
    "properties": {
        "golden_id": {"type": "string", "pattern": "^GT-[0-9]{2}$"},
        "topic_slug": {"type": "string"},
        "course_id": {"type": "string"},
        "class_level": {"type": "integer", "minimum": 6, "maximum": 12},
        "pipeline_version_min": {"type": "integer", "minimum": 1},
        "source_provenance": {
            "type": "object",
            "required": [
                "primary_book_id",
                "chapter_title_normalized",
                "matched_via",
            ],
            "properties": {
                "primary_book_id": {"type": "string"},
                "chapter_title_normalized": {"type": "string"},
                "matched_via": {"const": "title_line"},
                "forbidden_smuggled_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "structure_bounds": {
            "type": "object",
            "required": [
                "sections_min",
                "claims_min",
                "claims_max",
                "blocks_min",
                "blocks_max",
                "checks_min",
                "worked_examples_min",
                "simulations_min",
                "diagrams_max",
            ],
            "properties": {
                "sections_min": {"type": "integer"},
                "claims_min": {"type": "integer"},
                "claims_max": {"type": "integer"},
                "blocks_min": {"type": "integer", "minimum": 4},
                "blocks_max": {"type": "integer", "maximum": 45},
                "checks_min": {"type": "integer"},
                "worked_examples_min": {"type": "integer"},
                "simulations_min": {"type": "integer"},
                "diagrams_max": {"type": "integer"},
            },
        },
        "required_concepts_and_equations": {
            "type": "object",
            "required": ["key_terms_must_include", "equation_patterns_must_include"],
            "properties": {
                "key_terms_must_include": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "equation_patterns_must_include": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "canonical_numerical_anchors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "source_label",
                    "problem_numbers",
                    "expected_answer_values",
                    "tolerance_rel",
                ],
                "properties": {
                    "source_label": {"type": "string"},
                    "problem_numbers": {"type": "array", "items": {"type": "string"}},
                    "expected_answer_values": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                    "tolerance_rel": {"type": "number", "default": 0.02},
                },
            },
        },
        "visual_and_kit_invariants": {
            "type": "object",
            "required": [
                "requires_lang_bar",
                "requires_sim_readout_populated",
                "computed_graphs_as_simulations",
                "max_overflow_px",
            ],
            "properties": {
                "requires_lang_bar": {"type": "boolean"},
                "requires_sim_readout_populated": {"type": "boolean"},
                "computed_graphs_as_simulations": {"type": "boolean"},
                "max_overflow_px": {"type": "integer", "const": 2},
            },
        },
        "perf_budgets": {
            "type": "object",
            "required": [
                "profile",
                "ram_budget_mb",
                "fps_min",
                "load_budget_s",
                "fcp_budget_s",
            ],
            "properties": {
                "profile": {"type": "string"},
                "ram_budget_mb": {"type": "number"},
                "fps_min": {"type": "number"},
                "load_budget_s": {"type": "number"},
                "fcp_budget_s": {"type": "number"},
            },
        },
    },
}

SEEDED_DEFECT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SeededDefectSample",
    "type": "object",
    "required": [
        "sample_id",
        "stage",
        "origin_incident",
        "defect_class",
        "planted_mutation",
        "inputs",
        "expected",
    ],
    "additionalProperties": False,
    "properties": {
        "sample_id": {
            "type": "string",
            "pattern": "^SD-(CHK|SEC|REV)-[0-9]{3}$",
        },
        "stage": {"enum": ["03-check", "09-review"]},
        "origin_incident": {"type": "string", "minLength": 5},
        "defect_class": {"type": "string", "minLength": 3},
        "planted_mutation": {"type": "string", "minLength": 5},
        "target_call": {
            "type": ["string", "null"],
            "enum": [
                "03-check",
                "09-review-facts",
                "09-review-design",
                "both",
                "deterministic",
                None,
            ],
        },
        "inputs": {"type": "object"},
        "expected": {
            "type": "object",
            "required": [
                "outcome_type",
                "expected_verdict",
                "expected_severity",
                "must_quote_source",
            ],
            "additionalProperties": False,
            "properties": {
                "outcome_type": {"enum": ["positive_defect", "negative_clean"]},
                "expected_verdict": {"enum": ["pass", "fail"]},
                "expected_severity": {
                    "type": ["string", "null"],
                    "enum": ["fatal", "major", "minor", None],
                },
                "expected_category": {"type": ["string", "null"]},
                "expected_block_id": {"type": ["string", "null"]},
                "must_quote_source": {"type": "boolean"},
                "expected_quote_substrings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}

KID_SESSION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "KidComprehensionSession",
    "type": "object",
    "required": [
        "session_code",
        "topic_slug",
        "tester_class",
        "topic_class",
        "is_above_class_level",
        "restated_in_own_words",
        "followup_1_correct",
        "followup_2_correct",
        "gate_b_pass",
        "confusion_blocks",
        "promoted_defect_id",
        "notes",
        "recorded_at",
    ],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "session_code": {
            "type": "string",
            "pattern": "^kid-[a-z0-9-]+$",
        },
        "consent_record_id": {"type": ["string", "null"]},
        "topic_slug": {"type": "string", "minLength": 2},
        "lesson_version_id": {"type": ["string", "null"]},
        "tester_class": {"type": "integer", "minimum": 6, "maximum": 12},
        "topic_class": {"type": "integer", "minimum": 6, "maximum": 12},
        "is_above_class_level": {"type": "boolean"},
        "restated_in_own_words": {"type": "boolean"},
        "followup_1_correct": {"type": "boolean"},
        "followup_2_correct": {"type": "boolean"},
        "gate_b_pass": {"type": "boolean"},
        "confusion_blocks": {
            "type": "array",
            "items": {"type": "string", "pattern": "^b-[0-9]{2}$"},
        },
        "promoted_defect_id": {
            "type": ["string", "null"],
            "pattern": "^SD-(CHK|SEC|REV)-[0-9]{3}$",
        },
        "notes": {"type": "string"},
        "recorded_at": {"type": "string"},
    },
}

HUMAN_EDIT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "HumanEditRateRecord",
    "type": "object",
    "required": [
        "topic_slug",
        "course_id",
        "class_level",
        "factory_run_id",
        "pipeline_version",
        "total_generated_lines",
        "manual_added_lines",
        "manual_deleted_lines",
        "human_edit_rate",
        "human_edits_count",
        "edit_categories",
        "notes",
        "recorded_at",
    ],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "topic_slug": {"type": "string"},
        "course_id": {"type": "string"},
        "class_level": {"type": "integer", "minimum": 6, "maximum": 12},
        "factory_run_id": {"type": "string"},
        "pipeline_version": {"type": "integer", "minimum": 1},
        "lesson_version_id": {"type": ["string", "null"]},
        "generated_git_sha": {"type": "string"},
        "published_git_sha": {"type": "string"},
        "total_generated_lines": {"type": "integer", "minimum": 1},
        "manual_added_lines": {"type": "integer", "minimum": 0},
        "manual_deleted_lines": {"type": "integer", "minimum": 0},
        "human_edit_rate": {"type": "number", "minimum": 0.0},
        "human_edits_count": {"type": "integer", "minimum": 0},
        "edit_categories": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
        "recorded_at": {"type": "string"},
    },
}

EVAL_REPORT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ZivonEvalRunReport",
    "type": "object",
    "required": [
        "schema_version",
        "eval_run_id",
        "suite",
        "pipeline_version",
        "factory_image_tag",
        "git_sha",
        "prompt_bundle_sha256",
        "generator_model",
        "judge_model",
        "started_at",
        "completed_at",
        "duration_s",
        "overall_pass",
        "regression_detected",
        "baseline_eval_run_id",
        "summary",
        "cards",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "eval_run_id": {"type": "string"},
        "suite": {"enum": ["smoke", "full", "calibrate"]},
        "pipeline_version": {"type": "integer", "minimum": 1},
        "factory_image_tag": {"type": "string"},
        "git_sha": {"type": "string"},
        "prompt_bundle_sha256": {"type": "string"},
        "generator_model": {"type": "string"},
        "judge_model": {"type": "string"},
        "started_at": {"type": "string"},
        "completed_at": {"type": "string"},
        "duration_s": {"type": "number", "minimum": 0.0},
        "overall_pass": {"type": "boolean"},
        "regression_detected": {"type": "boolean"},
        "baseline_eval_run_id": {"type": ["string", "null"]},
        "summary": {
            "type": "object",
            "required": [
                "cards_total",
                "cards_passed",
                "cards_failed",
                "model_calls_total",
                "total_thinking_s",
                "human_edit_rate_rolling",
                "gate_b_comprehension_rate",
            ],
        },
        "cards": {"type": "array"},
    },
}

DIFF_REPORT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "ZivonEvalDiffReport",
    "type": "object",
    "required": [
        "schema_version",
        "eval_run_id",
        "baseline_eval_run_id",
        "pipeline_version",
        "regression_detected",
        "exit_code",
        "blocking_reasons",
        "card_diffs",
        "cost_delta",
        "human_edit_rate_delta",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "eval_run_id": {"type": "string"},
        "baseline_eval_run_id": {"type": ["string", "null"]},
        "pipeline_version": {"type": "integer"},
        "regression_detected": {"type": "boolean"},
        "exit_code": {"type": "integer", "enum": [0, 1, 2]},
        "blocking_reasons": {"type": "array", "items": {"type": "string"}},
        "card_diffs": {"type": "array"},
        "cost_delta": {"type": "object"},
        "human_edit_rate_delta": {"type": "number"},
    },
}


@dataclass(frozen=True)
class DeterministicCheckSpec:
    id: str
    entrypoint: str
    severity_on_fail: str
    description: str
    reuses_factory_rule: str | None = None


@dataclass(frozen=True)
class JudgeSpec:
    enabled_in_suites: list[str]
    entrypoint: str
    reuses_prompt_from: str
    severity_ladder: dict[str, str]
    way_out_rule: str
    anchor_examples: list[dict[str, Any]]


@dataclass(frozen=True)
class EvalCard:
    card_id: str
    version: int
    title: str
    stage: str
    agent_role: str
    suites: list[str]
    golden_inputs: dict[str, Any]
    deterministic_checks: list[DeterministicCheckSpec]
    llm_judge: JudgeSpec | None
    thresholds: dict[str, Any]
    cost_budget: dict[str, Any]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class IssueRecord:
    severity: str
    message: str
    check_id: str | None = None
    block_id: str | None = None
    category: str | None = None
    unverified: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "severity": self.severity,
            "message": self.message,
        }
        if self.check_id is not None:
            out["check_id"] = self.check_id
        if self.block_id is not None:
            out["block_id"] = self.block_id
        if self.category is not None:
            out["category"] = self.category
        if self.unverified or self.message.startswith("unverified:"):
            out["unverified"] = True
        return out


@dataclass
class DefectSampleResult:
    sample_id: str
    expected_verdict: str
    actual_verdict: str
    expected_severity: str | None
    actual_severity: str | None
    target_block_matched: bool
    source_quoted: bool
    outcome_class: str  # "TP" | "TN" | "FP" | "FN"
    latency_s: float = 0.0
    thinking_s: float = 0.0
    completion_tokens: int = 0
    finish_reason: str | None = "stop"
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CardResult:
    card_id: str
    stage: str
    topic_slug: str | None
    verdict: str  # "pass" | "fail" | "skip"
    deterministic_score: float
    judge_score: float | None
    fatal_count: int = 0
    major_count: int = 0
    minor_count: int = 0
    unverified_count: int = 0
    model_calls: int = 0
    thinking_s: float = 0.0
    max_completion_tokens: int = 0
    length_cuts: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    delta_vs_baseline: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    defect_samples: list[DefectSampleResult] = field(default_factory=list)
    target_scope_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {
            "card_id": self.card_id,
            "stage": self.stage,
            "topic_slug": self.topic_slug,
            "verdict": self.verdict,
            "deterministic_score": round(self.deterministic_score, 4),
            "judge_score": (
                round(self.judge_score, 4) if self.judge_score is not None else None
            ),
            "fatal_count": self.fatal_count,
            "major_count": self.major_count,
            "minor_count": self.minor_count,
            "unverified_count": self.unverified_count,
            "model_calls": self.model_calls,
            "thinking_s": round(self.thinking_s, 2),
            "max_completion_tokens": self.max_completion_tokens,
            "length_cuts": self.length_cuts,
            "metrics": self.metrics,
            "delta_vs_baseline": self.delta_vs_baseline,
            "issues": self.issues,
            "target_scope_label": self.target_scope_label,
        }
        if self.defect_samples:
            out["defect_samples"] = [s.to_dict() for s in self.defect_samples]
        return out


@dataclass
class EvalRunReport:
    eval_run_id: str
    suite: str
    pipeline_version: int
    factory_image_tag: str
    git_sha: str
    prompt_bundle_sha256: str
    generator_model: str
    judge_model: str
    started_at: str
    completed_at: str
    duration_s: float
    overall_pass: bool
    regression_detected: bool
    baseline_eval_run_id: str | None
    summary: dict[str, Any]
    cards: list[CardResult]
    schema_version: int = EVAL_RECORD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "eval_run_id": self.eval_run_id,
            "suite": self.suite,
            "pipeline_version": self.pipeline_version,
            "factory_image_tag": self.factory_image_tag,
            "git_sha": self.git_sha,
            "prompt_bundle_sha256": self.prompt_bundle_sha256,
            "generator_model": self.generator_model,
            "judge_model": self.judge_model,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": round(self.duration_s, 2),
            "overall_pass": self.overall_pass,
            "regression_detected": self.regression_detected,
            "baseline_eval_run_id": self.baseline_eval_run_id,
            "summary": self.summary,
            "cards": [c.to_dict() for c in self.cards],
        }
        validate_schema(payload, EVAL_REPORT_SCHEMA, "EvalRunReport")
        return payload


@dataclass
class CardDiff:
    card_id: str
    topic_slug: str | None
    baseline_verdict: str | None
    current_verdict: str
    deterministic_delta: float
    judge_delta: float | None
    metric_deltas: dict[str, float]
    regressed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiffReport:
    eval_run_id: str
    baseline_eval_run_id: str | None
    pipeline_version: int
    regression_detected: bool
    exit_code: int
    blocking_reasons: list[str]
    card_diffs: list[CardDiff]
    cost_delta: dict[str, float]
    human_edit_rate_delta: float
    schema_version: int = EVAL_RECORD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "eval_run_id": self.eval_run_id,
            "baseline_eval_run_id": self.baseline_eval_run_id,
            "pipeline_version": self.pipeline_version,
            "regression_detected": self.regression_detected,
            "exit_code": self.exit_code,
            "blocking_reasons": self.blocking_reasons,
            "card_diffs": [c.to_dict() for c in self.card_diffs],
            "cost_delta": self.cost_delta,
            "human_edit_rate_delta": round(self.human_edit_rate_delta, 4),
        }
        validate_schema(payload, DIFF_REPORT_SCHEMA, "DiffReport")
        return payload


@dataclass
class HumanEditRecord:
    topic_slug: str
    course_id: str
    class_level: int
    factory_run_id: str
    pipeline_version: int
    total_generated_lines: int
    manual_added_lines: int
    manual_deleted_lines: int
    human_edit_rate: float
    human_edits_count: int
    edit_categories: list[str]
    notes: str
    recorded_at: str
    generated_git_sha: str = "0" * 40
    published_git_sha: str = "0" * 40
    lesson_version_id: str | None = None
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {k: v for k, v in asdict(self).items() if v is not None or k != "id"}
        validate_schema(payload, HUMAN_EDIT_SCHEMA, "HumanEditRecord")
        return payload


@dataclass
class KidSessionRecord:
    session_code: str
    topic_slug: str
    tester_class: int
    topic_class: int
    is_above_class_level: bool
    restated_in_own_words: bool
    followup_1_correct: bool
    followup_2_correct: bool
    gate_b_pass: bool
    confusion_blocks: list[str]
    promoted_defect_id: str | None
    notes: str
    recorded_at: str
    consent_record_id: str | None = None
    lesson_version_id: str | None = None
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {k: v for k, v in asdict(self).items() if v is not None or k != "id"}
        validate_schema(payload, KID_SESSION_SCHEMA, "KidSessionRecord")
        return payload


def validate_schema(
    instance: dict[str, Any], schema: dict[str, Any], name: str
) -> None:
    """Validate `instance` against a JSON Schema Draft-07 definition."""
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "(root)"
        raise ValueError(f"{name} schema validation failed at '{path}': {first.message}")


def load_card(path: Path) -> EvalCard:
    """Load and validate one `EV-*.yaml` or `.json` eval card definition."""
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError(f"eval card {path} must be a YAML/JSON mapping")
    validate_schema(raw, EVAL_CARD_SCHEMA, f"EvalCard({path.name})")

    det_specs = [
        DeterministicCheckSpec(
            id=d["id"],
            entrypoint=d["entrypoint"],
            severity_on_fail=d["severity_on_fail"],
            description=d["description"],
            reuses_factory_rule=d.get("reuses_factory_rule"),
        )
        for d in raw["deterministic_checks"]
    ]
    judge_raw = raw.get("llm_judge")
    judge_spec = (
        JudgeSpec(
            enabled_in_suites=list(judge_raw["enabled_in_suites"]),
            entrypoint=judge_raw["entrypoint"],
            reuses_prompt_from=judge_raw["reuses_prompt_from"],
            severity_ladder=dict(judge_raw["severity_ladder"]),
            way_out_rule=judge_raw["way_out_rule"],
            anchor_examples=list(judge_raw["anchor_examples"]),
        )
        if isinstance(judge_raw, dict)
        else None
    )
    return EvalCard(
        card_id=raw["card_id"],
        version=int(raw["version"]),
        title=raw["title"],
        stage=raw["stage"],
        agent_role=raw["agent_role"],
        suites=list(raw["suites"]),
        golden_inputs=dict(raw["golden_inputs"]),
        deterministic_checks=det_specs,
        llm_judge=judge_spec,
        thresholds=dict(raw["thresholds"]),
        cost_budget=dict(raw["cost_budget"]),
        raw=raw,
    )


def load_all_cards(cards_dir: Path) -> dict[str, EvalCard]:
    """Load all eval cards in `cards_dir`, keyed by `card_id`."""
    if not cards_dir.is_dir():
        raise FileNotFoundError(f"eval cards directory not found: {cards_dir}")
    registry: dict[str, EvalCard] = {}
    for p in sorted(cards_dir.iterdir()):
        if p.suffix in (".yaml", ".yml", ".json"):
            card = load_card(p)
            if card.card_id in registry:
                raise ValueError(f"duplicate card_id {card.card_id} in {p}")
            registry[card.card_id] = card
    return registry
