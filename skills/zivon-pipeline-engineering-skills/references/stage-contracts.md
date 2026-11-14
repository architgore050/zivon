# Stage contracts (00-12)

Every fact here is read from `pipeline.py`, `factory/stages.py`, the stage
modules, and `docs/content-factory/architecture.md` at **2026-11-14**
(`PIPELINE_VERSION = "9"`). The architecture doc is the narrative source of
truth; this file is the contract table an engineer needs before editing a
stage.

## 1. The contract in one page

1. **One entry point.** `python pipeline.py "<chapter>" [--class N]
   [--fresh] [--run-id ID] [--locales a,b] [--stages ...]`.
2. **One stage order.** `STAGE_ORDER` in `factory/stages.py` is the only valid
   stage list. `--stages` validates against it and exits 2 on an unknown id.
3. **One artifact per stage.** A stage writes
   `runs/<run_id>/<stage>/output.json`, then the orchestrator calls
   `run_ctx.mark_stage(stage, "ok", ...)`.
4. **Resume is by state plus artifact.** `stage_ok(stage)` is true only when
   `status.json` says `ok` *and* `output.json` exists. A stage marked
   `failed` or `running` runs again.
5. **Downstream reads upstream artifacts.** `RunContext.load_stage_output`
   reads this run first, then copies the newest matching output from a sibling
   run under `runs/`, prints the source run, and continues. A `--stages` subset
   that starts too late raises `MissingArtifactError` with instructions.
6. **Upstream is never re-derived for a downstream failure.** `02-generate`
   output is reused across every `03/04` round; `06-render` output is reused
   across `07/08` and `09/10`.
7. **Only `11-link` writes `frontend/`.** Everything before it writes inside
   the run directory (staging site included).
8. **Only `06-render` and `10d-transrender` write HTML.** `05-interactive`
   writes simulation JS/CSS fragments; `08` and `10` may only rewrite
   topic-local `page.js` / `page.css` (plus corrected block specs at `10`).

## 2. Run identity, fingerprint, and freshness

| Concept | Contract |
|---|---|
| Run id | `make_run_id(chapter, class)` = slugified chapter plus `c<N>` when a class was supplied. Deterministic: the same topic resumes the same directory. |
| Overrides | `--run-id` keeps parallel attempts; `ZIVON_RUN_ID` is honored when it agrees with the id being made; otherwise the deterministic id wins. |
| Fingerprint | `status.json.fingerprint` = SHA-256 (first 16 hex) of `{pipeline_version, chapter, class, model, limits, retrieval, learner}` plus a `translation` payload only when `translation.enabled` is true (`target_locales`, `optional_locales`, `prompt_version`, `glossary_sha256`). |
| Fingerprint guard | A differing fingerprint raises `ConfigError` and tells the operator to pass `--fresh` or choose another `--run-id`. Stage artifacts from two pipeline shapes are never mixed silently. |
| Deliberately absent | Repair round caps (`content_rounds`, `code_rounds`, `translation_rounds`, `stall_rounds`, `perf.fix_rounds`) are runtime policy, not artifact semantics. Tuning them must not invalidate good generated work. |
| `--fresh` | Wipes the previous run directory, then starts clean. It is the operator's regenerate button, not a debugging tool. |
| Completed run | Re-triggering a fully complete run reuses everything and prints that nothing will be regenerated. This is the resume contract, not a bug. |
| `PIPELINE_VERSION` | Bumped when the stage graph or stage *artifact* contracts change. Current value `"9"` (chapter-derived topic identity; reviewfix spec-correction channel; numeric-answer and diagram/simulation laws). Version-8 and earlier run dirs are refused on resume. |

## 3. Stage summary

