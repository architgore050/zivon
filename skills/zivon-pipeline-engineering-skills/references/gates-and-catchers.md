# Gates and catchers

The factory's failure contract: **a gate's finding is a structured handoff to
its paired fixer, inside the same run.** This file explains the pairs, the
severity ladder, the progress-aware loop, and the safe way to add a gate.

Source of truth: `factory/stages.py` (routing and loops),
`factory/checks.py` (deterministic content rules), `factory/lint.py` (hard
code lints), `factory/review.py` (two review calls),
`factory/transcheck.py` (translation rules), `factory/narration/stage.py`
(narration repair), and `docs/content-factory/architecture.md` (failure
semantics). Dated **2026-11-14**.

## 1. The one rule

> A gate failure routes to **its** catcher, inside the same run. A downstream
> failure never re-runs an upstream stage, and a run process never dies just
> because a gate complained.

Why this is non-negotiable:

- **Cost.** `02-generate` is one giant thinking call; re-deriving it because a
  later gate found a defect re-buys the most expensive work in the pipeline.
- **Evidence.** The repaired draft and the round history are the record of
  what the gate caught. `--fresh` destroys that record.
- **Correctness.** A repair is scoped to the finding; a regeneration changes
  everything, including things that already passed.
- **The cluster contract.** The factory Job runs with `backoffLimit: 0`.
  Recovery is re-triggering the same chapter+class, which resumes; a
  whole-pod retry is never sanctioned.

The sanctioned recovery when a catcher exhausts: re-trigger the same
chapter+class. Completed stages are reused, the catcher runs again with a
fresh round budget against the kept repaired draft. `--fresh` is the
operator's regenerate button, not the debugger.

## 2. Routing table

| Gate | What it checks | Catcher | Loop config | Recheck |
|---|---|---|---|---|
| `02-generate` in-loop rules | shapes, citations, answer keys, invented numbers, SVG, self-containment | the model itself, via validation/rule feedback turns | `ZIVON_VALIDATION_ROUNDS` (default 5); transport retries separate | same call |
| `03-check` | facts, recomputation, coverage, pedagogical order + the same code rules | `04-repair` | `repair.content_rounds` (default 8), `repair.stall_rounds` (default 3) | full `03-check` |
| `05-interactive` in-loop lints | JS/CSS hard lints, page.css scope, canvas ownership | the model itself, via `extra_validator` | model validation rounds | same call |
| `07-perf` | load/FCP/RSS/FPS/console/overflow on the topic and landing pages | `08-fixloop` for a **fixable** topic-page miss | `perf.fix_rounds` (default 6), `repair.stall_rounds` | re-measure |
| `09-review` | truth (`facts`) + design/rendering/a11y (`design`) + static findings | `10-reviewfix` | `repair.code_rounds` (default 6), `repair.stall_rounds` | full `09-review` |
| `10b-transcheck` | 9 deterministic translation rules + 1 reviewer call per locale | `10c-transrepair` | `repair.translation_rounds` (default 6), `repair.stall_rounds` | recheck `10b` |
| `12-narration` per-block TTS/encode failure | synthesis + encode per block | bounded per-block repair inside `12` | `ZIVON_NARRATION_REPAIR_ROUNDS` (default 2) | per-block retry |

Two exceptions are deliberate:

- **`07-perf` landing-page miss is not fixable.** The landing page and shared
  assets are hand-maintained; the topic fix loop only touches topic-local
  files. The run stops and a human fixes `frontend/`.
- **`12-narration` failures degrade, they do not fail the page.** A block that
  still fails after its repair rounds gets the INF-089 disabled copy. Only
  configuration/wiring errors and an all-attempts-failed pass raise.

## 3. Severity ladder

The same three-level scale is used by `03-check`, `09-review`, and the
translation reviewer. The exact wording below is the calibrated contract; do
not invent a fourth level.

| Severity | Meaning | Blocks? |
|---|---|---|
| **fatal** | Contradicts the cited source passage, or a wrong answer key / wrong computed answer; must quote the source passage at `03`. At `09`: drawn behaviour contradicts a cited equation, HTML and JS disagree, or the page is physically misleading. | Yes |
| **major** | A concept smuggled in from outside the chapter's source material, or the learner is misled; at `09`, a clear doctrine violation or a major accessibility/rendering defect; at `10b`, a translation that changes meaning, drops a citation, or breaks a unit/answer. | Yes |
| **minor** | Everything else, including common-knowledge definitions the source does not spell out; advisory only. An `unverified:` suspicion is always minor. | No |

Rules that keep the ladder honest:

- **`unverified:` can never be fatal or major.** It is the reviewer's way out
  when it cannot ground a suspicion in the source.
