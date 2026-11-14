# Eval authoring — cards, checkers, goldens, judges

Sources: `docs/specs/evals/{README,spec,card-template,golden-sets}.md`,
`docs/backend/adr/0027-*` and `0028-*`, `evals/` (`models.py`, `runner.py`, `checkers/`,
`judges/`, `cli.py`, `config.py`, `diff.py`), `testing/evals/`. Verified 2026-11-14 at `main`
@ `57147bb`.

## 1. testing/ vs evals/ — the boundary

| | `testing/` | `evals/` |
|---|---|---|
| Question | Does the code do what it says? | Is the model output good enough? |
| Determinism | Must be 100% deterministic | Deterministic checkers first, then a calibrated judge |
| Network / model | Never | `smoke` never; `full`/`calibrate` do |
| Key-free | Always | `--mock` / `smoke` always |
| Failure means | A code defect | A quality regression or a rubric defect |
| Home | `testing/<area>/` | `evals/cards/`, `evals/checkers/`, `evals/goldens/`, `evals/judges/` |

A test that needs a model belongs in `evals/` as a judge. A checker that needs no model belongs
in `evals/checkers/` **and** is exercised by `testing/evals/`. Do not migrate deterministic
tests into evals just to raise a score.

## 2. The deterministic-first funnel (what the runner actually does)

`evals/runner.py::run_single_card`:

1. Runs every `deterministic_checks[]` entrypoint in order.
2. Applies the card's `severity_on_fail` floor to the issues the checker returned.
3. Counts `fatal`/`major`/`minor`; computes `deterministic_score = passed / evaluated`.
4. A checker that recorded `context["skipped_checks"][check_id]` is **not** counted as a pass
   and does not count toward `evaluated`. If no check was evaluated, the card verdict is
   `skip`, not `pass`.
5. The judge runs only when the card is not skipped, the deterministic checks did not fail,
   the suite is `full`/`calibrate` (or an explicit `--card` was passed), a judge exists, and a
   judge client exists.
6. Any deterministic failure (a fatal or major issue, or a below-1.0 pass rate) short-circuits
   the judge — no model call is spent on a broken artifact. Minor-only findings do not block it.

Consequences for card design:

- `suites` must include `smoke` iff the card has at least one deterministic checker. A card
  with only a judge never runs key-free and is not a PR gate.
- `cost_budget.smoke_model_calls` is `0` on every card. There is no exception.
- A checker must never return `[]` because it could not find data. Record a skip with a reason.

## 3. File locations

```
evals/
  cards/EV-<PREFIX>-<NNN>.yaml        one card per file
  checkers/<area>.py                  deterministic, 0 calls
  judges/<area>_judge.py              llm_manager-routed
  goldens/
    manifest.json                     registry + rotations
    topics/<slug>/                    expected.json, source_pack_meta.json, artifact_ref.json
    defects/<stage>/SD-*.json         seeded calibration samples
    profiles/weak-android.json        perf profile
  store.py                            dual-write persistence
  telemetry.py                        EVT-EVAL-* + Prometheus
  diff.py                             regression diff
  report.py                           report/summary/metrics writers
```

Tests: `testing/evals/test_models_and_goldens.py` (config, schemas, goldens, counts),
`test_checkers.py` (all shipped deterministic checks), `test_calibration_and_judges.py`
(judges + calibration), `test_store_diff_and_cli.py` (store, diff, CLI), `test_telemetry.py`
(event mapping + metrics).

## 4. Card anatomy and closed constraints

Required fields (`evals/models.py::EVAL_CARD_SCHEMA`): `card_id`, `version`, `title`, `stage`,
`agent_role`, `suites`, `golden_inputs`, `deterministic_checks`, `llm_judge`, `thresholds`,
`cost_budget`.

| Field | Constraint (2026-11-14) |
|---|---|
| `card_id` | `^EV-(CUR|SYN|VIS|PERF|REV|E2E|KID)-[0-9]{3}$` |
| `stage` | closed enum: `00-ingest..02-generate.ground_truth`, `02-generate.blocks..04-repair`, `02-generate.lesson..02-generate.blocks`, `05-interactive..06-render`, `07-perf..08-fixloop`, `03-check`, `09-review`, `00-ingest..11-link`, `post-11-link-gate-b` |
| `agent_role` | closed enum: `Curator`, `Synthesizer`, `Visual Builder`, `Performance Engineer`, `Comprehension & Fact Reviewer`, `Code Reviewer`, `End-to-End Pipeline`, `Kid-Comprehension Validator` |
| `suites` | non-empty subset of `smoke`, `full`, `calibrate` |
| `golden_inputs` | `topics` + `seeded_defects` + `source_catalog_ref`; optional `profiles` |
| `deterministic_checks` | min 1; each `{id: ^DET-[A-Z0-9-]+$, entrypoint, severity_on_fail, description, reuses_factory_rule?}` |
| `llm_judge` | object or null; if present, requires `enabled_in_suites`, `entrypoint`, `reuses_prompt_from`, `severity_ladder`, `way_out_rule` (exact const), and at least 2 anchor examples |
| `thresholds` | `deterministic_pass_rate_min: 1.0`, `fatal_issues_max: 0`, `major_issues_max`, `regression_drop_tolerance: 0.0`; calibration cards add recall/specificity floors |
| `cost_budget` | `smoke_model_calls: 0`, `full_model_calls_per_topic`, `calibration_model_calls_total`, `max_completion_tokens_per_call`, `call_deadline_s` |

