# Worked example — one event, one card, one checker (executed key-free)

Evidence date: **2026-11-14**. Base: `main` @ `57147bb`. The commands below were run in
`/tmp/opencode/evals-obs-demo` with `ZIVON_EVAL_CARDS_DIR`, `ZIVON_EVAL_RUNS_DIR`,
`ZIVON_RUNS_DIR`, `ZIVON_INSTRUMENTATION_MAP`, and `PYTHONPATH` pointed at temporary copies.
**No tracked file was changed.** The numbers and ids are real observations, not a mock-up.

Scenario: stage `11-link` has just written a catalogue manifest. It has no event, so an
operator cannot tell whether the catalogue write happened or how long it took. The change is
both logging (a new event) and evaluating (a tiny contract card that proves the card's goldens
are registered).

## Part A — add `factory.catalogue.written`

### A1. Map row

Append one line to `docs/specs/observability/instrumentation-map.csv`:

```csv
factory,factory.catalogue.written,INFO,run_id,topics_count;locales_count,yes,,L1,factory/link.py,11-link regenerated courses.js; duration is the write time
```

Why each column: `factory` is the closed component; `INFO` is normal progress; `run_id` is the
only correlation a build-time publish has; both counts are required by the consumer;
`latency_ms=yes` because the event measures the write; no `error_class` because it is not a
failure; L1 because it is build-time diagnostic data; the emitter is the real module.

### A2. Emission

```python
# factory/link.py, at the end of run()
log_event(
    "factory.catalogue.written",
    {"topics_count": len(entries), "locales_count": len(locales)},
    stage="11-link",
    latency_ms=int(elapsed * 1000),
)
```

No `run_id` argument: the pipeline binds it once at the edge (`bind_context(run_id=...)`). No
content, no page text, no paths beyond the counts.

### A3. Test update

In `testing/observability/test_events.py`:

```python
EMITTED_BY_THIS_BRANCH = [
    ...
    "factory.catalogue.written",
]
```

and bump the row count in
`MapParsingTests.test_map_parses_rfc4180_with_consistent_columns` from `73` to `74` (verify
`wc -l` minus the header; it was 73 on 2026-11-14). Run:

```bash
python -m unittest discover -s testing/observability -t .
```

### A4. Observe it

```bash
ZIVON_INSTRUMENTATION_MAP="$DEMO/instrumentation-map-plus.csv" \
ZIVON_RUNS_DIR="$DEMO/runs" python3 - <<'PY'
from logging_manager import bind_context, log_event
bind_context(run_id="demo-catalogue-run")
log_event("factory.catalogue.written",
          {"topics_count": 7, "locales_count": 3},
          stage="11-link", latency_ms=12)
PY
cat "$DEMO"/runs/logs/*-factory.jsonl
```

Observed JSONL (one line, fixed field order):

```json
{"ts":"2026-11-14T07:56:53.540Z","schema_version":1,"severity":"INFO","event":"factory.catalogue.written","component":"factory","env":"dev","run_id":"demo-catalogue-run","stage":"11-link","latency_ms":12,"fields":{"topics_count":7,"locales_count":3}}
```

The first line on stdout is the same event. Because no `ZIVON_LOG_DSN` was set, the module also
emitted `log.store_fallback` (WARNING, `store_error`, `target_path`), then wrote the JSONL file.

Control: emit a name with no row and the module delivers it with component `log` and emits
`log.event_unknown`:

```json
{"event":"factory.catalogue.unmapped","component":"log","fields":{"topics_count":7}}
{"event":"log.event_unknown","severity":"WARNING","component":"log","fields":{"offender_event":"factory.catalogue.unmapped"}}
```

That is the difference between "it printed" and "it is logged".

## Part B — add `EV-SYN-003` and `check_golden_registration`

### B1. Checker

Copy `templates/checker.py` to `evals/checkers/example_checks.py` (or your area module) and
rename the function. The template's `check_golden_registration` is a real invariant: every
topic the card names must exist with `expected.json`, `source_pack_meta.json`, and
`artifact_ref.json`, and `expected.json` must have coherent `blocks_min`/`blocks_max`.

```python
from typing import Any

from evals.config import EvalConfig
from evals.models import EvalCard, IssueRecord

CHECK_ID = "DET-SYN03-GOLDEN-REGISTERED"


def check_golden_registration(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]: ...
```

If the card has no topics, it records
`context["skipped_checks"][CHECK_ID] = "card declares no golden topics"` and returns `[]` —
never a silent pass.

### B2. Card

