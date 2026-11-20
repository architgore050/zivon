# Class 10 content campaign — the prototype's one-class build

**Status (2026-11-19):** the working prototype for product-market-fit testing covers
**one class only — Class 10** — the four NCERT Physics chapters below. This file is the
tracked execution record for that build: the chapter list, the current state, the
local-only generation rule, and the gates every chapter passes before it publishes.
Recorded by the W5 scope-docs pass; the founder decision it records is dated 2026-11-19
and also lives in the `Status 2026-11-19` blocks of [`TIMELINE.md`](../../TIMELINE.md)
and [`AGENTS.md`](../../AGENTS.md).

Evidence tags follow the repo convention: `[STRONG]` = verified against the committed
repo snapshot; `[ASSUMPTION]` = founder-local state that the committed snapshot cannot
show yet.

## 1. The scope decision (founder, 2026-11-19)

The prototype build target is **Class 10 only** — not all four classes. The older
multi-class scope statements for the prototype (the "Class 9/10 content complete"
milestone wording, and treating the Class 9–12 subject span as the current build
target) are **superseded** for the prototype; they are marked in place in
`AGENTS.md`, `TIMELINE.md`, and `README.md`, and the historical record is not
rewritten. What does not change:

- The **product's subject scope** stays academic Physics, Class 9–12; Class 10 is the
  first full campaign inside it, not a new subject scope.
- The frozen product decisions (`docs/product/`), the wave order, and the compliance
  rules are untouched; this decision narrows the prototype's content scope, it does not
  re-open anything frozen.
- The personalised-learning W5.5 exit gate already targets one Class 10 chapter taught
  end-to-end — this decision makes that gate's class the campaign class.

Why one class `[STRONG]` from the repo's own evidence: the syllabus manifest curates
exactly the four Class 10 chapters with concepts (`sources/syllabus/syllabus.json`,
updated 2026-11-17); the exam pipeline's honest coverage gate already reports the real
backlog shape — Class 10 has a bank for Light only, the other three chapters have zero
questions ([`exam.md`](exam.md) §7); and four published Class 11 chapters sit outside
the prototype's PMF audience. One class done deeply beats four done shallowly.

## 2. The four chapters

Chapter ids and titles are pinned by `sources/syllabus/syllabus.json` (do not rename
them; the assessment and exam pipelines key on the ids):

| # | chapter_id | NCERT chapter | Curated concepts | Lesson | Assessment bank | Translation | Narration |
|---|---|---|---|---|---|---|---|
| 1 | `class-10-light-reflection-and-refraction` | Light – Reflection and Refraction | 7 | **generated** (founder-local, 2026-11-19) `[ASSUMPTION]` | seed bank tracked (15 items + 3 speaking prompts, EN/HI/Hinglish) `[STRONG]` | pending | pending |
| 2 | `class-10-the-human-eye-and-the-colourful-world` | The Human Eye and the Colourful World | 5 | **generated** (founder-local, 2026-11-20) `[ASSUMPTION]` | none (0 questions) `[STRONG]` | pending | pending |
| 3 | `class-10-electricity` | Electricity | 5 | **generated** (founder-local, 2026-11-21) `[ASSUMPTION]` | none (0 questions) `[STRONG]` | pending | pending |
| 4 | `class-10-magnetic-effects-of-electric-current` | Magnetic Effects of Electric Current | 6 | **generated** (founder-local, 2026-11-21) `[ASSUMPTION]` | none (0 questions) `[STRONG]` | pending | pending |

State summary: **all four chapters generated.**

## 3. Current state (2026-11-19), against the committed snapshot

- **All four Class 10 lessons are generated and in the committed snapshot** — 10 topics
  in `frontend/catalogue.json` (Class 9 ×2, Class 10 ×4, Class 11 ×4), each Class 10
  chapter with `missing_locales: []`. The runs themselves stay founder-local
  (`runs/` is gitignored); the committed pages are the snapshot evidence `[STRONG]`.
