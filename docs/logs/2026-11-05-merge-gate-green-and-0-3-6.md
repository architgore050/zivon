# Session log — 2026-11-05 — merge gate green: first PR through CI + factory image 0.3.6

## What we set out to do

Merge `feature/content-factory-pipeline` (91 commits) into `main` the way AGENTS.md
requires: push the branch, open a same-repo PR (own-branch → own-main PRs are normal
and run CI), let the merge gate run, fix what it catches, merge.

PR #1 opened (`feature/content-factory-pipeline` → `main`). The repo's **first CI
run**: 6 of 8 checks green on the first try (tests, lint+typecheck, gitleaks,
pip-audit, kubeconform+kube-linter, CodeQL) — and 2 failures, both in the **gate
design**, not in the product.

## The two failures and their root causes

1. **`frontend-image` → Smoke test failed.** The smoke curled the bare image, but the
   image stages the shell at `/opt/zivon-shell`: the served html root is a volume/PVC
   in production (compose mount / seed-shell initContainer). Unseeded, `/` serves
   nginx's default page — the `grep -q "Zivon"` and asset checks could never pass.
   Reproduced locally first: the container answered `/healthz` "ok" and served
   "Welcome to nginx!".
2. **`docker` → Dockerfile lint (hadolint) failed** at the configured `info` threshold:
   **DL3013** (torch installed unpinned) and **DL3066** (`USER app` — non-numeric user;
   the same class as cluster gotcha 1, which had been fixed manifest-side).

## What we changed

