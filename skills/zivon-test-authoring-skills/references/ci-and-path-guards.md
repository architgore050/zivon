# CI and path guards

Every deterministic suite is a merge gate. This reference lists what CI runs,
how a new suite joins it without reddening `main`, and the integrity rules that
keep the gate meaningful. Source of truth: `.github/workflows/ci.yml` and
`docs/deployment/cicd.md`.

## 1. The jobs that matter to tests

| Job | What it proves | Key commands |
|---|---|---|
| `quality` | Workflow hardening, lint, format, skills, types | `check_workflows.py --self-test`, `check_workflows.py .`, `ruff check .`, `ruff format --check .`, `check_skills.py`, `mypy` |
| `tests` | Factory unit, factory integration (mock server + Chromium), frontend shell/behaviour/perf, every Wave-E suite that exists | `unittest discover` per folder |
| `db-migrations` | The Alembic chain builds a fresh Postgres 16 schema with one head, twice, idempotently | `alembic upgrade head` ×2 + `alembic current == heads` |
| `evals-smoke` | Deterministic eval checkers on goldens, no model calls | `python -m evals run --suite smoke --fail-on-regression` |
| `docker`, `llm-manager-image`, `frontend-image`, `backend-image`, `dashboard-image` | Images build, boot, and pass a smoke test; vulnerability scan | image build + smoke + trivy |
| `secrets` | No secret enters git history | gitleaks |
| `deps` | No known CVE in the Python dependency tree | pip-audit |
| `manifests` | Kubernetes manifests are valid and lint-clean | kubeconform + kube-linter |

A PR is mergeable only when all of these pass. Do not add `continue-on-error`,
`|| true`, or a background step that lets a failing suite return green.

## 2. Test discovery

The canonical command is always run from the repo root:

```bash
python -m unittest discover -s testing/<area> -t .
```

The `tests` job runs these explicitly:

```bash
python -m unittest discover -s testing/content_factory/unit -t . -v
python -m unittest testing.content_factory.integration.test_end_to_end -v
python -m unittest discover -s testing/frontend -t . -v
```

and then loops over the Wave-E folders that exist:

```bash
for d in backend voice translation narration observability logging_manager evals skills; do
  if [ -d "testing/$d" ]; then
    python -m unittest discover -s "testing/$d" -t . -v || status=1
  else
    echo "testing/$d not on this branch yet — reserved (path guard passes)"
  fi
done
exit $status
```

Consequences:

- A new suite inside one of those eight folders is covered automatically the
  day the folder lands. No workflow edit.
- A suite anywhere else (a new top-level area) needs an explicit line in the
  `tests` job. Add it in the same PR as the folder.
- `unittest discover` only finds `test*.py` modules in importable packages
  (every `testing/` folder has `__init__.py`). A file named `checks.py` is
  invisible.
- Each test module must be runnable alone. CI runs the whole folder; a
  developer debugs one module; both must work.

## 3. Path guards

A path guard is a gate for an incoming service, merged **before** the service,
written so it passes while the artefact is absent. This repo uses the pattern
in these places:

| Guard | Artefact checked | When absent |
|---|---|---|
| `backend-image` | `Dockerfile.backend` | `landed=false`, `::notice::` reservation, steps skipped |
| `dashboard-image` | `Dockerfile.dashboard` | same |
| `db-migrations` | `alembic.ini` in one of three locations | same |
| `evals-smoke` | `evals/__main__.py` | same |
| `quality` mypy | each candidate package directory | omitted from the path list |
| `tests` Wave-E loop | each `testing/<area>` folder | `::notice::`, loop continues |

Rules:

1. **The guard must never mask a real failure.** Once the artefact exists,
   every step runs exactly as hard as an always-present job. A guard that
   catches an exception from the real test is not a guard; it is a disabled
   gate.
2. **The absent case is loud.** Emit a `::notice::` naming what is reserved and
   why, so a green job is not mistaken for coverage.
3. **Do not add a duplicate job** for a suite that discovery already covers.
   The frontend perf budget is found by `unittest discover` over
   `testing/frontend/`; a separate perf job would duplicate torch and Chromium
   installs for a subset.
4. **The guard is temporary by design, not by neglect.** When the service
   lands, the guarded steps activate with no further workflow edit. Verify the
   first run after landing.

## 4. The key-free rule

CI has no product secrets:

- No `ZIVON_*_API_KEY`, no Gnani key, no model endpoint key, no production DSN.
- Vendor seams are mocked; the deterministic eval smoke uses `--mock`.
- The only database credential is a throwaway Postgres service container
  (`zivon`/`zivon`, `127.0.0.1:5432`) for backend and migration tests. It is a
  test fixture, not a product secret.
- `gitleaks` runs over full history. A committed secret is a blocker, even if
  the branch is deleted afterwards.

If a test needs a key to pass, the test is wrong for CI. Move the live check to
an infra window, record the evidence, and keep the deterministic contract test
in CI.

## 5. Lint, format, and types