`additionalProperties: false` everywhere. A typo fails at load time. A new prefix, stage, or role
is a schema extension in `evals/models.py` + `docs/specs/evals/card-template.md` +
`testing/evals/`, and is founder-gated (HANDSHAKE Q-5). Do not smuggle a new stage into a YAML
string.

## 5. Writing a deterministic checker

Entrypoint format is `module.path:callable_name`; the runner imports the module from
`sys.path`. Signature:

```python
def check_<name>(cfg: EvalConfig, card: EvalCard, context: dict[str, Any]) -> list[IssueRecord]:
    ...
```

Rules:

- Zero network, zero model, zero secrets. Pure function of artifacts + goldens.
- Reuse the factory rule: `factory.schemas:GENERATED`, `factory.checks:run_all_rules`,
  `factory.lint:lint_generated`, `factory.transcheck` rules. `reuses_factory_rule` names the
  real symbol; do not write a second implementation that will drift.
- Return `IssueRecord(severity=..., check_id=..., block_id=..., category=..., message=...)`.
  Severity is `fatal` / `major` / `minor` / `unverified`.
- If there is no data to grade, set
  `context.setdefault("skipped_checks", {})[check_id] = "reason"` and return `[]`. A skip is
  honest; a fabricated pass is how a broken pipeline reports `1.0`.
- Never raise for a data problem. Catch the parse error and return a `fatal` issue with the
  path and the problem.
- A checker that can produce a false fatal is a calibration bug, not a strictness virtue.

Start from [`../templates/checker.py`](../templates/checker.py). Add its unit test in
`testing/evals/`; `testing/evals/test_checkers.py` runs every shipped checker against the
shipped goldens and currently pins the total at `24`.

## 6. Goldens

### Topic golden

```
evals/goldens/topics/<slug>/
├── expected.json          invariants: structure bounds, required concepts, numerical anchors, perf
├── source_pack_meta.json  provenance of the source pack
└── artifact_ref.json      where the snapshot lives (never a full generated page in the golden)
```

`expected.json` is validated by `GOLDEN_EXPECTED_SCHEMA`: required `golden_id`, `topic_slug`,
`course_id`, `class_level`, `pipeline_version_min`, `source_provenance` (`matched_via` must be
`title_line`), `structure_bounds` (blocks 4–45), `required_concepts_and_equations`,
`canonical_numerical_anchors`, `visual_and_kit_invariants`, `perf_budgets`. Optional
`structure_bounds_note` explains a deviation.

Register the topic in `evals/goldens/manifest.json` (`golden_topics[]` with `golden_id`,
`directory`, `topic_slug`, `course_id`, `class_level`, `pipeline_version_min`, `status`).

Rotation (`python -m evals rotate-golden ...`) recomputes the SHA-256 and appends a `rotations[]`
audit entry to the manifest. Never mutate an `expected.json` in place without a recorded reason
and a version bump (see `docs/specs/evals/golden-sets.md` §4.2). A pipeline-version bump updates
the golden in the same PR; a prompt-only change usually does not rotate the golden.

### Seeded defect

```json
{
  "sample_id": "SD-CHK-009",
  "stage": "03-check",
  "origin_incident": "run 000509 b-21",
  "defect_class": "Wrong computed numerical answer",
  "planted_mutation": "b-21 claims a = -3.94 m/s2 and t = 8.9 s",
  "target_call": "03-check",
  "inputs": {"source_pack": {}, "ground_truth": {}, "lesson": {}, "blocks": {}},
  "expected": {
    "outcome_type": "positive_defect",
    "expected_verdict": "fail",
    "expected_severity": "fatal",
    "expected_category": "answer_key",
    "expected_block_id": "b-21",
    "must_quote_source": true,
    "expected_quote_substrings": ["m/s"]
  }
}
```

Samples are calibration inputs. Never weaken or delete one to hide a recall drop; only add or
update when the stage input schema itself changed shape.

## 7. Judges and calibration

- Route through `llm_manager` (`JudgeClient` / `EvalConfig.judge_llm_config()`), temperature
  `0.0`, no `max_tokens` from env, deadline from the card.