```yaml
card_id: EV-SYN-003
version: 1
title: "Golden registration contract for a new card"
stage: "02-generate.blocks..04-repair"
agent_role: "Synthesizer"
suites: [smoke]
golden_inputs:
  topics: ["evals/goldens/topics/class-9-motion"]
  seeded_defects: []
  source_catalog_ref: "sources/catalog.json"
deterministic_checks:
  - id: DET-SYN03-GOLDEN-REGISTERED
    entrypoint: "example_checks:check_golden_registration"
    severity_on_fail: fatal
    reuses_factory_rule: null
    description: "Every topic the card names exists with its three golden files."
llm_judge: null
thresholds:
  deterministic_pass_rate_min: 1.0
  fatal_issues_max: 0
  major_issues_max: 0
  regression_drop_tolerance: 0.0
cost_budget:
  smoke_model_calls: 0
  full_model_calls_per_topic: 0
  calibration_model_calls_total: 0
  max_completion_tokens_per_call: 35000
  call_deadline_s: 1800
```

Why this shape: one deterministic check and no judge, so the card runs in `smoke` with zero
model calls; `llm_judge: null` is honest (there is nothing a model adds to a file-existence
contract); every threshold is the schema's floor.

### B3. Run it key-free

```bash
PYTHONPATH="$DEMO/checks" \
ZIVON_EVAL_CARDS_DIR="$DEMO/cards" \
ZIVON_EVAL_RUNS_DIR="$DEMO/evals_runs" \
ZIVON_RUNS_DIR="$DEMO/runs" \
ZIVON_INSTRUMENTATION_MAP="$DEMO/instrumentation-map-plus.csv" \
python3 -m evals run --suite smoke --mock --card EV-SYN-003
```

Observed:

```text
# Zivon Eval Report — `eval-smoke-20261114T075701Z-57147bb-368025`
- **Suite:** `smoke`
- **Overall Verdict:** `PASS`
- **Models:** generator=`unconfigured` | judge=`unconfigured`
- **Window:** `2026-11-14T07:57:01Z` -> `2026-11-14T07:57:01Z` (`0.02 s`)

| Card ID | Stage | Verdict | Det. Score | Judge Score | Fatal | Major | Calls |
| `EV-SYN-003` | `02-generate.blocks..04-repair` | **PASS** | `1.0000` | `n/a` | `0` | `0` | `0` |
```

The negative control (a card pointing at `evals/goldens/topics/does-not-exist`) produced
`eval-smoke-20261114T075707Z-57147bb-ce3627`, verdict `FAIL`, deterministic score `0.0000`,
one fatal:

```text
| `EV-SYN-004` | `DET-SYN03-GOLDEN-REGISTERED` | `fatal` | `-` | golden topic directory is missing: evals/goldens/topics/does-not-exist |
```

That is the point of the funnel: the contract fails in code before any judge is considered.

## Part C — where the results landed

`$DEMO/evals_runs/eval_runs_ledger.jsonl` (last row, abbreviated):

```json
{"eval_run_id":"eval-smoke-20261114T075701Z-57147bb-368025","suite":"smoke","overall_pass":true,"summary":{"cards_total":1,"cards_passed":1,"cards_failed":0,"cards_skipped":0,"model_calls_total":0,"total_thinking_s":0.0,"human_edit_rate_rolling":null,"gate_b_comprehension_rate":null},"git_sha":"57147bbbc142","generator_model":"unconfigured","judge_model":"unconfigured", ...}
```

`$DEMO/evals_runs/eval-smoke-20261114T075701Z-57147bb-368025/`:

```text
eval_report.json
eval_summary.md
eval_metrics.prom
```

The run also emitted `EVT-EVAL-RUN-STARTED` and `EVT-EVAL-RUN-COMPLETED`. In the observed run
they arrived with `component:"log"` and each produced `log.event_unknown`, because the five
`factory.eval.*` names still have no instrumentation-map rows (P-GAP-14). That is the honest
state on 2026-11-14; the fix is in `references/eval-store-and-dashboard.md` §4. Do not present
the run as fully curated until those rows exist.

### PR evidence block