| # | Stage | Module | Model? | Primary output |
|---|---|---|---|---|
| 00 | `00-ingest` | `factory/ingest.py` | no | per-book chapter index + extracted page text |
| 01 | `01-locate` | `factory/locate.py` | embeddings only | `source_pack` |
| 02 | `02-generate` | `factory/agents.py` | **one giant call** | `{ground_truth, lesson, blocks}` |
| 03 | `03-check` | `factory/agents.py`, `factory/checks.py` | model + code | combined verdict + issues |
| 04 | `04-repair` | `factory/agents.py` | model | merged page + history |
| 05 | `05-interactive` | `factory/interactive.py` | one call per simulation | `{block_id: {id, files}}` |
| 06 | `06-render` | `factory/render.py` | no | staging site + manifest + `courses.js` |
| 07 | `07-perf` | `factory/perf.py` | no (Chromium) | budget report |
| 08 | `08-fixloop` | `factory/fixloop.py` | model | fixed topic files + history |
| 09 | `09-review` | `factory/review.py` | two calls (`facts`, `design`) | merged verdict + issues |
| 10 | `10-reviewfix` | `factory/reviewfix.py` | model | files + optional corrected blocks |
| 10a | `10a-translate` | `factory/translate.py`, `factory/tm_store.py` | per unit per locale | localized units + checkpoints |
| 10b | `10b-transcheck` | `factory/transcheck.py` | rules + one reviewer call per locale | per-locale verdicts |
| 10c | `10c-transrepair` | `factory/transrepair.py` | model | replacement units |
| 10d | `10d-transrender` | `factory/render.py::render_localized` | no | localized routes + i18n bundles |
| 11 | `11-link` | `factory/link.py` | no | published topic + `courses.js` |
| 12 | `12-narration` | `factory/narration/` | Timbre TTS (no LLM) | opus assets + narration manifests |

## 4. Per-stage contracts

### `00-ingest` - source library index

- **Input:** `sources/catalog.json`, cached PDFs under the configured
  `pdf_cache`, the chapter query's candidate books.
- **Output:** per-book chapter list/URL mapping and extracted page text
  (tables re-appended as `[table]` rows), written to the run's
  `00-ingest/output.json`; the text cache under `text_cache` is reused across
  runs.
- **Artifact:** `runs/<run_id>/00-ingest/output.json`; caches under
  `sources/cache/`.
- **Resume:** normal stage resume; the cross-run cache is why a resumed ingest
  is cheap.
- **Owner:** `factory/ingest.py`.
- **Hard failures:** missing/wrong PDFs, unparseable books, a required
  chapter with zero cached text. Network unreachable is *not* a 404: a book
  with at least one extracted chapter truncates loudly at the failed chapter;
  a book with none is fatal.

### `01-locate` - chapter matching and source pack

- **Input:** the `00-ingest` index, the chapter query, optional `--class`.
- **Output:** `source_pack` with `chapter` (`title`, `class`, `book_title`,
  `book_id`, `pages`, `number`, `matched_via`), `ncert_text`, and
  `supplements[]` with citation ids.
- **Artifact:** `runs/<run_id>/01-locate/output.json`.
- **Resume:** normal. The located chapter sets the learner class when
  `--class` was omitted; `_sync_learner_to_chapter` guarantees the class
  follows the chapter, never the flag that disagreed with it.
- **Owner:** `factory/locate.py`.
- **Matching law:** exact means a *title candidate* matches. A phrase found
  only in body prose is a demoted `body_phrase` partial, wins only when no
  title matches, prints a loud warning, and records `matched_via`. Ambiguity
  is a hard error listing candidates.

### `02-generate` - the one reasoning call

- **Input:** `source_pack`; the live design doctrine and parsed palette
  (`factory/design.py` reads `docs/frontend/design-doctrine.md` and
  `frontend/assets/zivon.css`); the coverage contract, grounding law, block
  budget, and SHAPE example in `factory/agents.py`.
- **Output:** one JSON object `{ground_truth, lesson, blocks}` validating
  against `GENERATED`; `blocks` is the canonical wrapper
  `{"blocks": [ ... ]}`.
- **Artifact:** `runs/<run_id>/02-generate/output.json` plus
  `attempts/attempt-NN/{request,response,meta}.json`.
- **Resume:** normal. `04-repair`'s merged page and `10-reviewfix`'s corrected
  blocks are preferred over the raw output on resume via `_preferred_blocks`.
- **Owner:** `factory/agents.py::run_generate`.
- **In-loop guarantees:** `factory/checks.py::run_all_rules` runs inside the
  model retry loop, so the model sees its own fatal/major rule violations
  (shape, citation, answer key, invented number, SVG, self-containment) and
  fixes them before the stage can pass. Validation rounds are separate from
  transport retries (`ZIVON_VALIDATION_ROUNDS` vs `ZIVON_MAX_ATTEMPTS`).

### `03-check` - the fact gate

