---
name: zivon-pipeline-engineering-skills
description: Safely changes Zivon's build-time content factory (pipeline.py plus factory/) - stage contracts, run artifacts and resume, gate/catcher design, block schemas, rendering and publishing, translation, narration, content-quality and eval boundaries, and structured logging. Use when adding or editing a factory stage, prompt, schema, manifest field, renderer output, gate, catcher, eval card, or publish step; when debugging a failed, stalled, or resumed run; when deciding whether a requirement belongs in the prompt, the harness, or an eval; or when reviewing a content-factory PR.
license: Internal Zivon use
compatibility: Requires a Zivon checkout with Python 3.12 (the CI version) and no secrets. Browser suites need Playwright Chromium; narration tests need ffmpeg; model stages need a configured OpenAI-format endpoint and are not run key-free.
metadata:
  owner: zivon
  version: "1.0"
  evidence_date: "2026-11-14"
  pipeline_version: "9"
---

# Zivon Pipeline Engineering

How to change the content factory without breaking the contracts that make it
resumable, reviewable, and safe to publish. The bundle is specific to this
repo: it names real stage ids, file paths, schemas, and commands. Facts are
dated **2026-11-14** against `PIPELINE_VERSION = "9"`; re-verify perishable
values before repeating them as current.

## When to use this

Use it when any of these is true:

- You are adding or changing a stage in `pipeline.py` / `factory/stages.py`,
  or any stage module's input/output contract.
- You are changing a prompt, rubric, severity ladder, or the agent graph
  (calls, gates, catchers, retries).
- You are adding or changing a block type, field, schema, manifest field, or
  catalogue entry.
- You are touching `factory/render.py`, `factory/link.py`,
  `scripts/publish-frontend.sh`, or `scripts/gen-seo-files.py`.
- You are adding a deterministic check, a gate, a repair catcher, an eval
  card, a checker, a judge, or a golden.
- You are debugging a run: a gate that will not converge, a resume that
  refuses, a page that fails perf, a translation that plateaus, or narration
  that degrades.
- You are reviewing a content-factory PR and need the content lens
  (grounding, coverage, render integrity, i18n, narration speakability).

Do **not** use it for ordinary voice-loop work, frontend shell design, backend
or deployment changes, or prompt theory divorced from this pipeline. Those
have their own docs and skills.

## Operating stance

1. **The run is an artifact graph, not a script.** Every stage writes
   `runs/<run_id>/<stage>/output.json`; a stage marked ok with its output on
   disk is resumed, not re-run. Any change that makes an artifact mean
   something different is a contract change.
2. **Guarantees live in the harness; judgement lives in a reviewer.** If a
   rule must hold every time, put it in code (`factory/checks.py`,
   `factory/lint.py`, `factory/transcheck.py`, schema validation), not in
   prompt prose. If it needs judgement ("does this teach before it tests?"),
   give a reviewer the material and a calibrated rubric.
3. **One gate, one catcher, inside one run.** A failure routes to its paired
   repair loop; it never re-runs upstream stages and never restarts the
   pipeline. The factory Job's `backoffLimit: 0` encodes the same rule.
4. **Progress beats a blind round count.** Catchers stop on a genuine plateau
   (`repair.stall_rounds`) or a generous cap (`repair.*_rounds`,
   `perf.fix_rounds`), scoring the blocking set (severity-weighted
   `fatal=2`, `major=1`; the perf loop scores its failure count).
5. **A change is not done until five things agree:** the artifact contract,
   the deterministic tests, the eval evidence, the structured event, and the
   doc that describes it.

## Read order by task

