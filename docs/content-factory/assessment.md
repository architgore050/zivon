# Assessment content pipeline (`factory.assessment`)

Status: **landed 2026-11-17 (W3 P2), first dry-run pack for two chapters.**
Entrypoint: `python -m factory.assessment`. Owner workstream: assessment
content (practice, speaking rubrics, concept tagging, time priors).

This is a **separate pipeline from the lesson factory**. A lesson run
(`pipeline.py`, stages `00–12`) must never spend assessment credits, and an
assessment run must never re-derive or touch a published page (HANDSHAKE Q-1,
founder decision 2026-11-15). The two share the repo's model discipline
(`llm_manager` through `factory/llm.py`), the run-artifact discipline
(`runs/<run_id>/<stage>/output.json`, deterministic fingerprints, resume) and
the eval/logging contracts — not the stage graph.

---

## 1. What it produces

For one chapter per run:

| Artifact | What it is | Consumer |
|---|---|---|
| `syllabus.json` | The four-class Physics map: chapter identity, curated concepts, prerequisites, section refs, honest exam-weight status | catalogue (CAT-01), concept graph, coverage checks |
| `concepts.json` | The chapter's concept graph + the P1 `section → curated concept` map + every published lesson block tagged | practice tags, tutor anchoring, DB import |
| `questions.json` | One row per (item, language): prompt, options, answer, explanation, misconception, marks, difficulty, concept, source section, `expected_time_ms` | practice player (F5), question bank (DB import) |
| `speaking.json` | Explain-back prompts: prompt, 3–5 key ideas, model answer, rubric thresholds, per language | speaking practice (F6) |
| `time-priors.json` | Per-question and per-topic expected-time priors with their formula basis | practice timing, SWOT pace (SWOT-01/10) |
| `manifest.json` | Pack identity, counts, coverage, gate verdict, per-file SHA-256, `content_hash` | publish/import gate, admin coverage view |

The pack is written under the run directory and optionally mirrored to
`--export-dir`:

```text
runs/assessment/<run_id>/
  status.json  run_report.json  calls_ledger.jsonl
  A1-syllabus/output.json
  A2-concept-tag/output.json
  A3-practice-items/output.json
  A4-speaking-rubrics/output.json
  A5-time-priors/output.json
  A6-publish-export/output.json
  A6-publish-export/pack/{manifest,syllabus,concepts,questions,speaking,time-priors}.json
```

Run ids are deterministic per chapter (`assessment-<chapter_id>`). Re-running
resumes completed stages; `--fresh` wipes the run directory. A fingerprint over
the assessment pipeline version, chapter id, syllabus digest, tracked chapter
data, the lesson manifest A2 consumed, the generator and (live only) the model
name refuses to resume a directory produced under different inputs.

Every chapter has its own run directory under the shared `runs/assessment/`
root. A targeted stage loads its upstream artifact only from this chapter; the
generic "newest previous run" fallback is refused when the artifact names a
different chapter, so two chapters can never mix in one pack.

A targeted re-run (`--stages A5-time-priors`) marks every stage that consumes
the re-run stage **stale** (`status.json` state `stale`): the old artifact stays
as evidence, but the next full run re-derives it instead of resuming a pack
built from the previous priors. The dependency map is the real data flow (A1
feeds A2–A6; A2/A4/A5 feed only A6; A3 feeds A5 and A6), so re-tagging blocks
does not spend A3 model credits. A targeted run that does not include A6 reports
`question_rows: 0` and an empty `content_hash`; it has not produced a pack.

**DB import** is the pack's runtime consumer and it landed with the W4 foundation
(2026-11-17): `scripts/import_assessment_packs.py` verifies the pack and writes
`question_bank`, `speaking_prompt`, `topic_time_prior`, and an `assessment_pack`
provenance row (db-spec §4.19). Functionally that write path is a later consumer,
so nothing in this pipeline touches `db/`, `backend/`, `frontend/`,
`factory/render.py` or `factory/link.py`; the importer lives outside the
pipeline's package.

---

## 2. Commands

