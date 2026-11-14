# Golden fixture template

Use this when adding a golden topic or a seeded defect. Goldens are committed contracts, not
scratch fixtures: a golden that was invented to make a card pass is a false baseline.

## 1. Topic golden directory

```
evals/goldens/topics/<slug>/
├── expected.json          invariants (schema-validated)
├── source_pack_meta.json  provenance of the source pack
└── artifact_ref.json      pointer to the page snapshot / run evidence
```

Do not commit a full generated page into a golden. `artifact_ref.json` points at the published
page or `runs/<run_id>/...`; git history is the version rotation.

## 2. `expected.json` skeleton

Required fields are enforced by `GOLDEN_EXPECTED_SCHEMA` in `evals/models.py`. `blocks_min/max`
must stay within 4–45; `matched_via` is `title_line`.

```json
{
  "golden_id": "GT-05",
  "topic_slug": "replace-with-topic-slug",
  "course_id": "class-9-physics",
  "class_level": 9,
  "pipeline_version_min": 9,
  "source_provenance": {
    "primary_book_id": "ncert-science-9",
    "chapter_title_normalized": "motion",
    "matched_via": "title_line",
    "forbidden_smuggled_terms": ["simple harmonic motion"]
  },
  "structure_bounds": {
    "sections_min": 3,
    "claims_min": 6,
    "claims_max": 40,
    "blocks_min": 8,
    "blocks_max": 45,
    "checks_min": 3,
    "worked_examples_min": 1,
    "simulations_min": 1,
    "diagrams_max": 2
  },
  "required_concepts_and_equations": {
    "key_terms_must_include": ["force", "friction"],
    "equation_patterns_must_include": ["net force", "N"]
  },
  "canonical_numerical_anchors": [
    {
      "source_label": "NCERT worked example: opposing forces",
      "problem_numbers": ["10", "6"],
      "expected_answer_values": [4.0, 16.0],
      "tolerance_rel": 0.02
    }
  ],
  "visual_and_kit_invariants": {
    "requires_lang_bar": false,
    "requires_sim_readout_populated": false,
    "computed_graphs_as_simulations": true,
    "max_overflow_px": 2
  },
  "perf_budgets": {
    "profile": "evals/goldens/profiles/weak-android.json",
    "ram_budget_mb": 750,
    "fps_min": 24,
    "load_budget_s": 6.0,
    "fcp_budget_s": 3.5
  },
  "structure_bounds_note": "Why these bounds differ from the defaults, if they do."
}
```

## 3. Register it in `evals/goldens/manifest.json`

```json
{
  "golden_id": "GT-05",
  "directory": "evals/goldens/topics/<slug>",
  "topic_slug": "<slug>",
  "course_id": "class-9-physics",
  "class_level": 9,
  "pipeline_version_min": 9,
  "status": "published"
}
```

`status` is one of `published`, `reference_golden`, `contract_frozen` in the current manifest.
Adding the directory without the manifest entry leaves an unregistered golden; the card's
`golden_inputs.topics` will point at something no test knows about.

## 4. Seeded defect (calibration only)

```json
{
  "sample_id": "SD-CHK-009",
  "stage": "03-check",
  "origin_incident": "run <run_id> block b-NN",
  "defect_class": "Wrong computed numerical answer",
  "planted_mutation": "Describe the exact mutation, including the block id.",
  "target_call": "03-check",
  "inputs": {
    "source_pack": {},
    "ground_truth": {},
    "lesson": {},
    "blocks": {}
  },
  "expected": {
    "outcome_type": "positive_defect",
    "expected_verdict": "fail",
    "expected_severity": "fatal",
    "expected_category": "answer_key",
    "expected_block_id": "b-NN",
    "must_quote_source": true,
    "expected_quote_substrings": ["m/s"]
  }
}
```

A clean sample uses `"outcome_type": "negative_clean"`, `"expected_verdict": "pass"`,
`"expected_severity": null`, and `"must_quote_source": false`. Both kinds are required: a
reviewer that only fails bad samples proves nothing about specificity.

## 5. Rotation rules

- **Prompt-only change, pipeline version unchanged:** do not rotate. Re-run `--suite full` and
  compare against the existing golden.
- **Schema/contract/kit change, pipeline version bumped:** regenerate the topic with a fresh
  factory run, publish it, verify the cards, then
  `python -m evals rotate-golden --topic <id> --reason "<why>"`. The command updates the SHA-256
  and appends a `rotations[]` audit entry to the manifest.
- **Never weaken a seeded defect** to pass a regression. Add a new sample for a new failure mode.
- **Never edit `expected.json` in place** without a rotation record and a PR explanation.
- Keep `pipeline_version_min` truthful: a golden from an older pipeline is grandfathered until
  it is regenerated, not silently relabelled.

## 6. Checklist

```text
[ ] Topic directory has all three files
[ ] expected.json validates against GOLDEN_EXPECTED_SCHEMA
[ ] Manifest entry added with the correct status and version
[ ] Card golden_inputs.topics points at the new directory
[ ] No child PII, transcript, audio/video path, or secret in any file
[ ] If a defect: it names a real block id and a real origin incident
[ ] If rotated: reason, old/new sha, and source recorded
[ ] Docs updated (golden-sets.md) in the same PR
```
