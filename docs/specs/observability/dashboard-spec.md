# Admin Dashboard v0 (SP3-OBS)

**Scope:** the Day-8 "admin dashboard v0" from `TIMELINE.md` — one small FastAPI app + static UI, admin-only per [ADR-0026](../../backend/adr/0026-admin-auth.md), reading the product telemetry plane (ADR-0025's `log_events`) plus the factory's existing run artifacts. The infra plane stays with Prometheus + Grafana (`docs/deployment/README.md`, Decisions locked); the dashboard **links** to Grafana, it does not embed or re-implement it. Auth, k8s shape, and the two trigger buttons are specified here; the event names it consumes live in [`instrumentation-map.csv`](instrumentation-map.csv), the query contract is SQL over `log_events` per [`logging-api.md`](logging-api.md) §5.

## 1. Kubernetes shape and deployment

| Item | Value |
|---|---|
| Manifests | `k8s/23-dashboard-deployment.yaml`, `k8s/24-dashboard-service.yaml` (numbers reserved in the mission brief; apply order between 20-factory-run and 30-frontend) |
| Service | ClusterIP `dashboard.zivon.svc.cluster.local:80`; reached via `kubectl port-forward` or the edge route if `ZIVON_PUBLIC_BASE_URL` is set |
| Image | New `Dockerfile.dashboard` (python:slim + FastAPI + uvicorn + driver), tag pinned in the manifest per gotcha 9; **new CI job required** (build + smoke + scan) — integration note I-2, the infra agent owns the workflow edit |
| Namespace/config | `zivon`; env via `k8s/infra.env` line-edits (`ZIVON_LOG_DSN`, `ZIVON_PUBLIC_BASE_URL`, `ZIVON_ENV`, `ZIVON_LOG_SYNC_SCHEDULE`), secret `zivon-admin-auth` (key `ZIVON_ADMIN_TOKEN`) mounted env-only — secrets never in manifests (AGENTS.md) |
| Resources | requests 64 Mi / 50 m, limits 256 Mi / 250 m (a read-mostly UI; measured post-deploy, retuned with evidence) |
| Probes | `/healthz` (liveness+readiness): 200 when the process is up and the store is reachable OR fallback is active (a dashboard that cannot read the store says so on the page — it does not flap) |
| Data mounts | `runs/` PVC **read-only** (run artifacts, status.json, run_report.json); no other volumes; sessions in-memory (single replica, ADR-0026) |

Lints: kubeconform + kube-linter clean like every other manifest; hadolint on the new Dockerfile; the Deployment is `USER 1000` numeric like the factory image (gotcha 1).

## 2. Auth (summary — full decision in ADR-0026)

Single-admin bearer secret in K8s Secret `zivon-admin-auth`; login sets an HttpOnly, SameSite=Strict session cookie (opaque 128-bit id, 12 h TTL, 60 min idle re-auth, ≤ 8 sessions); constant-time compare; fail-closed (`503` on all admin routes if the Secret is missing, `dashboard.auth_unconfigured` CRITICAL); 5 failures / 15 min / source → 15 min lockout (`dashboard.auth_lockout`); every auth outcome and every button press is an L3 audit event. Route guard is a FastAPI dependency covering everything except `/admin/login` and `/healthz`. No multi-user, no OAuth — post-challenge.

## 3. Routes

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | none | probes |
| GET | `/admin/login` | none | token form (CSRF token issued here) |
| POST | `/admin/login` | none | token → session cookie (audited) |
| POST | `/admin/logout` | session | drop session |
| GET | `/admin` | session | overview: the six views' headline tiles + alert banner |
| GET | `/admin/runs` | session | View 1: factory runs status |
| GET | `/admin/runs/{run_id}` | session | one run: stage timeline, catcher rounds, model-call stats, issues feed |
| GET | `/admin/tests` | session | View 2: test-suite results |
| GET | `/admin/voice` | session | View 3: voice latency percentiles |
| GET | `/admin/credits` | session | View 4: credit usage vs tranche/cap |
| GET | `/admin/errors` | session | View 5: error feed |
| GET | `/admin/publish` | session | View 6: publish status |
| POST | `/admin/actions/tests-now` | session + CSRF | trigger button 1 |
| POST | `/admin/actions/factory-run` | session + CSRF | trigger button 2 |

API conventions: server-rendered HTML (Jinja), `X-Request-Id` on every response; unauthenticated browser hits get `303 → /admin/login`, API clients `401`; no client-side framework, no external assets (CSP `default-src 'self'` for the dashboard's own pages).

## 4. Views (what each shows, and the exact source)

**V1 — Factory runs status.** Rows per recent run (last 20 by `factory.run.*` events, joined with `runs/<run_id>/status.json` from the read-only PVC for stage detail): state (running/completed/failed/resumed), current stage, wall time, catcher rounds, model-call count, last event age. The **manual-only rule is visible**: a run is "running" only if the `factory-run-<slug>-<HHMMSS>` Job exists (`kubectl get jobs` via in-cluster RBAC — read-only Role, see I-1); resume/fail states come from `factory.run.resumed` / `factory.run.failed`. Repair-catcher visibility per founder rule (failures never re-run the whole pipeline): each 04-repair/08-fixloop/10-reviewfix engagement is a row in the run detail with its `round`/`issues_count`.

**V2 — Test-suite results.** From `testing/` CronJob ecosystem: last N suite runs (scheduled `test-suite-<ts>` and manual `test-manual-<ts>`), pass/fail counts, duration, and the Job's log tail (last ~40 lines) — the same view the founder gets from `scripts/trigger-tests.sh` plus a `kubectl logs` tail today, minus the terminal. Source: Job status via kubectl + suite summary events (when the S-series test agent wires them, it adds `test.suite.*` rows to the map and a `test` component to the closed enum — until then V2 renders from Job status + log tail only; declared contract, OQ-4).

**V3 — Voice latency percentiles.** SQL over `voice.turn.e2e_latency`: p50/p95/max for trailing 1 h / 24 h / 7 d, split by hop (`stt_final_ms`, `llm_first_token_ms`, `tts_first_audio_ms`), against the Gate C budget line at **4,000 ms** (hop budgets in `spec.md` §9). A p95 breach raises `alert.voice_p95_breach` and pins the banner. Zero-data renders honestly as "no voice traffic yet" (Day-8 reality), never as a fake series.

**V4 — Credit usage vs tranche/cap.** From `credit.counter_update` (ADR-0015): latest cumulative per profile (`normal`, `demo`), bar vs cap, and the burn-budget line at **3,000** (40% = 2,000 demo reserve per `TIMELINE.md`). Crossing it raises `alert.credit_tranche_exhausted` + a red banner; `credit.guard_blocked` events (F-OPS-MET-01) surface as the guard's refusals.

**V5 — Error feed.** Latest ERROR/CRITICAL events grouped by `error_class` (the closed taxonomy, `spec.md` §7), each row: ts, event, component, correlation ids, fields summary; filter by class/component/run_id/session_id; the redaction-violation stream (`log.redaction_violation`) is its own pinned section — a nonempty section is a call-site bug to fix, not noise to clear.

**V6 — Publish status.** Current published page set per topic (from `factory.publish.*` + the frontend PVC listing), last publish time, source (`pvc`/`snapshot`), and per-page block counts from `runs/<run_id>/` artifacts.

Alert banner (all views): open `alert.*` conditions (spec §9) with the proving query; clears when the condition clears; acknowledgement is P1.

## 5. Trigger buttons (exact semantics — the dashboard adds no third path)

The buttons reproduce the existing scripts' semantics **by invoking those scripts** (kept as the implementation, `TIMELINE.md` "Admin trigger commands"); the dashboard is a remote control, not a re-implementation:

| Button | Runs (as the admin user inside the dashboard pod, `kubectl` in PATH, same RBAC) | Effect identical to |
|---|---|---|
| Run tests now | `scripts/trigger-tests.sh` | creates `test-manual-<HHMMSS>` Job from the CronJob spec; V2 shows it |
| Generate a topic | `scripts/trigger-factory-run.sh "<topic>" <class> --fresh` (form: topic text, class select 9–12, `--fresh` checkbox default on) | creates `factory-run-<slug>-<HHMMSS>` Job with `task=factory-run` labels; V1 shows it |

Guards: session + CSRF double-submit token (ADR-0026 §5); the factory Job keeps `backoffLimit: 0` and manual-only scheduling — the dashboard never schedules, retries, or deletes Jobs; concurrency rule preserved (a second factory run while one is running is refused in the form, matching `scripts/trigger-factory-run.sh`'s own guard); every invocation emits `dashboard.action_triggered` (L3) with action/args/result. "Watch the latest run" remains the label-based `scripts/logs-factory-run.sh` behavior, surfaced as a link from V1, not a websocket tail (P1 if wanted).

## 6. Non-goals

No model calls of any kind (no inference dependency); no writes to the store except its own audit/session events (the dashboard is not an emitter of business telemetry); no user management, no RBAC, no plugins, no alerting channels beyond the banner (email/Telegram P1); no Grafana replacement (link out); no public exposure beyond the admin gate (if `ZIVON_PUBLIC_BASE_URL` is unset, it is port-forward-only — the P1 "add edge route + TLS" step is a decision for the founder, not a default).
