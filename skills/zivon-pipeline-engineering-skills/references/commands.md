# Commands

Exact commands, what they need, and which side of the mock/live boundary they
sit on. Run from the repo root unless stated. Dated **2026-11-14**.

## 1. Ground rules

- **Key-free by default.** `testing/`, `evals --mock`, lint, types, and spec
  checks must pass without a model endpoint, a vendor key, or network.
- **No live calls in parallel agent work.** A live model/TTS run spends credits
  and uses a single-slot endpoint; the founder/infra owner runs it in the infra
  window. Build against fixtures and `--mock` until then.
- **No secrets in commands, files, tests, or PR bodies.** Set `ZIVON_*` in the
  environment at runtime; never echo the value.
- **A skipped test is not a pass.** Install Chromium/ffmpeg or report the
  suite as not run.

## 2. One-time setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium     # browser/perf/frontend suites
# ffmpeg must be on PATH for narration tests and live/mock opus encoding
```

First ingest downloads the sentence-transformers model (~90 MB); first perf use
launches Chromium. Everything after that is local.

## 3. Deterministic test suites

| Command | Needs | Covers |
|---|---|---|
| `python -m unittest discover -s testing/content_factory/unit -t .` | none | config, schemas, rules, lints, artifacts, render, agents, translate/transcheck mechanics |
| `python -m unittest discover -s testing/content_factory/integration -t .` | Chromium | full pipeline vs the mock OpenAI-format server + fixture PDFs |
| `python -m unittest discover -s testing/frontend -t .` | Chromium | shell, CSP, self-containment, i18n, catalogue, static page contracts |
| `python -m unittest discover -s testing/evals -t .` | none | eval models, checkers, store, diff, calibration mechanics |
| `python -m unittest discover -s testing/translation -t .` | none | `10a`-`10d` with a mocked llm-manager node, TM store |
| `python -m unittest discover -s testing/narration -t .` | ffmpeg | stage 12 selection, budget, publish, mock/live clients |
| `python -m unittest discover -s testing/observability -t .` | none | event map conformance, redaction, schema |
| `python -m unittest discover -s testing/voice -t .` | none | voice runtime (not this bundle's scope) |
| `python -m unittest discover -s testing/backend -t .` | none | backend runtime (not this bundle's scope) |
| `python -m unittest discover -s testing/skills -t .` | none | the skill validator and bundle contracts |

The integration test is the install check: it runs the whole pipeline against
the mock server with fixture PDFs and a fixture catalog. If it passes, your
install is correct end to end and the only remaining variable is your model.

## 4. Lint, types, spec, and skill gates

```bash
ruff check .
ruff format --check .
mypy --ignore-missing-imports factory docker pipeline.py testing evals \
  logging_manager dashboard backend db guard voice

python3 scripts/check_specs.py
python3 scripts/check_workflows.py --self-test
python3 scripts/check_workflows.py .
python3 scripts/check_skills.py                              # scan all bundles
python3 scripts/check_skills.py --strict --bundle skills/zivon-pipeline-engineering-skills
```

`ruff format` also formats Python code blocks inside Markdown; a new doc with a
Python fence must be ruff-formatted or use a `text`/`bash` fence.

## 5. Evals

Key-free:

```bash
python -m evals run --suite smoke --mock
python -m evals run --suite smoke --fail-on-regression
python -m evals calibrate --stage all --mock
python -m evals diff --prev <baseline_run_id> --curr <current_run_id>
python -m evals record-edit \
  --course class-9-physics --topic motion \
  --baseline-dir runs/<run_id>/11-link/courses/class-9-physics/motion \
  --published-dir frontend/courses/class-9-physics/motion