- **The Human Eye is generated** in a founder-local run on 2026-11-20 (43 blocks,
  EN/HI/Hinglish, `03-check` and `09-review` pass, translation `10b` pass). Its earlier
  failure was the provider output default, not reasoning quality: with
  `reasoning_effort=none` the Go gateway capped output at 8,192 tokens
  (`LengthFinishReasonError`), while `minimal`/`low` spent ~49k reasoning tokens and still
  hit 65,536. The founder-approved fix (`ZIVON_CONTENT_MAX_TOKENS`, default 131,072; the
  model's output limit is 384,000) let the same run finish with `completion_tokens=83,927`
  and `finish_reason=stop`. Thinking effort is now a separate numeric knob
  (`ZIVON_REASONING_EFFORT`, 0=none, 1=low default, 2=high, 3=max), so it can be raised on
  quality grounds without changing the output ceiling. See `TIMELINE.md` (2026-11-20).
- **Electricity is generated** in a founder-local run on 2026-11-21 (45 blocks, EN/HI/Hinglish, one interactive simulation; `03-check` and `09-review` pass, `10b` pass after one bounded `10c` repair).
- **Magnetic Effects is generated** in a founder-local run on 2026-11-21 (42 published blocks, one interactive simulation; `03-check` and `09-review` pass, `10b` pass after one bounded `10c` repair).
- **Assessment:** only Light has a tracked seed bank
  (`sources/syllabus/chapters/class-10-light-reflection-and-refraction.items.json` +
  `.speaking.json`); the other three chapters have no items, which is exactly what the
  exam coverage gate reports as the Class 10 blocker.
- **Series:** a Class 10 pack built today is `publish: blocked` by the volume/coverage
  gate — correct behaviour, not a defect. The gate unblocks when every chapter's bank
  exists (§5.4).
- Light's block-level concept tagging is recorded as `pending_lesson` debt in the W3 P2
  assessment run; a published Light page unblocks it.

## 4. The local-only generation rule

All four Class 10 chapters are generated **on the founder's local machine only**,
against the local single-slot inference endpoint through `llm_manager` — the same
model-call discipline as every factory run (streaming, inactivity timeout,
`ZIVON_CALL_DEADLINE_S` wall-clock backstop). No `k8s/20` factory Job is triggered for
this campaign; the cluster's factory Job path stays reserved for founder-triggered runs
outside the campaign, and generation remains **manual-only, never scheduled** (existing
repo rule).

Commands (runbook: ["Generate a topic"](runbook.md)):

```bash
export ZIVON_BASE_URL=<local OpenAI-format endpoint>   # value is runtime config, never committed
export ZIVON_MODEL=<model id exactly as GET /v1/models reports>
python pipeline.py "Light – Reflection and Refraction" --class 10
python pipeline.py "Light – Reflection and Refraction" --class 10 --locales hi,hi-Latn  # adds 10a..10d translation
```

- Run ids are deterministic per (chapter, class): re-running the same command **resumes**
  the previous attempt with zero model re-calls; `--fresh` wipes the attempt.
- A full happy-path run costs four model calls plus one per simulation (generate,
  check, review-facts, review-design — [`architecture.md`](architecture.md)) — tens of
  minutes on a ~20 tok/s single-slot local server.
- What the rule does **not** change: CI still passes key-free; the cluster test/eval
  CronJobs are untouched; secrets stay runtime-only (env vars / K8s Secrets, never
  files, manifests, or run artifacts).
- Why local-only: model spend stays founder-controlled; the single-slot local server
  would contend with itself if a cluster fan-out ran alongside it; and the review gates
  are identical either way, so nothing is skipped by running locally.

## 5. Gates every Class 10 chapter passes before it publishes

A chapter is "done" only when all six gates below are green. The pipeline's own gates
are unchanged — this section restates them per chapter so the tracker (§7) has one
checklist.

### 5.1 Lesson gates (the pipeline as-is)

`03-check` (fatal must quote the source), `07-perf` (weak-android budgets),
`09-review` (code review verdict=pass), `10-reviewfix` (bounded repair) — see
[`architecture.md`](architecture.md). A gate failure never re-runs the whole pipeline;
catchers repair bounded blocks only.

### 5.2 Translation gate — live lessons are fully translated

The standing rule (Q-2): **a missing translation is a publish failure, not a silent
English fallback.** Each chapter runs the `10a-translate → 10b-transcheck →
10c-transrepair → 10d-transrender` sub-graph with `--locales hi,hi-Latn`; units pass the
nine deterministic rules (`R1`..`R9`) plus the calibrated reviewer gate before entering
the Translation Memory. Contract: [`docs/specs/translation/`](../specs/translation/README.md).
Evidence bar: every published topic today ships `en`/`hi`/`hi-Latn` with no missing
locales `[STRONG]`.

### 5.3 Narration gate — opt-in, budgeted, never mock-published

Stage `12-narration` pre-generates per-block read-aloud at build time (C-051: zero
runtime credits). It is opt-in via `ZIVON_NARRATION_ENABLED=true`; live synthesis needs
`ZIVON_TIMBRE_BASE_URL` + `ZIVON_TIMBRE_API_KEY` and ffmpeg on PATH; the A-15 tranche
(`ZIVON_NARRATION_BUDGET_CREDITS`) refuses spend before it exceeds the cap. Mock assets
(labelled `mode: "mock"`) are never published to the live site; residual block failures
degrade read-aloud to the disabled copy honestly. Runbook: ["Narration builds"](runbook.md).
Reference bar: the committed snapshot carries 623 opus assets under `frontend/audio/` for
the six published topics (149 under `class-9-physics/`, 474 under `class-11-physics/`)
`[STRONG]`; the tranche's credit spend is founder-local ledger data
(`runs/narration-budget.json`, gitignored) `[ASSUMPTION]`.

**Two hard limits, both hit on 2026-11-19 (Light narration attempt):**

- **Single-locale v1.** `ZIVON_NARRATION_LANGS` must name **exactly one** locale — the
  stage raises a `NarrationError` before any synthesis on `en,hi,hi-Latn`
  (`factory/narration/stage.py`). The speakable units are the English lesson forms, so
  `hi`/`hi-Latn` audio needs the translated-block payload (EX2) that does not exist yet:
  per-locale narration is **not** a config flag today, it is unimplemented work.
- **The A-15 tranche is spent.** The ledger stood at **5,997.68 of 6,000** credits before
  the Light attempt; the run narrated 1 of its 44 blocks (81 chars, 1.35 credits) and the
  guard refused the remaining 43 (~418 credits) with the documented
  refuse-before-exceed message. Finishing Light needs ~420 more credits, i.e. a
  founder-approved tranche raise plus a re-trigger (completed blocks skip by content
  hash). Narration does not publish on a partial pass: a 1-of-44 page is not a build.

### 5.4 Assessment gate — practice and speaking banks per chapter

`python -m factory.assessment --chapter <chapter_id>` produces the practice items,
speaking prompts, concept tagging and time priors (stages A1–A6). `--generator seed` is
key-free over tracked curated banks; live generation (`--generator llm`) needs
`ZIVON_BASE_URL` + `ZIVON_MODEL` and is founder-triggered. The campaign requires a bank
for **each** of the four chapters (Light's exists; the other three wait on their lesson
pages for A2 block tagging and on live or curated generation). Contract:
[`assessment.md`](assessment.md).

### 5.5 Series gate — the Class 10 pack publishes only when coverage is real

`python -m factory.exam --class 10 --require-publishable` is the CI/admin gate. The
volume/coverage gate blocks the pack until every Class 10 chapter carries bank items
across the six series (`series.minimum.<series_id>`, `series.chapter_coverage`,
`series.chapter_floor`, `series.concept_coverage` are all major blockers). Compliance
env stays at the defaults: `EXAM_CONTENT_MODE=blueprint_only`,
`SERIES_EXACT_PYQ_ENABLED=false`, `EXAM_VERBATIM_CLEARANCE_ID` empty — the Exact PYQ
series stays dark until `DEC-COMP-001` has a clearance row. Contract: [`exam.md`](exam.md);
compliance: [`docs/compliance/`](../compliance/README.md).

### 5.6 Publish gate — the snapshot mirrors only gated output

`scripts/publish-frontend.sh` mirrors `courses/` + `catalogue.json` + `courses.js` into
the repo's `frontend/` (wholesale-replacing a topic's previous version, which survives
in git history), then `python3 -m factory.catalogue check --frontend-dir frontend
--strict` runs the catalogue/version/locale/hook/SEO smoke. A blocked pack is never
mirrored; a stale mirror exits loudly instead of silently republishing.

