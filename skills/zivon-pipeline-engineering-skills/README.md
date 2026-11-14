# Zivon Pipeline Engineering Skills

The engineering skill for changing Zivon's **build-time content factory**:
`pipeline.py`, `factory/`, the run artifacts, the gates and catchers, the
rendered pages, and the boundary between the prompt, the harness, and the
evaluation framework.

This bundle does not add code to the pipeline. It teaches an agent how to make
a pipeline change without breaking the contracts that make runs resumable,
reviewable, and publishable.

## Scope

In scope:

- stages `00-ingest` through `12-narration`, including `10a`-`10d`;
- run identity, resume, fingerprints, and `--fresh` / `--stages`;
- block schemas, manifests, catalogues, translation and narration artifacts;
- fact/design/perf/translation/narration gates and their repair catchers;
- rendering, localization routes, publishing, SEO generation, and integrity
  checks;
- deterministic tests, eval cards, goldens, and reviewer calibration;
- structured logging and run evidence.

Out of scope (read the sibling bundles instead):

- prompt wording and agent-graph design: `skills/prompting-and-agent-design/`;
- the runtime voice loop (`voice/`): the voice-agent spec and the audio
  discipline in `skills/zivon-audio-engineering-skills/`;
- frontend shell design and the design doctrine: `docs/frontend/` and
  `skills/zivon-frontend-skills/`;
- backend, database, deployment, and infra changes: `docs/backend/`,
  `docs/deployment/`, and `skills/zivon-systems-design-skills/`;
- the review method itself: `skills/code-review/`.

## Read order

1. `SKILL.md` — the stance, the laws, the triage table, the worked example,
   and the anti-patterns.
2. `references/stage-contracts.md` — what every stage takes, writes, and
   resumes from.
3. `references/gates-and-catchers.md` — the gate/catcher contract and how to
   add one safely.
4. `references/artifacts-and-schemas.md` — the on-disk contracts and the
   versioning rules.
5. `references/rendering-and-publishing.md` — how a page becomes a live page.
6. `references/quality-and-evals.md` — deterministic checks vs model review,
   and which eval to add.
7. `references/logging.md` — the structured-event contract.
8. `references/commands.md` — exact key-free commands and mock/live boundaries.

Templates are copied and filled per change:
`templates/stage-change-checklist.md`, `templates/artifact-contract.md`,
`templates/eval-plan.md`, `templates/pipeline-debug-log.md`.

## Layout

| Path | What it is |
|---|---|
| `SKILL.md` | Entry point: trigger-rich description, laws, triage, worked example, anti-patterns, sources |
| `references/stage-contracts.md` | All 17 stage ids: input, output, artifact, resume, owner module, and how to add a stage |
| `references/gates-and-catchers.md` | `03/04`, `07/08`, `09/10`, `10b/10c`, `12` repair; severity ladder; stall/cap rules; adding gates safely |
| `references/artifacts-and-schemas.md` | `status.json`, `run_report.json`, ledgers, `GENERATED`/`BLOCKS`/`LESSON`, manifest, catalogue, translation, narration, fingerprints |
| `references/rendering-and-publishing.md` | `06-render`, `10d-transrender`, `11-link`, `courses.js`, localized routes, SEO, integrity checks, duplicate pruning |
| `references/quality-and-evals.md` | `testing/` vs `evals/`, a11y/perf gates, content-quality debt, card/checker/golden workflow, known gaps |
| `references/logging.md` | `logging_manager` contract, stage events, `run_id` correlation, privacy, map rows, eval telemetry |
| `references/commands.md` | Exact test, lint, eval, pipeline, and debug commands; mock/live boundaries |
| `templates/stage-change-checklist.md` | Copy-paste checklist for any stage/prompt/schema/gate change |
| `templates/artifact-contract.md` | Fill-in contract for a new or changed artifact |
| `templates/eval-plan.md` | Fill-in eval plan: card, checkers, judge, goldens, thresholds, budget |
| `templates/pipeline-debug-log.md` | Fill-in run-debug log with evidence and resume decision |

## Provenance

- **Authored for this repo**, 2026-11-14, against `main` at `57147bb`
  (`PIPELINE_VERSION = "9"`, `git status` clean at authoring time).
- **Evidence date:** `2026-11-14`. Perishable facts (version numbers, stage
  ids, event names, eval schema enums, budgets) are true for that date and
  must be re-verified against `factory/`, `docs/`, and the run artifacts
  before being repeated as current.
- **No third-party text is copied.** External sources are linked and dated in
  `SKILL.md`; the discovery method and source quality notes come from
  `skills/skill-creation/references/source-catalog.md` (last full check
  2026-11-14).
- **Internal sources** are the code and docs named in each reference. When a
  doc and the code disagree, the code plus the newest dated doc win; record
  the conflict in the PR rather than silently choosing a side.

## Maintenance

Re-verify this bundle when any of these happens:

- `PIPELINE_VERSION` changes;
- `STAGE_ORDER` changes or a stage is added/removed/renamed;
- a gate's severity ladder, catcher metric, or cap semantics change;
- `factory/schemas.py` changes a required field or block type;
- `manifest.json` or `courses.js` gains a field the shell consumes;
- the eval card schema, suite names, or CLI changes;
- the logging component/event enums or instrumentation map change;
- a known gap in `references/quality-and-evals.md` closes.

Run the deterministic gate after any edit:

```bash
python3 scripts/check_skills.py --strict --bundle skills/zivon-pipeline-engineering-skills
python -m unittest discover -s testing/skills -t .
```

## Licence

Internal Zivon use. External sources are linked, never copied. No secrets, no
personal data, and no learner content appear in this bundle.