```bash
# key-free dry run (tracked seed data; no model endpoint needed)
python -m factory.assessment --list-chapters
python -m factory.assessment --chapter class-9-describing-motion-around-us
python -m factory.assessment \
  --chapter class-9-describing-motion-around-us \
  --chapter class-10-light-reflection-and-refraction \
  --export-dir runs/assessment-exports

# live generation (Q-10 window; DeepSeek V4.1 Flash via llm_manager)
export ZIVON_BASE_URL=http://127.0.0.1:18090/v1
export ZIVON_MODEL=<model as GET /v1/models reports it>
python -m factory.assessment --chapter <chapter_id> --generator llm

# targeted stage re-run (loads upstream outputs from the previous run)
python -m factory.assessment --chapter <chapter_id> --stages A5-time-priors
```

`--generator seed` (default in `config.json`) reads the tracked curated banks
under `sources/syllabus/chapters/`. `--generator llm` calls the model through
`factory.llm.LLMClient` with the same schema/validation budget as every factory
stage; it needs `ZIVON_BASE_URL` + `ZIVON_MODEL` and never reads a key from a
file. **No live generation was run for the first pack** (the Q-10 window is
founder/infra-triggered); the seed pack is the dry-run deliverable.

---

## 3. Stages and gates

| Stage | Input | Output | Deterministic gate |
|---|---|---|---|
| `A1-syllabus` | `sources/syllabus/syllabus.json` + `sources/catalog.json` | validated syllabus + SHA-256 | unique chapter/concept ids, contiguous order, resolving prerequisites, catalog books, section refs inside the chapter, honest `exam_weight` status |
| `A2-concept-tag` | syllabus chapter + `sources/syllabus/chapters/<chapter>.concept-map.json` + the P1 lesson manifest | concept graph, edges, block tags | every section mapped, every block tagged, no orphan concept, manifest chapter/class agreement |
| `A3-practice-items` | source pack concepts + seed bank (or live generator) | 15–20 base items, tri-lingual | schema, one correct answer, explanation, source book + chapter + the item's own concept sections, known concept, 3 languages + script, no duplicate, count/type/difficulty mix, concept coverage |
| `A4-speaking-rubrics` | concepts + seed bank (or live generator) | 3+ prompts, tri-lingual | 3–5 key ideas per language, key-idea counts agree across languages, model answer present, thresholds ordered, source + concept known, the cited section belongs to at least one of the prompt's concepts |
| `A5-time-priors` | A3 items | per-question + per-topic priors | every row has a prior inside the policy bounds; no prior points at a question outside the bank; topic priors exist for the chapter and every concept |
| `A6-publish-export` | A1–A5 | versioned pack + manifest | refuses to write a pack when any upstream gate failed; per-file hashes; deterministic `content_hash` |

### 3.1 Rule ids (stable; the eval cards assert on them)

**A1** — `syllabus.schema`, `syllabus.classes`, `syllabus.chapter_duplicate`,
`syllabus.chapter_class`, `syllabus.book_unknown`, `syllabus.concepts_thin`,
`syllabus.concepts_unexpected`, `syllabus.concept_duplicate`,
`syllabus.concept_prefix`, `syllabus.section_ref`, `syllabus.exam_weight`,
`syllabus.chapter_number`, `syllabus.chapter_order`,
`syllabus.prerequisite_self`, `syllabus.prerequisite_unknown`.

**A2** — `concept.mapping_unknown`, `concept.section_unmapped`,
`concept.block_unmapped`, `concept.orphan`, `concept.manifest_invalid`,
`concept.manifest_mismatch`, `concept.map_missing`; **minor (debt)**:
`concept.manifest_missing`, `concept.hooks_missing`.

**A3** — `item.schema`, `item.concept_unknown`, `item.source_unknown_book`,
`item.source_off_chapter`, `item.source_concept`, `item.answer.options`, `item.answer.index`,
`item.explanation`, `item.answer.numeric`, `item.answer.distractor`,
`item.language_missing`, `item.language_script`, `bank.schema`,
`bank.chapter_mismatch`, `bank.class_mismatch`, `bank.source_mismatch`,
`item.duplicate_id`, `item.duplicate_prompt`, `bank.count`, `bank.type_mix`,
`bank.difficulty_mix`, `bank.concept_coverage`; **minor (debt)**:
`bank.concept_density`, `bank.answer_balance`.