## 6. Environment variables (exact names — values and secrets are never committed)

Configuration has two layers: behaviour in `config.json` (committed), endpoints and
secrets in environment variables (runtime-only). Full semantics live in
[`config-reference.md`](config-reference.md) and `.env.example`; the names the campaign
touches:

| Concern | Variables |
|---|---|
| Model endpoint (lesson + live assessment generation) | `ZIVON_BASE_URL`, `ZIVON_MODEL`, `ZIVON_API_KEY` *(secret)*, `ZIVON_JSON_MODE`, `ZIVON_TEMPERATURE`, `ZIVON_TIMEOUT_S`, `ZIVON_STREAM`, `ZIVON_STREAM_USAGE`, `ZIVON_CALL_DEADLINE_S`, `ZIVON_CONNECT_TIMEOUT_S`, `ZIVON_MAX_ATTEMPTS`, `ZIVON_BACKOFF_BASE_S`, `ZIVON_VALIDATION_ROUNDS`, `ZIVON_HEARTBEAT_S`, `ZIVON_CONTENT_MAX_TOKENS`, `ZIVON_REASONING_EFFORT` (+ per-task `ZIVON_REASONING_EFFORT_*`), `ZIVON_EXTRA_HEADERS` |
| Narration / Timbre | `ZIVON_NARRATION_ENABLED`, `ZIVON_NARRATION_MODE`, `ZIVON_NARRATION_LANGS`, `ZIVON_NARRATION_BUDGET_CREDITS`, `ZIVON_NARRATION_REPAIR_ROUNDS`, `ZIVON_TIMBRE_BASE_URL`, `ZIVON_TIMBRE_API_KEY` *(secret)*, `ZIVON_TIMBRE_TTS_PATH`, `ZIVON_TIMBRE_VOICE`, `ZIVON_TIMBRE_CREDITS_PER_CHAR`, `ZIVON_TIMBRE_TIMEOUT_S`, `ZIVON_TIMBRE_CONNECT_TIMEOUT_S`, `ZIVON_TIMBRE_MAX_ATTEMPTS`, `ZIVON_TIMBRE_BACKOFF_BASE_S`, `ZIVON_FFMPEG_PATH` |
| Cold-store verify (SYNC-01, optional) | `ZIVON_COLDSTORE_UPLOAD_CMD`, `ZIVON_COLDSTORE_READBACK_CMD`, `ZIVON_COLDSTORE_PREFIX`, `ZIVON_COLDSTORE_TIMEOUT_S` |
| Exam / series compliance | `EXAM_CONTENT_MODE`, `EXAM_VERBATIM_CLEARANCE_ID`, `SERIES_EXACT_PYQ_ENABLED` |
| Test config override | `ZIVON_CONFIG` |

