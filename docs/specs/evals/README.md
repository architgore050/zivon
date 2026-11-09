# `docs/specs/evals/` — Content Factory Evaluation Framework Specification

This folder specifies Zivon's standalone **`evals/`** package and the migration plan that separates model-output quality evaluations from deterministic unit/integration tests in `testing/`.

- **Owner**: Wave S1 (`SP4-EVALS`)
- **Target package**: `evals/` (repo root, built by the execution wave)
- **Target branch**: `feature/backend-db-storage-spec`

---

## Folder Layout (Source of Truth)

| File | Purpose |
|---|---|
| [`README.md`](README.md) | Folder map, reading order, and architectural boundaries for the `evals/` specification. |
| [`spec.md`](spec.md) | Complete specification: separation rule (`testing/` vs `evals/`), per-stage and end-to-end eval cards, judge calibration, regression tracking, CI/CronJob wiring (`k8s/52-eval-cronjob.yaml` + `scripts/trigger-evals.sh`), reporting/dashboard hooks, kid-test feedback loop, and upgrade path. |
| [`migration-map.csv`](migration-map.csv) | File-by-file and test-by-test migration table mapping every current test in `testing/content_factory/` and `testing/frontend/` to either `KEEP_IN_TESTING`, `MIGRATE_TO_EVALS`, or `SPLIT`, with its target `eval_card_id`. |
| [`card-template.md`](card-template.md) | Canonical schema and Markdown/YAML template for authoring new eval cards, including deterministic checker bindings, calibrated LLM-judge rubrics, anchor examples, pass thresholds, and call-cost budgets. |
| [`golden-sets.md`](golden-sets.md) | Versioned golden topics inventory, expected-property schemas (`expected.json`), seeded-defect corpus for reviewer calibration (`03-check` and `09-review`), storage placement, and version-rotation rules. |
| [`open-questions.md`](open-questions.md) | Open questions, cross-agent alignment flags (Wave S0 DB/storage specs, SP3 observability/dashboard contracts, CI/CD workflow agent), and tracked assumptions. |

---

## Companion ADRs

| ADR | Decision |
|---|---|
| [`docs/backend/adr/0027-eval-result-store-and-tiering.md`](../../backend/adr/0027-eval-result-store-and-tiering.md) | Dual-mode eval persistence: append-only JSONL on PVC `zivon-sources` (`subPath: evals`) for P0/offline runs + PostgreSQL relational tables (`eval_run`, `eval_card_result`, `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session`) synced to cold object storage under data class `C4`. |
| [`docs/backend/adr/0028-eval-judge-model-and-calibration.md`](../../backend/adr/0028-eval-judge-model-and-calibration.md) | Judge model selection and cost control: all judge calls route through `llm_manager/`, deterministic checkers gate before any model call, reviewer rubrics are reused verbatim from `factory/agents.py` and `factory/review.py`, and judge accuracy is calibrated against seeded-defect sets. |

---

## Reading Order for Execution Agents

1. Read [`AGENTS.md`](../../../AGENTS.md), [`docs/content-factory/architecture.md`](../../content-factory/architecture.md), and [`skills/prompting-and-agent-design/SKILL.md`](../../../skills/prompting-and-agent-design/SKILL.md).
2. Read [`spec.md`](spec.md) for the `evals/` package architecture, CLI contract, eval cards (`EV-CUR-001` through `EV-KID-001`), regression store, and K8s/CI wiring.
3. Follow [`migration-map.csv`](migration-map.csv) row-by-row when extracting eval assertions out of `testing/content_factory/` into `evals/`.
4. Populate `evals/goldens/` using the schemas and defect catalog in [`golden-sets.md`](golden-sets.md) and [`card-template.md`](card-template.md).
5. Check [`open-questions.md`](open-questions.md) and ADRs [`0027`](../../backend/adr/0027-eval-result-store-and-tiering.md)–[`0028`](../../backend/adr/0028-eval-judge-model-and-calibration.md) before wiring database persistence or dashboard endpoints.
