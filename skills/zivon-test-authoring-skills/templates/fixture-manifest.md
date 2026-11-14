# Fixture manifest

One row per non-obvious fixture, golden, recorded artifact, or seeded defect.
Keep this with the fixture (a `README.md` beside the folder or a section in the
suite README). The goal: the next agent can tell whether the fixture is still
valid without reading the test that uses it.

## 1. Fixture rows

| ID | Path | Purpose | Source / provenance | Deterministic? | Secrets / PII | Size | Used by | Refresh trigger | Owner | Verified |
|---|---|---|---|---|---|---|---|---|---|---|
| FX-001 | `testing/<area>/fixtures/<name>.json` | Valid `03-check` handoff for the schema test | Hand-written from the documented schema, 2026-11-14 | yes | none | 4 KB | `testing/<area>/unit/test_schemas.py` | schema version change | `<owner>` | 2026-11-14 |
| FX-002 | `testing/<area>/fixtures/pdfs/<name>.pdf` | Ingest/locate fixture | Built by `make_pdfs.py`; reproducible | yes | none | 12 KB | integration ingest test | PDF parser or fixture script change | `<owner>` | 2026-11-14 |
| FX-003 | `testing/<area>/fixtures/<name>__fail500.json` | One-shot server failure for the retry path | Recorded from a real 500 shape, sanitized | yes | none | 1 KB | transport retry test | vendor error-shape change | `<owner>` | 2026-11-14 |

## 2. Golden topics

| Golden ID | Directory | Source artifact | Expected invariants | Registered in manifest | Rotated | Reason |
|---|---|---|---|---|---|---|
| `GT-01` | `evals/goldens/topics/<slug>/` | `<run id / published path>` | `expected.json` (schema bounds, concepts, numerical anchors, visual/perf) | yes | 2026-11-14 | `<why>` |

## 3. Seeded defects

| Sample ID | Stage | Defect class | Origin incident | Expected severity/verdict | Registered | Edited? |
|---|---|---|---|---|---|---|
| `SD-CHK-001` | `03-check` | Direct source contradiction | `<dated incident>` | `fatal` | yes | no |

A seeded defect is never edited to make a reviewer pass. If the reviewer is
wrong, fix the reviewer and record the calibration run.

## 4. Recorded artifacts

| Artifact | Path | Run id | Date | Pipeline version | Use | Mutable? |
|---|---|---|---|---|---|---|
| `<stage output>` | `runs/<run_id>/<stage>/output.json` | `<run id>` | 2026-11-14 | `<version>` | Debugging / golden rotation | no (read-only) |

If a recorded artifact becomes a regression input, promote a minimal sanitized
slice into `testing/.../fixtures/` and add a row above. Do not point a test at a
mutable `runs/` path.

## 5. Rules

- **No learner data.** No names, emails, phones, schools, transcripts, or raw
  audio. Kid-session fixtures use the DPDP-validated payload and pseudonymous
  codes only.
- **No secrets.** No keys, DSNs, tokens, or cookies, even fake-looking ones that
  trip the secret scanner.
- **Provenance is mandatory** for anything captured from a live run: date, run
  id, stage, pipeline version.
- **Refresh is a decision.** A fixture that no longer matches the schema is
  either stale (update it) or evidence of a schema break (fix the code). Record
  which.
- **The manifest is current.** A fixture with no row is a review finding; a row
  with no fixture is a broken link.

## 6. Cleanup checklist

- [ ] Inputs are copied to a temp dir before mutation.
- [ ] Temp dirs use `TemporaryDirectory` / `addCleanup`.
- [ ] Servers, browsers, subprocesses, and DB connections close.
- [ ] The test passes alone and in a different order.
- [ ] Tracked files are byte-identical after the suite (`git status` clean).
