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
