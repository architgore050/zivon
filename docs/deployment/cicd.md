# CI/CD — GitHub Actions pipelines

Repo is public on GitHub → GitHub Actions is the decided CI/CD system. Workflows live in `.github/workflows/` on the branch they run for: a same-repo PR runs the workflow version from its merge commit, so pipelines land via the same PR they gate. After merge, `main` carries them for all future PRs (fork PRs always use `main`'s version — forks cannot inject CI).

## The merge gate — `ci.yml`

Triggers: PR → `main`, push → `main`, manual dispatch. Twelve parallel jobs on fresh `ubuntu-latest` VMs:

| Job | Checks |
|---|---|
| `quality` | `ruff check`, `ruff format --check` (config in `ruff.toml`: vendored third-party skill trees under `skills/*/vendored/` are out of scope — they are other projects' code and docs, kept verbatim with their licences), `mypy --ignore-missing-imports`, then `scripts/check_workflows.py --self-test` + `scripts/check_workflows.py .` (YAML parse, SHA pins at step and reusable-workflow level, no `write-all`/`pull_request_target`, no product-secret references — findings name the file and rule only, never the matched expression, so the gate log cannot itself become the leak). Tools pinned (`ruff==0.17.4`, `mypy==2.4.1`, `pyyaml==6.0.3`) — see Gate integrity below |
| `docker` | hadolint (Dockerfile lint) → build with GHA layer cache (`type=gha`) → **smoke test** (`docker run --rm`) → trivy image scan (fails on CRITICAL/HIGH with fix available) → SBOM (CycloneDX) uploaded as build artifact |
| `llm-manager-image` | the model-call node (`Dockerfile.llm-manager`): hadolint → build → smoke (**boots with config, `/healthz` answers with a dead upstream; refuses to boot without config** — the original of the `docker/smoke_http_service.sh` pattern) → trivy scan |
| `frontend-image` | hadolint (`Dockerfile.frontend`) → build → **serve smoke test** (container up on :8080 with the html root seeded from the baked `/opt/zivon-shell` staging path — the cluster serving path, see `docker.md`; `/healthz` answers, landing page renders, shared assets resolve, CSP/nosniff/no-store headers present) → trivy scan |
| `secrets` | gitleaks over full git history (`fetch-depth: 0`) |
| `deps` | pip-audit on the resolved `requirements.txt` tree (known CVEs) |
| `manifests` | kubeconform (schema validity, strict) + kube-linter (security linting of `k8s/`). Both tools are downloaded with `-f` + retries to a file, then untarred — see Gate integrity below |
| `tests` | content-factory unit tests (no network, no browser) + integration test (real orchestrator vs mock inference server + headless Chromium) + frontend shell behaviour tests; torch CPU-only, pinned to the same wheel the factory image installs. The job installs **ffmpeg** explicitly (stage 12's narration suite runs the real encoder: 48 kHz WAV → 24 kb/s mono Opus, and fails loud when the binary is missing; the hosted runner image does not guarantee it — it was absent on run 42765825432) and, path-guarded, `dashboard/requirements.txt` (the observability suite imports the real dashboard app; `python-multipart` backs its login form) and `voice/requirements.txt` (the backend suite imports the real monolith app, which mounts `voice/` — so the job is never a weaker environment than `Dockerfile.backend`). A Postgres 16 service container + `ZIVON_DB_URL` are reserved for the Wave-E suites, and a guarded discovery step runs each Wave-E test set (`testing/backend|voice|translation|narration|observability|logging_manager|evals`) the day its folder lands |
| `backend-image` | the core-backend monolith (`Dockerfile.backend`): hadolint → build → smoke (boot-with-config with a dead-DB DSN + refuse-without-config, via `docker/smoke_http_service.sh`) → trivy. `voice/` has no image of its own (ADR-0020) — this job gates what voice rides in: the image installs `voice/requirements.txt` and copies `voice/`, and the app mounts the real `/voice/ws` router. The smoke contract is a **process** check: a dead Postgres must not stop `/healthz` (readiness reports 503 instead), and the server refuses to boot with no `ZIVON_ENV` |
| `dashboard-image` | the admin dashboard (`Dockerfile.dashboard`): hadolint → build → smoke (boots without the admin Secret by spec — `/healthz` answers via the fallback path; fail-closed happens per request) → trivy |
| `db-migrations` | Alembic upgrade-from-empty against a throwaway Postgres 16 service container (ADR-0016), plus an idempotent second `upgrade head` and a `current == head` post-condition. Installs `backend/requirements.txt` (the chain's own pins) — never the factory's `requirements.txt`, whose absent `alembic` made an `import alembic` probe resolve the repo's `alembic/` directory and skip the install. `alembic.ini`'s `version_locations` spans `alembic/versions` (EX0's `0001`→`0002`) and `migrations/versions` (EX2's `0022_translation_memory_c3`, wired `down_revision="0002"`), so the one-head assertion proves both directories form one chain. `alembic check` is not run: the schema is hand-authored DDL with no ORM metadata (documented skip; drift is covered by the second idempotent upgrade + `testing/backend/test_alembic_migrations.py`) |
| `evals-smoke` | the evals spec's deterministic-only PR subset (`python -m evals run --suite smoke --fail-on-regression`) — no judge model calls, key-free like every other gate |

## Path guards — reserved gates that stay green until the service lands

The four Wave-E jobs above (and every future service job) follow one rule:
**a gate for an incoming service is merged BEFORE the service, guarded so it
passes while the artifact is absent.** Each job's first step checks for the
artifact (`Dockerfile.backend`, `Dockerfile.dashboard`, the migration chain's
`alembic.ini`, `evals/__main__.py`) and emits `landed=true/false`; the real
steps run only when it landed, and the absent case emits a `::notice::`
naming the reservation. Consequences:

- adding a service mid-wave cannot red the gate — its checks activate
  automatically the day the artifact lands, with no further yml edit;
- the same guard pattern covers the type and test gates: the `quality` job's
  mypy paths and the `tests` job's suite discovery loop over candidate
  folders and include only the ones that exist (the merge agent appends EX0's
  monolith package names from its manifest to the mypy candidate list);
- a guard must never mask a REAL failure: once the artifact exists, every
  step runs exactly as hard as the always-present jobs. The `manifests`
  applied by `scripts/apply-k8s.sh` follow the same doctrine (reserved
  manifest numbers apply only when their file exists).

Deliberate non-addition: the frontend perf-budget tests need **no** new job —
the perf-budget spec (§6) states the `tests` job's existing `unittest
discover` over `testing/frontend/` already picks up
`test_perf_budget.py` when EX5 lands it; a separate job would duplicate the
torch + Chromium installs for a subset that already gates.

## Gate integrity — the 2026-11-09 red-main postmortem

`main` went red at `e644d5a` (factory 0.3.16 merge, 2026-11-08) on the three
image-scan jobs and stayed red through `35f0812`/`0a43d95`; the skill-bundles
merge (`5b93f3c`) added the `quality` failure on top and hit a `manifests`
flake. Four distinct causes, each fixed by removing the cause, never by
weakening a check:

| Red job | Evidence | Cause | Fix |
|---|---|---|---|
| `quality` (new at `5b93f3c`) | `ruff format --check .` → "13 files would be reformatted", every one under `skills/*/vendored/jeffallan-claude-skills/` | ruff ≥ 0.16 formats Python code blocks inside Markdown by default, so vendored third-party skill docs entered the product format gate | `ruff.toml` excludes `skills/*/vendored` (with `force-exclude`); Zivon's own code and prose stay in scope |
| `docker` + `llm-manager-image` (new at `e644d5a`) | trivy: zlib1g `1:1.3.dfsg+really1.3.1-1+b1`, 2 HIGH with fixes out (CVE-2026-85091, CVE-2026-76844) | the floating `python:3.12-slim` base freezes its apt index at build date — even the newest build (2026-11-08) predates the Debian point release, so bumping the tag cannot reach the fix | `apt-get update && apt-get upgrade` layer in both images (see `docker.md`) |
| `frontend-image` (new at `e644d5a`) | trivy: musl + musl-utils HIGH (CVE-2026-107891), zlib HIGH (CVE-2026-85091) in `nginx-unprivileged:1.31.7-alpine3.24` | same frozen-index problem; 1.31.7-alpine3.24 is still the newest micro build of that base, and the existing targeted apk-upgrade list only covered the round-1 packages | musl, musl-utils and zlib added to the freshening layer (see `docker.md`) |
| `manifests` (only `3ae510b`/`5b93f3c`, green again at `0a43d95`) | step died as "Process completed with exit code 2" naming nothing; locally on the same `k8s/`: kubeconform 0.8.0 → "11 resources found in 10 files — Valid: 11, Invalid: 0, Errors: 0", kube-linter 0.8.3 → "No lint errors found!" | `curl -sL <release-url> \| tar xz` hid a 504 from GitHub's release CDN: tar got an HTML error page, and tar's exit 2 was reported as a manifest-validation failure | download to a file with `-f --retry 5 --retry-all-errors --retry-delay 5`, then untar |

Rules this postmortem leaves behind (they extend the Hardening rules below):

1. **Vendored third-party code is not product code.** It stays verbatim with
   its licence and is out of the lint/format gates: a gate that formats other
   projects' files reddens on their style, not ours.
2. **Pin what the gate installs.** An unpinned `pip install ruff` let an
   upstream release (0.16, 2026-07-23) silently widen the gate's scope under a
   green branch. `ruff.toml`'s `required-version = ">=0.17,<0.18"` keeps
   "green locally" and "green in CI" the same statement.
3. **A download step must fail as itself.** A silent pipe turns a network blip
   into a fake product failure — `manifests` was red twice on valid manifests.
4. **Frozen package indexes are a standing CVE surface.** Both base families
   freeze their index at build date, so the images freshen it themselves (see
   `docker.md`); re-check the trivy gate after any base bump.
5. **A Dockerfile change is not deployed until the image is rebuilt.** The
   manifests pin `zivon-factory:0.3.22` / `zivon-frontend:0.1.6`: rebuild,
   `minikube image load`, re-apply the stack, then bump the version tag as the
   release ritual.

## Promotion pipeline — `promotion.yml`

`main` → `prod` goes ONLY through `.github/workflows/promotion.yml` (AGENTS.md
repo process; GAP-002). Triggers: manual dispatch or a `v*` release tag.
Three jobs:

0. **`resolve`** — pins the ONE commit this run promotes (`github.sha`, the
   tag's commit or the dispatched branch's tip) and proves it is an ancestor
   of `main`. Both later jobs check out that exact SHA and re-verify
   `HEAD == sha`, so a tag push can no longer gate one commit and promote
   another.
1. **`security-gate`** — the release-time security pass at that commit:
   gitleaks over full history, pip-audit, kubeconform + kube-linter, and a
   build + trivy scan (CRITICAL/HIGH with a fix available fails) of every
   image that ships: factory, llm-manager, frontend always; backend and
   dashboard behind the same path guards as the merge gate, so the scan set
   grows automatically as the Wave-E services land.
1b. **`codeql`** — CodeQL at the same commit, with `security-events: write`
   confined to this job exactly like `codeql.yml`; the image-build job keeps
   `contents: read`.
2. **`promote`** — opens a promotion PR `main → prod` from a
   commit-derived `promotion/main-to-prod-<sha12>` branch, still at the gated
   SHA. **The founder approves by reviewing and merging that PR — the PR is
   the manual-approval gate.** The workflow never pushes `prod` directly; it
   no-ops when prod is already at the gated commit, and a re-run on the same
   commit reuses its branch and PR (idempotent). A different commit gets a
   different branch, so no two promotions can be confused.

**Token model (why the PR needs `PROMOTION_TOKEN`):** a PR opened with
`GITHUB_TOKEN` does not trigger `pull_request` workflows, so its checks would
silently never run. The promotion PR is therefore opened with the repo secret
`PROMOTION_TOKEN` (a fine-grained PAT; registry entry in
[`secrets.md`](secrets.md) § CI/CD token) and the job fails loudly when it is
absent rather than opening an unchecked PR. `prod` branch protection should
require the checks the merge gate requires; the promotion PR runs them under
the token's actor.

Rollback: `prod` deploys only from the promotion tag — rollback = redeploy the
previous tag (image + `apply-k8s.sh` ritual per the docker.md rules). Secrets
never enter the pipeline: the gate runs key-free (its only secret is the
PR-creating token above).

## Smoke pattern for service images — `docker/smoke_http_service.sh`

The llm-manager CI job's inline check (boot-with-config → poll `/healthz` →
refuses-without-config) is extracted into one audited script the Wave-E image
jobs call with per-image arguments. Two deliberate strictness fixes over the
original inline: in the refuse phase, a container that HANGS without config
exits 124 from the `timeout` wrapper and is a FAILURE — a hang is not a
refusal; and a bare nonzero exit is not enough either — the captured
stdout/stderr must match a config-error marker (`--config-error-pattern`,
default `config|required|missing|not set|must be set|ZIVON_`), so a crashed
importer cannot masquerade as a refusal. The existing llm-manager job keeps
its inline check; new image jobs use the script.

## In-cluster test runs (scheduled + startup + the "button" stand-in)

CI gates every merge; the cluster ALSO runs the full suite continuously via the
`test-suite` CronJob (`k8s/50-test-cronjob.yaml`). The cadence is the config value
`TEST_CRON_SCHEDULE` in `k8s/infra.env` (rendered into the CronJob by
`scripts/apply-k8s.sh` — the manifest carries only the placeholder), and
`scripts/apply-k8s.sh` additionally triggers one full suite run immediately on
startup, because the CronJob's first tick can be up to a full interval away.
To trigger it on demand — the standing substitute for an admin-dashboard button until the
Day-8 dashboard exists (documented in `TIMELINE.md`) — developers use:

```bash
scripts/trigger-tests.sh                    # the "button" -> job test-manual-<HHMMSS>
kubectl logs -f job/test-manual-<HHMMSS> -n zivon   # watch it
```

(the script wraps `kubectl create job --from=cronjob/test-suite <name> -n zivon`; the
Kubernetes Dashboard's Recreate action works too). Content generation is NOT scheduled —
generation runs are triggered with `scripts/trigger-factory-run.sh "<chapter>" [class]`.
This is the pattern to keep using (and to wire into the dashboard later); do not hand-roll a new
test runner for it.

## Code scanning — `codeql.yml`

CodeQL analyzes **our own Python code** (injection, path traversal, unsafe deserialization patterns) on every PR, on merge, and weekly (cron). Free on public repos; alerts appear inline on PRs and under Security → Code scanning.

## Dependency monitoring — `.github/dependabot.yml`

Weekly checks for pip, Docker base image, and GitHub Actions dependencies. Dependabot opens update PRs; security advisories surface as alerts. It also rotates our pinned action SHAs when new versions ship.

Gotcha (Wave-E): the pip entries for `voice/` and `logging_manager/` are
registered before their directories exist (the specs announce the files,
GAP-001's consumers). Until then Dependabot logs a per-entry
"directory not found" config warning while every other ecosystem keeps
working; the entries activate on arrival. Do not delete them to silence the
warning — deleting it re-opens the coverage gap it exists to close.
CodeQL needs no per-package config: it analyzes all Python in the repo, so
new packages are covered automatically the day they land.

## Security posture summary

| Layer | Tool | Catches |
|---|---|---|
| Our code | CodeQL | vulnerability patterns in Python source |
| Dependencies | pip-audit + Dependabot | known CVEs in the resolved tree, ongoing |
| Image | trivy + SBOM artifact | CVEs in installed packages + OS layer; full package inventory per build |
| Secrets | gitleaks (CI) + GitHub secret scanning/push protection (repo setting) | leaked keys in history / at push time |
| Manifests | kubeconform + kube-linter | invalid or unsafe K8s config |
| Dockerfile | hadolint | insecure build patterns |
| CI itself | SHA-pinned actions, `permissions: {}` + per-job grants, no secrets on fork PRs | supply-chain attacks on the pipeline |

Known limitation: all scanners catch **published** CVEs only. Unknown vulnerabilities are handled by runtime containment: non-root containers, resource limits, no external calls from generated pages.

## Hardening rules (apply to every new workflow)

1. Pin every third-party action to a full commit SHA with a version comment (`@3d3c42e…  # v7.0.1`). Tags can be retagged; commit hashes cannot.
2. `permissions: {}` at workflow top; grant each job only what it needs.
3. CI never receives `ZIVON_API_KEY` or any product credential — the gate validates code/images/manifests key-free.
4. Prefer first-party or pinned-container steps over low-maintenance third-party actions.
5. Pin the tools a gate installs (`ruff==0.17.4`, `mypy==2.4.1`) and mirror the pin in the tool's own config (`required-version`) — an unpinned tool lets an upstream release silently change what the gate covers.
6. Every tool download writes to a file with `-f` + `--retry 5 --retry-all-errors` before being unpacked — never `curl -sL <url> | tar xz`, which turns a network blip into a fake product failure.
7. Vendored third-party code (`skills/*/vendored/`) is out of the lint/format gates; it is kept verbatim with its licence.
8. Workflows are themselves gated: `scripts/check_workflows.py .` (run in `quality`, with its `--self-test` rule fixtures first) parses every `.github/workflows/*.yml|*.yaml` and `.github/actions/**/action.yml|yaml`, enforces the SHA-pin rule at step AND reusable-workflow level, rejects `permissions: write-all` and `pull_request_target`, and catches product-secret references in both `secrets.NAME` and `secrets['NAME']` form.

## Pending setup (GitHub UI, before the first merge)

- **Branch protection on `main`** (Settings → Branches → Add rule): require PR before merging; require the checks above by name; forbid force pushes.
- **Branch protection on `prod`** the same way — the promotion PR is the only writer once it is on. Because a promotion PR opened by `GITHUB_TOKEN` would trigger no checks, the repo secret **`PROMOTION_TOKEN`** (fine-grained PAT: contents write + pull-requests write, scoped to this repo) must exist before the first promotion run; the workflow fails loudly without it. Registry entry (name only): [`secrets.md`](secrets.md) § CI/CD token. Optionally add a GitHub **environment** with a required reviewer for prod deploys, layered on top of the promotion PR review.
- **Secret scanning + push protection** and **Dependency review** (Settings → Advanced Security — free on public repos; make dependency review a required check).
- **Publish pipeline (CD)**: the promotion workflow is the release train — its registry push (build and push `ghcr.io/architgore050/zivon-*:<git-sha>` + attach SBOM on the promotion tag) is the remaining piece.
- **Deploy pipeline**: blocked on the cluster hosting decision (see kubernetes.md).
