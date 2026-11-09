# Eval Card Template & Schema (`evals/cards/EV-<STAGE>-<NNN>.yaml`)

Every evaluation in `evals/` is declared as a structured **Eval Card** under `evals/cards/`. Cards bind a specific factory stage (or end-to-end workflow) to:
1. Versioned **Golden Inputs** (`evals/goldens/` or `sources/`),
2. **Deterministic Checkers** (`evals/checkers/`, `0` model calls, run in both `--suite smoke` and `--suite full`),
3. **Calibrated LLM Judge Rubrics** (`evals/judges/`, reusing `factory/` reviewer rubrics verbatim with anchor examples, run in `--suite full` and `--suite calibrate`),
4. **Pass Thresholds & Regression Alert Rules**, and
5. **Model Call & Token Cost Budgets**.

---

## 1. JSON Schema for Eval Card Definitions (`EVAL_CARD_SCHEMA`)

`evals/models.py` validates every YAML/JSON file in `evals/cards/` against this schema at load time:

```json
{
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
    "cost_budget"
  ],
  "additionalProperties": false,
  "properties": {
    "card_id": {
      "type": "string",
      "pattern": "^EV-(CUR|SYN|VIS|PERF|REV|E2E|KID)-[0-9]{3}$"
    },
    "version": { "type": "integer", "minimum": 1 },
    "title": { "type": "string", "minLength": 10 },
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
        "post-11-link-gate-b"
      ]
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
        "Kid-Comprehension Validator"
      ]
    },
    "suites": {
      "type": "array",
      "minItems": 1,
      "items": { "enum": ["smoke", "full", "calibrate"] }
    },
    "golden_inputs": {
      "type": "object",
      "required": ["topics", "seeded_defects", "source_catalog_ref"],
      "additionalProperties": false,
      "properties": {
        "topics": { "type": "array", "items": { "type": "string" } },
        "seeded_defects": { "type": "array", "items": { "type": "string" } },
        "source_catalog_ref": { "type": "string" },
        "profiles": { "type": "array", "items": { "type": "string" } }
      }
    },
    "deterministic_checks": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "entrypoint", "severity_on_fail", "description"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "pattern": "^DET-[A-Z0-9-]+$" },
          "entrypoint": {
            "type": "string",
            "description": "Dotted Python callable in evals.checkers or factory.{checks,lint}"
          },
          "severity_on_fail": { "enum": ["fatal", "major", "minor"] },
          "reuses_factory_rule": { "type": ["string", "null"] },
          "description": { "type": "string" }
        }
      }
    },
    "llm_judge": {
      "type": ["object", "null"],
      "required": [
        "enabled_in_suites",
        "entrypoint",
        "reuses_prompt_from",
        "severity_ladder",
        "way_out_rule",
        "anchor_examples"
      ],
      "additionalProperties": false,
      "properties": {
        "enabled_in_suites": {
          "type": "array",
          "items": { "enum": ["full", "calibrate"] }
        },
        "entrypoint": { "type": "string" },
        "reuses_prompt_from": {
          "type": "string",
          "description": "Exact factory module and symbol reused (never a parallel rubric)"
        },
        "severity_ladder": {
          "type": "object",
          "required": ["fatal", "major", "minor"],
          "properties": {
            "fatal": { "type": "string" },
            "major": { "type": "string" },
            "minor": { "type": "string" }
          }
        },
        "way_out_rule": {
          "type": "string",
          "const": "Report unverifiable suspicions as severity='minor' with message starting 'unverified:' — never as fatal or major."
        },
        "anchor_examples": {
          "type": "array",
          "minItems": 2,
          "items": {
            "type": "object",
            "required": ["label", "input_summary", "expected_issue"],
            "properties": {
              "label": { "type": "string" },
              "input_summary": { "type": "string" },
              "expected_issue": { "type": "object" }
            }
          }
        }
      }
    },
    "thresholds": {
      "type": "object",
      "required": [
        "deterministic_pass_rate_min",
        "fatal_issues_max",
        "major_issues_max",
        "regression_drop_tolerance"
      ],
      "additionalProperties": true,
      "properties": {
        "deterministic_pass_rate_min": { "type": "number", "const": 1.0 },
        "fatal_issues_max": { "type": "integer", "const": 0 },
        "major_issues_max": { "type": "integer", "minimum": 0 },
        "recall_fatal_min": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "recall_blocking_min": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "specificity_clean_min": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
        "regression_drop_tolerance": { "type": "number", "const": 0.0 }
      }
    },
    "cost_budget": {
      "type": "object",
      "required": [
        "smoke_model_calls",
        "full_model_calls_per_topic",
        "calibration_model_calls_total",
        "max_completion_tokens_per_call",
        "call_deadline_s"
      ],
      "additionalProperties": false,
      "properties": {
        "smoke_model_calls": { "type": "integer", "const": 0 },
        "full_model_calls_per_topic": { "type": "integer", "minimum": 0 },
        "calibration_model_calls_total": { "type": "integer", "minimum": 0 },
        "max_completion_tokens_per_call": { "type": "integer", "minimum": 1000 },
        "call_deadline_s": { "type": "integer", "minimum": 60 }
      }
    }
  }
}
```

---

## 2. Canonical Eval Card Template (Copy & Fill per Card)

