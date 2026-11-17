# 2026-11-17 — W4 P3 exam ingest, blueprint and the six series

Branch: `feature/w4-p3-exam-series` (based on `main` @ `dc2b972`).

## Done

- **`factory/exam/`** (stages `E1-ingest`, `E2-blueprint`): paper **metadata**
  fixtures only (no question text anywhere in the schema or the tree), the
  compliance mode gate, the clearance-register parser, the approved notices,
  the similarity control, the deterministic validators and the E1–E4
  orchestrator + CLI (`python -m factory.exam`).
- **`factory/series/`** (stages `E3-series`, `E4-publish`): the six series
  (AI Lesson, PYQ Pattern, Exact PYQ, Board Practice, Challenge, Loop) with
  their approved languages/minimums, deterministic slot assembly, the
  volume/coverage gate, and the pack + publish decision.
- **Compliance is structural:** `EXAM_CONTENT_MODE=blueprint_only` by default;
  `attributed_verbatim` without a clearance row, an unknown mode, or the
  exact-PYQ flag without clearance are startup errors. Exact PYQ ships
  `disabled` with `disabled_reason: no_verbatim_clearance`. `verbatim_*` items
  are refused in blueprint mode and need licence basis + permission ref +
  source ref when the mode is ever cleared. Generated items carry
  `source_type`, `pattern_ref` and a similarity record; with no stored source
  text the record says `vacuously_clear` / `corpus_size: 0` instead of implying
  a comparison.
- **Data:** 14 tracked paper-design fixtures (Class 10 Science Physics section
  ×7, Class 12 Physics ×7; 2022–2026 main + 2024 compartment + 2026 sample),
  each with `provenance` saying the section template follows the published
  design and the question-to-chapter map is an authored estimate.
- **Honest gate:** the shrunk prototype is **blocked** — Class 10 has a bank
  for Light only, Class 12 has none — and the manifest names every missing
  chapter and series. A synthetic full-syllabus bank (temp-only, labelled,
  never published) makes the same gate pass for both classes, so the bar is
  real rather than impossible. `--require-publishable` turns a block into a
  non-zero exit; a blocked pack is never mirrored.
- **Tests:** `testing/content_factory/exam/` (149 tests: config/mode gate,
  ingest, blueprint, series, volume, notices, publish, pipeline/resume/CLI,
  evals, docs contract). `ruff`, `ruff format`, `mypy` clean.
- **Evals:** `EV-EXM-001`, `EV-SER-001..003` cards + `evals/checkers/exam_checks.py`
  + `evals/goldens/exam/` (2 class goldens, 11 seeded defects), registered in
  `evals/goldens/manifest.json`. Deterministic-first, zero model calls.
- **Observability:** 8 map rows (`factory.exam.run.*`,
  `factory.exam.pack.written`, `exam.item.ingested`, `exam.publish.blocked`,
  `exam.series.blocked`, plus the reserved `exam.takedown.received`).
- **Docs:** `docs/content-factory/exam.md` (full contract), config-reference
  `exam` section, runbook section, `docs/specs/evals/spec.md` matrix + P3
  paragraph, compliance README status, memo §7 status line, `AGENTS.md` doc map
  and pipeline list, `sources/exam/README.md`.

## Not done (owned elsewhere / later)

- Wiring `blueprint.chapters[].share` into `sources/syllabus/syllabus.json`'s
  `exam_weight` — the syllabus is P2-owned; this is a one-field follow-up, not
  a cross-workstream edit.
- Real item authoring: the P2 banks are objective (MCQ/assertion-reason/
  numeric), so 3/4/5-mark board slots stay empty on real data. The assembler
  handles them (proven by the synthetic fixture); the content is a later batch.
- F7 series UI/localized labels/notice placement; F10 admin blueprint,
  series and coverage screens; F0 DB import; F8 SWOT exam-weight integration.
- Verbatim ingest and the exact-PYQ launch — blocked on `DEC-COMP-001`
  clearance. The schema, gate and dark series already exist.
- A judged item-quality card (`EV-EXM`/`EV-SER` are provenance/volume checks,
  not pedagogy).

## Next

- Run `python -m factory.exam --require-publishable` as the admin/CI gate once
  the content backlog makes a class publishable end to end.
- When the first real clearance lands: add the register row with a parseable
  scope (`Class 12 / Physics / 2022-2026 / en, hi`), then flip
  `EXAM_CONTENT_MODE` and `SERIES_EXACT_PYQ_ENABLED` in the deployment env.