python -m evals record-kid-test --input session.json
python -m evals report --run <eval_run_id>
```

Live (authorized infra window only):

```bash
python -m evals run --suite full
python -m evals calibrate --stage all
python -m evals calibrate --stage 03-check
python -m evals calibrate --stage 09-review
```

Semantics: `smoke` = deterministic checkers + fake judge (0 model calls);
`full` = checkers + judges; `calibrate` = seeded-defect reviewer calibration.
`--fail-on-regression` compares to the most recent same-suite run in the ledger
and exits 2 on regression. A deliberate baseline change must be stated in the
PR with the reason and new expected values.

## 6. Pipeline runs

A full run needs `ZIVON_BASE_URL` and `ZIVON_MODEL` (and `ZIVON_API_KEY` only
if the server requires one):

```bash
export ZIVON_BASE_URL=http://127.0.0.1:18090/v1   # llm-manager node (or the server)
export ZIVON_MODEL=<the name GET /v1/models reports>
# export ZIVON_API_KEY=<runtime secret>           # never in a file

python pipeline.py "Motion" --class 9
python pipeline.py "Motion" --class 9 --locales hi,hi-Latn
python pipeline.py "Motion" --class 9 --fresh
python pipeline.py "Motion" --class 9 --run-id motion-c9-experiment
```

- Run ids are deterministic per chapter+class; a re-trigger resumes.
- `--class` pre-sets the learner class; without it the located chapter
  supplies it. The class decides the course folder and prompts.
- `--locales` enables the `10a`-`10d` sub-graph.
- `--fresh` wipes the run directory; use it only when you intend to
  regenerate.
- A completed run reuses every stage and prints that nothing will change.

## 7. Targeted stage re-runs

`--stages` runs a subset in `STAGE_ORDER`. Upstream outputs are read from this
run first, then copied from the newest previous run that has them. Starting too
late raises `MissingArtifactError` with instructions.

| Command | Model calls? | Use |
|---|---|---|
| `python pipeline.py "Motion" --class 9 --stages 06-render,11-link` | no | Re-render a page from existing blocks, publish it |
| `python pipeline.py "Motion" --class 9 --stages 10d-transrender,11-link` | no | Rebuild localized routes from existing translations |
| `python pipeline.py "Motion" --class 9 --stages 11-link` | no | Re-publish an already-rendered topic (regenerates `courses.js`, prunes duplicates) |
| `python pipeline.py "Motion" --class 9 --stages 03-check,04-repair` | yes | Re-run the fact gate and its catcher |
| `python pipeline.py "Motion" --class 9 --stages 05-interactive` | yes (one per sim) | Rebuild simulation code |
| `python pipeline.py "Motion" --class 9 --stages 07-perf,08-fixloop` | Chromium; model only if `07` fails | Re-measure and repair a page budget |
| `python pipeline.py "Motion" --class 9 --stages 09-review,10-reviewfix` | yes (two review calls + catcher) | Re-review and repair |
| `python pipeline.py "Motion" --class 9 --stages 10a-translate,10b-transcheck,10c-transrepair,10d-transrender` | yes (per unit/locale) | Localization only |
| `python pipeline.py "Motion" --class 9 --stages 02-generate,03-check,04-repair,05-interactive,06-render,07-perf,08-fixloop,09-review,10-reviewfix,11-link` | yes | A clean re-author of one topic without touching earlier source stages |

Rules:

- The last row re-authors the topic from `02-generate` onward; it is an
  operator decision for an intentional rebuild, never the remedy for a gate or
  catcher finding (that finding routes to its catcher). Get the owner's
  agreement before running it.
- A targeted re-run does **not** re-run upstream stages. If the upstream
  artifact is stale, fix it explicitly or use `--fresh`.
- The fingerprint guard still applies: changing the model/config/translation
  payload invalidates the run dir even for a subset.
- `12-narration` is opt-in per environment:
  ```bash
  export ZIVON_NARRATION_ENABLED=true
  python pipeline.py "Motion" --class 9 --stages 11-link,12-narration
  ```
  With no `ZIVON_TIMBRE_BASE_URL` or `ZIVON_NARRATION_MODE=mock`, the stage
  writes real opus files containing silence, labelled mock, spending zero
  credits. It still needs ffmpeg. Live mode needs `ZIVON_TIMBRE_BASE_URL` +
  `ZIVON_TIMBRE_API_KEY` and ffmpeg.

## 8. Performance harness standalone

```bash
python -m testing.content_factory.perf.harness \
  --url file:///path/to/page.html \
  --profile testing/content_factory/perf/profiles/weak-android.json
