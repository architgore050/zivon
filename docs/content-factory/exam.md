# Exam-pattern pipeline (`factory.exam`, `factory.series`)

Status: **landed 2026-11-17 (W4 P3), blueprint-only.** Entrypoint:
`python -m factory.exam`. Owner workstream: exam ingest, blueprint and series
assembly (`SER-01`…`SER-09`, `SER-13`, `SER-14`; `CNT-07`, `CNT-12`).

This pipeline turns **paper design metadata** into an exam blueprint and the six
approved test series. It is a separate entrypoint from the lesson factory
(`pipeline.py`, stages `00–12`) and from the assessment pipeline
(`factory.assessment`, stages `A1–A6`), for the same reason those are separate:
a lesson run must never spend exam work, an assessment re-run must never
re-derive a series pack, and stopping a series rebuild must never touch a
published page.

> **Compliance posture is structural.** `docs/compliance/decision-log.md`
> `DEC-COMP-001` makes blueprint-only the shipping default and verbatim CBSE
> content a cleared mode. This pipeline therefore **never stores question
> text**: a paper fixture is a design record, the ingest gate rejects a
> text-bearing key, and `EXAM_CONTENT_MODE` fails closed. Read
> `docs/compliance/` before changing anything here.

---

## 1. What it produces

Per run (one run per class, `exam-class-<n>`):

| Artifact | What it is | Consumer |
|---|---|---|
| `E1-ingest/output.json` | One record per paper (year, type, scope, sections, marks, provenance, file hash) + one metadata row per question (no text) | E2, admin review |
| `E2-blueprint/output.json` | Recency-weighted chapter weightage, type mix, section template, question archetypes, honest confidence block | E3, SWOT-07 (later), admin blueprint view (ADM-04) |
| `E3-series/output.json` | Six series manifests + the item pool, each item with `source_type`, `pattern_ref`, similarity record, languages | E4 |
| `E4-publish/pack/` | `papers.json`, `blueprint.json`, `items.json` (one row per item × language), `series.json`, `manifest.json` with the publish decision | F7 test player, DB importer (later), ADM-11 |

Run layout:

```text
runs/exam/exam-class-10/
  status.json  run_report.json
  E1-ingest/output.json
  E2-blueprint/output.json
  E3-series/output.json
  E4-publish/output.json
  E4-publish/pack/{papers,blueprint,items,series,manifest}.json
```

Run ids are deterministic per class. Re-running resumes completed stages;
`--fresh` wipes the run directory. The fingerprint covers the exam pipeline
version, class, syllabus digest, every paper fixture's hash, every item bank's
hash, the content mode, the clearance id, the exact-PYQ flag, and the
blueprint/series/similarity policies — a mismatch refuses resume rather than
mixing two shapes.

---

## 2. Commands

```bash
# inspect the tracked fixtures (no writes, no model)
python -m factory.exam --list-papers

# build both classes (default)
python -m factory.exam

# one class, into a chosen export root
python -m factory.exam --class 10 --export-dir runs/exam-exports

# rebuild from scratch
python -m factory.exam --class 10 --fresh

# targeted stage re-run (loads upstream artifacts from the run directory)
python -m factory.exam --class 10 --stages E4-publish

# CI/admin gate: exit non-zero unless the pack is publishable
python -m factory.exam --class 10 --require-publishable
```

There is **no live-generation switch**. E1–E4 make no model calls: the item
pool is the P2 assessment bank (curated content), and the paper fixtures are
tracked metadata. This is deliberate — a blueprint is derived, not generated;
`DEC-COMP-006` requires generated items to be source-blind, and this pass has
no generator for them. Adding one is a later, separately reviewed change.

`--export-dir` is honoured **only for a publishable pack**. A blocked pack stays
under `runs/exam/<run_id>/E4-publish/pack/` as evidence; mirroring it would be
publishing below the approved threshold (`SER-13`).

---

## 3. Stages and gates

