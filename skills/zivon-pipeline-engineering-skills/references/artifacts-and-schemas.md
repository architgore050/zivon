# Artifacts and schemas

Everything a stage hands to the next stage is a file. This file is the on-disk
contract: the run directory, the schemas, the stable IDs, the manifest and
catalogue shapes, translation/narration artifacts, and the versioning rules.

Sources: `factory/artifacts.py`, `factory/schemas.py`, `factory/config.py`,
`factory/stages.py`, `factory/render.py`, `factory/link.py`,
`factory/translate.py`, `factory/tm_store.py`, `factory/narration/`, and
`docs/content-factory/{architecture,blocks-schema}.md`. Dated **2026-11-14**
(`PIPELINE_VERSION = "9"`).

## 1. Run directory layout

```text
runs/<run_id>/
  status.json                 # per-stage state, elapsed_s, fingerprint
  run_report.json             # terminal summary + durations + ledger rollups
  calls_ledger.jsonl          # one line per model attempt
  issues_ledger.jsonl         # one line per reviewer-found issue
  narration_usage.jsonl       # per-block narration estimates/spend (stage 12)
  00-ingest/
    output.json
  01-locate/
    output.json
  02-generate/
    output.json
    attempts/attempt-01/{request.json,response.json,meta.json}
    ...
  03-check/
    output.json
    combined-<round>.json     # one per recheck round
    attempts/round-01/attempt-01/...
  04-repair/
    output.json               # {page, history}
  05-interactive/
    output.json
    attempts/...
  06-render/
    output.json
    site/                     # staging site: index.html, assets/, courses/...
  07-perf/
    output.json
    topic_page.perf.json
    landing_page.perf.json
  08-fixloop/
    output.json
    attempts/round-NN/...
  09-review/
    output.json
    attempts/facts/attempt-NN/...
    attempts/design/attempt-NN/...
    attempts/round-01-facts/...
  10-reviewfix/
    output.json
    attempts/round-NN/...
  10a-translate/
    output.json
    blocks/<locale>/<unit_id>.json
  10b-transcheck/
    output.json
    combined-<round>.json
  10c-transrepair/
    output.json
  10d-transrender/
    output.json
  11-link/
    output.json
  12-narration/
    output.json
```

`runs/` is gitignored. In the cluster it lives on the `zivon-sources` PVC
(`subPath: runs`) so stage artifacts and evidence survive pod death.
`scripts/publish-artifacts.sh` mirrors it read-only to the host for
inspection.

### `status.json`

```json
{
  "run_id": "motion-c9",
  "started_at": 1760000000.0,
  "fingerprint": "0f3c...",
  "stages": {
    "06-render": {"state": "ok", "detail": "...", "at": 1760000123.4, "elapsed_s": 12.3}
  }
}
```

- `state` is `running`, `ok`, or `failed`.
- `elapsed_s` is measured; a resumed stage inherits its previous measured time.
- `fingerprint` is the resume contract (see §8).
- `blocks` / `attempts` are emitted in stage events, not stored in the status
  entry; read `output.json` for counts.

### `run_report.json`

Written by `RunContext.finish()`:

- `run_id`, `ok`, `detail`
- `started_at`, `completed_at`, `duration_s`
- `stage_durations_s` (multi-round stages accumulate; resumed stages inherit)
- `model_call_stats` — per stage: attempts, rejected, transport failures,
  `thinking_s` (sum of first-token time), `max_completion_tokens`
- `issues_found` — total, unverified, by stage/severity/category

### Ledgers

- `calls_ledger.jsonl`: one line per model attempt — answered, rejected (with
  the exact violation), or transport-failure (last heartbeat + error class),
  plus latency, `first_token_s`, token usage, finish reason.
- `issues_ledger.jsonl`: one line per reviewer issue — stage, call, severity,
  category, block, unverified flag.
- `scripts/issue_report.py` aggregates both across runs. This is the input to
  prompt/rubric work; do not replace it with ad-hoc greps.

### Attempt evidence

Every model call writes `attempts/[<round-tag>/]attempt-NN/`:

