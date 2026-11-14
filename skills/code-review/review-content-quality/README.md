# review-content-quality

The seventh specialist lens in `skills/code-review/`. It reviews generated learning content and content-pipeline PRs: lesson pages and blocks, comprehension checks and answer keys, translations/i18n bundles, narration assets, catalogue/publish output, and the prompts/checkers that produce them. Practice packs, marks-scheme papers, and test series are not product surfaces in this repo today; the lens says so explicitly rather than inventing a contract for them.

## Layout

| File | Purpose |
|---|---|
| [`SKILL.md`](SKILL.md) | Entry point: triggers, when not to use, evidence rules, rubric, review order, reporting, worked example, severity guidance, contract and source list |
| [`references/content-quality-checklist.md`](references/content-quality-checklist.md) | Per-area checklist: schema/IDs, grounding, answer keys, numeric tolerance/units, coverage, language, claims, technical integrity, accessibility/perf, narration, eval/debt evidence |
| [`references/review-procedure.md`](references/review-procedure.md) | Artifact map, stage tracing, sampling, exact deterministic commands, reference comparison, severity calibration, product-decision guard, report procedure |
| [`references/anti-patterns.md`](references/anti-patterns.md) | Eighteen recurring failure shapes with symptom, detection, default severity, and fix/gate |
| [`templates/content-review-report.md`](templates/content-review-report.md) | Ready report skeleton in the suite's finding format and severity scale |

## How it fits

`code-review` routes here when a PR touches generated content or the pipeline that produces it. This lens uses the same `[severity][lens][confidence]` finding format and the same `blocker / major / minor / nit / question / praise` scale as every other lens, so its findings merge into the orchestrator's report without translation.

It is **not** a product-design, visual-design, voice-runtime, docs, or infrastructure lens. See "When NOT to use this lens" in `SKILL.md` for the routing.

## Validation

```bash
python3 scripts/check_skills.py --strict --bundle skills/code-review/review-content-quality
python -m unittest discover -s testing/skills -t .
```

## Evidence date

The rubric and the external evidence basis were checked on **2026-11-14** (`metadata.evidence_date`). Re-verify perishable claims (board/edition wording, chapter numbering, WCAG edition) at review time.