| Stage | Input | Output | Gate |
|---|---|---|---|
| `E1-ingest` | `sources/exam/papers/*.json` | paper records + question metadata rows | schema, no text-bearing key, no PDF/binary in the tree, subject/code/scope per class, marks and section sums, chapter exists and belongs to the class, marks-per-type convention, provenance |
| `E2-blueprint` | E1 + `sources/syllabus/syllabus.json` + `exam.blueprint_years` / `recency_decay` / `include_paper_types` | blueprint per class | papers used exist, every syllabus chapter present, chapter/type/archetype shares sum to 1, section template equals the latest paper's structure **and** every other included paper's, confidence block honest |
| `E3-series` | E2 + P2 banks (`sources/syllabus/chapters/*.items.json`) | six series manifests + items | manifest schema, item schema, source metadata, pattern reference, similarity record, language policy (`en`/`hi`/`hi-Latn` per series), answer shape per type, Hindi script, no duplicate item inside a paper, notice id and copy claims |
| `E4-publish` | E1–E3 | pack + publish decision | re-validates every series manifest and item (the publish gate is not allowed to trust E3), volume/coverage gate, row language, manifest consistency |

### 3.1 Rule ids (stable; the eval cards assert on them)

**E1** — `exam.paper.schema`, `exam.paper.source_text`, `exam.paper.source_file`,
`exam.paper.missing`, `exam.paper.duplicate`, `exam.paper.class_subject`,
`exam.paper.scope`, `exam.paper.set_code` (minor), `exam.paper.provenance`,
`exam.paper.question_count`, `exam.paper.marks_sum`, `exam.paper.sections`,
`exam.paper.question_no`, `exam.paper.year_window` (minor),
`exam.question.marks_type`, `exam.question.chapter_unknown`,
`exam.question.chapter_class`.

**E2** — `blueprint.schema`, `blueprint.papers`, `blueprint.chapter_unknown`,
`blueprint.chapter_uncovered` (major), `blueprint.share_sum`,
`blueprint.type_mix`, `blueprint.section_template`, `blueprint.archetype`,
`blueprint.confidence` (minor).

**E3/E4 item and manifest rules** — `series.item.schema`,
`series.item.source_type` (schema), `series.item.verbatim_in_blueprint`,
`series.item.licence_basis`, `series.item.third_party`, `series.item.source_ref`,
`series.item.pattern_ref`, `series.item.similarity`,
`series.item.similarity_missing`, `series.item.concept`, `series.item.marks`,
`series.item.chapter`, `series.item.language`, `series.item.answer`,
`series.item.duplicate`, `series.item.missing`, `series.manifest.schema`,
`series.paper_duplicate`, `series.copy.notice`, `series.copy.claim`,
`series.status.exact_pyq`, `series.row.schema`, `series.row.language`,
`pack.mode_mismatch`, `pack.verbatim_without_clearance`.

**Volume/coverage** — `series.minimum.<series_id>` (major),
`series.chapter_coverage` (major), `series.chapter_floor` (major),
`series.concept_coverage` (major), `series.paper_structure` (fatal),
`series.language` (fatal).

Severity scale is the repo's: `fatal` / `major` block, `minor` is recorded debt.

### 3.2 Catcher behaviour

There is none, and that is correct: no stage calls a model, so there is nothing
to ask again. A gate failure writes the stage's output *and* its report before
the stage is marked failed, so the run stays inspectable; nothing downstream
runs on a failed stage; the next attempt resumes from the failure, never from
scratch.

---

## 4. Data contracts

Schemas live in `factory/exam/schemas.py` and are registered in
`factory.schemas.SCHEMAS` (`exam_*` keys).

### 4.1 Paper metadata fixture (`sources/exam/papers/<paper_id>.json`)

```json
{
  "schema_version": 1,
  "paper_id": "cbse-c12-physics-2024-main",
  "board": "CBSE",
  "class_num": 12,
  "subject": "Physics",
  "subject_code": "042",
  "year": 2024,
  "paper_type": "main",
  "set_code": null,
  "language": "en",
  "scope": "full_paper",
  "max_marks": 70,
  "duration_min": 180,
  "sections": [{"id": "A", "marks_each": 1, "question_count": 16}],
  "questions": [
    {"no": "1", "section": "A", "type": "mcq", "marks": 1,
     "chapter_id": "class-12-electric-charges-and-fields"}
  ],
  "provenance": {
    "basis": "public_blueprint",
    "question_map_basis": "authored_estimate",
    "source_url": "https://www.cbse.gov.in/cbsenew/question-paper.html",
    "retrieved_at": "2026-11-17",
    "verified": false,
    "notes": "..."
  }
}
```

There is **no text field**, by design: no prompt, no options, no answer, no
passage. The gate also scans the whole document for a text-bearing key under
any name (`exam.paper.source_text`), so a fixture cannot smuggle source text in
through an unexpected property. `sources/exam/README.md` carries the data
policy and says exactly what is authored versus observed.