| Task | Read |
|---|---|
| Add/change a stage, or trace what a run wrote | [references/stage-contracts.md](references/stage-contracts.md) |
| Add a check, gate, or catcher; debug a plateau | [references/gates-and-catchers.md](references/gates-and-catchers.md) |
| Change a schema, block type, manifest, or resume behavior | [references/artifacts-and-schemas.md](references/artifacts-and-schemas.md) |
| Change HTML, JS, CSS, a route, the catalogue, or publishing | [references/rendering-and-publishing.md](references/rendering-and-publishing.md) |
| Decide test vs eval, add an eval card, or judge quality | [references/quality-and-evals.md](references/quality-and-evals.md) |
| Emit an event or debug with run evidence | [references/logging.md](references/logging.md) |
| Run anything, or separate key-free from live work | [references/commands.md](references/commands.md) |

Templates: [stage-change-checklist.md](templates/stage-change-checklist.md),
[artifact-contract.md](templates/artifact-contract.md),
[eval-plan.md](templates/eval-plan.md),
[pipeline-debug-log.md](templates/pipeline-debug-log.md).

## The stage graph in one table

The full contract per stage is in
[references/stage-contracts.md](references/stage-contracts.md). This is the map
you need before opening the file.

| Phase | Stages | Model? | Gate → catcher |
|---|---|---|---|
| Source | `00-ingest`, `01-locate` | code / embeddings | none (hard errors) |
| Author | `02-generate` | one giant call | rule checks inside the retry loop |
| Facts | `03-check`, `04-repair` | model + code | `03` → `04` → recheck `03` |
| Visual code | `05-interactive` | model per simulation | hard lints inside the retry loop |
| Render/perf | `06-render`, `07-perf`, `08-fixloop` | code / Chromium / model | `07` → `08` → retest |
| Code/design | `09-review`, `10-reviewfix` | two review calls + model catcher | `09` → `10` → re-review `09` |
| Localization | `10a-translate`, `10b-transcheck`, `10c-transrepair`, `10d-transrender` | model + code | `10b` → `10c` → recheck `10b` |
| Publish | `11-link` | code | smoke test, hard error |
| Narration | `12-narration` | Timbre TTS | bounded per-block repair; degrade, never fail the page |

## Fast triage: where does my change belong?

| If the requirement is... | Put it in... | Re-validate with... |
|---|---|---|
| A shape, type, citation, number, answer-key, URL, or SVG rule that must always hold | `factory/checks.py` (rules) or `factory/schemas.py` | unit tests, `03-check`, evals |
| A hard code-safety rule (no `eval`, no external calls, canvas scope) | `factory/lint.py` | lint unit tests, `06-render`, `09-review` |
| A translation invariant (citations, units, digits, answers, script) | `factory/transcheck.py` `R1`-`R9` | translation tests, `10b` |
| A judgement about truth, pedagogy, coverage, design, or accessibility | a reviewer prompt + rubric (`factory/agents.py`, `factory/review.py`) | calibration on seeded defects, eval card |
| A new artifact field | `factory/schemas.py` + the producing stage + docs | schema tests, resume test, eval golden |
| A new block type or `spec` shape | `factory/schemas.py`, `blocks-schema.md`, `render.py`, `translate.py`, `interactive.py` | schema/render/translate tests, golden page |
| New page chrome | `frontend/assets/zivon.js` (shell), not `render.py` | `testing/frontend/` |
| A catalogue/manifest/publish change | `factory/render.py`, `factory/link.py`, publish script | `testing/content_factory/unit/test_render.py`, `testing/frontend/`, `check_specs` |
| A quality measurement that needs a model | `evals/` card + checker + golden; never a unit test | `python -m evals run --suite smoke --mock` |

## Worked example: add a deterministic check safely

The real precedent is `rule_shapes` in `factory/checks.py` (2026-11-05): a
model emitted `worked_example.steps` as one dict, and every later rule crashed
with an `AttributeError` instead of telling the model what shape to fix. The
safe change was a deterministic shape rule, not a prompt paragraph.

Do it in this order:

1. **Name the failure class and cite evidence.** Read the failing run's
   `runs/<run_id>/<stage>/attempts/*/response.json` or the rule report. If you
   cannot point at an artifact, you do not yet know the failure class.
2. **Decide the layer.** A shape that later code indexes is a harness
   guarantee: `factory/checks.py`, fatal severity. A judgement call is not.
