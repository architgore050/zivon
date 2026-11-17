# Assessment packs (tracked)

The A6 export packs from `python -m factory.assessment`, committed so the DB
import is reproducible from the repo alone.

```
packs/
  <chapter_id>/
    manifest.json      pack identity, counts, coverage, gate verdict,
                       per-file SHA-256, content_hash
    syllabus.json      four-class Physics map (catalogue import consumes it later)
    concepts.json      the chapter's concept graph + block tagging
    questions.json     one row per (item, language)
    speaking.json      one row per (prompt, language)
    time-priors.json   per-question priors + chapter/concept topic priors
```

These files are **A6 output, byte-for-byte**. Do not hand-edit them: the
importer verifies every SHA-256, the `content_hash`, and the gate verdict, and
refuses a pack that does not match (see
`docs/backend/runbooks/assessment-import.md`).

To add or update a pack:

```bash
python -m factory.assessment --chapter <chapter_id> --export-dir runs/assessment-exports
# replace this directory's six files with the export, then commit the mirror
python3 scripts/import_assessment_packs.py --dry-run
```

The importer writes `question_bank`, `speaking_prompt`, `topic_time_prior`, and
one `assessment_pack` provenance row per pack version
(`docs/backend/db-spec.md` §4.19). Learner data never lives here.

Provenance of the first two packs: W3 P2 dry run, 2026-11-17, seed generator,
deterministic gate only (`review_mode: deterministic`, `status: reviewed`) —
pedagogical review is recorded debt, not a claim
(`docs/content-factory/assessment.md` §10).