**A4** — `rubric.schema`, `rubric.chapter_mismatch`, `rubric.prompt_count`,
`rubric.duplicate_id`, `rubric.concept_unknown`, `rubric.source_unknown_book`,
`rubric.source_off_chapter`, `rubric.source_concept`, `rubric.key_ideas`,
`rubric.thresholds`, `rubric.language_script`.

**A5** — `time_prior.schema`, `time_prior.duplicate`, `time_prior.bounds`,
`time_prior.missing`, `time_prior.unknown`, `time_prior.topic_missing`,
`time_prior.topic_scope`.

Severity scale is the repo's: `fatal` / `major` block; `minor` is recorded
debt. A gate failure writes the stage output (including the full gate report)
before the stage is marked failed, so the run stays inspectable.

### 3.2 Catcher behaviour

A3's live generator is re-called at most `assessment.item_repair_rounds`
(default 2) with the blocking findings as context; the loop stops on a genuine
plateau (error count not decreasing). The seed generator has no model to ask, so
it reports a plateau and fails the stage — it never loops silently. A4's live
call enforces its gate inside the model's validation rounds. There is no
whole-pipeline re-run on a gate failure.

---

## 4. Data contracts

Schemas live in `factory/assessment/schemas.py` and are registered in
`factory/schemas.SCHEMAS` (`assessment_*` keys).

### 4.1 Syllabus (`sources/syllabus/syllabus.json`)

Tracked data, not model output. Classes 9–12, NCERT Physics chapters.
Chapter numbers and titles were extracted from the cached NCERT PDFs in
`sources/pdfs/` on 2026-11-17 (Science Grade 9 2025 edition; Science Class X;
Physics Part I/II Classes XI and XII, rationalised editions). Concepts,
prerequisites and section references are curated and reviewed here.

- Curated concepts currently exist for the eight Class 9/10 Physics chapters
  (49 concepts). Classes 11/12 carry chapter identity only and say so
  (`concepts_status: pending_r1_5`); R1.5 owns their practice banks.
- `exam_weight` is **always `null`** with `exam_weight_status:
  pending_p3_blueprint`. P3's CBSE blueprint (SER-02) is the only source of a
  real mark weight; an invented number is worse than an absent one.
- The 2025 Class 9 edition has four Physics chapters (Describing Motion Around
  Us, How Forces Affect Motion, Work Energy and Simple Machines, Sound Waves),
  not the five of the pre-2025 division. The manifest follows the textbook.

### 4.2 Chapter seed bank (`sources/syllabus/chapters/<chapter_id>.items.json`)

One entry per item, all three languages together:

```json
{
  "item_id": "q-c9-motion-001",
  "concept_id": "class-9-describing-motion-around-us-position-distance-displacement",
  "type": "mcq | numeric | assertion_reason",
  "difficulty": "easy | medium | hard",
  "marks": 1,
  "computation_steps": 0,
  "source_ref": {"book_id": "ncert-science-9", "section": "4.1.2", "example": "Fig. 4.4"},
  "answer": {"index": 0},
  "distractor_index": 1,
  "locales": {
    "en": {"prompt": "...", "options": ["..."], "explanation": "...", "misconception": "..."},
    "hi": {"prompt": "...", "options": ["..."], "explanation": "...", "misconception": "..."},
    "hi-Latn": {"prompt": "...", "options": ["..."], "explanation": "...", "misconception": "..."}
  }
}
```

Numeric items use `{"value", "tolerance", "unit"}` and carry no options.
Assertion-reason items carry the four standard options. Every source section
must start with the chapter number; the book must be in `sources/catalog.json`.

### 4.3 Concept map (`sources/syllabus/chapters/<chapter_id>.concept-map.json`)