3. **Implement the rule.** Return the same issue shape as the other rules:
   `{"block_id", "severity", "rule", "message"}`. If later rules depend on the
   shape, run yours first in `run_all_rules` and short-circuit on a fatal shape
   issue, so the retry transcript lands the fix instead of a traceback.
4. **It is wired for free, in three places.** `02-generate` runs
   `run_all_rules` inside its model retry loop, `03-check` runs it as an
   independent gate, and `04-repair` runs it on the merged page. Do not add a
   fourth call site.
5. **Test the mechanics.** Add valid/invalid cases to
   `testing/content_factory/unit/test_checks.py`. The test asserts the rule
   contract, not a prompt string.
6. **Add evaluation coverage.** A new rule that can fail a page belongs in a
   deterministic checker referenced by an eval card (usually `EV-SYN-001` or
   `EV-REV-002` Part A), with a seeded defect if the class is calibratable.
   See [references/quality-and-evals.md](references/quality-and-evals.md).
7. **Do not add a new event for a rule hit.** The rejection already rides
   `factory.call.rejected` with a `reason_code`; reviewer findings ride
   `issues_ledger.jsonl`. Add an event only for a new observable transition,
   and add its map row the same PR.
8. **Update the contract docs.** `docs/content-factory/blocks-schema.md` for
   the shape, `architecture.md` for the failure semantics, `runbook.md` only
   if an operator-visible behavior changed.
9. **Run the key-free gate.** The command list is in
   [references/commands.md](references/commands.md): unit tests, the touched
   suites, `ruff`, `mypy`, and `python -m evals run --suite smoke --mock`.
10. **Decide the resume impact explicitly.** Adding a rule does not change
    artifact semantics, so it does not by itself require a `PIPELINE_VERSION`
    bump. But an existing run dir whose `03-check` is marked ok will resume
    without applying the new rule. If the rule must apply to an already-built
    draft, re-run `03-check` and, on blocking issues, `04-repair`, or use
    `--fresh`. Say which you did in the PR.

An additive **manifest field** follows the same logic with one extra decision:
if no gate consumes it, the change is safe; if the shell or a downstream stage
reads it, a resumed `06-render` output that predates the field is stale, so
re-render or bump the version. Never assume "additive" means "resume-safe".

## Anti-patterns

- **"Just re-run the pipeline."** A downstream gate never sanctions a
  whole-pipeline re-run. Route the finding to its catcher; re-trigger only to
  resume with a fresh catcher budget.
- **`--fresh` as a debugger.** It wipes the evidence for the failure you are
  trying to understand. Resume first; use `--run-id` to keep a parallel
  attempt; `--fresh` is the operator's regenerate button.
- **Prompt prose for a rule that code can enforce.** Citation presence,
  answer-key consistency, external URLs, `eval`, palette scope, and block shapes
  are harness rules. Prompt prose is for goals and judgement.
- **A gate with no catcher, or a catcher with no progress metric.** Both turn
  a repairable defect into either an infinite loop or a silent pass.
- **Lowering a checker to make a page pass.** Fix the page or calibrate the
  rubric with evidence; a weakened check is a future defect.
- **Editing a seeded defect or golden to make a reviewer pass.** The corpus is
  the calibration baseline; change the reviewer, not the truth.
- **Renumbering blocks or claims after publish.** IDs are anchors,
  read-aloud keys, and citation targets. Append new blocks; merge corrections
  by id.
- **Changing `BLOCKS` in place.** The v1 block schema is frozen. Add optional
  fields or additive per-type payloads; a breaking change needs a version bump,
  a migration story, and docs.
- **Hand-editing generated output.** `frontend/courses/**`, `courses.js`,
  `audio/**`, and `runs/**` are produced by their owning flow. Fix the
  producer, not the artifact.
- **Putting chrome in `render.py`.** The renderer emits content plus hooks;
  the shell (`zivon.js` / `zivon.css`) owns chrome and idempotent injection.