Class identity is enforced, not inferred: Class 10 is `Science`/`086` with
`scope: physics_section` (the Physics part of the Science paper, 27 of 80
marks); Class 12 is `Physics`/`042` with `scope: full_paper` (70 marks).

Marks-per-type follows the paper template: `mcq` 1, `assertion_reason` 1,
`numeric` 1–2, `very_short` 2, `short` 3, `case_based` 4, `long` 5. A paper
that breaks it is either mistyped or a different design — a human updates the
template instead of the gate guessing.

### 4.2 Blueprint (`blueprint.json`)

- `papers_used`, `window`, `recency.weights` — every paper that contributed and
  its weight.
- `chapters[]` — `weighted_marks`, `share` (sums to exactly 1.0 by
  construction), `papers_observed`.
- `type_mix[]` — the same, per response mode.
- `section_template[]` — the current paper design (sections, marks, counts).
- `archetypes[]` — `chapter × type × marks` weighted frequency, sorted; this is
  what the Loop series drills and what `pattern_ref` names.
- `confidence` — `verified_papers`, `unverified_papers`,
  `question_map_basis`. Today every fixture is `authored_estimate`, so the block
  says so and the gate records `blueprint.confidence` as `minor` debt.

Recency weighting is explicit:

```
weight(year) = recency_decay ** (latest_year - year)
```

with `recency_decay` from config (default `0.8`). The eval checker recomputes
every weighted number from the raw rows and the declared weights.

### 4.3 Items and rows

An authored item carries:

```json
{
  "item_id": "exam-q-c10-light-001",
  "base_item_id": "q-c10-light-001",
  "origin": "assessment_bank",
  "class_level": 10,
  "chapter_id": "class-10-light-reflection-and-refraction",
  "concept_id": "class-10-light-reflection-and-refraction-reflection-of-light",
  "type": "mcq",
  "difficulty": "easy",
  "marks": 1,
  "section": null,
  "languages": ["en", "hi", "hi-Latn"],
  "locales": {"en": {"prompt": "...", "options": ["..."], "explanation": "..."}},
  "answer": {"index": 0},
  "source_type": "generated_blueprint",
  "source_ref": null,
  "licence_basis": "none",
  "permission_ref": null,
  "pattern_ref": "class-10-light-reflection-and-refraction:mcq:1",
  "similarity": {"ngram": 8, "corpus_size": 0, "max_ngram_overlap": 0.0,
                 "shared_ngram": false, "verdict": "vacuously_clear",
                 "nearest_source_item_id": null, "checked_at": "..."},
  "series_ids": ["ai_lesson", "board_practice", "loop", "pyq_pattern"]
}
```

`items.json` is one row per `(item, language)`, with `series_ids` filtered to
the series that actually offer that language — a Class 10 board-style series
never exports a Hinglish row, and a row never names a series that does not
offer its language.

`item_id` is `exam-` + the P2 `item_id`, so traceability to the assessment bank
survives.

### 4.4 Series manifest (`series.json`)

`series_id`, `label` (English; the frontend owns localized display copy),
`label_key`, `purpose`, `status` (`active` | `disabled`), `enabled`,
`disabled_reason`, `language_policy`, `source_policy`, `notice_id`, `copy`,
`minimum`, `delivered`, `gap`, `item_ids`, `papers[]`, `sets[]`,
`marks_total`, `duration_min`.

A full-paper series' `papers[].sections[]` is a **slot list**: every slot names
its section, type, marks, allocated chapter and the item that fills it (or
`null`). An unfillable slot stays empty — the assembler never borrows a
question from another chapter, because that would make the paper look complete
and let chapter coverage pass on a chapter the paper never teaches.

### 4.5 Pack manifest (`manifest.json`)

`pack_version`, `exam_pipeline_version`, `run_id`, `generated_at`, class and
subject, `content_mode`, `notice_version`, `compliance`, counts, `coverage`,
`publish`, `gate`, `content_hash`, `files`.

`compliance` records: mode, clearance id and presence, `verbatim_allowed`,
exact-PYQ visibility and status, the notice ids in use, verbatim/third-party
item counts, and `source_corpus_items: 0` with the similarity policy. That
number is the honest one: blueprint mode stores no source text, so the
similarity gate is **vacuously clear** and the manifest says so rather than
implying a comparison happened.

---

## 5. The six series