```json
{
  "chapter_id": "...",
  "lesson_topic_slug": "...",
  "section_concept_map": {"sec-01": "<curated concept id>", "...": "..."},
  "notes": "why the map looks like this"
}
```

P1's `concept_id` (`...-sec-03`) is a section-scoped grouping key, not a
curated syllabus concept. A2 owns the translation and fails on any unmapped
section, any untagged block, or any curated concept that owns no block. The
map is required only when a published lesson manifest exists.

### 4.4 Speaking bank (`sources/syllabus/chapters/<chapter_id>.speaking.json`)

Per prompt: `prompt_id`, `concept_ids`, `source_ref`, `thresholds`
(`pass_ratio`, `strong_ratio`, `min_key_ideas`, `max_duration_s`), and
`locales.{en,hi,hi-Latn}` each carrying `prompt`, 3–5 `key_ideas`, and a
`model_answer` grounded in the cited section.

### 4.5 Export pack

`questions.json` follows REQUIREMENTS §7.3: one row per language with
`question_id` (`<item_id>-<lang>`), `base_item_id`, class/chapter/concept, type,
difficulty, marks, language, `source_type`, `source_ref`, prompt, options
(where applicable), answer, explanation, misconception, `expected_time_ms`,
`status`, `review_mode`, version, generator and run id.

`review_mode: "deterministic"` and `status: "reviewed"` are deliberate: the
first pack passed the deterministic technical gate (Q-6 permits the v1 base
batch to publish on technical gates alone). No human or judged pedagogical
review has happened yet — that is recorded debt, not a claim.

`speaking.json` rows carry the prompt-level `concept_ids` and
`model_answer_source`; key ideas are `{idea_id, text}`. The authored bank does
not carry a per-key-idea concept, so the pack does not invent one from the first
prompt concept.

`manifest.json` carries `pack_version`, the assessment pipeline version, the
run id, counts, coverage (type / difficulty / language / concept / block
tagging), the aggregate gate verdict, per-file SHA-256 + byte size, and a
`content_hash` over the data files. `generated_at` is excluded from the hash, so
an unchanged pack re-exports to the same hash.

---

## 5. Language rules