1. **`ci.yml` frontend smoke now mirrors the cluster serving path**: tmpfs html root
   (`uid=101,gid=101` — the fsGroup stand-in) seeded **after** the healthz wait with
   the same no-clobber glob copy the seed-shell initContainer uses
   (`cp -rn /opt/zivon-shell/* …`, gotcha 6's safe form).
2. **Factory Dockerfile**: torch pinned to `torch==2.15.0+cpu` (wheel verified on the
   CPU index; it is exactly what 0.3.5 installed) and `useradd --create-home --uid 1000`
   + numeric `USER 1000` — gotcha 1's fix now lives in the image itself.
3. **`tests` job**: torch pinned to the same wheel, so CI tests run the torch the image
   ships.
4. **Release 0.3.6** (gotcha 5: new content → new tag): version bumps across compose,
   k8s manifests (10/20/50), Dockerfile comments, README, deployment docs; deployment
   README history line extended.
5. **Docs kept current**: `cicd.md` job table corrected (seven jobs — the `tests` job
   was missing) + seeded-smoke wording; `docker.md` image bullets (pinned torch,
   numeric USER) + a frontend-image bullet recording that a bare `docker run` of the
   image serves nginx's default page by design; `kubernetes.md` gotcha 1 note; TIMELINE
   entry + pending Motion trigger retagged to 0.3.6.

## Verification (all green)

- Local: both Dockerfiles hadolint-clean at `--failure-threshold info` (same hadolint
  version CI pins); frontend smoke 7/7 against the seeded image; kubeconform strict
  9/9 + kube-linter clean on the retagged manifests.
- Image 0.3.6: built; CMD smoke green (all 19 factory modules + pipeline + heavy deps);
  `pipeline.py --help` green; runs as uid 1000; torch `2.15.0+cpu`.
- Cluster: `minikube image load` (1 m 43 s); `scripts/apply-k8s.sh` re-applied;
  `factory-smoke` **Complete** on 0.3.6; startup suite green — **209 unit + 10 frontend
  + 7 integration**; site 200 (landing + `assets/zivon.css`).

## What this deliberately does NOT do

- **No branch protection yet** — `main` is unprotected today; the TIMELINE item stays
  open (required-checks checklist in `cicd.md`). The merge is gated by convention +
  green CI, not enforcement.
- **No GHCR publish pipeline** — images are still built locally + `minikube image load`
  (the publish-pipeline item stays open).
- **No frontend image change** — `Dockerfile.frontend` untouched; frontend stays 0.1.2.
- **No generation run** — the Motion `--fresh` trigger remains the founder's call.

## Next

1. CI re-run on PR #1 → green → merge to `main` (then verify the post-merge `main` run).
2. Founder: branch protection + required checks per the `cicd.md` checklist.
3. Founder triggers `scripts/trigger-factory-run.sh "Motion" 9 --fresh` on 0.3.6.

---

# Batch 2 (same day): CI round 2 — CodeQL + trivy gates bite, all fixed → factory 0.3.7 + frontend 0.1.3

## What happened

CI round 2 on PR #1 (head `e5cc1e9`): batch-1 fixes verified — frontend smoke step green,
factory hadolint green, Tests job green. Three new failures surfaced (two of them gates
that had never executed — in round 1 those jobs died at earlier steps):

1. **CodeQL check failure — 6 new HIGH alerts** on code changed by the PR (the whole
   91-commit diff vs `main`). The alerts live on the PR merge ref
   (`?ref=refs%2Fpull%2F1%2Fmerge` — the default alerts API returns 0, which first made
   the check look flaky): 4× `py/path-injection` in `testing/content_factory/mocks/openai_mock.py`
   (mock built fixture paths from system-prompt text); 1× `py/weak-sensitive-data-hashing`
   in `factory/retrieval.py` (md5 in the test-only `FixtureEmbedder`); 1× `py/bad-tag-filter`
   in `factory/lint.py` (regex inline-`<script>` body extraction).
2. **Frontend trivy scan failure** — 61 findings (3 CRITICAL, 58 HIGH), all fixable, all
   from the stale Alpine base of `nginx-unprivileged:1.27-alpine`.
3. **Factory trivy scan failure** — 3 HIGH: `setuptools 78.1.0` (torch pins it exactly),
   `wheel 0.45.1`, `jaraco.context 5.3.0`.

## Fixes (all in code or image — no gate weakened, no alert dismissed)

- **Mock whitelist index**: `_fixture_index()` snapshots the fixture files per `start_mock`
  call and injects them into the bound handler like `state`; request-derived text is only
  ever a dict key, never a path component. (First attempt built the index at import time —
  7 `test_llm.py` unit tests failed: those tests inject a temp fixtures dir per test.)
- **`FixtureEmbedder` md5→sha256** — test-only code, zero pipeline impact.
- **`lint.py` parser-based inline-script check**: `_InlineScriptBodyParser(HTMLParser)`
  replaces the regex path — the parser sees the document the way a browser does, catches
  unclosed `<script>` bodies the regex missed, and treats `<script/>` as opening (HTML does
  not self-close script).
- **Frontend base bump**: `1.27-alpine` → `1.31.7-alpine3.24` + `apk update && apk upgrade
  --no-cache brotli-libs curl libcurl libexpat`. Two traps: the base ships a frozen package
  index from its build date (fixes invisible without `apk update` → apk exit 99), and the
  unprivileged base runs as UID 101 (apk needs root → `USER 0`/`USER 101` sandwich; `USER
  root` itself trips hadolint DL3066 → numeric `USER 0`). nginx itself is not upgraded.
  → frontend **0.1.3**.
- **Factory pip security pins**: `setuptools==84.2.1 wheel==0.46.2 jaraco.context==6.1.0`
  after the requirements install. The first attempt (setuptools 78.1.1) still left 2 HIGH:
  trivy counts setuptools's **vendored** dist-info copies (`setuptools/_vendor/
  jaraco.context-5.3.0`, `wheel-0.45.1`), and 78.1.x vendors the vulnerable ones; 84.2.1 is
  clean and vendors the fixed copies (jaraco.context 6.1.0, wheel 0.46.3). The torch pin
  conflict is a pip warning only (setuptools is a build-time dep for torch). → factory **0.3.7**.

## Gotcha 9, live again

The first 0.3.7 build started before the mock fix landed on disk: its COPY layer baked the
pre-fix mock (pip layer rebuilt, COPY layer stale). The in-cluster startup suite caught it
(`AssertionError: 'Motion' != 'x'` — the mock served the repo's static fixture instead of
the test's temp fixture) while the local mounted-tree test run was green — the mount masked
the stale baked code. Diagnosis: grep the baked file inside the image + compare mtimes.
Fix: rebuild (pip layer cache hit, COPY invalidated by changed content) + run the suite
against baked code with NO mount before loading. Lesson: never trust a mounted-tree test
run for image-content verification.

## Verification

- Local: 209 unit + 7 integration + 10 frontend green; ruff + format + mypy clean (56
  files); both Dockerfiles hadolint-clean at `--failure-threshold info`; frontend 0.1.3
  trivy exit 0 + seeded smoke 7/7; factory 0.3.7 smoke + `pipeline --help` + trivy exit 0;
  baked-code grep shows the fixed mock; baked-code suite (no mount) 209 + 7 green.
- Cluster: both images loaded; stack re-applied (kubeconform + kube-linter green);
  factory-smoke Complete; frontend rolled out on 0.1.3 — PVC **not** re-seeded (shell
  content unchanged 0.1.2→0.1.3, no-clobber seed no-ops; gotcha 14 confirmed: reseed only
  when shell content changes); startup suite `test-manual-033604` 209 + 10 + 7 green; site
  200 (landing + css + healthz).

## Still open

- CI round 3 on the new head → green → merge PR #1 (CodeQL alerts #1–#6 should auto-close
  as fixed on re-analysis).
- Branch protection + required checks (founder); GHCR publish pipeline (founder).
- Motion `--fresh` trigger retagged: now on **0.3.7**.
