# CI/CD — GitHub Actions pipelines

Repo is public on GitHub → GitHub Actions is the decided CI/CD system. Workflows live in `.github/workflows/` on the branch they run for: a same-repo PR runs the workflow version from its merge commit, so pipelines land via the same PR they gate. After merge, `main` carries them for all future PRs (fork PRs always use `main`'s version — forks cannot inject CI).

## The merge gate — `ci.yml`

Triggers: PR → `main`, push → `main`, manual dispatch. Seven parallel jobs on fresh `ubuntu-latest` VMs:

| Job | Checks |
|---|---|
| `quality` | `ruff check`, `ruff format --check`, `mypy --ignore-missing-imports` |
| `docker` | hadolint (Dockerfile lint) → build with GHA layer cache (`type=gha`) → **smoke test** (`docker run --rm`) → trivy image scan (fails on CRITICAL/HIGH with fix available) → SBOM (CycloneDX) uploaded as build artifact |
| `frontend-image` | hadolint (`Dockerfile.frontend`) → build → **serve smoke test** (container up on :8080 with the html root seeded from the baked `/opt/zivon-shell` staging path — the cluster serving path, see `docker.md`; `/healthz` answers, landing page renders, shared assets resolve, CSP/nosniff/no-store headers present) → trivy scan |
| `secrets` | gitleaks over full git history (`fetch-depth: 0`) |
| `deps` | pip-audit on the resolved `requirements.txt` tree (known CVEs) |
| `manifests` | kubeconform (schema validity, strict) + kube-linter (security linting of `k8s/`) |
| `tests` | content-factory unit tests (no network, no browser) + integration test (real orchestrator vs mock inference server + headless Chromium) + frontend shell behaviour tests; torch CPU-only, pinned to the same wheel the factory image installs |

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

## Pending setup (GitHub UI, before the first merge)

- **Branch protection on `main`** (Settings → Branches → Add rule): require PR before merging; require the checks above by name; forbid force pushes.
- **Secret scanning + push protection** and **Dependency review** (Settings → Advanced Security — free on public repos; make dependency review a required check).
- **Publish pipeline** (CD): on merge to `main`, build and push `ghcr.io/architgore050/zivon-factory:<git-sha>` + attach SBOM. Not written yet — next piece.
- **Deploy pipeline**: blocked on the cluster hosting decision (see kubernetes.md).
