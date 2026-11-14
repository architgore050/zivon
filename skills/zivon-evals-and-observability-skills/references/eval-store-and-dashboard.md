# Eval store, telemetry, and the one curation front

Sources: `docs/specs/evals/spec.md` §4–§6, `docs/backend/adr/0027-*` and `0028-*`,
`evals/store.py`, `evals/telemetry.py`, `evals/runner.py`, `evals/report.py`,
`docs/specs/observability/dashboard-spec.md`, `dashboard/queries.py`. Verified 2026-11-14 at
`main` @ `57147bb`.

## 1. What "one curation front" means

Until the dashboard's eval panel (ADM-10) ships, a result is curated only when **all five**
of these exist:

1. **List:** a row in `evals_runs/eval_runs_ledger.jsonl` (append-only, one object per run,
   idempotent on `eval_run_id`).
2. **Detail:** `evals_runs/<eval_run_id>/eval_report.json`,
   `eval_summary.md`, `eval_metrics.prom` (and `eval_diff.json` when a diff was computed).
3. **Relational mirror:** `eval_run`, `eval_card_result`, `eval_defect_sample_result`,
   `eval_human_edit`, `eval_kid_session` when a DB URL is configured, or an outbox bundle when
   the write failed.
4. **PR evidence:** the run id + `eval_summary.md` linked in the PR.
5. **Telemetry:** the `EVT-EVAL-*` events emitted and declared in the instrumentation map.

A run that exists only in terminal scrollback is a local experiment, not evidence.

`evals_runs/` is gitignored (`/evals_runs/`); the ledger and reports are operational artifacts,
not commits. The PR carries the durable evidence.

## 2. `EvalStore.persist_run()` — exact outputs

`evals/runner.py::run_eval_suite` builds an `EvalRunReport` and calls
`EvalStore(cfg).persist_run(report)`.

`persist_run` writes:

1. `evals_runs/eval_runs_ledger.jsonl` — one JSON object per run, de-duplicated on
   `eval_run_id` (a retried persist after a DB error must not duplicate the row).
2. `evals_runs/<eval_run_id>/eval_report.json` — indented report.
3. When `ZIVON_EVAL_STORE_BACKEND` is `dual` or `postgres` **and** a DB URL exists:
   the five relational tables (Postgres, or SQLite for offline verification).
4. On DB failure: `evals_runs/outbox/<eval_run_id>.tar.zst` (or `.tar.gz` when the `zstd`
   binary is absent) plus an `EVT-EVAL-RUN-COMPLETED` event with
   `store_degraded_to_jsonl=true` and `error_class=store_error`. With backend `postgres`, the
   failure re-raises — no silent downgrade.

Then `runner.write_run_artifacts` writes `eval_summary.md` and `eval_metrics.prom` (and
`eval_diff.json` when a diff was computed). It writes to `--out` when given, otherwise to the
run directory; use the default for evidence, because `--out` leaves the run directory with only
`eval_report.json`.

Ledger row keys (observed shape): `baseline_eval_run_id`, `cards`, `completed_at`,
`duration_s`, `eval_run_id`, `factory_image_tag`, `generator_model`, `git_sha`, `judge_model`,
`overall_pass`, `pipeline_version`, `prompt_bundle_sha256`, `regression_detected`,
`schema_version`, `started_at`, `suite`, `summary`.

## 3. Configuration

| Variable | Meaning | Default |
|---|---|---|
| `ZIVON_EVAL_RUNS_DIR` | output root | `evals_runs/` |
| `ZIVON_EVAL_GOLDENS_DIR` | golden input root | `evals/goldens/` |
| `ZIVON_EVAL_CARDS_DIR` | card input root | `evals/cards/` |
| `ZIVON_FRONTEND_DIR` | published site root for render checks | `frontend/` |
| `ZIVON_EVAL_STORE_BACKEND` | `jsonl` / `dual` / `postgres` | `dual` |
| `ZIVON_DB_URL` or `EVAL_DB_URL` | relational store | unset |
| `ZIVON_BASE_URL` / `ZIVON_MODEL` | generator endpoint/model | unset |
| `ZIVON_EVAL_BASE_URL` / `ZIVON_EVAL_JUDGE_MODEL` | judge endpoint/model (fall back to generator) | unset |
| `ZIVON_EVAL_API_KEY` or `ZIVON_API_KEY` | runtime secret | unset |
| `ZIVON_EVAL_MOCK` | deterministic fake judge | false |

