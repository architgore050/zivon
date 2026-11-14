# Quality and evals

The factory has two quality systems that must not be confused:

- **`testing/`** — deterministic code tests: schemas, rules, lints, resume,
  render, mock-server orchestration, static shell contracts. They pass 100%
  key-free and offline.
- **`evals/`** — model and prompt quality: golden topics, seeded defects,
  deterministic checkers, calibrated judges, regression diffs, human edit rate,
  and kid-comprehension sessions. They answer "does the page teach well?", not
  "does the code run?".

The separation is binary (`docs/specs/evals/spec.md` §1). A test that needs a
real model is an eval judge; an eval that needs no model is a checker exercised
by `testing/evals/`.

Dated **2026-11-14**; the eval schema is still closed (see §9).

## 1. The quality bar

A generated page is acceptable only when all of these hold:

| Dimension | What it means | Enforced by |
|---|---|---|
| **Grounded** | Every factual block cites ground-truth claim ids; no concept the source chapter does not teach; no invented numbers in problems/questions | `rule_citations`, `rule_numbers`, `03-check` reviewer |
| **Complete** | Every titled section, in-text question, worked example, and exercise type appears; repeats may fold | Coverage contract + `03-check` fatal omissions + `04-repair` |
| **Teachable** | Teach-before-test ordering, worked steps, glossary, plain English for the class level | `03-check` reviewer + lesson schema |
| **Mechanically safe** | Lint clean, CSP clean, no external calls, no `eval`, accessible names/roles, no overflow | `factory/lint.py`, `06-render`, `07-perf`, `09-review` |
| **Localizable** | `data-i18n` complete; glossary/UI strings present; no silent English pretending to be Hindi; a visible "not available yet" marker | `10b-transcheck` `R1`-`R9` + reviewer, `10d-transrender` |
| **Narratable** | Speakable rules hold: no answers in check narration, no JS code, no SVG labels beyond `svg_texts` | `factory/narration/select.py`, stage 12 |

