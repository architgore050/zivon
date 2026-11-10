# ADR-0027: Eval Result Store, Dual-Write Ledger, and Cold Storage Tiering

- **Status**: accepted (Wave S1 — `SP4-EVALS`)
- **Date / deciders**: 2026-11-09 / Founder + `SP4-EVALS`
- **Driving NFRs / requirements**:
  - `NEED-EVAL-TRACKING`: Regress-track content-factory stage scores, reviewer calibration (`03-check`, `09-review`), and weak-Android performance budgets across `PIPELINE_VERSION`, prompt, and model changes.
  - `NEED-PIPELINE-RELIABILITY`: Record and trend `TIMELINE.md`'s primary factory metric (**human edit rate per generated topic**) and Gate B kid-comprehension sessions (`INF-GATE-B-RESULT`).
  - `NFR-DURABILITY-C4`: Content-factory and evaluation evidence (`C4` in `skills/zivon-systems-design-skills/skills/zivon-systems-design/references/02-data-classification-and-tiering.md`) must survive pod restarts on the local cluster PVC and sync to a separate cold-storage failure domain without blocking P0/offline factory runs.
  - `NFR-PRIVACY-DPDP`: Kid-comprehension evaluation records must be private-by-default (zero child PII, zero raw audio, linked to `consent_record`, hard-deletable on guardian withdrawal).

---

## Context

Zivon's content factory already writes per-run stage artifacts and two append-only JSONL ledgers (`calls_ledger.jsonl` and `issues_ledger.jsonl`, added 2026-11-08) under `runs/<run_id>/` on the `zivon-sources` PersistentVolumeClaim (`subPath: runs`). However:
1. `runs/<run_id>/` is scoped to a single topic generation run and can be wiped when an operator passes `--fresh`.
2. Eval runs (`python -m evals run`) evaluate *across* multiple golden topics, seeded-defect calibration samples (`EV-REV-001`, `EV-REV-002`), human post-publish edits (`EV-E2E-001`), and Gate B kid-testing cohorts (`EV-KID-001`).
3. In P0 / local-cluster mode (`minikube` with `HF_HUB_OFFLINE=1`, gotcha 15), `evals/` must work with **zero external database or cloud SaaS dependencies**, while in Phase B / production (`docs/backend/db-spec.md` and `docs/backend/storage-tiering.md`), the Day-8 Admin Dashboard and regression alerter need indexed relational queries over historical eval runs and cold-storage durability.

---

## Options considered

| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Option 1: Flat JSONL files on `zivon-sources` PVC only (do nothing / simplest)** | Zero DB setup; works offline in CI and minikube immediately; matches `calls_ledger.jsonl` pattern. | No transactional integrity with `lesson_version` or `consent_record`; linear scan slows down dashboard queries; PVC loss destroys history unless synced to cold storage. | ₹0 / zero extra pods. | Fails `NFR-DURABILITY-C4` (single failure domain on node SSD) and `NFR-PRIVACY-DPDP` (no FK cascade on consent withdrawal) in Phase B. |
| **Option 2: PostgreSQL-only store (require DB for all eval runs)** | Strong relational integrity (`UUIDv7` PKs, FK to `lesson_version` and `consent_record`), indexed diff queries, covered by WAL archiving (`ADR-0006`). | Breaks key-free CI (`eval-smoke`) and standalone/offline cluster runs when Postgres is not running; violates `AGENTS.md` ("avoid over-engineering databases early"). | Low (uses existing backend Postgres instance). | Fails P0/CI zero-dependency requirement (`AGENTS.md` line 125). |
| **Option 3: External SaaS Eval Store (LangSmith / Braintrust / Arize Cloud)** | Pre-built UI for traces and dataset diffs. | Requires outbound internet from cluster pods (impossible under gotcha 15: containers only reach `192.168.49.1`); requires third-party API keys in CI/cluster; vendor lock-in. | Paid SaaS tier + secret management overhead. | Fails offline cluster constraint (gotcha 15) and `AGENTS.md` key-free CI rule. |
| **Option 4: Dual-Mode Store — Append-Only JSONL on PVC (`Phase A`) + Optional PostgreSQL Dual-Write & Transactional Outbox to Cold Storage (`Phase B`) (Selected)** | Works 100% offline/key-free in CI and P0 (`evals_runs/*.jsonl` on `zivon-sources` PVC `subPath: evals`); when `ZIVON_DB_URL` is set, dual-writes to 5 PostgreSQL tables (`eval_run`, `eval_card_result`, `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session`) and archives completed run bundles to cold object storage under data class `C4`. | Small adapter layer (`evals/store.py`, ~180 LOC) to support both JSONL and SQLAlchemy/psycopg writers plus a `backfill-db` CLI command. | ₹0 in P0; marginal KB/day in Postgres + S3 cold storage in Phase B. | Fails none. |

---

## Decision

We adopt **Option 4 (Dual-Mode Store)**:

