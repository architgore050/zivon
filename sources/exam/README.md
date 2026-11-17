# `sources/exam/` — exam-pattern metadata (no papers)

This folder holds **pattern metadata**, never source text. It exists so the
exam/series pipeline (`factory/exam`, `factory/series`) can derive a blueprint
and assemble series **without ingesting a single CBSE question**.

> **Compliance first.** `docs/compliance/decision-log.md` `DEC-COMP-001` says
> blueprint-only is the shipping default and verbatim CBSE content needs a
> clearance record. The operative contract for this folder is
> `docs/content-factory/exam.md` §4 and §6, plus
> `docs/compliance/cbse-exam-content.md` §5's content-type matrix: *derived
> pattern metadata* (marks, type, chapter, difficulty) is reusable; *source
> text* is not. A `.pdf` in this tree is a gate failure.

## What a paper fixture is

`papers/<paper_id>.json` describes one paper's **design**:

| Field | Meaning |
|---|---|
| `paper_id` | stable id, `cbse-<class>-<subject>-<year>-<type>` |
| `class_num` | `10` (Science, Physics section) or `12` (Physics) |
| `subject`, `subject_code` | `Science`/`086` or `Physics`/`042` |
| `year`, `paper_type` | `main`, `compartment`, `sample` |
| `scope` | `full_paper` (Class 12) or `physics_section` (Class 10) |
| `max_marks`, `duration_min` | the paper's own totals |
| `sections[]` | section id, marks per question, question count |
| `questions[]` | `{no, section, type, marks, chapter_id}` — **no text, no options, no answer** |
| `provenance` | where the design came from, whether it was verified, and what is an estimate |

`questions[].chapter_id` points at `sources/syllabus/syllabus.json`. The ingest
gate rejects a chapter that is missing or belongs to another class.

## What these fixtures are — and are not

They are **prototype fixtures**, and they say so in `provenance`:

- `basis: "public_blueprint"` — the section structure, question counts, marks
  and type mix follow the published paper design (the templates the pipeline
  enforces: A–E, 16/5/7/2/3 questions for Class 12 Physics at 70 marks; the
  Physics section of the Class 10 Science paper at 27 of 80 marks).
- `question_map_basis: "authored_estimate"` — the **question-to-chapter map is
  a curated estimate**, not a transcription of the actual paper. The blueprint
  computes chapter weightage from this map, so the weightage is internally
  consistent and honest about its source; the gate records
  `blueprint.confidence` as a `minor` finding while any paper is unverified.
- `set_code: null` — no paper was ingested, so no set code is claimed. The gate
  records `exam.paper.set_code` as `minor` debt for main/compartment papers.
- `verified: false` — nothing here has been checked against a real paper,
  because checking it would mean storing or reading one.

When a clearance exists (`DEC-COMP-001`), the real ingest replaces these
fixtures: same schema, plus a verified question map, set codes, page numbers,
source URLs and file hashes. The pipeline does not change; only the data and
the `source_type` of the items do.

## Files

| Pattern | Content |
|---|---|
| `papers/cbse-c12-physics-<year>-main.json` | Class 12 Physics, 2022–2026 |
| `papers/cbse-c12-physics-2024-compartment.json` | Class 12, compartment 2024 |
| `papers/cbse-c12-physics-2026-sample.json` | Class 12 official SQP design |
| `papers/cbse-c10-science-<year>-main.json` | Class 10 Science, Physics section, 2022–2026 |
| `papers/cbse-c10-science-2024-compartment.json` | Class 10, compartment 2024 |
| `papers/cbse-c10-science-2026-sample.json` | Class 10 official SQP design |

The blueprint's default window is five years and includes `main` + `sample`
papers; the compartment fixtures are ingested (so paper-type handling is tested)
but excluded from weighting (`config.json` `exam.include_paper_types`).

## Adding a paper

1. Copy the structure of an existing fixture; do not add a field.
2. Keep `provenance` truthful — `verified: false` until a human has compared it
   to the paper.
3. Run `python -m factory.exam --list-papers` and then
   `python -m unittest discover -s testing/content_factory/exam -t .`.
4. The ingest gate will reject a text-bearing key, a wrong marks sum, an
   unknown chapter, or a section whose counts disagree with its questions.
