# Evals versus tests

`testing/` and `evals/` answer different questions and have different costs.
The boundary is binary in this repo, not a judgement call:

| Dimension | `testing/` | `evals/` |
|---|---|---|
| Question | Does the code execute its deterministic contract? | Does the model, prompt, or reviewer produce good output? |
| Model dependency | Never a real model; mocks/fakes at seams | Deterministic smoke is 0 model calls; full uses a judge via `llm_manager` |
| Expected value | Computable from fixed input | A rubric, a threshold, a calibrated corpus |
| Cadence | Every PR and every merge | Deterministic smoke every PR; full/calibration in the infra window |
| Home | `testing/<area>/` | `evals/` |
| Command | `python -m unittest discover -s testing/<area> -t .` | `python -m evals run --suite smoke --mock` |
| Failure meaning | A code contract broke | Output quality regressed or a judge miscalibrated |
| Cost | Milliseconds to seconds, free | Minutes and model credits (full/calibrate) |

The source of truth is `docs/specs/evals/spec.md` §1 and
`docs/specs/evals/README.md`; ADR-0027 covers persistence, ADR-0028 the judge
model and calibration.

## 1. The three-way decision

```
Does the check need a model to decide pass/fail?
├── no  → Can a checker decide it with zero model calls?
│         ├── yes → evals/checkers/ (and a testing/evals/ unit test)
│         └── no  → testing/  (unit, contract, integration, browser)
└── yes → Is the expected answer a judgement (teaching quality, grounding,
          coverage, reviewer verdict)?
          ├── yes → an evals/ card with a deterministic-first funnel and a judge
          └── no  → you have not found the deterministic observable yet
```

A checker that needs no model belongs in `evals/checkers/` **and** is exercised
by `testing/evals/`. A test that needs a model is not a unit test. A judge
without a card is a prompt experiment, not evidence.

## 2. What stays in `testing/`

- Config and CLI parsing, env-var tripwires, fingerprints.
- Stage handoff schemas and validation.
- Lint and rule checkers (`factory/lint.py`, `factory/checks.py`) — their code
  mechanics, not their judgement of a real page.
- Ingestion, PDF table extraction, retrieval mechanics with a fixture embedder.
- Renderer mechanics: HTML shape, CSP, manifest, staging, link integrity.
- Frontend shell runtime mechanics: quiz wiring, simulation error boundary,
  keyboard behaviour, clean load.
- Adapter mechanics: vendor payload mapping, retries, deadlines, error types.
- Database repository mechanics on SQLite, plus the migration chain on Postgres
  in CI.
- Observability contract: event schema, redaction, sinks, map conformance.

## 3. What moves to `evals/`

- Prompt-contract and prompt-anchor checks (does `02-generate` carry the
  grounding law, coverage contract, geometry routing?).
- Prompt-design quality and model-output quality.
- Golden-topic grading: grounding, coverage, teach-before-test, numerical
  anchors, visual and kit invariants.
- Reviewer calibration (`03-check`, `09-review`) against seeded defects.
- Weak-hardware performance grading of generated pages (`EV-PERF-001`).
- End-to-end page quality and human edit rate (`EV-E2E-001`).
- Kid-comprehension sessions (`EV-KID-001`).

If a check mixes both — for example, "the renderer emits the right attributes"
(code) and "the page teaches the concept" (quality) — split it: a `testing/`
contract test for the attributes and an eval card for the pedagogy.

## 4. The deterministic-first funnel

Every card runs code checkers before any judge call. A fatal checker failure
short-circuits the judge and records the deterministic failure; the judge is
skipped unless `--force-judge` is passed. This is both a cost control and a
truth control: a schema-broken page should not spend a model call to be told it
is broken.

Rules for checkers:

- Zero network, zero model, zero secrets; a pure function of artifacts and
  goldens.
- Reuse the factory rule instead of reimplementing it
  (`factory.schemas:GENERATED`, `factory.checks:run_all_rules`,
  `factory.lint:lint_generated`, the translation checker).
- Return `IssueRecord`s with a stable `check_id` and a severity from
  `fatal | major | minor | unverified`.
- Any checker that can produce a false fatal is a calibration bug, not a
  strictness virtue.

## 5. Card anatomy

Required fields (validated by `evals/models.py`):