- **A new stage that is not in `STAGE_ORDER`, the instrumentation map, the
  eval schema, and the docs.** It will run somewhere, and be invisible
  everywhere.
- **Model calls outside `factory/llm.py` / `llm_manager`.** No hand-rolled
  HTTP, no second retry policy, no `max_tokens` on the factory's thinking
  calls.
- **Live model calls in `testing/`.** A test that needs a model is an eval
  judge; a test that needs a browser or ffmpeg must install it, not skip and
  call it green.
- **`print()` or stdlib `logging` as telemetry.** Progress prints are allowed;
  events go through `logging_manager.log_event` with a map row.
- **Trusting a live page as the reference.** The published tree mixes pipeline
  versions. Match the best page and the tests, not the average, and never copy
  a known defect.

## Definition of done

- [ ] The stage/artifact contract in `docs/content-factory/` is updated in the
      same PR (architecture, blocks schema, config reference, or runbook).
- [ ] `PIPELINE_VERSION` decision recorded: bumped for artifact/graph
      semantics, not bumped for runtime policy (caps, rules).
- [ ] Deterministic tests added or updated; they pass key-free.
- [ ] The touched eval smoke suite passes (`--mock`); a live run is linked by
      run id only if an authorized endpoint was used.
- [ ] Every new event has an instrumentation-map row and the observability
      suite passes.
- [ ] A before/after run artifact or golden diff is attached to the PR.
- [ ] Known debt is labelled, not hidden.

## Reference map

| Read this | When |
|---|---|
| [references/stage-contracts.md](references/stage-contracts.md) | You need any stage's input, output, artifact path, resume behavior, or owner module; or you are adding a stage |
| [references/gates-and-catchers.md](references/gates-and-catchers.md) | You are adding or debugging a gate/catcher, or deciding severity and stall rules |
| [references/artifacts-and-schemas.md](references/artifacts-and-schemas.md) | You are changing a schema, IDs, manifest, catalogue, translation/narration artifact, or fingerprint |
| [references/rendering-and-publishing.md](references/rendering-and-publishing.md) | You are changing HTML/JS/CSS output, localized routes, `courses.js`, SEO, or the publish flow |
| [references/quality-and-evals.md](references/quality-and-evals.md) | You are deciding test vs eval, adding a card/checker/golden, or reading quality debt |
| [references/logging.md](references/logging.md) | You are emitting an event, adding a correlation edge, or debugging with ledgers |
| [references/commands.md](references/commands.md) | You need the exact command for a suite, a targeted stage re-run, or a mock/live boundary |

## Sources and provenance

Internal authority, in precedence order: `AGENTS.md` and `TIMELINE.md`;
`docs/content-factory/{architecture,blocks-schema,config-reference,runbook}.md`;
`docs/specs/evals/` and `docs/specs/observability/`; `docs/specs/translation/`;
the code under `factory/`, `evals/`, and `logging_manager/`.

External sources (linked, not copied; accessed 2026-11-14):

| Source | What this bundle uses it for |
|---|---|
| [Agent Skills specification](https://agentskills.io/specification) | Bundle format and progressive disclosure |
| [Evaluating skill output quality](https://agentskills.io/skill-creation/evaluating-skills) | Eval design: baseline, assertions, evidence, iteration |
| [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | Prompt chaining, evaluator-optimizer, bounded loops, simplicity |
| [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Accessibility target for generated pages |
| [JSON Schema 2020-12 core](https://json-schema.org/draft/2020-12/json-schema-core) | Artifact validation semantics |

Discovery provenance and access notes:
`skills/skill-creation/references/source-catalog.md` (SRC-001, SRC-003, and the
tiering rules). The dated known gaps are recorded in
[references/quality-and-evals.md](references/quality-and-evals.md) and
[references/artifacts-and-schemas.md](references/artifacts-and-schemas.md); they
are observations from this bundle, not rows in the repo's
`docs/specs/gaps/gap-register.md` (`GAP-###`). Re-verify each against code
before treating it as open.
