# CI/CD — GitHub Actions pipelines

Repo is public on GitHub → GitHub Actions is the decided CI/CD system. Workflows live in `.github/workflows/` on the branch they run for: a same-repo PR runs the workflow version from its merge commit, so pipelines land via the same PR they gate. After merge, `main` carries them for all future PRs (fork PRs always use `main`'s version — forks cannot inject CI).

## The merge gate — `ci.yml`

Triggers: PR → `main`, push → `main`, manual dispatch. Seven parallel jobs on fresh `ubuntu-latest` VMs:

| Job | Checks |
|---|---|
| `quality` | `ruff check`, `ruff format --check` (config in `ruff.toml`: vendored third-party skill trees under `skills/*/vendored/` are out of scope — they are other projects' code and docs, kept verbatim with their licences), `mypy --ignore-missing-imports`. Tools pinned (`ruff==0.17.4`, `mypy==2.4.1`) — see Gate integrity below |
| `docker` | hadolint (Dockerfile lint) → build with GHA layer cache (`type=gha`) → **smoke test** (`docker run --rm`) → trivy image scan (fails on CRITICAL/HIGH with fix available) → SBOM (CycloneDX) uploaded as build artifact |
| `frontend-image` | hadolint (`Dockerfile.frontend`) → build → **serve smoke test** (container up on :8080 with the html root seeded from the baked `/opt/zivon-shell` staging path — the cluster serving path, see `docker.md`; `/healthz` answers, landing page renders, shared assets resolve, CSP/nosniff/no-store headers present) → trivy scan |
| `secrets` | gitleaks over full git history (`fetch-depth: 0`) |
| `deps` | pip-audit on the resolved `requirements.txt` tree (known CVEs) |
| `manifests` | kubeconform (schema validity, strict) + kube-linter (security linting of `k8s/`). Both tools are downloaded with `-f` + retries to a file, then untarred — see Gate integrity below |
| `tests` | content-factory unit tests (no network, no browser) + integration test (real orchestrator vs mock inference server + headless Chromium) + frontend shell behaviour tests; torch CPU-only, pinned to the same wheel the factory image installs |

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

## Pending setup (GitHub UI, before the first merge)

- **Branch protection on `main`** (Settings → Branches → Add rule): require PR before merging; require the checks above by name; forbid force pushes.
- **Secret scanning + push protection** and **Dependency review** (Settings → Advanced Security — free on public repos; make dependency review a required check).
- **Publish pipeline** (CD): on merge to `main`, build and push `ghcr.io/architgore050/zivon-factory:<git-sha>` + attach SBOM. Not written yet — next piece.
- **Deploy pipeline**: blocked on the cluster hosting decision (see kubernetes.md).