- **A reviewer must be able to pass a good page.** The framing is "hunt for
  real errors; if the draft is faithful, pass it with an empty issues array",
  never "assume there is at least one defect".
- **The verdict is harness code, not prompt prose.** `09-review`'s calls output
  issues only; the harness computes `verdict = fail iff any fatal`. At
  `03-check`, the combined verdict is fail if the model verdict or the rule
  verdict fails.
- **Blocking set:** `_blocking_issues` is any `fatal` or `major` from the model
  or the rules. `minor` rides along in the report.
- **Progress metric:** `_severity_score` = `2 * fatals + majors`. Downgrading a
  fatal to a major is real progress even when the raw issue count stands still.

## 4. The progress-aware loop

All catchers share one shape. The exact Python lives in `factory/stages.py`;
the contract is:

```text
report = run_gate(round=None)
best = score(blocking(report))
stalls = 0
rounds = 0
while blocking(report) and rounds < max_rounds and stalls < stall_limit:
    rounds += 1
    fix = run_catcher(report, round=rounds)
    apply(fix)                      # merge by id, keep history
    report = run_gate(round=rounds) # full recheck, same gate
    now = score(blocking(report))
    if now < best:
        best, stalls = now, 0
    else:
        stalls += 1
if blocking(report):
    raise StageError(reason = plateau or cap, history, resume hint)
```

Why each piece exists:

- **Full recheck, not a spot check.** A repair can introduce a new defect
  elsewhere. The gate re-runs in full (`10c` is the scoped exception: it
  rechecks the repaired units only, then the required-locale verdict is
  recomputed).
- **Severity-weighted score.** Count-only progress lets a fixer trade one
  fatal for two majors and look successful. The score treats a fatal as twice
  a major.
- **Stall limit is the real stopper.** `stall_rounds` consecutive
  no-improvement rechecks declare a genuine plateau. The cap is a safety
  valve, not the intended stop.
- **Round history is evidence.** `04-repair` saves `{page, history}`;
  `10-reviewfix` saves files plus history; per-round model evidence lives under
  `attempts/round-NN/...` so rounds never overwrite each other.
- **Failure is loud and actionable.** The raised `StageError` names the stage,
  the reason (plateau or cap), the remaining issues, the evidence directory,
  and the resume instruction.

### A fix that breaks something costs a round

A catcher's own fix can fail a hard check. It is not raised immediately; it
becomes the next round's assignment:

| Fix outcome | Effect |
|---|---|
| Breaks a hard lint (`lint_js`, `lint_css`, `lint_page_css_scope`) | `10-reviewfix` records `lint_hits`, skips the re-review (a lint-broken page is not worth a model review), and feeds the violation to the next round. |
| Regresses the perf budget | `10-reviewfix` records `perf_after_fix`, feeds the failures to the next round. |
| Touches a renderer-owned file (`index.html`) | The file is not applied; the round is consumed and the assignment says why. |
| Changes a simulation block spec through the `10` channel | Excluded: sim behaviour is page.js draw code owned by `05`/`10`. A sim spec edit costs a round, not the run. |

The principle: **errors are context.** A precise violation fed back into the
next attempt is more valuable than pre-emptive prohibition prose.

## 5. Gate-by-gate details

### `03-check` / `04-repair`

- **Input to 03:** source pack, ground truth, lesson text, current blocks. The
  lesson text is included so "taught before tested" is verifiable.
- **Model issues:** facts, recomputation of every worked example and numeric
  check, coverage (sections, in-text questions, worked examples, exercise
  types), teaching order, age fit. The reviewer must quote the source for a
  fatal.
- **Rule issues:** `rule_shapes` (short-circuits), `rule_answer_keys`,
  `rule_citations`, `rule_self_containment`, `rule_numbers`,
  `rule_diagram_svg`.
- **What is deliberately not code-checked:** answers and options. Textbook
  exercises are meant to be computed; string-matching an answer would forbid
  every real numerical. The reviewer recomputes; a wrong computed answer is
  fatal there.
- **04's merge:** replacement blocks merged by `id`; flagged blocks omitted by
  the model are removed; coverage additions append new ids at the end,
  teach-then-test, last added block a check. It never re-runs `02`.

### `07-perf` / `08-fixloop`

- **Measured:** Navigation Timing, FCP/LCP, peak Chromium-tree RSS, rAF FPS,
  console/page errors, horizontal overflow at the profile viewport.
- **Shipping profile:** `weak-android.json` — 750 MB peak RSS, 4x CPU throttle,
  2 cores, 24 fps floor, 360 px overflow check. Load/FCP budgets are currently
  loosened to 6.0 s / 3.5 s pending measured tightening; the Phase-4 target is
  stricter. Treat the profile JSON as the gate, not the prose.
