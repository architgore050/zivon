# Observability operations — logging_manager, the log store, and the admin dashboard

The **spec** for this subsystem is [`docs/specs/observability/`](../specs/observability/) (system spec + the `logging_manager` API contract + the instrumentation map + the dashboard spec), with the decisions in ADR-0024 (stdlib JSON logging), ADR-0025 (hot store + fallback + retention) and ADR-0026 (admin auth). This page is the **operator view**: what runs where, how to deploy it, and how to troubleshoot it.

## What runs

| Piece | Code | Image / manifest | Notes |
|---|---|---|---|
| `logging_manager` module | `logging_manager/` | shipped inside the factory, dashboard, and retention images | every event goes through `log_event()`; the module owns redaction, sinks, correlation, and the `log_events` DDL |
| Hot log store | Postgres `log_events` (day-partitioned, ADR-0025 DDL) | the backend DB (OQ-7 tenancy) | written ONLY by `logging_manager` (`ZIVON_LOG_DSN`); the DSN lives in the runtime Secret `zivon-backend-env`, never in `infra.env` |
| JSONL fallback | `runs/logs/YYYYMMDD-<component>.jsonl` | the `zivon-sources` PVC (subPath `runs`) | byte-identical schema; a sync source for the daily Job; switch/recovery is loud (`log.store_fallback` / `log.store_recovered`) |
| Log retention + cold sync | `python -m logging_manager.store sync` | CronJob `log-retention` (`k8s/51`), factory image | daily 03:30 IST (`ZIVON_LOG_SYNC_SCHEDULE` in `k8s/infra.env`); exports yesterday's UTC day + checksum manifest, ingests fallback JSONL, then sweeps (L1/L2/credit 7 hot days, L3 30); retain-until-synced — an unverified day is never dropped |
| Admin dashboard | `dashboard/` | `zivon-dashboard:0.1.0` (`Dockerfile.dashboard`), `k8s/23` Deployment + `k8s/24` ClusterIP Service | six views, two trigger buttons (the SAME scripts), ADR-0026 auth; reached via `kubectl port-forward svc/dashboard 8082:80 -n zivon` unless `ZIVON_PUBLIC_BASE_URL` is set |

## Deploy

```bash
docker build -f Dockerfile.dashboard -t zivon-dashboard:0.1.0 .
minikube image load zivon-dashboard:0.1.0
# one-time per cluster: the admin secret (rotation = replace + rollout restart)
kubectl -n zivon create secret generic zivon-admin-auth \
  --from-literal=ZIVON_ADMIN_TOKEN="$(openssl rand -hex 32)"
scripts/apply-k8s.sh        # renders zivon-dashboard-config, applies 23/24, envsubsts 51
kubectl -n zivon port-forward svc/dashboard 8082:80
```

Config is env-only: `ZIVON_ENV`, `ZIVON_LOG_LEVEL`, `ZIVON_PUBLIC_BASE_URL`, `ZIVON_GRAFANA_URL` and `ZIVON_LOG_SYNC_SCHEDULE` come from `k8s/infra.env` (rendered by `scripts/apply-k8s.sh`); `ZIVON_ADMIN_TOKEN` and `ZIVON_LOG_DSN` come from runtime Secrets. The dashboard pod mounts the `runs/` PVC **read-only** and needs the RBAC grants from the EX3-OBS manifest's integration note I-1 (list/get Jobs, pods/log, create Jobs from the test CronJob) — until those land, Job views answer Forbidden and say so on the page.

## Troubleshoot

- **`log.store_fallback` in the error feed** — the hot store was unreachable; events went to `runs/logs/*.jsonl` on the PVC. Fix the DSN/pod; the next `log-retention` run ingests the fallback files (idempotent per file checksum) and `log.store_recovered` fires when Postgres accepts a batch again.
- **Redaction violations in the error feed** — a call site tried to log denied keys (`transcript*`, `token`, …) or scrubbed payloads. The event names the offending key, never the payload: fix the call site, do not clear the section.
- **Dashboard says `log store unreachable`** — the banner carries the driver error; `/healthz` answers `{"store": "unreachable"}`. Views degrade to honest empty states; nothing fabricated is shown.
- **Voice/credit views show "no data"** — those events start when the voice backend ships (S2 contract rows in the instrumentation map). The dashboard never fakes a series.
- **Buttons fail** — every invocation emits `dashboard.action_triggered` (action, args, result); the result carries the script's own output. Missing RBAC → Forbidden; a second factory run while one is active → refused (manual-only rule).