| Series | Source policy | Languages | Notice | Purpose |
|---|---|---|---|---|
| `ai_lesson` | generated, from lesson concepts | EN/HI/Hinglish | N-01 | Chapter tests + mixed practice: does the student understand what was taught? |
| `pyq_pattern` | generated to blueprint archetypes | EN/HI | N-01 | Recurring exam shapes, close to the paper pattern |
| `exact_pyq` | curated verbatim | EN/HI | N-03 when cleared | **Dark** until a clearance record exists |
| `board_practice` | blueprint + generated | EN/HI | N-01 | Full-paper rehearsal: same sections, marks, duration |
| `challenge` | generated hard items | EN/HI/Hinglish | N-01 | Stretch practice |
| `loop` | high-frequency archetypes | EN/HI/Hinglish | N-01 | Drill the shapes that keep appearing |

Approved minimums (`FEATURE-MAP` §12.2, enforced verbatim; identical for
Class 10 and 12):

| Series | Minimum |
|---|---|
| `ai_lesson` | 20 questions/chapter + 1 chapter test/chapter + 2 mixed tests |
| `pyq_pattern` | 5 full papers + 10 chapter/unit tests |
| `exact_pyq` | 5 years (main + compartment) — only when cleared |
| `board_practice` | 5 full papers |
| `challenge` | 100 hard questions (10 sets of 10) |
| `loop` | 100 frequent-pattern questions (10 sets of 10) |

Coverage rules: every chapter in every full-paper series; every concept in AI
Lesson and in at least one of Challenge/Loop; no chapter under 10 distinct
questions across all series; each full paper's section structure equals the
blueprint template.

**Series assembly is deterministic.** Chapter-to-slot allocation is a
largest-remainder allocation over blueprint shares (so every weighted chapter
appears before any chapter exceeds its target); item selection cycles through
chapters and concepts (so coverage is by construction, not luck); each paper is
filled from a pool rotated inside every chapter (so five papers are not the
same five questions in the same order) and never repeats an item inside one
paper. `series.paper_duplicate` blocks a pack in which two complete papers are
the same item set: one paper repeated is not a second paper.

---

## 6. Compliance posture

### 6.1 Modes and flags

| Flag | Values | Default | Behaviour |
|---|---|---|---|
| `EXAM_CONTENT_MODE` | `blueprint_only` \| `attributed_verbatim` | `blueprint_only` | Gates every verbatim publish path |
| `EXAM_VERBATIM_CLEARANCE_ID` | string or empty | empty | Must match a row in the clearance register; empty blocks `attributed_verbatim` |
| `SERIES_EXACT_PYQ_ENABLED` | `true` \| `false` | `false` | Hides the past-year series entirely until mode + clearance are set |

The build **fails closed**: an unknown mode, `attributed_verbatim` without a
clearance id, a clearance id that resolves to no row, an unreadable boolean, or
the exact-PYQ flag turned on while verbatim is not cleared is a startup error.

### 6.2 The clearance register is scoped

`EXAM_VERBATIM_CLEARANCE_ID` must equal a `clearance_id` in
`docs/compliance/decision-log.md#clearance-register`. The row's scope cell must
name the class, subject, year(s) and language(s) so the publish gate can verify
it, e.g. `Class 12 / Physics / 2022-2026 / en, hi`. An unparseable or partial
scope refuses: the parser is not counsel. Today the register is empty, so
`attributed_verbatim` cannot start and `exact_pyq` stays `disabled`.

### 6.3 What a verbatim item would need

`verbatim_*` items are rejected unless: the run is `attributed_verbatim`; a
licence basis (`written_permission` or `counsel_opinion`) and a permission
reference equal to the active clearance are recorded; the source ref carries
`source_url`, `retrieved_at`, `file_sha256` and `page`; and
`third_party_content` is false (`DEC-COMP-005`). The exact-PYQ series needs
N-03 and its copy is the approved intro, never a generated blurb.

### 6.4 Copy

`factory/exam/notices.py` holds the approved `N-01`…`N-05` strings and the
placeholder contract. `testing/content_factory/exam/test_notices.py` parses
`docs/compliance/notices.md` and fails if a template drifts by one character.
An unresolved `{{token}}` or a missing value is an error, never a blank.

Generated series copy says what the series is and is not — “close to the paper
pattern”, “built for practice”, “not an official CBSE paper”. `scan_claims`
finds the forbidden positive claims (`official CBSE`, `CBSE-approved`,
`affiliated with CBSE`, `in partnership with CBSE`, `previous year question`,
`past paper`, `PYQ`, `exact CBSE`, `actual board paper`, `exact reproduction`)
and understands a negated sentence as the approved disclaimer. It runs on every
series label/purpose/copy and every item prompt in every locale.