- `request.json` — the exact messages/config sent.
- `response.json` — the exact model output.
- `meta.json` — latency, token usage, sampling, payload sizes, and streaming
  evidence (`stream`, `first_token_s`, `chunks_received`, `call_deadline_s`,
  `finish_reason`) plus an `outcome` line for a call that died mid-stream.

Rounds are namespaced so no round overwrites another's evidence. `09-review`
namespaces its two calls under `facts/` and `design/`; re-reviews use
`round-NN-facts/` / `round-NN-design/`.

## 2. Schema map

All schemas live in `factory/schemas.py`. They are JSON Schema Draft-07
(declared in the schema; the validation loop is `llm_manager.validation`).

| Schema | Used by | Top-level contract |
|---|---|---|
| `GROUND_TRUTH` | `02-generate` | `topic`, `summary`, `claims[]`, `key_terms[]`, `equations[]`, `misconceptions`, `uncertain` |
| `LESSON` | `02-generate` | `title`, `objectives[]`, `sections[]` (`sec-NN`), `glossary[]` |
| `BLOCKS` | `02`, `04`, `05`, `06`, `09`, `10` | `{"blocks": [...]}`, 4-45 blocks, each `{id, type, spec, citations}` |
| `GENERATED` | `02-generate` | `{ground_truth, lesson, blocks}` in one object |
| `INTERACTIVE` | `05-interactive` | `{id, files: {filename: content}}` |
| `FIX_PLAN` | `08-fixloop`, `10-reviewfix` | `analysis`, `files`, optional corrected `blocks` |
| `REPAIR` | `04-repair` | `analysis`, replacement `blocks[]` |
| `CHECK_REPORT` / `REVIEW_REPORT` | `03`, `09` | `verdict` (`pass`/`fail`), `issues[]` |
| `TRANSLATED_*_PAYLOAD` | `10a`, `10b`, `10c` | per-unit translation payloads; do not modify `BLOCKS`/`LESSON` |
| `TRANSLATION_REVIEW_CALL_REPORT` | `10b` | reviewer verdict + issues per locale |

There is no separate `animation` block type in v1: a simulation with zero
controls is an animation. `GLOSSARY` is a lesson-level array rendered as a
section, not a block type. (A requirement document that lists it as a block
type is in conflict with the frozen schema; record the conflict, do not add a
seventh block type casually.)

## 3. The canonical block shape

```json
{
  "blocks": [
    {
      "id": "b-01",
      "type": "text",
      "spec": {"paragraphs": ["..."]},
      "citations": [{"claim_id": "claim-01"}]
    }
  ]
}
```

- `id` matches `^b-[0-9]{2}$`; IDs are stable and never renumbered after
  publish.
- `type` is one of `text`, `worked_example`, `check`, `reveal`, `diagram`,
  `simulation`.
- `spec` carries the type-specific payload; every payload lives under `spec`.
- `citations` is required on the block object. Factual blocks (`text`,
  `worked_example`, `check`, `reveal`) must carry at least one `claim_id`;
  `rule_citations` enforces it. A citation `source_id` not present in the
  source pack is a major issue.
- Ordering contract: first block `text`, last block `check`, at least 3 checks
  spread through the page, visuals interleaved where a teacher would put them.

### Per-type `spec`

| Type | Required payload |
|---|---|
| `text` | `{"paragraphs": ["...", ...]}` |
| `worked_example` | `{"problem", "steps": [{"title","detail"}], "answer"}` |
| `check` | MCQ: `question`, `format: "mcq"`, `options[]`, `answer_index`, `answer`, `explanation`, `expected_understanding`. Numeric: `format: "numeric"`, `answer` is a bare number, no options. |
| `reveal` | `{"title", "steps": [{"title","detail"}]}`; rendered as native `<details>` |
| `diagram` | `{"svg", "caption"}`; SVG starts with `<svg`, presentation attributes only, no script/style/external URL/image/event handler |
| `simulation` | `title`, `description`, `learning_goal`, `controls[]` (`id`, `label`, `min`, `max`, `step`, `initial`), `default_behaviour` |

The enforcing rules (`factory/checks.py`) are strict about shape and
traceability, not prose:

- `rule_answer_keys`: MCQ index range, `answer == options[answer_index]`,
  numeric answer parses as a number.