`card_id`, `version`, `title`, `stage`, `agent_role`, `suites`,
`golden_inputs`, `deterministic_checks`, `llm_judge`, `thresholds`,
`cost_budget`.

Current schema constraints (validated by `evals/models.py`) and card rules
(as of 2026-11-14):

- Card ID: `^EV-(CUR|SYN|VIS|PERF|REV|E2E|KID)-[0-9]{3}$`.
- `suites`: `smoke`, `full`, `calibrate`. A card with at least one
  deterministic checker includes `smoke`; judges run in `full`/`calibrate`.
- `stage` and `agent_role` are closed enums. Assessment/exam/series cards need
  an additive schema extension in `evals/models.py`,
  `docs/specs/evals/card-template.md`, and `testing/evals/` before a card can
  be written; do not invent a prefix.
- `golden_inputs.topics` must be registered in `evals/goldens/manifest.json`.
- `deterministic_checks[].reuses_factory_rule` names the real rule it mirrors.
- `thresholds` carry deterministic pass rate, max fatal, max major, and
  regression tolerance.
- `cost_budget` carries `smoke_model_calls: 0`, per-topic full calls, calibration
  calls, max completion tokens, and the call deadline.

The canonical template is `docs/specs/evals/card-template.md`; the live cards
are in `evals/cards/`.

## 6. Judges

- Routed through `llm_manager` (ADR-0028), `temperature=0.0`, no `max_tokens`
  from env.
- The rubric is **reused verbatim** from the factory prompt it evaluates
  (`factory/agents.py::run_check`, `factory/review.py`). Do not invent a second
  rubric that drifts.
- Every judge has anchor examples (fatal/major/minor), an `unverified:` way
  out, a severity ladder, and a bounded procedure.
- Calibration is measured on the 19 seeded defects: fatal recall and clean
  specificity. A prompt or rubric change without a calibration run is not
  reviewable.

## 7. Commands

| Command | Network | What it does |
|---|---|---|
| `python -m evals run --suite smoke --mock` | none | Deterministic checkers on goldens; no judge calls |
| `python -m evals run --suite smoke --fail-on-regression` | none | CI merge gate; exits `2` on regression |
| `python -m evals run --suite full` | model endpoint | Checkers plus judges (founder/infra window) |
| `python -m evals run --card EV-SYN-001 --topic <slug>` | depends | One card |
| `python -m evals calibrate --stage all --mock` | none | Calibration harness, fake judge |
| `python -m evals calibrate --stage all` | model endpoint | Live calibration (infra window) |
| `python -m evals diff --prev <id> --curr <id>` | none | Regression diff; exits `2` on regression |
| `python -m evals record-edit ...` | none | Human edit rate (`EV-E2E-001`) |
| `python -m evals record-kid-test ...` | none | DPDP-validated kid session (`EV-KID-001`) |
| `python -m evals report --run <id>` | none | Render an existing run |
| `python -m evals rotate-golden --topic-id <id> --reason "<why>"` | none | Golden rotation; keeps history |
| `python -m evals backfill-db --db-url ...` | DB | Replay JSONL ledgers into the relational store |

Suite semantics:

- `smoke` = deterministic only, zero model calls, key-free.
- `full` = deterministic plus judges, needs the model endpoint.
- `calibrate` = seeded-defect reviewer calibration.

CI runs the deterministic smoke (`evals-smoke` job). The cluster CronJob
(`k8s/52-eval-cronjob.yaml`) runs `--suite full --fail-on-regression` daily at
02:00 UTC. The on-demand button is `scripts/trigger-evals.sh [smoke|full|calibrate]`.

## 8. Adding an eval card

1. **Confirm the stage and role are in the schema.** If not, land the additive
   extension first (owner P4; do not fork the enum).
2. **Write `evals/cards/EV-<PREFIX>-<NNN>.yaml`** from the card template. Name
   the stage, the role, the goldens, the checkers, the judge (if any), the
   thresholds, and the cost budget.
3. **Add the deterministic checker** in `evals/checkers/<area>.py`. Reuse a
   factory rule. Add its unit test in `testing/evals/`.
4. **Add or extend the goldens** under `evals/goldens/` and register them in
   `evals/goldens/manifest.json`. Do not invent a golden from a hand-written
   page.
5. **If a judge is added:** reuse the factory rubric, add anchors and a way
   out, extend the calibration mapping, and run
   `python -m evals calibrate --stage <stage> --mock`.