### 6.5 Similarity

`factory/exam/similarity.py` implements `DEC-COMP-006`'s control: normalise
(lowercase, punctuation stripped, whitespace collapsed, digits mapped to `#`),
8-word shingles, block when a generated item shares an 8-gram with a stored
source item or when Jaccard exceeds the configured maximum (`0.20`). In
blueprint mode the corpus is empty, so the gate is `vacuously_clear` and the
record says `corpus_size: 0`. The gate is a copying-prevention control, not
legal clearance, and the docs say so in both places.

### 6.6 Takedown

P3 ships the **pack-side** half: an item can be removed from the pool by
deleting it from the series manifests and re-publishing (the pack mirrors
wholesale, so removal is atomic). The public route, the ticket and the register
entry belong to the admin feature (F10); the instrumentation map reserves
`exam.takedown.received` for it. The process itself is
`docs/compliance/notices.md` §Removal path.

---

## 7. Volume, coverage and honest gaps

The gate is built and proven in both directions:

- `EV-SER-002` and `testing/content_factory/exam/test_volume.py` assemble a
  **synthetic full-syllabus bank** (clearly labelled, temp directory, never
  published) for every chapter of a class and assert the pack becomes
  `publish: ready` — 5 complete and distinct full papers, 100 Challenge
  questions, 100 Loop questions, every chapter in every paper at the approved
  minimums;
- the same gate on the **shipped prototype** fails, and the blockers name the
  gap: Class 10 has banks for Light only (`class-10-light-reflection-and-refraction`),
  so the human eye, electricity and magnetic effects chapters have zero
  questions; Class 12 has no banks at all, so all 14 chapters are empty.

That is the honest state of the content backlog, surfaced as data instead of a
token sample. A blocked pack is never mirrored; `--require-publishable` turns
the block into a non-zero exit for CI/admin use.

---

## 8. Logging

| Event | When | Fields |
|---|---|---|
| `factory.exam.run.started` | run edge | `class_level`, `content_mode`, `exact_pyq_enabled`, `clearance_id`, `fresh`, `resumed` |
| `factory.exam.run.completed` | terminal ok | `class_level`, `papers_count`, `items_count`, `series_count`, `question_rows`, `publishable`, `content_hash` |
| `factory.exam.run.failed` | terminal fail | `failed_stage`, `reason_code`, `error_count`; `error_class` |
| `factory.exam.pack.written` | E4 wrote the pack | `class_level`, `base_items`, `question_rows`, `publishable`, `content_hash` |
| `exam.item.ingested` | one per ingested metadata row | `paper_id`, `class_level`, `chapter_id`, `type`, `marks` |
| `exam.publish.blocked` | a compliance reason blocks publish | `class_level`, `reason_codes`, `blockers_count` |
| `exam.series.blocked` | volume/structure blocks publish | `class_level`, `reason_codes`, `blockers_count` |
| `factory.stage.start/ok/fail` | every E1–E4 transition | same contract as the lesson factory; `stage` is the E-stage id |

Rows live in `docs/specs/observability/instrumentation-map.csv`; the
observability suite asserts them. `exam.item.ingested` is safe by construction:
the artifact has no question text to leak. No prompt, answer, explanation,
learner text or secret enters a field.

---

## 9. Evals

Deterministic-first, key-free, no judge (a provenance check does not need a
model). Cards: `EV-EXM-001` (ingest fidelity), `EV-SER-001` (blueprint
alignment), `EV-SER-002` (coverage/volume), `EV-SER-003` (copy/source
compliance). Each checker rebuilds the artifact through the real E1–E4 stage
functions, so an eval cannot drift from the code it measures.

Goldens: `evals/goldens/exam/<class>/expected.json` (paper counts by type,
chapter universe, section template, scope marks, type-weight minimums, approved
minimums, expected gaps, dark series) and
`evals/goldens/exam/defects/SD-EXM-*.json` / `SD-SER-*.json` (patches against
the shipped fixtures/artifacts; each must make its declared rule fire).

```bash
python -m unittest discover -s testing/content_factory/exam -t .
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
```

---

## 10. Configuration (`config.json` → `exam`)