- **Input:** `source_pack`, `ground_truth`, `lesson`, the current `blocks`.
- **Output:** `{model_verdict, model_issues, rule_verdict, rule_issues,
  verdict}`; `verdict` is `fail` if either side fails. Issues carry the fixed
  severity ladder.
- **Artifact:** `runs/<run_id>/03-check/output.json`; recheck rounds also
  write `combined-<round>.json` and namespace attempts under
  `attempts/<round>/`.
- **Resume:** if `03-check` is ok, its validated unit is reused. If
  `04-repair` is also ok, the repaired page is loaded so a pod death between a
  repair and its recheck resumes mid-loop.
- **Owner:** `factory/agents.py::run_check` + `factory/checks.py`.
- **Blocking rule:** any `fatal` or `major` from either the model or the
  rules. `minor` rides along and never blocks.

### `04-repair` - the fact catcher

- **Input:** blocking issues, source pack, ground truth, lesson, current
  page.
- **Output:** `{page: {"blocks": [...]}, history: [...]}`. Replacement blocks
  are merged by `id`; flagged blocks omitted by the model are removed; coverage
  omissions are fixed by appending new ids at the end, teach-then-test, with
  the last added block a check.
- **Artifact:** `runs/<run_id>/04-repair/output.json` (full merged page plus
  round history); per-round attempts under
  `attempts/round-NN/attempt-NN/`.
- **Resume:** normal; the saved `page` becomes the preferred draft.
- **Owner:** `factory/agents.py::run_repair`, loop owned by
  `factory/stages.py`.

### `05-interactive` - simulation code per block

- **Input:** every `simulation` block spec, its cited claims, all ground-truth
  equations ("facts the simulation must obey"), the live doctrine + lesson
  examples + palette, and a rigid `ZivonSim.register` skeleton.
- **Output:** `{block_id: {"id": block_id, "files": {"page.js": "...",
  "page.css": "..."}}}`; a simulation with zero controls is an animation.
- **Artifact:** `runs/<run_id>/05-interactive/output.json` plus attempts.
- **Resume:** normal; output is merged into the page by `06-render`.
- **Owner:** `factory/interactive.py`.
- **In-loop guarantees:** `lint_js`, `lint_css`, and `lint_page_css_scope`
  run as the model's `extra_validator`, so a lint violation is fed back and
  repaired before the stage passes. An empty `page.js` or a surviving hard
  lint raises `LintError`.

### `06-render` - assemble the static page

- **Input:** chapter/source pack, lesson, blocks, `05-interactive` fragments,
  the shared shell (`frontend/assets/zivon.css`, `zivon.js`, landing
  `index.html`).
- **Output:** staging site at
  `runs/<run_id>/06-render/site/`, topic directory
  `site/courses/class-N-physics/<slug>/` (`index.html`, optional `page.js` /
  `page.css`, `manifest.json`), and a staging `courses.js`.
- **Artifact:** `runs/<run_id>/06-render/output.json` holds `topic_dir`,
  `site_dir`, `manifest`, and `files`; the tree itself is the page evidence.
- **Resume:** normal. A resumed render reuses the previous output; a schema
  or template change that must reach old pages needs a re-render, not a
  resume.
