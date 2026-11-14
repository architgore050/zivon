---
name: zivon-evals-and-observability-skills
description: Makes "logged" and "evaluated" concrete for Zivon and guides the change end to end. Covers structured events through logging_manager and the instrumentation map, eval cards, deterministic checkers, golden topics, seeded defects, judges, calibration, the dual-write eval store, EVT-EVAL-* telemetry, regression diffs, and the PR evidence that proves a run happened. Use when adding or changing telemetry, a log event, an instrumentation-map row, an eval card, a checker, a golden fixture, reviewer calibration, an eval run, a regression baseline, the eval store or dashboard readout; when a PR needs its logging/eval evidence; when reviewing such a change; or when asked "is this logged?", "is this evaluated?", "where do eval results land?", or "why is map-lint red?".
license: MIT
compatibility: Works from the Zivon repo root with Python 3.10+. Smoke evals, `--mock` calibration, and every test in this bundle run key-free and offline; live `full`/`calibrate` suites need a configured model endpoint.
metadata:
  owner: zivon
  version: "1.0"
  evidence_date: "2026-11-14"
---

# Zivon Evals and Observability

Two contracts, one question each:

- **Logging:** can an operator reconstruct what happened, for whom, and how long it took —
  without any child's words, page content, prompt, or secret entering the store?
- **Evals:** is the model/content change measured against a durable baseline, deterministically
  first, with its result visible in one curation front?

A change is not done because it prints something or because a model was "checked manually".

## When to use this

Use it when any of these is true:

- You add or change a stage, route, service, button, or worker that does work someone will
  later need to diagnose.
- You touch a prompt, rubric, schema, generator, renderer content contract, translation rule,
  or assessment generator — i.e. anything whose quality is a model output.
- You add a log line, an event name, a map row, an eval card, a checker, a golden, a judge, or
  a regression baseline.
- A PR template asks for an eval run id, an `eval_summary.md`, or the events a change adds.
- CI fails on `testing/observability` or `evals-smoke`, or an event shows up as
  `log.event_unknown`.
- You are reviewing a logging/eval change and need the acceptance bar.

Do **not** use it for a pure refactor with identical behaviour, a visual/style-only change with
no judged content, or a one-off local experiment that will not be repeated. Those still need
the normal tests and review, not new telemetry or cards.

## The two definitions

### "Logged" (all seven must hold)

1. Every new event has a row in `docs/specs/observability/instrumentation-map.csv` with the
   right component, severity, correlation IDs, required fields, latency flag, error class,
   privacy class, and a real emitter.
2. Code emits through `logging_manager.log_event` only — no `print()`, stdlib `logging`,
   hand-built JSON, or SQL into `log_events`.
3. Correlation comes from context (`bind_context` at the edge); no ID is threaded through
   function arguments or invented where no edge exists.
4. Failure-shaped events carry a closed `ErrorClass`; duration events carry `latency_ms`.
5. The payload survives redaction: no transcript/text/content/prompt/response/answer/audio/
   token/secret key, no learner words, no secret value.
6. `python -m unittest discover -s testing/observability -t .` passes, including the map row
   count assertion.
7. A normal run shows the event in at least one sink (stdout JSON line, `runs/logs/*.jsonl`,
   or `log_events`), and the PR names the event and its consumer (or says "audit only").

"It prints something" is not logged. "The test asserts a string" is not logged.

### "Evaluated" (all seven must hold)

1. An eval card under `evals/cards/` covers the affected stage **and the specific new failure
   mode**, not just the old happy path.
2. At least one deterministic checker in `evals/checkers/` is referenced by the card and
   passes key-free. It reuses the factory rule instead of re-implementing it.
3. Goldens exist and are registered (`evals/goldens/manifest.json` for topics; the seeded
   defect set for reviewer calibration).
4. `python -m evals run --suite smoke --mock` passes, and the regression form is clean:
   `python -m evals run --suite smoke --fail-on-regression`.
