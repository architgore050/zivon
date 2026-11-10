# Open Questions, Cross-Agent Alignment Flags & Assumptions (`SP4-EVALS`)

This file records cross-wave integration checkpoints, tracked assumptions (`[ASSUMPTION]`), and open product/ops questions for the founder and downstream execution agents (`EX*`, `CI/CD`, `SP3`).

---

## 1. Cross-Agent Integration & Alignment Flags

| ID | Counterpart Agent / Wave | Area | Contract Specified Here (`SP4-EVALS`) | Action Required at Merge / Execution |
|---|---|---|---|---|
| `ALIGN-S0-DB` | Wave S0 (`feature/backend-db-storage-spec`: `docs/backend/db-spec.md`, `storage-tiering.md`, `adr/0001..0016`) | Relational schema & cold-storage tiering for eval records | `spec.md` §4.1 and [`ADR-0027`](../../backend/adr/0027-eval-result-store-and-tiering.md) define five tables (`eval_run`, `eval_card_result`, `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session`) using UUIDv7 PKs, UTC `timestamptz`, JSONB, and data class `C4` (`zivon-sources` PVC `subPath: evals` → cold object store via transactional outbox `object` table). | Merge agent / `EX0-BACKEND` adds these 5 tables to the Alembic migration chain (`skills/zivon-backend-engineering-skills/README.md` §1) and links `eval_run.report_object_id` to the `object` catalogue table in `db-spec.md`. |
| `ALIGN-SP3-OBS` | Wave S1 (`SP3` — Observability & Admin Dashboard Spec) | Dashboard endpoints, Prometheus metrics & `EVT-*` event names | `spec.md` §6.2 defines `POST /api/v1/admin/evals/trigger`, `GET /api/v1/admin/evals/runs`, `GET /api/v1/admin/evals/runs/{id}/diff`, 6 Prometheus metrics (`zivon_eval_*`), and 5 event names (`EVT-EVAL-*`). | Reconcile endpoint paths and `EVT-EVAL-*` payload envelopes with `SP3`'s dashboard and telemetry spec during S1 merge. |
| `ALIGN-CICD` | CI/CD Agent / Merge Agent (`.github/workflows/ci.yml`) | PR `eval-smoke` gate & `mypy` path | Protocol §7 forbids `SP4-EVALS` from editing `.github/workflows/ci.yml`. `spec.md` §5.1 provides the exact `eval-smoke` YAML job and `mypy` path addition (`evals/`). | CI/CD or merge agent adds `eval-smoke` to `.github/workflows/ci.yml` once the execution agent builds `evals/`. |
| `ALIGN-PERF-SHIM` | Content Factory Execution Agent (`factory/perf.py`, `factory/fixloop.py`) | Migration of `testing/content_factory/perf/harness.py` | `testing/content_factory/perf/harness.py` moves to `evals/checkers/perf_harness.py`. To avoid breaking `factory/perf.py` and `factory/fixloop.py` mid-wave, a 5-line re-export shim stays at `testing/content_factory/perf/harness.py`. | Execution agent building `evals/` creates `evals/checkers/perf_harness.py` and replaces `testing/content_factory/perf/harness.py` with `from evals.checkers.perf_harness import *`. |

---

## 2. Tracked Assumptions (`[ASSUMPTION]`)

1. **`[ASSUMPTION]` A-EVAL-01 (Judge Model Default in Cluster)**:
   Until a separate judge endpoint or model is provisioned, `ZIVON_EVAL_JUDGE_MODEL` defaults to the cluster's configured `ZIVON_MODEL` (`stealth/crouton-alpha` on OpenRouter or the local Strata model) served through the existing single-model `llm-manager` node (`k8s/16-llm-manager.yaml`). See [`ADR-0028`](../../backend/adr/0028-eval-judge-model-and-calibration.md) for how multi-model judge routing is enabled when a second model is desired.
2. **`[ASSUMPTION]` A-EVAL-02 (Eval CronJob Cadence)**:
   `EVAL_CRON_SCHEDULE` ships as `"0 2 * * *"` (daily, 02:00 UTC) in `k8s/infra.env` — not `"*/30 * * * *"` (`TEST_CRON_SCHEDULE`): a full eval + calibration run makes `~26` model calls (`~5–10 min` on cloud, longer on a local ~20 tok/s server) and must not starve interactive factory generation jobs on a single-slot server. The `"0 */6 * * *"` figure floated earlier is superseded by the shipped daily cadence; on-demand `scripts/trigger-evals.sh` covers pre-merge checks. `k8s/infra.env` remains the single source of truth for the value (the CronJob renders it via `scripts/apply-k8s.sh`).
3. **`[ASSUMPTION]` A-EVAL-03 (Phase 1–3 vs Phase 4 Perf Budgets)**:
   `EV-PERF-001` enforces the current loosened `weak-android.json` load/FCP budgets (`load_s <= 6.0`, `fcp_s <= 3.5` per the 2026-11-04 founder decision in `docs/content-factory/architecture.md`) as `fatal`, while reporting violations of the Phase-4 target (`load_s <= 2.0`, `fcp_s <= 1.2`) as `major` advisories until the Phase-4 frontend pass re-tightens `weak-android.json`.

---

## 3. Open Questions for Founder Sign-Off

| Question ID | Question | Recommended Default (Used in Spec) | Impact if Changed |
|---|---|---|---|
| `OQ-EVAL-01` | Should `scripts/apply-k8s.sh` trigger an immediate startup `eval-suite` run (like `scripts/trigger-tests.sh startup`), or only `eval-smoke` on cluster apply? | **Run `scripts/trigger-evals.sh smoke startup` on `apply-k8s.sh`** (`0` model calls, `< 30s`), leaving `--suite full` to the 6-hour CronJob and manual triggers so `apply-k8s.sh` never burns model credits or blocks the single-slot server on every redeploy. | One line in `scripts/apply-k8s.sh` (`scripts/trigger-evals.sh smoke startup` vs `full`). |
| `OQ-EVAL-02` | When `03-check` or `09-review` prompts are edited, should CI require a manual calibration artifact (`eval_report.json` from `--suite calibrate`) before merging to `main`? | **Advisory in PR description for P0; required check post-challenge (P1)** via a branch-protection status check posted by `scripts/trigger-evals.sh calibrate`. | None on `evals/` code; policy toggle in GitHub branch protection. |
| `OQ-EVAL-03` | Should `GT-01` (`frontend/courses/class-9-physics/how-forces-affect-motion/`, generated `2026-11-03` pre-kit v1.6) be regenerated with `--fresh` on `0.3.17` (`PIPELINE_VERSION = 7`) before locking its `expected.json` visual invariants? | **Yes — regenerate `Motion` Class 9 with `--fresh` on `0.3.17`** so `GT-01` carries kit chrome (`.zn-lang-bar`, `.zn-sim-read`) and computed-geometry sims just like `GT-02`; until regenerated, `GT-01/expected.json` sets `pipeline_version_min: 3` and `requires_lang_bar: false`. | Flipping `requires_lang_bar: true` and re-pinning `diagrams_max` in `GT-01/expected.json` after `--fresh` publish (it currently reads `2`, reconciled with the refreshed published page on `2026-11-10` — see §2.2 of `golden-sets.md`). |