- **Fixable vs unfixable:** a topic-page miss is `BudgetError(fixable=True)`
  and routes to `08`; a landing-page miss is `fixable=False` and stops the run.
- **08's boundary:** `FIXABLE = {"page.js", "page.css"}`.
  `index.html` is renderer-owned. `_rebuild_html_if_needed` re-renders the body
  from the block specs by default when specs are given (and collapses nested
  shells when extracting a body without specs); it is idempotent and fails
  loudly on a shell-nesting rebuild rather than shipping a doubly nested page.
- **Preserve what the page teaches.** A perf fix may not strip physics or
  delete a simulation; the post-fix review is what catches a bad optimization.

### `09-review` / `10-reviewfix`

- **Two calls, by design.** A single giant review call was measured at
  24k-130k tokens per pass and the catcher plateaued. The split gives each call
  only its context:
  - `09-review-facts`: block specs + cited facts + final files. No doctrine, no
    example. Checks answer keys, cited-fact contradictions, drawn behaviour,
    HTML-vs-JS consistency.
  - `09-review-design`: compact block inventory + final files + doctrine +
    lesson example + rendered screenshots when the endpoint reads images.
    Checks doctrine, frame, usability/access, and a rendering sweep that
    verifies drawn geometry numerically against the cited equations.
- **Vision fallback is honest.** If the design call rejects image input, it
  retries text-only; that is a capability fallback, not a quality pass.
- **Verdict rule:** fail iff any fatal. Categories are a fixed enum; keep
  `03-check`'s `category` gap in mind (its prompt does not ask for one, so
  cross-run analysis sees `content`).
- **10's exits:** replacement `page.js` / `page.css`; corrected full block
  objects under `blocks` (the spec-correction channel); and nothing outside
  those. A manifest-only correction has no channel today; coordinate with the
  renderer owner rather than smuggling it through a file rewrite.
- **Re-review after a clean round.** Lint-broken or perf-regressed fixes are
  sent back before a re-review; a model review of known-broken code is wasted
  spend.

### `10b` / `10c` translation

- **Nine deterministic rules:** `R1` schema/reassembly; `R2` citation equality;
  `R3` no regional digits and multiset preservation; `R4` equations and SI
  units; `R5` check format/answer-index/option invariants; `R6` script policy
  (no Devanagari in `hi-Latn`, native script for Indic locales); `R7` no
  placeholder/truncation artifacts; `R8` diagram SVG structure; `R9` expansion
  budgets on labels/controls.
- **One calibrated reviewer call per locale** for meaning and naturalness.
- **Blocking:** `fatal`/`major` in a required locale. `optional_locales` may
  fall back per block to English (`fallback_en`) when only optional locales
  remain blocked; a required locale that plateaus raises.
- **10c is unit-scoped:** it re-translates only flagged `(locale, unit_id)`
  items, then rechecks those units. Passing units are promoted to TM only after
  `10b` passes.

### `12-narration` repair

- **Per block:** synthesis + encode failures are retried up to
  `ZIVON_NARRATION_REPAIR_ROUNDS`.
- **Degrade:** residual failures mark the block unavailable and the shell shows
  the INF-089 disabled copy. A narration failure never fails a page that
  already passed every gate.
- **Raise only when:** configuration/wiring is wrong, or a pass attempted work
  and nothing succeeded. A budget refusal is a policy outcome, not a failure:
  the stage narrates the deterministic prefix that fits and tells the operator
  how to raise the tranche.

## 6. How to add a deterministic check safely

Use this when the requirement is "must always hold" and code can decide it.

1. **Prove the failure class from evidence.** Name the artifact
   (`runs/<id>/<stage>/...`) or the production incident. A rule without a
   failing case is speculation.
2. **Choose the file:** `factory/checks.py` for content shape/semantics,
   `factory/lint.py` for generated code, `factory/transcheck.py` for
   translation, `factory/schemas.py` for structural validity.
3. **Choose the severity.** Fatal if the page is wrong or unsafe; major if it
   misleads; minor only if advisory. A rule that can produce a false fatal is a
   calibration bug, not strictness.