`EvalConfig.from_env` deliberately does **not** require a model URL at load time; `--suite
smoke` must run with no keys. The judge config validates the endpoint only when a judge is
actually invoked.

`ZIVON_EVAL_CARDS_DIR` and `ZIVON_EVAL_RUNS_DIR` are useful for a sandbox: copy the cards to a
temp dir, add one, and run without touching the tracked catalogue (the worked example does
this).

## 4. `evals/telemetry.py` — `EVT-EVAL-*`

Use `emit_eval_event(evt_id, fields, *, severity=None, error_class=None, latency_ms=None,
run_id=None, stage=None, fallback_dir=None)`. It maps the five canonical ids:

| EVT id | Dot event | Default severity | Caller |
|---|---|---|---|
| `EVT-EVAL-RUN-STARTED` | `factory.eval.run_started` | INFO | `runner.run_eval_suite` |
| `EVT-EVAL-RUN-COMPLETED` | `factory.eval.run_completed` | INFO | `runner.run_eval_suite`, `store.persist_run` (degraded) |
| `EVT-EVAL-REGRESSION-ALERT` | `factory.eval.regression_alert` | ERROR | `diff.compute_run_diff` |
| `EVT-EVAL-HUMAN-EDIT-RECORDED` | `factory.eval.human_edit_recorded` | INFO | `store.record_human_edit` |
| `EVT-EVAL-KID-SESSION-LOGGED` | `factory.eval.kid_session_logged` | INFO | `store.record_kid_session` |

The shim delegates to `logging_manager` when it is importable; otherwise it writes
`evals_runs/logs/YYYYMMDD-evals.jsonl`.

**Known Wave-1 defect (P-GAP-14, confirmed 2026-11-14).** The instrumentation map has **zero**
rows for these five dot events, and the shim's own fallback record uses `component="evals"`,
which is outside the closed component enum. Observed on a real smoke run:

```json
{"ts":"2026-11-14T07:50:15.064Z","schema_version":1,"severity":"INFO","event":"factory.eval.run_started","component":"log","env":"dev","run_id":"eval-smoke-20261114T075015Z-57147bb-f35e0c","fields":{"evt_id":"EVT-EVAL-RUN-STARTED","eval_run_id":"eval-smoke-20261114T075015Z-57147bb-f35e0c","suite":"smoke","git_sha":"57147bbbc142","cards_selected":["EV-CUR-001","EV-E2E-001","EV-KID-001","EV-PERF-001","EV-REV-001","EV-REV-002","EV-SYN-001","EV-SYN-002","EV-VIS-001"],"mock_mode":true}}
{"ts":"2026-11-14T07:50:15.064Z","schema_version":1,"severity":"WARNING","event":"log.event_unknown","component":"log","env":"dev","fields":{"offender_event":"factory.eval.run_started"}}
```

Consequences: `log.event_unknown` warnings, map-lint red once the names are listed as emitted,
and eval events attributed to `log` instead of a real component. The required fix is one
recorded decision:

- **Option A (recommended by the handshake):** add `evals` to the component enum in
  `logging-api.md` §8, add the five map rows (`component=evals`, `correlation_ids=run_id`,
  `privacy_class=L1` for run-level events, `required_fields` from `spec.md` §6.2), and add the
  names to `testing/observability/test_events.py` + the row-count assertion.
- **Option B:** map them to `component=factory` (no enum change, semantically muddier).

Do not ship a new eval card while the events it emits are undeclared. Land the map rows (or
coordinate with the P4 owner) in the same Wave as the card.

## 5. Other eval ledgers

