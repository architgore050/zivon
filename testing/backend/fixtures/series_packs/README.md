Synthetic minimal E4 series-pack fixture (Class 10) — data, not a golden.

Written by a one-off generator for `testing/backend/test_series_import.py`;
every prompt is prefixed "[Synthetic fixture]" and no prompt is a real exam
question. It is shaped exactly like the pack `python -m factory.exam` writes
at `E4-publish` (`factory/series/publish.py`):

- `papers.json` / `blueprint.json`  — metadata-only documents (no question text)
- `items.json`                      — 11 rows: 4 items x the languages their
                                      series offer (one row per item x language)
- `series.json`                     — the six series manifests; `exact_pyq` is
                                      dark (`no_verbatim_clearance`) with no
                                      items, as DEC-COMP-001 requires
- `manifest.json`                   — pack version, run id, compliance record,
                                      counts, `publish.status: "ready"`, the
                                      gate verdict, and the SHA-256 content
                                      hash over the four data files

The referenced base items (`q-c10-light-001..004`) are real tracked assessment
bank items, so the test suite seeds `question_bank` with the real assessment
importer (`scripts/import_assessment_packs.py`) over
`sources/assessment/packs/`, then imports this pack — the production order.

Planned rows when this pack imports (see the test assertions):
13 `test` rows (papers/sets x offered languages) and 18 `test_question` rows.