5. The run is persisted: `evals_runs/eval_runs_ledger.jsonl` has its row and
   `evals_runs/<eval_run_id>/` has `eval_report.json`, `eval_summary.md`, `eval_metrics.prom`.
6. `EVT-EVAL-*` telemetry is emitted and its event names are declared in the instrumentation
   map (today this is an open Wave-1 fix; see `references/eval-store-and-dashboard.md`).
7. The PR links the run id and the summary. Until the dashboard eval panel (ADM-10) ships,
   that **is** the single curation front.

A judge prompt without a card, a card without goldens, a run without persistence, or "I
checked it manually" is not evaluated.

## Decide first

### When to log

Log at the **edges and state transitions** an operator would need to reconstruct a failure:
run/stage start and finish, request/session start and finish, a gate verdict, a retry attempt,
a fallback, a deletion, a guard refusal. Every event is map-declared and emitted once when the
thing happens.

Do not log: a loop iteration that changes nothing, a value you already logged in the same
attempt, page content, prompts, learner words, or "just in case" detail with no consumer. If
the event has no dashboard view, query, or audit purpose, it is noise — say "audit only" in the
PR or do not add it.

### When to add an eval

Add or extend an eval when the **quality of a model output** is the deliverable: a prompt,
rubric, schema, generator, renderer content rule, translation rule, assessment generator, or
judge. Extend the existing card if the failure mode is adjacent; add a card only when the stage
or failure class is genuinely new.

Do not add an eval card for a pure refactor, a deterministic bug fix, a visual/style-only
change, or a change whose acceptance is already fully expressed by a unit test. An eval that
cannot fail is not an eval; an eval with no baseline is a first run, not a regression gate.

| Change | Required evidence |
|---|---|
| New stage / route / background job / button | Logging: new rows + emissions; tests updated; no eval card unless quality is judged |
| New or changed model prompt, rubric, schema, generator, renderer content rule | Eval: new or updated card + checker + goldens + smoke run; logging only if a new event is needed |
| New user-visible frontend interaction | Frontend event only if an existing `EVT-F01..F12` cannot express it; otherwise reuse the existing event |
| Bug fix in deterministic code | Unit test in `testing/`; no eval card |
| Bug fix in model behaviour | Eval card covering the failure mode (or extend the existing card) + unit test for the checker |
| Pure docs, formatting, dependency bump | Neither, unless it changes a contract described here |

## Workflow A — add an event

1. **Name it.** `<component>.<subject>.<action>`, lower snake case, one row per name. Component
   must be in the closed enum in `logging_manager.events.COMPONENTS`. Pick the stage id from
   the real stage list.
2. **Write the map row** in `docs/specs/observability/instrumentation-map.csv`. The column
   contract and examples are in [`references/event-map.md`](references/event-map.md).
3. **Emit it** from the owning module with `log_event(...)`, correlation from context, and no
   denylisted keys. The exact API is in
   [`references/logging-manager.md`](references/logging-manager.md).
4. **Update the map-conformance test** `testing/observability/test_events.py`: add the name to
   `EMITTED_BY_THIS_BRANCH` (or `RESERVED_ROWS` when declared but not yet emitted) and bump
   the `len(rows) == 73` assertion (verify the current number; it was 73 on 2026-11-14).
5. **Run** `python -m unittest discover -s testing/observability -t .` and verify the JSON
   line locally (`ZIVON_RUNS_DIR=/tmp/...` keeps the fallback out of the repo).
6. **Update the owning doc** if the surface changed (`logging-api.md` for API/enum changes;
   the map for the event itself) and put the event names in the PR evidence.

If the event is for the browser, read the frontend path in
[`references/logging-manager.md`](references/logging-manager.md) first: the browser emits
`EVT-Fxx` through `window.ZivonEvents` to `POST /api/v1/events`; it does not call
`log_event` directly.