6. **Run the checks:**
   ```bash
   python -m unittest discover -s testing/evals -t .
   python -m evals run --suite smoke --mock
   python -m evals run --suite smoke --fail-on-regression
   ```
7. **Persist the run** (the runner calls `EvalStore.persist_run()`), and make
   sure the `EVT-EVAL-*` events are declared in the instrumentation map.
8. **Update the docs** (`docs/specs/evals/spec.md`, and
   `docs/specs/evals/golden-sets.md` when a golden is added).
9. **Attach the run id and `eval_summary.md` to the PR.** A run that exists
   only in terminal scrollback is not evidence.

## 9. Logging eval results

A run is "logged" only when all of these are true:

1. `evals_runs/eval_runs_ledger.jsonl` contains its row.
2. `evals_runs/<eval_run_id>/` contains `eval_report.json`.
3. `eval_summary.md` and `eval_metrics.prom` are written.
4. The relational mirror is written when a DB URL is configured, or an outbox
   bundle exists when it failed.
5. The five `EVT-EVAL-*` events resolve to instrumentation-map rows and are
   emitted through `evals/telemetry.emit_eval_event`.
6. The PR links the run id and the summary.

The event IDs are:

| ID | Dot event | Default severity |
|---|---|---|
| `EVT-EVAL-RUN-STARTED` | `factory.eval.run_started` | INFO |
| `EVT-EVAL-RUN-COMPLETED` | `factory.eval.run_completed` | INFO |
| `EVT-EVAL-REGRESSION-ALERT` | `factory.eval.regression_alert` | ERROR |
| `EVT-EVAL-HUMAN-EDIT-RECORDED` | `factory.eval.human_edit_recorded` | INFO |
| `EVT-EVAL-KID-SESSION-LOGGED` | `factory.eval.kid_session_logged` | INFO |

Known gap (checked 2026-11-14): the instrumentation map
(`docs/specs/observability/instrumentation-map.csv`) has no rows for these five
events, and the closed component enum in `logging-api.md` has no `evals`
member. The fix is an instrumentation-map/spec change (add the component and
the five rows, then update `testing/observability/test_events.py`). Do not ship
a new card while the events it emits are undeclared without recording that
decision in the PR.

Persistence environment variables:

| Variable | Meaning |
|---|---|
| `ZIVON_EVAL_RUNS_DIR` | Output root (default `evals_runs/`) |
| `ZIVON_EVAL_GOLDENS_DIR`, `ZIVON_EVAL_CARDS_DIR`, `ZIVON_FRONTEND_DIR` | Input roots |
| `ZIVON_EVAL_STORE_BACKEND` | `jsonl`, `dual`, `postgres` (default `dual`) |
| `ZIVON_DB_URL` or `EVAL_DB_URL` | Relational store |
| `ZIVON_BASE_URL` / `ZIVON_MODEL`, `ZIVON_EVAL_BASE_URL` / `ZIVON_EVAL_JUDGE_MODEL`, `ZIVON_EVAL_API_KEY` | Model endpoints |
| `ZIVON_EVAL_MOCK` | Deterministic fake judge |

## 10. Cost and cadence

- **Smoke = 0 model calls, always.** It is the PR gate.
- A full card stays within its per-topic call budget; the run report tracks
  `model_calls_total` and `total_thinking_s`.
- Calibration is the only place a reviewer is called many times. It runs in an
  infra window, not in parallel agent work.
- Live suites spend credits and use the single-slot model endpoint. Founders or
  the infra owner trigger them; a parallel agent does not.

## 11. Anti-patterns

| Pattern | Why it is not an eval |
|---|---|
| A judge prompt with no card | Not versioned, not thresholded, not comparable |
| A card with no goldens | Nothing stable to compare against |
| A seeded defect edited to make a reviewer pass | Destroys the calibration baseline |
| A "manual check" in the PR description | Not persisted, not reproducible |
| A mock judge presented as quality evidence | Proves the harness, not the model |
| Running `--suite full` in CI | Needs a key, spends credits, nondeterministic |
| Reimplementing a factory rule in a checker | Two sources of truth drift |
| Using an eval to test parser mechanics | Slower, costlier, and less precise than a unit test |
| A run not persisted or linked | A local experiment, not the curation front |