1. **Always-On Local/PVC Ledger (`Phase A` — P0 & CI)**:
   - Every `evals` invocation writes to `/app/evals_runs/` (mounted from PVC `zivon-sources`, `subPath: evals` in `k8s/52-eval-cronjob.yaml` — separate from `subPath: runs` so `pipeline.py --fresh` never wipes eval history):
     - `evals_runs/eval_runs_ledger.jsonl` (one summary JSON line per suite run, including its card results)
     - `evals_runs/human_edits_ledger.jsonl` (one line per `evals record-edit`)
     - `evals_runs/kid_sessions_ledger.jsonl` (one line per `evals record-kid-test`)
     - `evals_runs/<eval_run_id>/{eval_report.json,eval_summary.md,eval_metrics.prom}` (plus `eval_diff.json` when a diff is written)
2. **Relational Persistence (`Phase B` — `db-spec.md` Alignment)**:
   - When `ZIVON_DB_URL` is present in the environment, `evals/store.py` dual-writes to five tables in PostgreSQL (schemas defined in [`docs/specs/evals/spec.md`](../../specs/evals/spec.md) §4.1):
     - `eval_run` (UUIDv7 PK, indexed on `(suite, pipeline_version, started_at DESC)`)
     - `eval_card_result` (UUIDv7 PK, FK to `eval_run`, indexed on `(card_id, topic_slug, created_at DESC)`)
     - `eval_defect_sample_result` (UUIDv7 PK, FK to `eval_card_result`, indexed on `(sample_id, outcome_class)`)
     - `eval_human_edit` (UUIDv7 PK, tracks `human_edit_rate` per topic/version)
     - `eval_kid_session` (UUIDv7 PK, FK `consent_record_id` with `ON DELETE CASCADE` for DPDP erasure)
   - A CLI command `python -m evals backfill-db --from-dir evals_runs` idempotently imports Phase A JSONL rows into PostgreSQL using deterministic UUIDv5/UUIDv7 keys derived from `(eval_run_id, card_id, sample_id)`.
3. **Storage Tiering (`storage-tiering.md` Data Class `C4` Alignment)**:
   - Relational rows in `eval_run`, `eval_card_result`, `eval_defect_sample_result`, and `eval_human_edit` are covered by continuous PostgreSQL WAL archiving + daily base backups (`C14`, `ADR-0006`).
   - Raw per-run artifact directories (`evals_runs/<eval_run_id>/`) are classified under **`C4` (Content-factory & eval run evidence)**:
     - **Sync Trigger**: On `eval_run` completion, a transactional outbox job compresses `evals_runs/<eval_run_id>/` to `.tar.zst`, computes its `sha256`, and uploads to the cold S3-compatible provider at `c4/evals/dt=YYYY-MM-DD/<eval_run_id>/<sha256>.tar.zst`.
     - **Verification & Eviction**: The outbox worker verifies the read-back SHA-256 and sets `cold_verified_at` on the `object` catalogue row. Local SSD directories on `zivon-sources` PVC are only eligible for LRU eviction when `cold_verified_at IS NOT NULL`, `pinned = FALSE` (the active baseline run for each `PIPELINE_VERSION` is `pinned = TRUE`), and `age > 14 days`.

---

## Consequences

- **What gets easier**:
  - `eval-smoke` in GitHub Actions and local developer runs need zero database containers or credentials.
  - `--fresh` factory topic regenerations never delete historical eval baselines or human-edit-rate records because `subPath: evals` is isolated from `subPath: runs`.
  - Phase B dashboard queries (`GET /api/v1/admin/evals/runs`, `GET /api/v1/admin/evals/runs/{id}/diff`) hit indexed PostgreSQL tables with millisecond latency.
- **What gets harder**:
  - Schema changes to `EvalRun` or `CardResult` must keep the JSONL serializer (`evals/models.py`) and the Alembic migration (`eval_run`, `eval_card_result`) in lockstep.
- **What we must monitor**:
  - Disk usage on PVC `zivon-sources` (`subPath: evals`); alert if unverified cold-sync backlog exceeds 15 minutes (`storage-tiering.md` §3.1 SLO).

---

## Revisit trigger

- Revisit if `evals_runs/` exceeds `2 GiB` on the `zivon-sources` PVC before Phase B cold-storage eviction is enabled, or if concurrent eval writers ever exceed `1` (`k8s/52-eval-cronjob.yaml` enforces `concurrencyPolicy: Forbid`).

---

## References

- [`docs/specs/evals/spec.md`](../../specs/evals/spec.md) §4 (Regression Tracking, Persistence & Human-Edit-Rate Capture)
- [`skills/zivon-systems-design-skills/skills/zivon-systems-design/references/02-data-classification-and-tiering.md`](../../../skills/zivon-systems-design-skills/skills/zivon-systems-design/references/02-data-classification-and-tiering.md) (Data classes `C4`, `C9`, `C14` and eviction safety invariant)
- [`skills/zivon-systems-design-skills/skills/zivon-systems-design/references/03-database-spec-method.md`](../../../skills/zivon-systems-design-skills/skills/zivon-systems-design/references/03-database-spec-method.md) (UUIDv7, `timestamptz`, JSONB, retention)
- [`skills/zivon-backend-engineering-skills/README.md`](../../../skills/zivon-backend-engineering-skills/README.md) (§1 Alembic discipline, §2 Postgres WAL/PITR `ADR-0006`)