```

The harness launches Chromium with `--allow-file-access-from-files` so `file://`
pages load font preloads as they would over HTTP(S); do not pass that flag
yourself. The shipping profile is `weak-android.json`; `mid-laptop.json` is the
mild dev profile.

## 9. Evidence and debugging

```bash
# Read a run's terminal state and rollups
python - <<'PY'
import json
from pathlib import Path
run = Path("runs/<run_id>")
print(json.loads((run / "status.json").read_text())["stages"].keys())
print(json.loads((run / "run_report.json").read_text()))
PY

# Aggregate call/issue ledgers across runs
python3 scripts/issue_report.py

# Mirror the cluster's runs/ and evals_runs/ to the host (read-only bridge)
scripts/publish-artifacts.sh
```

Do not hand-edit `status.json`, `run_report.json`, or a ledger. The evidence is
the diagnosis; a hand-edited artifact is not evidence.

## 10. Publish, triggers, and infra

These are owning-flow / founder commands, not feature-PR steps:

```bash
scripts/publish-frontend.sh          # mirror the PVC's generated site into frontend/
scripts/publish-artifacts.sh         # mirror runs/ and evals_runs/ read-only
scripts/trigger-tests.sh             # in-cluster test-suite button
scripts/trigger-evals.sh [smoke|full|calibrate]
scripts/trigger-factory-run.sh "<chapter>" [class 6-12] [--fresh]   # manual only
python3 scripts/gen-seo-files.py --frontend-dir frontend --base-url <production-url>
```

- The factory Job is manual only; never schedule it.
- Re-triggering the same chapter+class resumes; `--fresh` is an explicit
  regenerate.
- `publish-frontend.sh` exits 2 when the PVC site is identical to the repo
  snapshot (a narration-only re-publish can hit this before the audio mirror).
- `gen-seo-files.py` is a generator, not a checker. Run it through the publish
  flow; `--allow-placeholder` is for a local dry run only.

## 11. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `ConfigError` "different fingerprint" | Model/config/limits/translation changed since the run | `--fresh`, or keep the old run with a new `--run-id`; do not delete `status.json` by hand |
| `MissingArtifactError` | `--stages` starts too late and no prior run has the artifact | Run the earlier stages or include them in `--stages` |
| Re-trigger "does nothing" | The run is already complete | That is resume; pass `--fresh` only if you intend to regenerate |
| `BudgetError` on the landing page | Shared/hand-maintained assets miss the budget | Fix `frontend/` directly; `08` cannot repair it |
| `LintError` at `05`/`06`/`10` | Generated JS/CSS/HTML violated a hard lint | Read `attempts/*/response.json`, fix the generator/prompt; do not weaken the lint |
| 400 blaming `response_format` | Server lacks JSON mode | `ZIVON_JSON_MODE=false` |
| 400 blaming `stream_options` | Server lacks usage-in-stream | `ZIVON_STREAM_USAGE=false` |
| Model call silent for minutes | Thinking model before first token | Watch the chunk counter; do not kill; `ZIVON_CALL_DEADLINE_S` is the wall-clock backstop |
| Translation plateau | A recurring `(locale, unit_id)` finding the fixer cannot satisfy | Read `10b/combined-*.json` and `10c` history; re-trigger resumes only failed blocks; optional locale may fall back |
| Narration all blocks failed | Endpoint/ffmpeg wiring wrong | Fix the endpoint/ffmpeg; a budget refusal is a policy outcome, not a failure |
| Chromium missing | Playwright not installed | `python -m playwright install chromium` |
| ffmpeg missing | Not on PATH | Install it; narration/mock encode needs it |
| Live tree mixes versions | No homogeneity guard | Re-publish the topic at one `PIPELINE_VERSION`; do not patch pages by hand |

## 12. Do not run

- `pipeline.py --fresh` on a run you did not create without the owner's
  agreement.
- A live model/TTS run in CI, a unit test, or a parallel agent's PR.
- `scripts/trigger-factory-run.sh` on a schedule.
- A test with a secret or a real learner record.
- `gen-seo-files.py` against the production tree outside the publish flow.