Rule: the two `*_API_KEY` variables are the only secrets in the table — runtime-only,
never written to any file, image, manifest, or run artifact. No secret values appear in
this file or in any committed artifact.

## 7. Campaign tracker

One row per chapter; update the cell, cite the run id, keep the gate order. A chapter
row is complete when every cell is green and the topic appears in the committed
catalogue with `missing_locales: []`.

| Gate → | Lesson (00–10) | Translation (10a–10d) | Narration (12) | Assessment bank | Series pack contribution | Published in snapshot |
|---|---|---|---|---|---|---|
| Light – Reflection and Refraction | generated (founder-local) `[ASSUMPTION]` | ✅ (EN/HI/Hinglish) | ⛔ blocked (§5.3: tranche spent, single-locale v1) | ✅ seed bank | ⬜ (pack blocked: coverage) | ✅ |
| The Human Eye and the Colourful World | generated (founder-local, 2026-11-20) `[ASSUMPTION]` | ✅ (EN/HI/Hinglish) | ⛔ deferred (narration is English-only and over budget §5.3) | ⬜ | ⬜ (pack blocked: coverage) | ✅ |
| Electricity | generated (founder-local, 2026-11-21) `[ASSUMPTION]` | ✅ (EN/HI/Hinglish) | ⛔ deferred (narration is English-only and over budget §5.3) | ⬜ | ⬜ (pack blocked: coverage) | ✅ |
| Magnetic Effects of Electric Current | generated (founder-local, 2026-11-21) `[ASSUMPTION]` | ✅ (EN/HI/Hinglish) | ⛔ deferred (narration is English-only and over budget §5.3) | ⬜ | ⬜ (pack blocked: coverage) | ✅ |

## 8. Records

- The decision: `Status 2026-11-19` blocks in [`TIMELINE.md`](../../TIMELINE.md) and
  [`AGENTS.md`](../../AGENTS.md) (the multi-class prototype statements carry
  `superseded 2026-11-19` markers there, in place).
- The contract test: `testing/docs/test_class10_scope_docs.py` pins this file's
  required sections, the four chapter ids, the local-only rule, the gate env names, and
  that every relative link in it resolves.
- Generation evidence stays in `runs/` on the founder machine (gitignored); the
  committed evidence is the published snapshot plus this tracker.