- `rule_numbers`: every numeral in a worked-example **problem** or check
  **question** must appear verbatim in the ground truth or primary source
  (boundary-aware: `5` matches `5`/`5.0`, never `15` or `1.5`). Answers and
  options are deliberately not code-checked; the reviewer recomputes them.
- `rule_self_containment`: no "previous chapter", "the textbook",
  "Figure X.Y", "Exercise N", or external URL.
- `rule_diagram_svg`: the SVG law above.
- `rule_shapes`: `steps` is a list of objects (short-circuits the rest).

## 4. Stable IDs

| ID | Shape | Where it is used |
|---|---|---|
| Block id | `b-01` ... `b-45` | DOM `id`, read-aloud keys, review/catcher merge, i18n keys |
| Meta unit | `b-00-meta` | localized lesson title/objectives/glossary |
| Claim id | `claim-01` ... | citations, ground truth, issue reports |
| Equation id | `eq-01` ... | simulation facts, review cross-checks |
| Section id | `sec-01` ... | lesson structure |
| Locale | `en`, `hi`, `hi-Latn` (plus the ADR-0009 locale enum) | translation, routes, manifest |
| Translation unit | `b-00-meta` or `b-NN` | checkpoints, TM, recheck scoping |
| TM key | `sha256(composite)[:64]` | content-addressed translation memory |
| Narration hash | text hash of `lang|voice|spoken-form` | content-addressed audio asset |

Rules:

- **Append, do not renumber.** A correction keeps the id; a new concept gets a
  new id at the end. This is why `04-repair` appends coverage additions.
- **IDs are not display text.** Do not derive a slug, title, or anchor from a
  model headline; topic identity comes from the chapter.
- **A changed source creates a new translation key.** The old TM entry stays
  addressable; do not mutate it in place.
- **A changed spoken text creates a new narration hash.** The old audio asset
  stays addressable; do not overwrite it.

## 5. `manifest.json`

Written by `06-render`, amended by `10d-transrender` and `12-narration`.

Required base fields:

```json
{
  "course_id": "class-9-physics",
  "class": 9,
  "topic_slug": "motion",
  "title": "Motion",
  "lesson_title": "Motion: Describing How Things Move",
  "chapter": {
    "query": "Motion",
    "title": "Motion",
    "book": "NCERT Science Class 9",
    "pages": "100-123",
    "number": 8
  },
  "sources": [{"id": "ncert-science-9", "title": "NCERT Science Class 9", "license": "NCERT (free educational use)"}],
  "run_id": "motion-c9",
  "generated_at": "2026-11-14T00:00:00Z",
  "block_counts": {"text": 8, "check": 5, "simulation": 2}
}
```

Additive locale fields from `10d`:

```json
{
  "default_locale": "en",
  "locales_available": ["en", "hi", "hi-Latn"],
  "titles_by_locale": {"en": "...", "hi": "...", "hi-Latn": "..."},
  "translation_status": {
    "hi": {"status": "verified", "fallback_blocks": [], "glossary_version": "1.0.0"}
  },
  "i18n_hashes": {"hi": "...", "hi-Latn": "..."}
}
```

Additive narration fields from `12`:

```json
{
  "narration": {
    "available": true,
    "lang": "en",
    "hash": "sha256[:16] of the deterministic manifest content (lang, voice, mode, blocks; not generated_at)",
    "mode": "live",
    "blocks": {
      "b-01": {"available": true, "path": "audio/class-9-physics/b-01.en.<hash>.opus", "hash": "...", "duration_ms": 12345}
    }
  }
}
```

`narration-manifest.json` sits next to the topic manifest and lists
`{block_id, lang, hash, chars, duration_ms, path}` per block.

**Known gap (verified 2026-11-14):** `docs/specs/evals/spec.md` §4.3 specifies
`generation_fingerprints` (`sha256` + line count per generated file) in the
manifest for human-edit-rate capture. The current `factory/render.py` /
`factory/link.py` do **not** emit it. Do not cite it as present; add it only
with the owning flow and a test.

## 6. `courses.js` and the catalogue

`write_courses_js(frontend_dir)` is the single generator, reused by
`06-render` (staging) and `11-link` (published). It reads every
`courses/*/*/manifest.json`, builds entries, sorts, and writes
`window.ZIVON_COURSES`.