- Reuse the factory rubric **verbatim** (`factory.agents:run_check`, `factory.review` facts and
  design procedures). `reuses_prompt_from` names the symbol; a parallel rubric is a blocker.
- Include fatal/major/minor anchors drawn from real run forensics, the exact `way_out_rule`
  ("Report unverifiable suspicions as severity='minor' with message starting 'unverified:' —
  never as fatal or major."), and a bounded procedure.
- Calibrate on the seeded defects (`EV-REV-001` for `03-check`, `EV-REV-002` for `09-review`):
  report fatal recall and clean specificity. `python -m evals calibrate --stage all --mock` is
  the key-free form; the live form is run in the authorised infra window.
- A prompt/rubric change without a calibration run is not reviewable. A recall drop is a
  regression, not a "strictness improvement".

## 8. Suites, commands, mock vs live

| Command | Network / model | What it runs |
|---|---|---|
| `python -m evals run --suite smoke --mock` | none | deterministic checkers on goldens; fake judge only if `--card` forces it |
| `python -m evals run --suite smoke --fail-on-regression` | none | CI merge gate; exit `2` on regression |
| `python -m evals run --suite full` | model endpoint | checkers + judges |
| `python -m evals run --card EV-SYN-001 --topic <slug> --mock` | none with `--mock` | one card, one topic |
| `python -m evals calibrate --stage {03-check,09-review,all} --mock` | none | seeded-defect calibration |
| `python -m evals calibrate --stage all` | model endpoint | live calibration |
| `python -m evals diff --prev <id> --curr <id>` | none | regression diff; exit `2` on regression |
| `python -m evals record-edit ...` | none | human edit rate (`EV-E2E-001`) |
| `python -m evals record-kid-test ...` | none | DPDP-validated kid session (`EV-KID-001`) |
| `python -m evals report --run <id>` | none | render an existing run |
| `python -m evals rotate-golden ...` | none | golden digest rotation |
| `python -m evals backfill-db` | DB | replay the JSONL ledger into the relational store |

Gotcha: `--card` sets `execute_judge=True` even in `smoke` (the runner's condition is
`suite in ("full","calibrate") or card_id is not None`). Always pass `--mock` for a key-free
single-card run.

Live suites are **authorised, not assumed**. They spend credits and use the single-slot model
endpoint; the founder/infra owner runs them in the infra window. Parallel agents build schemas,
checkers, and fixtures key-free until then.

## 9. Regression diffs

`evals/diff.py` compares a current run with the most recent same-suite run in the ledger:

- any card `pass` → `fail` is blocking;
- a `fatal_recall` drop > 0.0 is blocking;
- a `blocking_recall` drop > 0.05 is blocking;
- `EV-PERF-001` p95 frame time up > 15% or long tasks up > 0 is blocking;
- a `human_edit_rate_rolling` increase > 0.05 is blocking;
- card `regression_drop_tolerance` is applied;
- a `skip` card means "not measured", not "scored 0", and is excluded from metric diffs;
- exit code `2` when `regression_detected`.

A deliberate baseline change is stated in the PR with the reason and the new expected values.
"It was already failing" is not a baseline.

## 10. Counts other tests pin (update them in the same PR)

Verified 2026-11-14:

| Test | Pinned value | When it changes |
|---|---|---|
| `testing/evals/test_models_and_goldens.py::test_all_nine_eval_cards_load_and_validate_schema` | 9 cards, exact id set | new/removed card |
| `...::test_all_golden_topics_and_seeded_defects_validate_schemas` | 4 golden topics, 19 defect files | new golden/defect |
| `testing/evals/test_checkers.py::test_all_card_deterministic_checks_pass_on_shipped_goldens` | 24 executed deterministic checks | new/removed checker |
| `testing/observability/test_events.py` map parse | 73 rows | new/removed event row |

If you add a card, checker, golden, or event and these counts fail, fix the counts **and**
explain why in the PR. Do not delete the assertion.

## 11. Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Card exists but no checker | Never runs key-free; smoke cannot gate it | Add a deterministic checker or move the card to `full` only |
| Checker returns `[]` on missing data | Card reports PASS with nothing measured | Record a skip reason |
| Checker re-implements a factory rule | Drift; the gate and the eval disagree | Import the factory rule and name it in `reuses_factory_rule` |
| Judge rubric copied into `evals/judges/` | Two rubrics, two truths | Reuse the factory symbol; `reuses_prompt_from` proves it |
| `smoke` card performs a model call | CI spends credits / fails key-free | `smoke_model_calls: 0`; judge only in `full`/`calibrate` |
| Golden edited to make a failing card pass | Baseline loss; false green | Rotate with a reason; fix the artifact or the checker |
| Run not persisted | Not evidence | `EvalStore.persist_run` must have run; check the ledger |
| `--card` run without `--mock` | Judge is invoked in smoke | Add `--mock` |
| Counts not updated | CI red | Update the pinned counts above |