```yaml
card_id: EV-REV-001
version: 1
title: "Comprehension & Fact Reviewer (03-check) Calibration on Seeded Defects and Clean Goldens"
stage: "03-check"
agent_role: "Comprehension & Fact Reviewer"
suites:
  - smoke
  - full
  - calibrate

golden_inputs:
  topics:
    - "evals/goldens/topics/class-9-motion"
    - "evals/goldens/topics/class-11-motion-in-a-straight-line"
  seeded_defects:
    - "evals/goldens/defects/03-check/SD-CHK-001.json"
    - "evals/goldens/defects/03-check/SD-CHK-002.json"
    - "evals/goldens/defects/03-check/SD-CHK-003.json"
    - "evals/goldens/defects/03-check/SD-CHK-004.json"
    - "evals/goldens/defects/03-check/SD-CHK-005.json"
    - "evals/goldens/defects/03-check/SD-CHK-006.json"
    - "evals/goldens/defects/03-check/SD-CHK-007.json"
    - "evals/goldens/defects/03-check/SD-CHK-008.json"
  source_catalog_ref: "sources/catalog.json"

deterministic_checks:
  - id: DET-REV01-PROMPT-CONTRACT
    entrypoint: "evals.checkers.prompt_contract_checks:check_03_check_prompt_contract"
    severity_on_fail: fatal
    reuses_factory_rule: "factory.agents:run_check"
    description: >
      Verifies that 03-check's prompt carries the exact severity ladder, THE LESSON THE PAGE TEACHES,
      RECOMPUTE every worked_example, COVERAGE, the 'unverified:' way-out, and no adversarial framing.
  - id: DET-REV01-STATIC-RULES
    entrypoint: "evals.checkers.synthesizer_checks:check_static_rules_on_defect_corpus"
    severity_on_fail: fatal
    reuses_factory_rule: "factory.checks:run_all_rules"
    description: >
      Verifies that deterministic code checks (rule_answer_keys, rule_citations, rule_self_containment,
      rule_numbers, rule_diagram_svg) pass on clean samples and catch synthetic rule defects in 0ms.

llm_judge:
  enabled_in_suites:
    - full
    - calibrate
  entrypoint: "evals.judges.pedagogy_judge:calibrate_03_check"
  reuses_prompt_from: "factory.agents:run_check (CHECK_REPORT schema in factory/schemas.py)"
  severity_ladder:
    fatal: >
      A statement contradicts the source material, a check's answer key or a worked_example's
      computed answer is wrong, or the page omits a chapter section or an exercise TYPE that the
      source material itself teaches. Must quote the source passage or omitted item.
    major: >
      A block teaches, tests, or relies on a Physics concept that the source material never explains
      (a smuggled-in concept), or tests an expected_understanding before the lesson teaches it.
    minor: >
      Style, wording, or common-knowledge definitions not spelled out in the source. Advisory only;
      never fails the page.
  way_out_rule: "Report unverifiable suspicions as severity='minor' with message starting 'unverified:' — never as fatal or major."
  anchor_examples:
    - label: "Fatal — Wrong Computed Numerical Answer (from production run 000509 b-21)"
      input_summary: "Car decelerates from 126 km/h (35 m/s) to rest over 200 m; worked_example b-21 claims a = -3.94 m/s² and t = 8.9 s."
      expected_issue:
        block_id: "b-21"
        severity: "fatal"
        message: "Recomputation from u = 35 m/s, v = 0, s = 200 m via v² - u² = 2as gives a = -3.06 m/s² and t = 11.4 s, not 3.94 m/s² / 8.9 s [ncert Example 2.6]."
    - label: "Major — Smuggled Concept from Outside Chapter (from production run 040410 b-28)"
      input_summary: "Class 11 Ch. 2 (Motion in a Straight Line) check block b-28 asks about simple harmonic motion period T = 2π√(l/g)."
      expected_issue:
        block_id: "b-28"
        severity: "major"
        message: "Block b-28 tests simple harmonic motion (SHM), a concept from Oscillations (Part II Ch. 13) that this chapter pack never explains."
    - label: "Minor — Unverified Suspicion / Common Knowledge Hedge"
      input_summary: "Text block b-01 notes that 'SI stands for Système International' while the NCERT excerpt only writes 'SI units'."
      expected_issue:
        block_id: "b-01"
        severity: "minor"
        message: "unverified: The expansion 'Système International' is common knowledge not explicitly spelled out in the chapter text."

thresholds:
  deterministic_pass_rate_min: 1.0
  fatal_issues_max: 0
  major_issues_max: 0
  recall_fatal_min: 1.0
  recall_blocking_min: 0.80
  specificity_clean_min: 1.0
  regression_drop_tolerance: 0.0

cost_budget:
  smoke_model_calls: 0
  full_model_calls_per_topic: 0
  calibration_model_calls_total: 8
  max_completion_tokens_per_call: 35000
  call_deadline_s: 1800
```

---

## 3. Authoring Rules for New Cards

1. **Never Duplicate a Factory Rubric**: `llm_judge.reuses_prompt_from` must reference an existing function or constant in `factory/` (`factory.agents:run_check`, `factory.review:_FACTS_TASK`, `factory.review:_DESIGN_TASK`). If a new evaluation dimension is needed, add it to the factory's own reviewer first so build-time gating and post-hoc evaluation stay identical.
2. **Every Judge Card Needs Both Positive and Negative Anchors**: Include at least one `fatal`, one `major`, and one `minor`/`unverified:` anchor example drawn from real factory run forensics (`TIMELINE.md` / `docs/logs/`).
3. **Zero-Call Smoke Requirement**: `cost_budget.smoke_model_calls` is strictly `0` on every card. Every card must contribute at least one deterministic check (`deterministic_checks`) that runs in CI key-free.
4. **All Model Calls Route Through `llm_manager/`**: `evals/judges/base.py` instantiates `llm_manager.LLMManager(LLMConfig.from_env())` and uses `llm_manager.validation.run_validation_rounds` — never `requests.post` or raw `openai.OpenAI`.