4. **Return the canonical issue shape** (`block_id`, `severity`, `rule`,
   `message`) and keep the message actionable ("expected a list of
   `{title, detail}` objects").
5. **Mind ordering.** If later rules index the thing you validate, run yours
   first and short-circuit on fatal shape issues. `run_all_rules` already does
   this for `rule_shapes`.
6. **Wire once.** `02`, `03`, and `04` all call `run_all_rules`; do not add a
   fourth call site. Lints are wired at their authoring sites (`05`, `06`,
   `08`, `10`), not on files being read back.
7. **Test mechanics, not prompt strings:** valid and invalid fixtures in
   `testing/content_factory/unit/test_checks.py` (or the matching suite).
8. **Add eval coverage:** a deterministic checker referenced by the relevant
   card; a seeded defect if the class is calibratable. A checker that can
   produce a false fatal needs calibration, not just a unit test.
9. **Update the contract docs:** blocks schema or architecture, whichever the
   rule enforces.
10. **Decide resume impact:** rules are runtime gates, not artifact semantics,
    so a rule alone does not bump `PIPELINE_VERSION`. But a run whose `03-check`
    is already `ok` will resume without the new rule. Re-run `03-check` (and
    `04` on failure) or use `--fresh` when the rule must apply to an existing
    draft; record the choice.

## 7. How to add a model gate safely

Use this when the requirement needs judgement: truth, pedagogy, design,
accessibility, naturalness.

1. **Give the reviewer the material it needs to judge, and nothing else.**
   A "taught before tested" reviewer needs the lesson text; a design reviewer
   needs the doctrine and the rendered page; a facts reviewer must not receive
   visual-language context. Context bloat is a measured cause of thinking
   loops.
2. **Write a calibrated rubric**, following
   `skills/prompting-and-agent-design/`: goal, exact severity ladder, anchor
   examples, an `unverified:` way out, and a bounded inspection procedure if
   the judge is a reviewer (not a generation plan).
3. **Let the harness own the verdict.** The model outputs issues; code computes
   fail iff any fatal. Do not ask the model for a verdict it can rubber-stamp.
4. **Pair it with a catcher and a progress metric.** The severity-weighted
   blocking score is the default. If the gate is not repairable, fail loudly
   instead and add a smoke test.
5. **Calibrate before trusting it.** Run it against the seeded-defect corpus
   and clean goldens; measure fatal recall and clean specificity. A reviewer
   that passes everything or fails everything is broken scaffolding. The
   calibration command is in [commands.md](commands.md).
6. **Split the call if thinking bloats.** The `09` split is the precedent:
   one giant call became two focused calls, each with its own context and
   evidence namespace.
7. **Name the failure category** from the fixed enum so cross-run analysis and
   `scripts/issue_report.py` can find the class.
8. **Add the eval card, the logging row, and the docs** in the same PR.

## 8. How to add a catcher (or reuse one)

- **Scope the fix.** Name exactly which artifacts the catcher may write
  (`block objects`, `page.js`/`page.css`, localized units, narration assets).
  Anything outside the scope costs a round and is fed back.
- **Keep a history.** Save `{page/files, history}` each round; put model
  evidence under `attempts/round-NN/...`. Resume reads the latest saved state.
- **Make the loop progress-aware.** Use the shared score/stall/cap pattern;
  add a config key only if the existing caps are wrong for this gate.
- **Make failure actionable.** The `StageError` must name the stage, the
  reason, the remaining issues, the evidence directory, and the resume hint.
- **Test the loop.** Mock the gate and catcher; assert that the run stops on
  plateau, stops on cap, keeps the repaired draft, and resumes mid-loop after a
  simulated pod death between a repair and its recheck.

## 9. Debugging a plateau

1. Read `03-check/combined-<round>.json`, `04-repair/history`,
   `10-reviewfix` history, or `10b`'s issues ledger. Find the recurring
   `(stage, call, block_id, category)` tuple.
2. Read the catcher's round attempts: did it understand the finding? Did it
   fix a different block? Did its fix break lint/perf?
3. Read the reviewer's attempts: is it repeating a finding that the source
   does not support? Is it flagging a minor as major? Is its context missing
   the material it needs?
4. Run `python3 scripts/issue_report.py` across runs for the same
   block+category pattern; a recurring finding is a prompt/contract problem,
   not a one-off.
5. Choose the remedy: fix the prompt/rubric, add a deterministic rule for the
   mechanical part, split the call, or (rarely) raise a cap with a measured
   reason. Do not lower the severity to make it pass.

## 10. Anti-patterns

- A gate that raises on a repairable finding instead of routing.
- A catcher that re-runs `02-generate` "to be safe".
- A cap-only loop with no stall detection: it burns the full budget on a
  defect the fixer cannot see.
- A "fix" that silently drops a block or a citation to make the score improve.
- Raising a round cap without a measured plateau reason.
- Adding a rule that can false-fatal and calling it calibration.
- A reviewer asked to judge material it was not given.
- Changing a seeded defect or clean golden so the reviewer passes.
- Logging a gate failure at INFO without an `error_class`.