Entry fields: `href`, `course_id`, `class`, `chapter_number`, `title`,
`chapter`, `generated_at`, plus optional `default_locale`,
`locales_available`, `titles_by_locale`, `translation_status`.

Sort: class ascending, unnumbered last, chapter number ascending, chapter title
casefold, title. This makes the catalogue read in textbook order regardless of
run order.

Rules:

- `courses.js` is generated-only; never hand-edit it.
- A catalogue entry must resolve to a real `index.html`; `11-link` smoke-tests
  every href and every declared locale file.
- A chapter owns one topic directory. `11-link` prunes a stale sibling with the
  same `course_id` and `chapter.title`; the old version survives in git history
  after publish.
- The committed `frontend/` tree is the standalone-deployable snapshot; the
  cluster's `zivon-frontend` PVC is the live generated tree. `scripts/publish-frontend.sh`
  is the bridge. Generated pages are never baked into images.

**Known gaps:** localized hubs currently load the same `courses.js`, whose
hrefs point at the English page (no locale-aware href rewrite); catalogue
entries carry no status/language-coverage/counts/concept/exam-weight metadata.
Both are recorded here (not in the repo's `GAP-###` register); fix through the
owner (`factory/render.py` / `factory/link.py` / shell) with tests.

## 7. Translation artifacts

- **Checkpoint:**
  `runs/<run_id>/10a-translate/blocks/<locale>/<unit_id>.json`, written
  atomically, carrying the `tm_key`. A mismatched `tm_key` invalidates the
  checkpoint.
- **Translation Memory:**
  `sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json`. Two tiers: the PVC
  JSON store and the DB tables (`migrations/versions/0022_translation_memory_c3.py`).
  Only units that pass `10b` are promoted.
- **`tm_key`:** `sha256` of a composite that includes source content, locale,
  prompt version, and glossary hash. A changed source/glossary/prompt creates
  a new key; the old entry remains addressable.
- **Output:** `10a-translate/output.json` =
  `{"locales": {<locale>: {"meta", "blocks": {"blocks": [...]},
  "sim_strings", "unit_status", "fallback_blocks", "stats"}}}`. `10c` writes
  `{"locales": {<locale>: {"page": <the 10a locale dict>, "history": [...]}},
  "rounds": N}` and refreshes `10a` so a resume sees repairs.
- **Issues:** every `10b` issue also lands in the run's
  `issues_ledger.jsonl`; recheck rounds write `combined-<round>.json`.

Do not add a field to a translated payload without adding it to
`TRANSLATED_*_PAYLOAD` and the harness reassembly function; the model must
never own `id`, `type`, `citations`, `answer_index`, numeric answers, or
control geometry.

## 8. Narration artifacts

- **Asset path:** `frontend/audio/<course_id>/<block_id>.<lang>.<hash>.opus`
  (ST-04). 24 kbps mono Opus; an opus input passes through. The hash is a text
  hash of `lang|voice|spoken-form`, so a re-run finds completed work and
  changed text bumps the hash.
- **Manifests:** topic `manifest.json` `narration` block +
  `narration-manifest.json` catalogue (see §5).
- **Budget:** cross-run ledger `runs/narration-budget.json`; per-run usage
  `runs/<run_id>/narration_usage.jsonl`. The A-15 tranche is enforced
  refuse-before-exceed in LIVE mode only; mock builds spend zero credits and
  are never refused.
- **Publish:** `scripts/publish-frontend.sh` mirrors `audio/` additively and
  runs the SYNC-01 cold gate (sha256 read-back) when the cold-store commands
  are configured; without them it reports a loud SKIP. Standalone verify:
  `python -m factory.narration.publish --root frontend/audio --cold`.
- **Single-locale v1:** exactly one locale in `ZIVON_NARRATION_LANGS`; more is
  a hard `NarrationError` before synthesis. Per-locale narration waits on
  translated blocks.

## 9. Versioning and fingerprints

### `PIPELINE_VERSION`

Current `"9"`. Bump it when:

- the stage graph changes (stage added/removed/renamed/reordered);
- a stage's artifact *meaning* changes (a field's semantics, a required block
  shape, the source-pack contract, the reviewfix channel);