```bash
ruff check .
ruff format --check .
mypy --ignore-missing-imports factory docker pipeline.py testing \
  voice logging_manager dashboard evals narration backend db guard
```

Notes:

- CI pins `ruff==0.17.4` and `mypy==2.4.1`; `ruff.toml` requires
  `>=0.17,<0.18`. Bump deliberately, after running both commands locally on the
  same version.
- Since ruff 0.16, `ruff format` formats Python code blocks inside Markdown.
  Keep snippets in skill docs and specs formatted, or they redden the gate.
  The one exclusion is `skills/*/vendored` (third-party code kept verbatim).
- The mypy path list is a **path guard**: fixed core paths plus candidate
  packages appended only if their directory exists. A new package joins the
  gate the day it lands; the merge agent appends its name when it is not in the
  candidate list.
- `mypy` is not a substitute for a runtime test. It catches shape errors, not
  behaviour.

## 6. Browser, ffmpeg, and database prerequisites

| Need | Install | Why |
|---|---|---|
| Chromium | `python -m playwright install --with-deps chromium` | Frontend shell, behaviour, perf, and any page test |
| ffmpeg | `sudo apt-get install -y --no-install-recommends ffmpeg` | Stage 12 narration runs the real encoder (48 kHz WAV → 24 kb/s Opus) |
| Postgres 16 | service container + `ZIVON_DB_URL` | Backend and migration suites; SQLite is not a substitute for dialect behaviour |
| torch CPU | `pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu` | Same wheel the factory image ships; keep CI and image aligned |

A skipped prerequisite is reported as skipped. It is not a pass. Do not add a
silent shim that runs a different stack; `testing/frontend/__init__.py` fails
loudly when Playwright is missing for exactly this reason.

## 7. Evals in CI

- The PR gate is deterministic: `python -m evals run --suite smoke --fail-on-regression`.
- It exits `2` on a regression against the most recent same-suite run in
  `evals_runs/eval_runs_ledger.jsonl`.
- Full suites and calibration need a model endpoint and spend credits; they run
  in the cluster CronJob / infra window, not in the PR gate.
- `python -m unittest discover -s testing/evals -t .` is the unit test for the
  eval framework itself (schemas, funnel, calibration harness, store, diff).
  Keep it in the `tests` loop.

## 8. Scheduled and on-demand runs

| Trigger | What it runs |
|---|---|
| `k8s/50-test-cronjob.yaml` | The full test suite on `TEST_CRON_SCHEDULE` |
| `k8s/52-eval-cronjob.yaml` | `python -m evals run --suite full --fail-on-regression` daily at 02:00 UTC |
| `scripts/trigger-tests.sh` | On-demand suite run |
| `scripts/trigger-evals.sh [smoke|full|calibrate]` | On-demand eval run |
| `scripts/trigger-factory-run.sh "<chapter>"` | Manual content generation (never scheduled) |

The CronJobs persist evidence to the `zivon-sources` PVC (`subPath: evals` for
evals). A green PR gate does not prove the full suite is green; check the
scheduled run before a release.

## 9. Adding a suite: checklist

- [ ] `testing/<area>/__init__.py` exists.
- [ ] Modules are named `test_*.py` and run alone with
      `python -m unittest testing.<area>.<module>` from the repo root.
- [ ] The suite is key-free and offline, or the gated part is skipped honestly
      with a reason.
- [ ] The folder is in the Wave-E discovery list, or you added an explicit line
      to the `tests` job.
- [ ] `mypy` covers the new package (candidate list or explicit path).
- [ ] `testing/README.md` has a row with the command.
- [ ] Any new fixture has a manifest row and no secret/PII.
- [ ] CI passes locally with the same commands; no `--ignore` flags added to
      hide a failure.
- [ ] If the suite needs a service (Postgres, Chromium, ffmpeg), the job
      installs it and the skip path is tested.

## 10. When CI is red

1. Read the failing step, not the summary. The step name says which suite.
2. Reproduce with the exact command from the job log, on the same Python and
   tool versions.
3. If the failure is environmental (missing browser, missing ffmpeg, dead
   service), fix the environment or the skip path; do not weaken the assertion.
4. If the failure is a real contract break, fix the production code. If the
   contract deliberately changed, update the test and the doc in the same PR
   and explain why.
5. If the failure is flaky, reproduce with repetition and isolation; fix the
   cause (time, order, shared state, network, race). Do not add retries to hide
   it.
6. Never bypass branch protection or merge on a red gate. A red `main` is a
   repo-wide outage; the 2026-11-09 postmortem in `docs/deployment/cicd.md`
   records what happens when a gate is weakened instead of fixed.

## 11. Workflow changes

If you must edit `.github/workflows/`:

- Third-party actions stay pinned to a full commit SHA.
- Keep top-level `permissions: {}` and grant per job only what it needs.
- No product secrets in workflows; no `pull_request_target` with write access.
- Run `python3 scripts/check_workflows.py --self-test` and
  `python3 scripts/check_workflows.py .` locally.
- A new job that is not a path guard needs a green run on the PR before merge.