- **Owner:** `factory/render.py::run`.
- **Deterministic guarantees:** topic slug comes from the chapter title (not
  the model's lesson headline); `lint_generated` gates JS/CSS/HTML; the page
  carries the strict CSP; the renderer never touches `frontend/`.

### `07-perf` - the weak-hardware gate

- **Input:** the staged topic page and staged landing page, plus the configured
  perf profile (`testing/content_factory/perf/profiles/weak-android.json` by
  default).
- **Output:** `{profile, pages: {topic_page, landing_page}, pass}` with each
  page's measurements and failures.
- **Artifact:** `runs/<run_id>/07-perf/output.json` plus
  `topic_page.perf.json` / `landing_page.perf.json`; budget-fail events.
- **Resume:** normal.
- **Owner:** `factory/perf.py` + `testing/content_factory/perf/harness.py`.
- **Routing:** a topic-page miss raises a **fixable** `BudgetError` and routes
  to `08-fixloop`. A landing-page or shared-asset miss is **unfixable** by the
  loop and stops the run; a human fixes `frontend/`.

### `08-fixloop` - the perf catcher

- **Input:** the perf report, page files, block specs, doctrine + example +
  palette.
- **Output:** fixed topic-local files plus round history; `rounds=0` and no
  model call when `07` passed.
- **Artifact:** `runs/<run_id>/08-fixloop/output.json`; attempts under
  `attempts/round-NN/`.
- **Resume:** normal; fixed files are applied to the staging tree.
- **Owner:** `factory/fixloop.py`.
- **Boundary:** only `page.js` / `page.css` are fixable. A fix that breaks a
  hard lint, touches a renderer-owned file (`index.html`), or fails to improve
  the budget costs a round and is fed back, not raised.

### `09-review` - the code and design gate

- **Input:** block specs, ground truth, final page files, static findings,
  rendered screenshots for the design call when the endpoint supports vision,
  and the doctrine + lesson example for the design call only.
- **Output:** one merged report: `verdict` plus issues with a category from
  the fixed enum (`answer_key`, `fact`, `drawn_behaviour`, `inconsistency`,
  `visual_language`, `frame`, `accessibility`, `rendering`, `other`).
- **Artifact:** `runs/<run_id>/09-review/output.json`; attempts namespaced
  `attempts/facts/attempt-NN/` and `attempts/design/attempt-NN/`, re-reviews as
  `attempts/round-NN-facts/...`.
- **Resume:** normal; a fail verdict routes to `10-reviewfix`, it does not
  raise here.
- **Owner:** `factory/review.py`.
- **Two-call law:** `09-review-facts` checks truth (answer keys, cited-fact
  contradictions, drawn behaviour, HTML-vs-JS consistency) and gets no
  visual-language context. `09-review-design` checks doctrine, frame,
  usability/access, and a numerical rendering sweep, and gets no full facts
  list. The verdict is computed by the harness: fail iff any fatal.

### `10-reviewfix` - the code/design catcher

- **Input:** the review report, page files, block specs, ground truth,
  doctrine, and any feedback from the previous round (`extra_feedback`).
- **Output:** replacement topic files and, since `PIPELINE_VERSION 8`, a
  **spec-correction channel**: corrected full block objects under `blocks`.
  The harness merges them by id, re-renders the page body from the merged
  specs, and threads the corrected draft through re-review, render, and
  resume. Simulation blocks are excluded from the channel; sim behaviour is
  page.js draw code owned by the `05`/`10` boundary.
- **Artifact:** `runs/<run_id>/10-reviewfix/output.json`; per-round attempts;
  round history.
- **Resume:** normal; the corrected `page` is preferred over the raw draft.
- **Owner:** `factory/reviewfix.py`, loop owned by `factory/stages.py`.

### `10a-translate` - build-time localization

- **Input:** ground truth, lesson, blocks, render output (for metadata/UI
  strings), glossary and UI strings, neighbour context.
- **Output:** per locale, `{meta, blocks: {"blocks": [...]}, sim_strings,
  unit_status, fallback_blocks, stats}` under `{"locales": {...}}`.
- **Artifact:** `runs/<run_id>/10a-translate/output.json`; per-unit
  checkpoints at
  `runs/<run_id>/10a-translate/blocks/<locale>/<unit_id>.json`; a
  content-addressed Translation Memory under
  `sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json`.
- **Resume:** per unit, by `tm_key`. The key includes source content,
  locale, prompt version, and glossary hash; a changed source or glossary
  creates a new key while the old entry stays addressable.
- **Owner:** `factory/translate.py`, `factory/tm_store.py`.
- **Guard:** harness code preserves `id`, `type`, `citations`,
  `answer_index`, numeric answers, and control geometry; the model only
  translates strings.

### `10b-transcheck` - the translation gate

- **Input:** localized units, English source, glossary, UI strings.
- **Output:** per-locale verdict and issues from nine deterministic rules
  (`R1`-`R9`) plus one calibrated reviewer call per locale.
- **Artifact:** `runs/<run_id>/10b-transcheck/output.json`; recheck rounds
  write `combined-<round>.json`; every issue also lands in the run's
  `issues_ledger.jsonl`.
- **Resume:** normal; passing units are promoted to TM only after this gate.
- **Owner:** `factory/transcheck.py`.
- **Blocking rule:** any `fatal` or `major` in a required locale. An optional
  locale may fall back per block to English (`fallback_en`) when only optional
  locales remain blocked.

### `10c-transrepair` - the translation catcher

- **Input:** flagged `(locale, unit_id)` items only.
- **Output:** replacement localized units; recheck per round; per-locale
  history in `{locales: {loc: {page, history}}}`.
- **Artifact:** `runs/<run_id>/10c-transrepair/output.json`; it also refreshes
  `10a-translate/output.json` so a resume sees the repaired units.
- **Resume:** normal mid-loop; checkpointed units are kept.
- **Owner:** `factory/transrepair.py`, loop owned by `factory/stages.py`.

### `10d-transrender` - localized routes

- **Input:** English render output, translated units, translation verdicts,
  source pack, lesson, blocks.
- **Output:** `<locale>/index.html` under the topic, `i18n/<locale>.json`,
  `i18n/en.json`, `i18n.js`, locale hub pages (`site/<locale>/index.html`), and
  CP-TRN-004 manifest metadata (`default_locale`, `locales_available`,
  `titles_by_locale`, `translation_status`, `i18n_hashes`).
- **Artifact:** `runs/<run_id>/10d-transrender/output.json`.
- **Resume:** normal.
- **Owner:** `factory/render.py::render_localized`.
- **Boundary:** renders localized content into the staging site; `11-link`
  publishes it.

### `11-link` - publish into `frontend/`

- **Input:** the staging site and topic directory from `06-render` /
  `10d-transrender`.
- **Output:** the topic copied to
  `frontend/courses/<course_id>/<slug>/`; stale same-chapter duplicate topic
  directories pruned; locale hubs copied to `frontend/<locale>/`; `courses.js`
  regenerated; every href and declared locale file smoke-tested.
- **Artifact:** `runs/<run_id>/11-link/output.json` with entries,
  `course_count`, pruned names, and published hubs.
- **Resume:** normal; only this stage writes `frontend/`.
- **Owner:** `factory/link.py`.
- **Duplicate rule:** a chapter owns exactly one topic directory. Any sibling
  manifest with the same `course_id` and `chapter.title` that is not this topic
  is a superseded copy and is removed. The previous copy survives in git
  history after publish.

### `12-narration` - build-time read-aloud audio

- **Input:** the published topic (after every gate), `02-generate` lesson and
  blocks, `05-interactive` readout strings, speakable selection rules.
- **Output:** opus assets under `frontend/audio/<course_id>/`, the topic
  manifest's `narration` availability block, `narration-manifest.json`, a
  per-run `narration_usage.jsonl`, and the cross-run budget ledger
  `runs/narration-budget.json`.
- **Artifact:** `runs/<run_id>/12-narration/output.json` plus the asset tree.
- **Resume:** per block by content hash
  (`<block_id>.<lang>.<text-hash>.opus`); changed text bumps the hash and the
  old asset remains addressable.
- **Owner:** `factory/narration/` (`stage.py`, `select.py`, `timbre.py`,
  `audio.py`, `budget.py`, `publish.py`, `env.py`).
- **Failure policy:** per-block failures route to a bounded repair catcher
  (`ZIVON_NARRATION_REPAIR_ROUNDS`, default 2), then degrade read-aloud to the
  INF-089 disabled copy. A narration failure never fails a page. Only a pass
  where attempts were made and nothing succeeded raises.
- **Mock/live:** no Timbre endpoint or `ZIVON_NARRATION_MODE=mock` produces
  real opus files whose audio is silence, labelled `mode: "mock"`; never publish
  mock audio to the live site.

## 5. Translation sub-graph activation

The four `10*` stages are activated when either condition holds:

- `config.translation.enabled` is true; or
- `--locales` is passed (`Config.with_locales` enables the target locales); or
- `--stages` explicitly names a translation stage.

Otherwise `wanted()` returns false for them and an English-only run is
unchanged. `10d-transrender` runs before `11-link`; `11-link` publishes both
English and localized trees.

## 6. Stage dependencies (what must exist before a subset run)

| Stage subset | Needs from earlier artifacts |
|---|---|
| `02-generate` | `01-locate` |
| `03-check` / `04-repair` | `01-locate`, `02-generate` |
| `05-interactive` | `02-generate` |
| `06-render` | `01-locate`, `02-generate`, `05-interactive` (optional) |
| `07-perf` / `08-fixloop` | `06-render` (and `05` for block facts) |
| `09-review` / `10-reviewfix` | `02-generate`, `06-render` |
| `10a-translate` | `02-generate`; `06-render` when render metadata is needed |
| `10b` / `10c` | `10a-translate` |
| `10d-transrender` | `06-render`, `10a`, `10b` (verdicts) |
| `11-link` | `06-render` (and `10d` for localized trees) |
| `12-narration` | `11-link`, `02-generate`, `05-interactive` |

`load_stage_output` can pull a missing upstream artifact from the newest
previous run that has it. That is a convenience for targeted re-runs, not a
substitute for a coherent artifact set: the fingerprint guard still decides
whether a run directory may be resumed at all.

## 7. How to add a stage

1. Add the id to `STAGE_ORDER` in `factory/stages.py` (and to
   `_TRANSLATION_STAGES` only if it is conditional like `10a`-`10d`).
2. Implement `run(cfg, run_ctx, ...) -> dict` in a focused module under
   `factory/`. Use `run_ctx.stage_dir`, `write_json`, `save_stage_output`, and
   `mark_stage`; never write run state by hand.
3. Route every model call through `factory/llm.py` (which uses
   `llm_manager`). No direct HTTP. No `max_tokens` on factory calls.
4. Decide the artifact contract and write it down: input schema, output
   schema, artifact path, resume behavior, side effects, failure classes.
5. Decide the gate/catcher pair. A new quality gate without a catcher is a
   pipeline that either fails every draft or never repairs. If the stage is
   deterministic and must never fail (e.g. render, link), fail loudly instead
   and add a smoke test.
6. Add the stage to `config._STAGE_IDS` if it accepts `stage_overrides`;
   update `docs/content-factory/config-reference.md` and `runbook.md`.
7. Add the stage id to the instrumentation map's stage list and to
   `testing/observability/test_events.py`; emit `factory.stage.start/ok/fail`
   through `mark_stage`.
8. Add tests: unit mechanics, a mock-server orchestration test, and an eval
   card if model quality is the deliverable. The eval card schema's stage enum
   is currently closed (`EV-CUR`/`SYN`/`VIS`/`PERF`/`REV`/`E2E`/`KID`); an
   assessment/exam stage needs the additive schema extension first.
9. Bump `PIPELINE_VERSION` if the new stage changes the stage graph or artifact
   semantics. Adding an optional post-publish stage that does not alter
   existing artifacts may not require a bump; say why in the PR.
10. Update `docs/content-factory/architecture.md`'s stage table and this
    bundle's stage table in the same PR.

## 8. How to change an existing stage contract

| Change | Required work |
|---|---|
| Add an optional output field no gate consumes | Producer + schema (if validated) + docs + a render/resume test. No version bump usually. |
| Add a field the shell or a later stage reads | Producer + schema + consumer + docs + a test that the consumer handles absence; re-render or bump the version if resumed artifacts would be stale. |
| Change a field's meaning, type, or requiredness | Breaking: schema + every producer/consumer + docs + `PIPELINE_VERSION` bump + `--fresh` instruction. |
| Change a prompt or rubric | `skills/prompting-and-agent-design/` first; add/update an eval card; calibration for a reviewer; no version bump unless the artifact schema changes. |
| Change severity or blocking semantics | Gate + catcher + docs + seeded-defect calibration + eval thresholds. This changes what may publish; treat it as a contract change even if no schema moves. |
| Change a repair cap | Config + docs. Caps are not in the fingerprint and must not invalidate runs. |
| Change a model | Fingerprint changes via `model`, so resume refuses old dirs. Record the Gate decision and re-baseline evals. |

## 9. Facts to re-verify before editing

- `STAGE_ORDER`, `PIPELINE_VERSION`, and `run_fingerprint` in
  `factory/stages.py`.
- The exact `GENERATED` / `BLOCKS` / `LESSON` schemas in `factory/schemas.py`.
- The stage table in `docs/content-factory/architecture.md`.
- The config keys and defaults in `config.json` and `factory/config.py`.
- The eval card stage/role enums in `evals/models.py` before adding a card.
- The instrumentation map's stage and event rows before adding an event.

If a doc and the code disagree, do not silently pick a side: fix the doc in
the same PR if the code is the intended contract, or open a decision if the
code is wrong. Record the conflict in the PR body.