Content-quality debt (wording, thin explanation, awkward translation) is
**recorded, not blocking**, except where it breaks the technical gate. The
founder's R1 rule allows the one-shot v1 base batch to publish on technical
gates alone with debt logged (FEATURE-MAP #14). That is a launch rule, not a
license to ignore a measured defect class: log it, link the evidence, and put
the fix on the timeline.

## 2. What is gated automatically today

| Layer | Check | Failure behavior |
|---|---|---|
| Content shape/semantics | `factory/checks.py` rules | fatal/major issues in `02`/`03`; route to `04` |
| Generated code | `factory/lint.py` | `LintError` at authoring sites (`05`, `06`, `08`, `10`) |
| Page performance | `factory/perf.py` + Chromium harness | topic miss → `08`; landing/shared miss → stop |
| Code/design/accessibility | `09-review` model calls + static findings | fail → `10-reviewfix` |
| Translation | `10b` rules + reviewer | fatal/major → `10c`; optional locale may fall back |
| Narration | speakable selection + TTS/encode | per-block repair, then degrade |
| Shell/site contracts | `testing/frontend/` | CI test failure |
| Catalogue/link | `factory/link.py` smoke test | `StageError` |

Not gated automatically today (confirmed 2026-11-14):

- **No axe/ARIA assertion.** Accessibility depends on the `09-design` model's
  attention; every run tends to show a couple of accessibility findings.
- **No deterministic numeric/unit recomputation.** The reviewer recomputes; a
  wrong answer is caught by a model, not code.
- **No JS-byte budget enforcement.** The stated lesson-JS budget is already
  exceeded by the current shell + i18n bundles; the perf profile measures
  load/FCP/RSS/FPS, not a per-family byte cap.
- **No i18n completeness sweep before translate.** `data-i18n` completeness is
  checked late, on localized routes.
- **No version-homogeneity guard.** The live tree can mix pipeline versions.

## 3. Deterministic checks vs model review

Use the decision rule from `skills/prompting-and-agent-design/`:

- If a requirement must hold every time and code can decide it, it is a
  **deterministic check** (`factory/checks.py`, `factory/lint.py`,
  `factory/transcheck.py`, schema validation).
- If it needs judgement, it is a **reviewer** with the material and a
  calibrated rubric (`03-check`, `09-review`, `10b` reviewer).
- If it is a measurement of model/prompt quality that needs a model, it is an
  **eval card/judge**, never a unit test.
- If it is a measurement that needs no model (schema, lints, perf, DOM), it is
  a **deterministic checker** under `evals/checkers/`, exercised by
  `testing/evals/`.

A checker failure short-circuits the judge. That is the deterministic-first
funnel: cheap, objective checks run first; the expensive judge sees only
artifacts that survived.

## 4. The eval cards

| Card | Stage(s) | What it measures |
|---|---|---|
| `EV-CUR-001` | `00`, `01`, `02.ground_truth` | Source provenance, title matching, citation integrity, no smuggled priors |
| `EV-SYN-001` | `02.blocks`, `04` | Block schema, 4-45 budget, ordering, computed-geometry routing, coverage |
| `EV-SYN-002` | `02.lesson`, `02.blocks` | Pedagogy, teach-before-test, self-containment, answer keys, readability structure |
| `EV-VIS-001` | `05`, `06` | Renderability, kit scope, a11y invariants, computed sim loops, visual doctrine |
| `EV-PERF-001` | `07`, `08` | Weak-Android budget + fixloop pedagogy preservation |
| `EV-REV-001` | `03-check` | Reviewer calibration on 8 seeded/clean samples: fatal recall, clean specificity |
| `EV-REV-002` | `09-review` | Part A: 5 deterministic security/scope defects; Part B: 6 truth/render samples |
| `EV-E2E-001` | `00`→`11` | End-to-end quality, catcher convergence, thinking efficiency, human edit rate |
| `EV-KID-001` | Post-`11` | Gate B kid-comprehension sessions, defect promotion |

Cards live in `evals/cards/EV-*.yaml`. Goldens:

- `evals/goldens/topics/<slug>/` with `expected.json` invariants (required
  sections, minimum counts, block types, language requirements, perf budgets).
- `evals/goldens/defects/03-check/SD-CHK-001..008.json` — 5 planted defects,
  1 unverifiable-minor hedge, 2 clean goldens.
- `evals/goldens/defects/09-review/SD-SEC-001..005.json` (deterministic) and
  `SD-REV-001..006.json` (5 planted + 1 clean).
- `evals/goldens/manifest.json` registers topics and compatibility.

## 5. Which eval to add

| Your change | Add/update |
|---|---|
| `02-generate` prompt, coverage, block shape, computed-geometry routing | `EV-SYN-001`/`002` checker + a golden/`expected.json`; judge only for a new judgement class |
| Ground-truth/citation/matching behavior | `EV-CUR-001` checker or judge |
| `03-check` or `09-review` rubric, severity, category | `EV-REV-001`/`002`; add a seeded defect and re-calibrate |
| `05`/`06` rendered code, kit scope, a11y invariants | `EV-VIS-001` checker; add a static DOM probe |
| `07`/`08` perf or fixloop behavior | `EV-PERF-001` profile/checker |
| Full-pipeline reliability, catcher convergence, edit rate | `EV-E2E-001` metrics |
| Kid comprehension / Gate B | `EV-KID-001` session schema |
| A new stage (assessment/exam/series) | **Blocked by the closed card schema** (see §9); land the additive enum extension first |

If no existing card can express the new failure mode, say so in the PR and
name the schema change needed. Do not bend an unrelated card.

## 6. Key-free commands

Run from the repo root:

```bash
# deterministic code tests (all key-free, offline)
python -m unittest discover -s testing/content_factory/unit -t .
python -m unittest discover -s testing/content_factory/integration -t .
python -m unittest discover -s testing/evals -t .
python -m unittest discover -s testing/frontend -t .        # needs Playwright Chromium
python -m unittest discover -s testing/translation -t .
python -m unittest discover -s testing/narration -t .       # needs ffmpeg
python -m unittest discover -s testing/observability -t .

# eval smoke: deterministic checkers + fake judge, zero model calls
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression     # CI form; exits 2 on regression

# reviewer calibration, mocked (seeded defects, zero model calls)
python -m evals calibrate --stage all --mock

# explicit run comparison (no network)
python -m evals diff --prev <baseline_id> --curr <current_id>
```

Live forms (`--suite full`, `calibrate` without `--mock`, any pipeline run with
model stages) use the configured endpoint, spend credits, and are run in the
infra window by the founder/infra owner, not by parallel agents. See
[commands.md](commands.md) for the full matrix.

## 7. Adding an eval card, checker, or golden

1. **Confirm the stage is in the schema enum** (`evals/models.py`). The card id
   pattern and stage/role enums are closed; an assessment/exam/series card
   needs the additive extension in `evals/models.py`,
   `docs/specs/evals/card-template.md`, and `testing/evals/`.
2. **Write `evals/cards/EV-<PREFIX>-<NNN>.yaml`** from
   `docs/specs/evals/card-template.md`: stage, role, golden inputs,
   deterministic checks, judge (if any), thresholds, cost budget.
3. **Add the deterministic checker** in `evals/checkers/<area>.py`. Reuse
   factory rules (`factory.schemas:GENERATED`, `factory.checks:run_all_rules`,
   `factory.lint:lint_generated`, `factory.transcheck` rules); do not fork the
   logic. Return stable `check_id` + severity.
4. **Add/extend goldens** under `evals/goldens/` and register them in
   `evals/goldens/manifest.json`. An `expected.json` is an invariant contract,
   not a byte snapshot; never mutate it in place without a recorded version.
5. **If a judge is added:** route it through `llm_manager`, temperature 0.0, no
   `max_tokens` from env; reuse the factory rubric verbatim; add anchor
   examples, a severity ladder, an `unverified:` way out, and a bounded
   procedure. Extend the calibration stage enum if needed and run
   `python -m evals calibrate --stage <stage> --mock`.
6. **Run** the eval tests and smoke:
   ```bash
   python -m unittest discover -s testing/evals -t .
   python -m evals run --suite smoke --mock
   python -m evals run --suite smoke --fail-on-regression
   ```
7. **Persist and link.** `EvalStore.persist_run()` writes
   `evals_runs/eval_runs_ledger.jsonl` + `evals_runs/<id>/eval_report.json`;
   `write_run_artifacts` writes `eval_summary.md` + `eval_metrics.prom`. The PR
   links the run id and summary. A terminal scrollback is not evidence.
8. **Update the spec** (`docs/specs/evals/spec.md` card table) and, for a new
   golden, `docs/specs/evals/golden-sets.md`.
9. **Emit `EVT-EVAL-*` via `evals/telemetry.emit_eval_event`**, not
   `log_event` directly. See the known gap: the map rows are missing, so this
   is currently a Wave-1 fix before new cards land.

## 8. Reading an eval run

| Need | Read |
|---|---|
| List of runs | `evals_runs/eval_runs_ledger.jsonl` |
| Per-card detail | `evals_runs/<eval_run_id>/eval_report.json` |
| Human summary | `eval_summary.md` |
| Metrics | `eval_metrics.prom` |
| Diff vs baseline | `eval_diff.json` / `python -m evals diff` |
| Relational mirror | `eval_run`, `eval_card_result`, `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session` when a DB URL is set |
| Raw reviewer behavior | the run's card `metrics`/`issues`, plus the factory run's `issues_ledger.jsonl` |

A run is "logged" only when the ledger row, the run directory
(`eval_report.json`, `eval_summary.md`, `eval_metrics.prom`), the relational
mirror or outbox bundle, the declared telemetry events, and the PR link all
exist. Otherwise it is a local experiment.

## 9. Known eval/quality gaps

These are dated observations local to this bundle, not rows in the repo's gap
register (`docs/specs/gaps/gap-register.md`, `GAP-###`). Re-verify each against
the code before treating it as open:

- **Closed card schema:** ids are
  `EV-(CUR|SYN|VIS|PERF|REV|E2E|KID)-NNN`; stage and role enums are fixed.
  Assessment/exam/series cards cannot be added until the additive extension
  lands.
- **Eval telemetry undeclared:** `EVT-EVAL-*` maps to
  `factory.eval.*` but the instrumentation map has zero rows and the shim uses
  `component="evals"`, outside the closed enum. Fix the map/component before
  adding cards.
- **Version drift:** `evals/runner.py` hardcodes
  `pipeline_version=1`; the goldens manifest says 7; actual is 9. A diff across
  versions is not trustworthy until this is fixed.
- **No a11y gate:** no axe/ARIA assertion; accessibility depends
  on the model reviewer. A deterministic a11y probe is the highest-value
  checker to add.
- **No deterministic numeric recompute:** a wrong answer is
  model-caught only.
- **`03-check` has no category:** its issues are tagged `content` at the call
  site, so cross-run analysis cannot separate answer-key, fact, and
  coverage failures.
- **No JS-byte budget:** the current lesson JS (~103-125 KB gzip)
  exceeds the stated 60 KB budget before new features. The budget definition is
  an open founder question; do not enforce a number that the current site
  already fails.
- **Human edit rate capture is specified, not complete:** the manifest
  `generation_fingerprints` are not emitted; `record-edit` compares run output
  to published files and is the current capture path.

## 10. Accessibility and performance

- **Target:** WCAG 2.2 AA for lesson surfaces (keyboard operability, names and
  roles, contrast, reflow at 320 CSS px equivalent, focus visible, status
  messages). WCAG 2.2 is the current W3C Recommendation (12 December 2024).
- **Current checks:** static shell contracts in `testing/frontend/`, a11y
  findings from `09-review-design`, perf from `07-perf` / `EV-PERF-001`.
- **Before calling an a11y change done:** run axe on the surface, walk the
  keyboard path, check 360 px overflow, and add a static assertion for whatever
  can be checked without a browser. A model finding is evidence, not a gate.
- **Perf budgets are profile data,** not prose. `weak-android.json` currently
  gates 750 MB peak RSS, 24 fps floor, 6.0 s load, 3.5 s FCP, 360 px overflow,
  zero console errors, under 4x CPU throttle and 2 cores. The Phase-4 target is
  stricter; tightening is a measured change, not a comment.

## 11. The content lens for a pipeline PR

Review a content-factory change with these questions in order:

1. **Grounding:** can every factual block still be traced to a claim and a
   source? Did the change add a concept the chapter does not teach?
2. **Coverage:** did the change remove a section/exercise type, or make the
   block budget contradict the coverage contract?
3. **Pedagogy:** is anything tested before it is taught? Are worked steps
   complete? Is the reading level still class-appropriate?
4. **Render integrity:** did block ids, CSP, self-containment, SVG rules,
   simulation skeletons, or `page.css` scope survive?
5. **i18n:** are new visible strings in the i18n path? Does a missing
   translation show a marker instead of English?
6. **Narration:** is the new text speakable under the selection rules? Does a
   check still avoid speaking its answer?
7. **Evidence:** is there a before/after artifact or golden diff, and does the
   PR state what is still debt?

## 12. Anti-patterns

- Putting a model-quality assertion in `testing/` because it is convenient.
- A judge with a rubric that has drifted from the factory gate it evaluates.
- A card with no golden, or a golden that is not registered.
- A `--mock` smoke run presented as a quality result; mock is a plumbing check.
- Editing a seeded defect/clean golden to make a reviewer pass.
- Treating a skipped browser/ffmpeg test as a pass.
- Adding a card while `EVT-EVAL-*` is undeclared; the run will not be in the
  curation front.
- Enforcing a JS-byte budget the current shell already fails without a founder
  decision on what the budget counts.
- Calling content-quality debt "fine" without logging it and linking evidence.