Before writing any field, read
[`references/privacy-and-redaction.md`](references/privacy-and-redaction.md). If a value is a
child's words or page content, log a reference id instead.

## Workflow B — add an eval

1. **Confirm the schema can express it.** Card ids are `EV-(CUR|SYN|VIS|PERF|REV|E2E|KID)-NNN`;
   the stage and agent-role enums are closed. A new stage prefix/role is a schema extension
   (founder-gated), not a YAML edit. Details:
   [`references/eval-authoring.md`](references/eval-authoring.md).
2. **Write the deterministic checker first** in `evals/checkers/<area>.py`. Signature is
   `check_<name>(cfg, card, context) -> list[IssueRecord]`; zero network, zero model, zero
   secrets; reuse a factory rule. Start from [`templates/checker.py`](templates/checker.py).
3. **Add or select goldens.** Topic goldens need `expected.json`, `source_pack_meta.json`,
   `artifact_ref.json` and a `manifest.json` entry. Seeded defects are calibration inputs, not
   unit fixtures. Use [`templates/golden-fixture.md`](templates/golden-fixture.md).
4. **Write the card** in `evals/cards/EV-*.yaml` from
   [`templates/eval-card.yaml`](templates/eval-card.yaml). `suites` includes `smoke` iff the
   card has a deterministic checker; `cost_budget.smoke_model_calls` is always `0`; a judge
   reuses the factory rubric verbatim and supplies fatal/major/minor anchors plus the
   `unverified:` way out.
5. **Run the funnel key-free:** `python -m evals run --suite smoke --mock` and
   `python -m evals run --suite smoke --fail-on-regression`. A failing deterministic check
   (fatal or major) short-circuits the judge; a checker with no data must record a skip, never
   a pass.
6. **Persist and verify.** The run must appear in the ledger and its run directory. If the
   store was degraded, confirm the outbox bundle and the `EVT-EVAL-*` warning.
   [`references/eval-store-and-dashboard.md`](references/eval-store-and-dashboard.md) has the
   exact paths and env vars.
7. **Update the counts other tests pin:** the shipped card count (9), golden-topic count (4),
   seeded-defect count (19), and deterministic-check count (24) in `testing/evals/` — all
   verified 2026-11-14.
8. **Update the docs** (`docs/specs/evals/spec.md` card table; `golden-sets.md` if a golden is
   added) and attach the run id + `eval_summary.md` to the PR using
   [`templates/eval-run-checklist.md`](templates/eval-run-checklist.md).

Live suites (`--suite full`, `calibrate` without `--mock`) are run in an authorised infra
window by the founder/infra owner, not by parallel agents: they spend model credits and use
the single-slot endpoint.

## Where results land

| Artifact | Path | Committed? |
|---|---|---|
| Run list (append-only) | `evals_runs/eval_runs_ledger.jsonl` | No (`/evals_runs/` is gitignored) |
| Run detail | `evals_runs/<eval_run_id>/eval_report.json` | No |
| Human summary | `evals_runs/<eval_run_id>/eval_summary.md` | No |
| Metrics | `evals_runs/<eval_run_id>/eval_metrics.prom` | No |
| Regression diff | `evals_runs/<eval_run_id>/eval_diff.json` (when computed) | No |
| Relational mirror | `eval_run`, `eval_card_result`, `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session` | No (DB) |
| Degraded-store bundle | `evals_runs/outbox/<eval_run_id>.tar.zst` or `.tar.gz` | No |
| PR evidence | run id + `eval_summary.md` + verdict | Yes |

The frontend/observability side has its own sinks: stdout always, `log_events` when
`ZIVON_LOG_DSN` is set, otherwise `runs/logs/YYYYMMDD-<component>.jsonl`.

## Worked example