| Key | Default | Meaning |
|---|---|---|
| `papers_dir` | `sources/exam/papers` | tracked paper metadata fixtures |
| `syllabus_path` | `sources/syllabus/syllabus.json` | chapter universe (P2-owned) |
| `chapters_dir` | `sources/syllabus/chapters` | item pools (P2-owned) |
| `decision_log_path` | `docs/compliance/decision-log.md` | clearance register source |
| `export_dir` | `""` (run dir only) | mirror root for a publishable pack |
| `content_mode` | `blueprint_only` | default; env `EXAM_CONTENT_MODE` overrides |
| `verbatim_clearance_id` | `""` | default; env `EXAM_VERBATIM_CLEARANCE_ID` overrides |
| `exact_pyq_enabled` | `false` | default; env `SERIES_EXACT_PYQ_ENABLED` overrides |
| `blueprint_years` | `5` | weighting window |
| `recency_decay` | `0.8` | per-year weight multiplier |
| `include_paper_types` | `["main", "sample"]` | which ingested papers contribute to weightage |
| `chapter_question_floor` | `10` | distinct questions per chapter across all series |
| `chapter_test_size` / `mixed_test_size` | `10` / `20` | AI Lesson test shapes |
| `unit_test_size` | `10` | PYQ-pattern chapter/unit test size |
| `set_size` | `10` | Challenge/Loop set size |
| `similarity_ngram` / `similarity_max_overlap` | `8` / `0.2` | `DEC-COMP-006` control |

The dry-run loader is `load_config(require_server=False)`; this pipeline never
reads a model endpoint.

---

## 11. Current content and known debt

Shipped in this pass:

| Class | Papers | Item banks used | Items | Question rows | Publish |
|---|---|---|---|---|---|
| 10 | 7 (5 main + 1 compartment + 1 sample) | 1 of 4 chapters (Light) | 15 | 45 | **blocked** — volume/coverage |
| 12 | 7 | 0 of 14 chapters | 0 | 0 | **blocked** — volume/coverage |

Debt, labelled:

1. **The question-to-chapter map is authored, not verified.** The fixtures
   follow the published paper design (sections, counts, marks, type mix) but
   the per-question chapter assignment is a curated estimate, because verifying
   it would mean reading a paper. Every blueprint records
   `question_map_basis: authored_estimate` and the gate logs
   `blueprint.confidence` as `minor`.
2. **No set codes.** `set_code` is `null` because no paper was ingested; the
   gate records `exam.paper.set_code` as `minor`. A verbatim item would need a
   real set code before it could publish.
3. **No subjective item authoring.** The P2 banks carry objective items
   (MCQ/assertion-reason/numeric), so 3-, 4- and 5-mark slots in
   `board_practice`/`pyq_pattern` stay empty on real data. The synthetic
   fixture proves the assembler handles those slots; authoring real ones is a
   content task, not a pipeline gap.
4. **Exact PYQ is dark by design**, not by omission: the series exists in the
   catalogue with `status: disabled` and `disabled_reason:
   no_verbatim_clearance`, and the gate refuses to enable it without a
   clearance row.
5. **No DB import.** The pack is JSON; F0's importer is the later consumer.
6. **No frontend rendering.** F7 owns the series UI, the localized labels and
   the notice placement; the pack supplies `label`, `label_key`, `notice_id`
   and `copy`.
7. **`syllabus.json` `exam_weight` is still `null`.** P3 now produces a real
   mark weight, but the syllabus is P2-owned; wiring `blueprint.chapters[].share`
   into `exam_weight` is a P2 follow-up (a one-field consumer change), not a
   silent cross-workstream edit.
8. **One blueprint window, one template.** The fixtures reuse the current
   paper design for every year; per-year structural variation (e.g. the
   2022–23 two-term year) is not modelled. When a real ingest lands, the
   section template check will force the question.
9. **No judged review.** Item quality is P2's deterministic gate plus the
   blueprint alignment; `EV-EXM`/`EV-SER` are provenance and volume checks, not
   pedagogy. A judge card is a later addition.

## 12. Out of scope (and who owns it)

- Rendering the series, the notice placement and localized labels — F7.
- Admin blueprint/series/coverage screens — F10 (`ADM-04`, `ADM-05`,
  `ADM-11`); this pipeline writes the artifacts they read.
- DB tables and import — F0's later consumer.
- SWOT exam-weight integration — F8, consuming `blueprint.json`.
- Verbatim ingest — blocked on `DEC-COMP-001` clearance; the schema, the gate
  and the dark path already exist.
