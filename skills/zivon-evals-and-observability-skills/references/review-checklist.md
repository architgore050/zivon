# Review checklist — accepting a logging or eval change

Use this with `skills/code-review/code-review/SKILL.md`. The severity scale is the repo's:
**blocker / major / minor / nit / question / praise**. Label evidence **confirmed** (you ran
or traced it), **likely** (strong reading), **suspected** (a hunch; phrase as a question).
Review top-down: design → correctness & privacy → tests → operability → docs → style.

## 1. First question: does the change need this at all?

| Change | Expected |
|---|---|
| New stage / route / job / button | Logged (map row + emission) |
| Prompt, rubric, schema, generator, renderer content rule | Evaluated (card + checker + goldens + smoke run) |
| Pure refactor with identical behaviour | Neither; ordinary tests only |
| Visual/style-only frontend change | Neither; maybe reuse an existing `EVT-Fxx` |
| New frontend interaction no `EVT-Fxx` covers | New map row + spec change; not a raw fetch |
| Bug fix in deterministic code | Test in `testing/`; no card |
| Bug fix in model behaviour | Existing card extended or new failure-mode card |

A missing artifact is a **major** when the change affects model quality or operability; a
**blocker** when it is privacy/security-relevant.

## 2. Logging checks

### Blocker

- Learner text, transcript, prompt, response, answer, page HTML, audio, or a secret appears in
  `fields`, a test fixture, or a doc example.
- An event is emitted outside `logging_manager.log_event` (print, stdlib logging, hand-built
  JSON, SQL into `log_events`).
- A redaction or retention test was weakened, skipped, or deleted to make the payload pass.
- A deletion path bypasses `delete_subject` or hides its failure.
- A new component/enum value was added without the `logging-api.md` spec change.

### Major

- An emitted event has no map row, or the row names an emitter that does not exist.
- The map row's severity, `error_class`, `latency_ms`, or privacy class contradicts the event's
  shape (failure at INFO, timing without `latency_ms`, L3 audit declared L1).
- Correlation is threaded through function arguments or invented where no edge exists.
- The map-conformance test list or row count was not updated.
- No evidence the event reaches a sink in a normal run (stdout / `runs/logs` / `log_events`).
- Frontend event added without the `EVT-Fxx` catalogue/ingest change.

### Minor

- A field is allowed but unnecessary (data minimisation).
- The map note is too vague for the next agent to know what the event measures.
- The event duplicates an existing one that could have been reused.

### Questions to ask

- Which dashboard view or query consumes this event? If none, is it "audit only" in the PR?
- Is the privacy class justified by the retention it selects?
- Does the event fire once per attempt (retry loops log one per attempt with `attempt`)?

### Commands

```bash
python -m unittest discover -s testing/observability -t .
ZIVON_RUNS_DIR=/tmp/zivon-review python - <<'PY'
from logging_manager import bind_context, log_event
bind_context(run_id="review-run")
log_event("<event>", {"<field>": 1})
PY
ls /tmp/zivon-review/logs/
```

## 3. Eval checks

### Blocker

- A judge uses a parallel rubric that can drift from the factory's
  (`reuses_prompt_from` missing or false).
- A golden or seeded defect was weakened/deleted to make a failing card pass.
- `smoke` makes a model call, or a key is required for the smoke gate.
- A run is claimed as evidence but has no ledger row / run directory / PR link.
- Eval artifacts contain child PII, raw audio, or a transcript.
- A new eval card ships while the five `EVT-EVAL-*` names still have no map rows (P-GAP-14).
- A live suite was run by an unauthorised agent (credit spend / endpoint contention).

### Major

- The card does not cover the new failure mode (only the old happy path).
- No deterministic checker, or a checker that returns `[]` for missing data and silently passes.
- `suites` includes `smoke` but the card has no checker; or the card needs a model in smoke.
- Goldens are not registered in `evals/goldens/manifest.json`; a new topic lacks one of the
  three required files.
- `cost_budget.smoke_model_calls` is not `0`, or the judge runs outside `full`/`calibrate`.
- The persistent counts in `testing/evals/` were not updated (cards 9, topics 4, defects 19,
  checks 24 — verify current values).
- The PR does not link the run id and `eval_summary.md`.
- The run used `--card` without `--mock`, so a judge was invoked during a "smoke" run.

### Minor

- The card title/description does not name the failure mode.
- The checker message does not identify the artifact path or block id.
- The summary omits the model/endpoint used or the baseline run id.

### Questions to ask

- What is the baseline, and what exactly improved or regressed?
- If the judge was calibrated, what are fatal recall and clean specificity on the seeded set?
- Did the run persist to the ledger and the run directory, or only to stdout?
- Is `pipeline_version` the real `factory/stages.py::PIPELINE_VERSION` or the hardcoded report
  value?

### Commands

```bash
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
python -m unittest discover -s testing/evals -t .
tail -1 evals_runs/eval_runs_ledger.jsonl
ls evals_runs/<eval_run_id>/
```

## 4. Cross-cutting checks

| Check | Pass condition |
|---|---|
| Secrets | No key, DSN, token, or `.env` value in code, fixtures, docs, or PR body |
| CI key-free | Smoke/tests pass with no model endpoint and no DB |
| Docs | The map, card table, golden set, or API doc is updated in the same PR |
| Scope | No unrelated refactor, no new dependency, no second logging/eval path |
| Error handling | Failures are surfaced (event + `error_class`), never swallowed |
| Reversibility | A bad event/card can be removed without a migration; store schema changes have a migration |

## 5. What not to block on

- Naming/taste when the name already follows `<component>.<subject>.<action>`.
- More telemetry than you personally would add, if it is map-declared, minimal, and has a
  consumer or an "audit only" note.
- A checker being strict about a real contract, if it does not produce false fatals.
- A card adding a second deterministic check where one would do — that is a nit, not a blocker.
- Formatting, import order, or type style that `ruff`/`mypy` already enforce.

## 6. Report template

```
## Review: <PR / branch>
**Verdict:** Approve | Approve with comments | Request changes
**Evidence reviewed:** diff, tests run, run id, map rows, docs
**Lenses:** implementation, tests, security, docs-sync, production-readiness

### Blockers
### Major
### Minor and nits
### Questions
### What's good
### Not reviewed / assumptions
```

Verdict rule: any blocker → request changes. Majors only → request changes unless they are
named follow-ups. Everything else → approve, with comments if worth reading.