- `record_human_edit` compares the published topic against the run's baseline files
  (`index.html`, `page.css`, `page.js`, `plan.json`), computes `human_edit_rate =
  (added + deleted) / max(1, total_lines)`, appends to
  `evals_runs/human_edits_ledger.jsonl` (+ `eval_human_edit`), and emits
  `EVT-EVAL-HUMAN-EDIT-RECORDED`. It feeds `EV-E2E-001`.
- `record_kid_session` validates the payload with `validate_kid_session_dpdp`, appends to
  `evals_runs/kid_sessions_ledger.jsonl` (+ `eval_kid_session`), and emits
  `EVT-EVAL-KID-SESSION-LOGGED`. It feeds `EV-KID-001`. It is not a substitute for the edit
  rate: edit rate measures pipeline reliability; kid sessions measure comprehension.
- `backfill_db` replays the three JSONL ledgers into the relational store; it requires a DB URL
  and is idempotent.

## 6. Dashboard and read paths today

- The admin dashboard (`dashboard/`) reads `log_events` through `dashboard/queries.py` and
  `runs/<run_id>/` artifacts from the read-only PVC. Its views are factory runs, test-suite
  status, voice latency, credit usage, error feed, and publish status
  (`dashboard-spec.md` §4).
- **There is no eval view yet** (ADM-10, P-GAP-17). The dashboard does not read
  `evals_runs/`. The curation front is the ledger + run directory + PR evidence.
- The eval spec's target endpoints (`GET /api/v1/admin/evals/runs`, `.../diff`,
  `POST .../trigger`) and the `zivon_eval_*` Prometheus metrics are **specified**, not built.
  Do not assume they exist; check `dashboard/app.py` before wiring a UI to them.
- In-cluster runs: the `eval-suite` CronJob (`k8s/52-eval-cronjob.yaml`) runs
  `python -m evals run --suite full --fail-on-regression` on the `EVAL_CRON_SCHEDULE` cadence
  (daily 02:00 UTC in `k8s/infra.env`) and persists evidence to the `zivon-sources` PVC
  (`subPath: evals`). The on-demand button is `scripts/trigger-evals.sh [smoke|full|calibrate]`.
  The GitHub Actions job is `evals-smoke`.

## 7. What "logged" means for an eval run

A run is logged only when:

1. the ledger contains its row;
2. the run directory contains `eval_report.json`, `eval_summary.md`, and `eval_metrics.prom`;
3. the relational mirror exists when a DB URL is configured, or the outbox bundle exists when
   the write failed;
4. the five `EVT-EVAL-*` names resolve to map rows and are emitted;
5. the PR links the run id and the summary.

Any missing item means the run is a local experiment.

## 8. Verification commands

```bash
# key-free smoke and regression gate
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression

# inspect persistence
tail -1 evals_runs/eval_runs_ledger.jsonl | python3 -m json.tool | head -40
ls evals_runs/<eval_run_id>/

# compare two runs
python -m evals diff --prev <id> --curr <id>

# relational replay (needs a DB URL)
python -m evals backfill-db
```

## 9. Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Only reading stdout, never checking the ledger | The "run" disappears; no evidence | Confirm the row and run dir |
| Assuming the dashboard shows evals | It does not (ADM-10 pending) | Link the ledger/report in the PR |
| Treating `evals_runs/` as committed | It is gitignored | Put the run id + summary in the PR body |
| Adding a card while `factory.eval.*` is undeclared | More `log.event_unknown`, map-lint debt | Land the map rows or coordinate with P4 first |
| Using `pipeline_version=1` from the report as truth | `runner.py` hardcodes it (P-GAP-15); the actual `PIPELINE_VERSION` is higher | Read `factory/stages.py::PIPELINE_VERSION` for the real value; record it in the PR |
| Backfilling without a DB URL | CLI raises | Configure `ZIVON_DB_URL` or use `--store`-free smoke |
| Passing `--out` for a PR run | The run directory has only `eval_report.json`; summary/metrics are elsewhere | Use the default run directory for evidence |
| Treating a degraded store as success | Evidence is only in the outbox | Report the warning and attach the bundle path |
