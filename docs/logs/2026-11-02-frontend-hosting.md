# Session log — 2026-11-02 — frontend hosting (separate nginx image)

## Done

- **Separate frontend image**: `Dockerfile.frontend` on
  `nginxinc/nginx-unprivileged:1.27-alpine` (official non-root nginx: UID
  101, port 8080). Bakes only the hand-maintained shell — `index.html`,
  `assets/` (shared CSS/JS, local fonts) — staged at `/opt/zivon-shell`,
  plus `docker/nginx.conf`. Generated pipeline output (`courses/`,
  `courses.js`) is never baked (repo rule); it arrives at runtime on a
  mounted volume/PVC at the html root.
- **nginx site config** (`docker/nginx.conf`): site-wide CSP + `nosniff` +
  `no-referrer` headers, `no-store` for HTML/directory URLs/`courses.js`
  (demo-day freshness — a re-run shows immediately), 5-min revalidation
  otherwise, gzip, `/healthz` probe, autoindex off.
- **Local hosting**: compose `web` service — `docker compose up web` serves
  `./frontend` on `:8080`, LAN-reachable from a phone (kid testing path).
- **Cluster hosting**: `k8s/15-frontend-pvc.yaml` (shared site volume),
  `k8s/30-frontend-deployment.yaml` (nginx + no-clobber `cp -rn`
  initContainer that seeds the shell into an empty PVC),
  `k8s/40-frontend-service.yaml` (ClusterIP 80→8080). The run Job's
  `frontend/` moved from ephemeral `emptyDir` to the PVC — 11-link now
  publishes straight onto the served site. Apply order: 00 → 10 → 15 → 20
  → 30 → 40.
- **kube-linter was failing on the pre-existing manifests** (the gate had
  never run live): missing `ttlSecondsAfterFinished` on Jobs, no read-only
  root filesystem. Fixed across 10/20/30: Job TTLs (1 day),
  `readOnlyRootFilesystem: true` everywhere with writable mounts for the
  real write paths (`/tmp`, PDF/text caches, nginx pid/cache/log dirs).
  Verified locally with the CI-pinned tool versions: kubeconform 6/6 valid
  (strict, 1.33.0), kube-linter 0 errors.
- **CI**: new `frontend-image` job — hadolint → build → serve smoke test
  (container up: `/healthz` answers, landing renders, shared assets
  resolve, CSP/nosniff/no-store headers present) → trivy. Same pinned
  action SHAs and least-privilege pattern as the factory job.
- **Perf harness honesty**: docstring claimed "Navigation Timing"; the code
  measures wall-clock around `page.goto(wait_until="load")` with the
  browser already launched and throttled (startup never counted, cold
  cache every time). Docstring now matches the instrument.
- **Perf budget verdict (no change)**: keep `load_budget_s: 2.0`. The
  budget is enforced under 4× CPU throttle + 2-core pinning + mobile
  viewport, so 2 s throttled ≈ 500 ms unthrottled — the tightening was
  already baked in. A literal 0.5 s under throttle ≈ 125 ms unthrottled is
  below Chromium's own baseline for a multi-file page → permanent fix-loop
  churn and wasted credits. Revisit from measured `load_s` after the first
  real runs, not from intuition.
- Docs updated in the same commits: `docs/deployment/` README/docker/
  kubernetes/cicd, root README (`docker compose up web`), AGENTS.md infra
  section (new image + PVC facts).

## Not done / open

- The frontend image has never been built locally (docker daemon not
  reachable from this machine) — the CI `frontend-image` job is the first
  real build; the branch is unpushed, so that validation is pending.
- Public-domain piece still open (Phase-3): real cluster choice, NodePort
  vs ingress vs LB, TLS, DNS. The deploy pipeline waits on those.
- `courses.js` is served `no-store` even when absent (404 before the first
  run) — the landing page handles the empty state; fine for now.

## Next

- Push the branch → first live CI run of the whole gate (including the
  now-green manifests job and the new frontend-image job).
- First real-server pipeline run (Gate B); afterwards, revisit perf
  budgets from measured `load_s` headroom.