- a resumed run could not faithfully continue from an old artifact.

Do **not** bump it for runtime policy: repair caps, rule additions, prompt
wording, eval thresholds, logging fields. Those do not change what an artifact
means. If a new rule must apply to an existing draft, re-run the gate; do not
pretend the version bump is the fix.

### Fingerprint payload

`{pipeline_version, chapter, class, model, limits, retrieval, learner}` plus
`translation` (`target_locales`, `optional_locales`, `prompt_version`,
`glossary_sha256`) only when translation is enabled. A fingerprint mismatch
refuses resume with instructions. This is why changing the model, the config
limits, or the translation glossary invalidates a run directory, while changing
a repair cap does not.

### Schema-change decision table

| Change | Version bump? | Resume impact |
|---|---|---|
| Add an optional output field nobody reads yet | Usually no | Old artifacts still valid; new field appears on the next run |
| Add a field a later stage or the shell reads | Usually yes, or re-render the stage | Old artifacts lack the field; a resumed consumer must handle absence or be re-run |
| Rename/remove/retype a field; change a required field | Yes | Old artifacts are incompatible; `--fresh` |
| Add a deterministic rule | No | Old gate verdicts stand; re-run the gate to apply |
| Change a severity/blocking rule | Treat as contract | Old verdicts may have published; re-review/re-run and document |
| Change a prompt/rubric | No (unless schema) | Re-run the stage; calibrate the eval |
| Change a repair cap | No (deliberately absent) | None |

## 10. Changing a schema safely

1. Read the schema and every producer/consumer (`grep` the field name).
2. Decide additive vs breaking using the table above; write the decision in
   the PR.
3. Update `factory/schemas.py`, the producing stage, every consumer, and the
   SHAPE example in the prompt if the model emits it. The shape example **is**
   the contract; a mismatch between the example and the schema is how a killed
   class-11 run died twice on validation.
4. Add a unit test for valid/invalid shapes and a resume/round-trip test if the
   field crosses a stage.
5. Update `docs/content-factory/blocks-schema.md` (for blocks) and
   `architecture.md` (for the stage table).
6. Add or update an eval golden/`expected.json` if a published artifact changes
   shape.
7. If the change affects what may publish, bump `PIPELINE_VERSION` and say
   `--fresh` in the PR/runbook.

## 11. Known gaps at the evidence date

These are confirmed against code/docs on 2026-11-14; re-verify before acting.

- **No concept/syllabus identity layer.** `concept_id`, `chapter_id`, exam
  weight, difficulty, marks, and expected-time priors are absent from the
  factory's schemas. Everything downstream that needs mastery evidence is
  blocked on this.
- **Renderer hooks incomplete.** `data-block-type` / `data-element-id` and
  rendered `lesson.sections` are not emitted; the shell contract expects them.
- **Catalogue metadata incomplete.** `courses.js` lacks status, per-topic
  language coverage, counts, concepts, and exam weight; no `catalogue.json`.
- **No automated a11y gate.** Accessibility findings depend on the `09-design`
  model review; there is no axe/ARIA assertion.
- **No deterministic numeric/unit recomputation.** Wrong computed answers are
  caught by the model reviewer, not code.
- **`03-check` issues lack a category.** The prompt does not ask for one;
  `factory/agents.py` tags them `content` (the ledger builder's own default is
  `other`), so cross-run analysis collapses this gate.
- **Eval schema and version drift.** `evals/runner.py` hardcodes
  `pipeline_version=1`; `evals/goldens/manifest.json` says 7; actual
  `PIPELINE_VERSION` is 9. Eval telemetry (`EVT-EVAL-*`) has zero rows in the
  instrumentation map and uses a component outside the closed enum. Fix before
  adding new cards.
- **`generation_fingerprints` specified, not emitted** (see §5).
- **Sitemap/robots placeholder and stale.** They are generated by the publish
  flow, not `11-link`; the committed files are placeholder `zivon.local` and
  cover fewer topics than the catalogue. Treat SEO as an owning-flow change.
- **Config reference drift.** `docs/content-factory/config-reference.md`'s
  `stage_overrides` valid-id list omits `12-narration`; the code's `_STAGE_IDS`
  includes it. Fix the doc when touching that area.