Practice and speaking carry **EN + HI + Hinglish** (FEATURE-MAP #3). The gate
enforces:

- all three locale blocks on every item and prompt (`item.language_missing`,
  `rubric.*`);
- Hindi text contains Devanagari; `en`/`hi-Latn` contain none
  (`item.language_script`, `rubric.language_script`);
- key-idea counts agree across languages (`rubric.key_ideas`);
- a missing variant fails; there is no silent English fallback.

CBSE-style series are P3 and EN/HI only; this pipeline does not produce them.

---

## 6. Time priors

`A5-time-priors` computes a deterministic prior per question variant
(`formula_version = "tp-v1"`):

```
words       = words(prompt) + words(options)
raw         = (BASE[type] + 260 ms/word + 12 000 ms/step)     # reading + arithmetic
              x DIFFICULTY[difficulty]                        # 0.8 / 1.0 / 1.35
              x (1 + 0.15 x (marks - 1))
              x LANGUAGE[language]                            # en 1.0, hi 1.12, hi-Latn 1.05
prior       = clamp(round(raw / 1000) x 1000, 15 000, 300 000)
```

`BASE` is 45 s for MCQ, 75 s for numeric and 60 s for assertion-reason. Every
prior stores its basis (type, difficulty, marks, language, word count,
computation steps, formula version) so an operator can recompute it. Topic
priors are the mark-weighted mean of the English variants, per chapter and per
concept. This is a starting guess, not a measurement: SWOT replaces it with the
all-student recency-weighted average (FEATURE-MAP #16).

---

## 7. Logging

| Event | When | Fields |
|---|---|---|
| `factory.assessment.run.started` | run edge | `chapter_id`, `class_level`, `generator`, `languages`, `fresh`, `resumed` |
| `factory.assessment.run.completed` | terminal ok | `chapters_count`, `items_count`, `speaking_prompts_count`, `question_rows`, `content_hash`, `latency_ms` |
| `factory.assessment.run.failed` | terminal fail | `failed_stage`, `reason_code`, `error_count`; `error_class` |
| `factory.assessment.pack.written` | A6 wrote + optionally mirrored | `chapter_id`, `base_items`, `question_rows`, `content_hash`, `exported` |
| `factory.stage.start/ok/fail` | every A1–A6 transition | same contract as the lesson factory; `stage` is the A-stage id |

Rows live in `docs/specs/observability/instrumentation-map.csv`; the
observability suite asserts them. No prompt, answer, explanation, learner text
or secret enters a field — only reference ids and counts.

---

## 8. Evals

Additive `EV-ASM-*` cards (Q-5 schema extension, already registered; the
assessment cards are P2's). All are deterministic-first and key-free; no judge
runs in CI.

| Card | Checker | Asserts |
|---|---|---|
| `EV-ASM-001` | `check_practice_pack_integrity` | exported row schema, one correct answer, explanation, source book/chapter/**item concept** section, known concept, unique ids, three language rows per item; five seeded defects must fire their rules (wrong answer, missing explanation, off-chapter concept, duplicate prompt, missing variant) |
| `EV-ASM-002` | `check_chapter_concept_coverage` | four-class syllabus integrity, every curated concept practised, no unknown concept, pack coverage agrees with rows, every published lesson block tagged (no-lesson chapters are recorded as a metric, not a pass) |
| `EV-ASM-003` | `check_difficulty_marks_time_priors` | item count, type minimums, difficulty shares, 1–2 marks band, prior bounds, no orphan prior row, topic priors for the chapter and every concept, hard-not-faster-than-easy sanity; the 900 s seeded prior must fail |
| `EV-ASM-004` | `check_language_completeness` | one row per base item/prompt per language, script rules, source-concept match, 3–5 key ideas with matching counts, golden speaking minimum |

Goldens: `evals/goldens/assessment/<chapter>/expected.json` (ranges, not
generated output: the checker rebuilds the pack from tracked data) and
`evals/goldens/assessment/defects/SD-ASM-*.json` (patches against the real
bank). Registration: `evals/goldens/manifest.json` →
`assessment_goldens` + `assessment_seeded_defect_sets`.

Run the funnel:

```bash
python -m unittest discover -s testing/content_factory/assessment -t .
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
```

---

## 9. Configuration (`config.json` → `assessment`)

| Key | Default | Meaning |
|---|---|---|
| `syllabus_path` | `sources/syllabus/syllabus.json` | tracked map |
| `chapters_dir` | `sources/syllabus/chapters` | seed banks + concept maps |
| `export_dir` | `""` (run dir only) | optional mirror root; each chapter lands in `<export_dir>/<chapter_id>/` |
| `generator` | `seed` | `seed` (key-free) or `llm` (Q-10 endpoint) |
| `languages` | `["en","hi","hi-Latn"]` | fixed; validated |
| `min_items_per_chapter` / `max_items_per_chapter` | `15` / `20` | practice-bank bounds |
| `max_items_per_concept` | `6` | density warning |
| `speaking_prompts_min` | `3` | per chapter |
| `item_repair_rounds` | `2` | bounded live-generation repair |
| `time_prior_min_ms` / `time_prior_max_ms` | `15000` / `300000` | prior bounds |

`load_config(require_server=False)` is the dry-run loader; the lesson pipeline
keeps the hard `ZIVON_BASE_URL`/`ZIVON_MODEL` tripwire. `stage_overrides` may
set a temperature for A1–A6.

---

## 10. Current content and known debt

Shipped in this pass:

| Chapter | Class | Items | Speaking prompts | Question rows | Block tagging |
|---|---|---|---|---|---|
| `class-9-describing-motion-around-us` | 9 | 15 | 3 | 45 | complete (42 blocks) |
| `class-10-light-reflection-and-refraction` | 10 | 15 | 3 | 45 | pending — no published lesson manifest |

Debt, labelled (Q-6: the v1 base batch publishes on technical gates alone):

1. **No live generation yet.** The seed banks are curated, grounded content;
   the live `--generator llm` path is implemented and unit-tested with a fake
   client but has not been run against a model (Q-10 window is founder/infra).
2. **No judged or human pedagogical review.** The deterministic gate is the
   only review; an `EV-ASM` judge card is a later addition.
3. **Class 10 Light block tagging is pending** because no lesson page exists
   for that chapter yet. Question tagging is complete. A2 records the debt; it
   is not a gate pass.
4. **Exam weight is unpopulated** until P3's blueprint lands.
5. **Only two chapters have banks.** The other six curated Class 9/10 chapters
   have concepts but no practice/speaking content yet.
6. **DB import is a manual operator step.** The importer exists and the two
   tracked packs are imported by it, but nothing runs it automatically after an
   A6 export yet: an operator runs `scripts/import_assessment_packs.py` (see
   §11). Wiring it into the publish path is P5/F7's later work.
7. **Class 9 chapter-count delta.** FEATURE-MAP's "5 chapters" counted the
   pre-2025 division; the 2025 textbook has four Physics chapters. The manifest
   follows the book.

Content-quality bar for later passes: per-option misconception feedback on
every distractor, more assertion-reason coverage, and a judged alignment card
against the source chapter.

---

## 11. Database import (W4 foundation)

The pack is the pipeline's output; `scripts/import_assessment_packs.py` is the
only write path from a pack into the hot database. It imports four things
(db-spec §4.19):

| Pack file | Table | Row key |
|---|---|---|
| `questions.json` | `question_bank` | `question_id` (one row per item per language) |
| `speaking.json` | `speaking_prompt` | `(prompt_id, language)` |
| `time-priors.json` → `topics` | `topic_time_prior` | `(chapter_id, scope, scope_id)` |
| `manifest.json` | `assessment_pack` | deterministic id from chapter + content hash |

Per-question priors from `time-priors.json` are already on
`question_bank.expected_time_ms` (A5 fills them), so only the topic priors need
their own table. `syllabus.json` and `concepts.json` are not imported by this
script: the catalogue import (P1/P2) owns `syllabus_chapter`/`concept`.

**Tracked packs.** The first two A6 exports are committed under
`sources/assessment/packs/<chapter_id>/` (six files each, exactly as A6 wrote
them). The exporter still writes to `runs/assessment/...`; mirroring a new pack
into `sources/` is a deliberate, reviewable commit (same pattern as
`publish-frontend.sh` for generated pages), so the DB import is reproducible
from the repo alone.

**Verification before any write** (all-or-nothing per pack):

- every data file's SHA-256 and byte size match `manifest.json`;
- the manifest `content_hash` is recomputed from the per-file hashes;
- the gate verdict is `pass` with `error_count == 0`;
- the manifest `chapter_id` matches the directory name, and every question,
  speaking row, and prior agrees with it;
- question rows carry the required fields, a known type/difficulty/language/
  source type, positive marks, and an answer object; `(base_item_id, language)`
  is unique; the manifest's `question_rows`/`speaking_prompts` counts agree.

A tampered or stale pack is refused whole, so the DB never holds half a pack.

**Idempotency.** Question and speaking rows are upserted by their stable ids and
`assessment_pack` by chapter + content hash, so re-running an unchanged pack
leaves the row counts unchanged. Question rows are never deleted by an import:
learner evidence references `question_id`, and a withdrawn item is retired by
`status`. A chapter's topic priors are replaced (nothing references them).

**Not imported / not stored.** No raw audio (there is no audio column), no
learner data, no attempt rows: the importer only writes content and provenance.

Run it from the repo root (see
`docs/backend/runbooks/assessment-import.md` for the full procedure):

```bash
python3 scripts/import_assessment_packs.py --dry-run        # verify only
python3 scripts/import_assessment_packs.py --db-url sqlite:///zivon.db
ZIVON_DB_URL=postgresql://... python3 scripts/import_assessment_packs.py
```

Tests: `testing/backend/test_assessment_import.py` (integrity, gate, counts,
idempotency, content-hash parity with `factory.assessment.pack`).