[`references/worked-example.md`](references/worked-example.md) adds one event
(`factory.catalogue.written`), one card (`EV-SYN-003`), and one deterministic checker
(`check_golden_registration`), then runs both key-free. It records the observed run id, the
JSON line, the ledger row, and the run artifacts, plus the anti-pattern list. Use it as the
copy template; do not add its example card to the repo unless the failure mode is real.

## Definition of done

| Check | Command | Pass condition |
|---|---|---|
| Logging contract | `python -m unittest discover -s testing/observability -t .` | All pass, map rows resolve, row count updated |
| Eval smoke | `python -m evals run --suite smoke --mock` | PASS, 0 model calls |
| Regression gate | `python -m evals run --suite smoke --fail-on-regression` | Exit 0 |
| Eval unit tests | `python -m unittest discover -s testing/evals -t .` | All pass |
| Lint/format | `ruff check . && ruff format --check .` | Clean |
| Skill validator | `python3 scripts/check_skills.py --strict --bundle skills/zivon-evals-and-observability-skills` | Clean |
| Docs | the owning spec / card table / map | Updated in the same PR |
| Evidence | PR body | Run id, summary, event names, known debt |

## Anti-patterns (one-line versions)

- A `print()` or stdlib `logging` call pretending to be telemetry.
- An event with no map row, or a row with no real emitter.
- Logging learner text, prompts, answers, page HTML, audio, or secrets "for debugging".
- Inventing correlation IDs where no edge exists, or threading them through arguments.
- A failure logged as `INFO` with no `ErrorClass`.
- An eval card with no deterministic checker, a checker with no data that silently passes, or
  a smoke suite that makes a model call.
- A judge with a second rubric that drifts from the factory's.
- A golden edited in place to make a failing card pass.
- A run that exists only in terminal scrollback: no ledger row, no summary, no PR link.
- Weakening `testing/observability` or `testing/evals` assertions instead of fixing the call
  site.

The full list with consequences is in
[`references/worked-example.md`](references/worked-example.md).

## Reference map

| Read this | When |
|---|---|
| [`references/logging-manager.md`](references/logging-manager.md) | You need the exact `log_event` surface, component enum, severity/error class, correlation rules, redaction, or sinks |
| [`references/event-map.md`](references/event-map.md) | You are adding/editing an instrumentation-map row or fixing map-lint |
| [`references/eval-authoring.md`](references/eval-authoring.md) | You are writing a card, checker, golden, defect sample, or judge; deciding suite/mock/live; or reading a diff |
| [`references/eval-store-and-dashboard.md`](references/eval-store-and-dashboard.md) | You need to know where a run lands, how `EVT-EVAL-*` works, or what the dashboard can read today |
| [`references/privacy-and-redaction.md`](references/privacy-and-redaction.md) | Before writing any field, fixture, note, or kid-session payload |
| [`references/review-checklist.md`](references/review-checklist.md) | You are reviewing a logging/eval PR or self-reviewing before opening one |
| [`references/worked-example.md`](references/worked-example.md) | You want the executed example and the full anti-pattern list |

Templates: [`templates/instrumentation-row.csv`](templates/instrumentation-row.csv),
[`templates/eval-card.yaml`](templates/eval-card.yaml),
[`templates/checker.py`](templates/checker.py),
[`templates/eval-run-checklist.md`](templates/eval-run-checklist.md),
[`templates/golden-fixture.md`](templates/golden-fixture.md).

## Non-negotiables

- One emission point: `logging_manager.log_event`. One eval store: `EvalStore`. One curation
  front: the ledger + run directory + PR evidence (until ADM-10).
- A declared event and its row land in the same PR; a card and its checker/goldens land in the
  same PR; the run and its PR evidence land in the same PR.
- Smoke is always key-free. Live runs are authorised, not assumed.
- No secrets, no child PII, no page content, no transcripts in logs, fixtures, or eval
  artifacts.
- If the spec and the code disagree, stop and record the conflict; do not teach the drift as
  the contract.