```markdown
## Logging
- Event: `factory.catalogue.written`; map row added; emitter `factory/link.py`
- `python -m unittest discover -s testing/observability -t .` -> N/N OK
- Observed: one JSON line in `runs/logs/YYYYMMDD-factory.jsonl`; stdout line identical

## Evals
- Card: `EV-SYN-003`; checker `DET-SYN03-GOLDEN-REGISTERED`
- Run id: `eval-smoke-20261114T075701Z-57147bb-368025`; suite `smoke`; verdict PASS; 0 model calls
- Regression: `python -m evals run --suite smoke --fail-on-regression` -> clean
- Artifacts: `eval_report.json`, `eval_summary.md`, `eval_metrics.prom`
- Known debt: `EVT-EVAL-*` map rows still pending (P-GAP-14)
```

## Part D — anti-patterns (with the consequence)

### Logging

1. **`print()` / stdlib `logging` as telemetry.** No correlation, no redaction, no retention,
   no dashboard query. The event is invisible to every consumer.
2. **An event with no map row.** `log.event_unknown` on every emit; map-lint red; the dashboard
   groups it under `log`.
3. **A row with no emitter.** The next agent trusts a contract that never fires.
4. **Learner text, prompts, answers, page HTML, audio, or secrets in `fields`.** Redaction
   fires, a `privacy_violation` audit event is written, and the PR is blocked. The harness
   scrubs the value, but the call site is still wrong.
5. **Inventing `run_id`/`session_id`/`turn_id`.** False joins; dashboards show activity that
   did not happen; incident timelines lie.
6. **Threading IDs through function arguments.** The context is the mechanism; arguments
   duplicate it and drift.
7. **Logging around a failure** (swallow → `INFO`). The failure disappears from the error feed
   and the SLO; the catcher cannot be debugged.
8. **Overriding `severity=`** because the message feels worse. The map is the contract; change
   the row if the severity is genuinely wrong.
9. **A new component name** without `logging-api.md` §8. The closed enum becomes folklore.
10. **A test that asserts a string was passed** rather than that the event resolves, serializes,
    and redacts. It proves the call exists, not that it is correct.
11. **Row count not updated.** `testing/observability` fails; the next agent spends an hour
    finding the `len(rows) == 73` assertion.
12. **Writing the JSONL fallback by hand.** It is the sync source; a hand-written line can
    violate the schema and break the daily ingest.

### Evals

13. **A card with no deterministic checker.** It cannot run key-free, so it is not a PR gate;
    the "eval" is a full-suite-only opinion.
14. **A checker that returns `[]` when it cannot find data.** The card reports `PASS` with
    nothing measured. Record a skip reason instead.
15. **A checker that re-implements a factory rule.** The gate and the eval drift; a rule fix
    lands in one and not the other.
16. **A judge with a second rubric.** Two truths; calibration becomes meaningless. Reuse the
    factory symbol and prove it with `reuses_prompt_from`.
17. **A judge without anchors or a way out.** It manufactures fatal findings or cannot say
    "unverified". The `unverified:` minor is mandatory.
18. **A smoke card that makes a model call.** CI spends credits, fails key-free, and the suite
    is no longer a merge gate.
19. **Editing a golden or seeded defect to make a failing card pass.** The baseline is lost and
    the next regression is invisible.
20. **A run that exists only in terminal scrollback.** No ledger row, no summary, no PR link:
    not evidence.
21. **`--card` without `--mock`.** The runner forces the judge path for an explicit card, so a
    "smoke" run calls the model. Add `--mock`.
22. **Deleting a test assertion instead of fixing the call site.** The counts in
    `testing/evals/` and `testing/observability/` are the contract; update them only for a real
    addition/removal and say why.
23. **Reporting a skip as a pass.** A skipped card means "not measured"; the report and the
    dashboard must say so.
24. **Using the hardcoded `pipeline_version=1` in the report as truth.** Read
    `factory/stages.py::PIPELINE_VERSION` and record the real value.
25. **Pasting a child quote into a golden, a defect, or a PR comment.** Goldens are build-time;
    kid sessions are pseudonymous and PII-validated. No exceptions.

## What the real repo change would look like

A real PR for this scenario would contain:

```text
docs/specs/observability/instrumentation-map.csv          +1 row
factory/link.py                                          +1 log_event call
testing/observability/test_events.py                     +1 name, row count 73 -> 74
evals/cards/EV-SYN-003.yaml                              new card
evals/checkers/example_checks.py                         new checker
testing/evals/test_checkers.py                           +1 check (total 24 -> 25)
testing/evals/test_models_and_goldens.py                 card count 9 -> 10 (rename the test too)
docs/specs/evals/spec.md                                 card table row
```

The worked example did **not** apply these changes: it ran against temp copies so the skill
could be tested without perturbing the repo's baseline. The real change still needs the
authorised review and, if a judge is involved, an infra-window calibration run.
