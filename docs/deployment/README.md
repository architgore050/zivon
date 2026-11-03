# Deployment docs

Everything about how Zivon is packaged, run, and shipped: containers, orchestration, and the CI/CD pipelines that gate every merge into `main`.

| Doc | Covers |
|---|---|
| [`docker.md`](docker.md) | Containerizing the content factory: image design, build/run workflow, decisions and gotchas |
| [`kubernetes.md`](kubernetes.md) | Running containers on a cluster: object model, our manifests, local minikube workflow |
| [`cicd.md`](cicd.md) | GitHub Actions pipelines: the merge gate, security scans, Dependabot, hardening rules, pending setup steps |

Pending infra work lives in **`TIMELINE.md` (repo root) — the centralized task list**. No separate TODO files in this folder.

## Status snapshot (2026-11-02)

| Piece | State |
|---|---|
| Content factory image (`Dockerfile`, smoke test, compose) | ✅ v0.3.1 covers the full factory **graph v2** + fixed test sets + the pinned-chain NCERT fetch path + resumable text cache + symbol-font text decoding + effectively-non-binding model-call limits + whole-chapter source packs (0.2.1: pdfplumber era; 0.2.2: read-only-safe tests; 0.2.3: pinned chain bundle + polite retries; 0.2.4: reusable text cache + 8 Gi run memory; 0.2.5: U+F0XX symbol-font decode in `clean_pdf_text`; 0.2.8: huge `max_tokens`/`timeout_s` defaults — qwen thinking counts against `max_tokens`; 0.2.9: `max_chars_ncert_to_model` 60k → 120k — measured class-9 chapters run 19k–62k chars, so no chapter is truncated; 0.3.0: graph v2 — one giant generate call, bounded catcher loops, resumable runs, `reviewfix.py`; 0.3.1: per-stage timing prints + `elapsed_s`/`stage_durations_s` accounting + model-call bracket logs with 60 s heartbeats (stall-vs-thinking is now diagnosable from the log), prompt rework per `skills/prompting-and-agent-design/` (goal-first generate prompt, lesson in 03-check's context, honest 09-review framing), loosened `weak-android` load/FCP budgets, `HF_HUB_OFFLINE=1` on the cluster Jobs) (`factory/` + `pipeline.py` + `sources/certs/`); rebuild + reload after the patch drop |
| Frontend image (`Dockerfile.frontend`, nginx site config, compose `web` service) | ✅ v0.1.0 serves the static site on host :8081 via compose (host :8080 stays free for the dev inference server; LAN-reachable for kid testing); CI builds + serves + scans it |
| K8s manifests (`k8s/`) — namespace, smoke Job, hf-cache PVC, sources PVC, frontend PVC + Deployment + Service, test CronJob, run Job TEMPLATE, `infra.env` | ✅ smoke Job + frontend hosting verified on local minikube: site live at **http://192.168.49.2:30080** (NodePort 30080, no manual command); test CronJob live — cadence rendered from `TEST_CRON_SCHEDULE` in `k8s/infra.env` (the config value; scheduled runs verified green) + manual trigger + startup run live; run Job is a topic-agnostic TEMPLATE (name + `__CHAPTER__` placeholders) triggered only via script — generation is manual-only, never scheduled; `backoffLimit: 0` (whole-pipeline re-runs are never sanctioned — gate failures are repaired in-run by their catchers) and the factory's `runs/` lives on the sources PVC (subPath `runs`) so re-triggering the same topic+class RESUMES; first generation re-running from the `zivon-sources` PVC (all 11 catalog books ingested and cached — 10 NCERT fetched, OpenStax + Siyavula seeded as manual-download PDFs; NCERT fetch unblocked via the pinned chain bundle, gotcha 10; OOM fixed, gotcha 11; symbol-font prelims fixed + cache purged, gotcha 13; model-call limits made effectively non-binding: `ZIVON_MAX_TOKENS=65536` + `ZIVON_TIMEOUT_S=3600` in `infra.env`) |
| Cluster config + admin trigger scripts (`k8s/infra.env`, `scripts/apply-k8s.sh`, `scripts/trigger-tests.sh`, `scripts/trigger-factory-run.sh`) | ✅ live: single-source cluster config (test cadence, server URL, model, request timeout → ConfigMap); apply flow runs the suite once on startup; the two trigger scripts are the documented Day-8 dashboard button stand-ins (TIMELINE.md) |
| Dev inference router (`docker/inference-router.Dockerfile` + compose `inference-router`) | ✅ live: bridges the host's loopback-only inference server to containers/cluster pods (`192.168.49.1:18080`); verified from host + from inside a cluster pod |
| CI merge gate (incl. test-suite job: content factory unit + e2e + frontend shell) + CodeQL + Dependabot | ✅ written; first live run will be the feature-branch PR |
| Branch protection on `main` (required checks) | ⬜ to configure in GitHub UI before the PR |
| Publish pipeline (merge → build → push to `ghcr.io`) | ⬜ next piece of CD |
| Deploy pipeline + cluster hosting decision | ⬜ partially closed: frontend hosting pattern decided (PVC + nginx Deployment); real-cluster choice + public domain/TLS still open |
| Voice backend image (FastAPI/WebSockets) + Deployment + Service | ⬜ comes with the voice loop (Phase 2) |

## Decisions locked here

- **Docker + Kubernetes + GitHub Actions + GHCR** are the decided infra stack. No alternative tools to evaluate.
- The content factory is a **batch workload → K8s Job**. Long-running services (voice backend) will be **Deployment + Service**.
- CI must never need `ZIVON_API_KEY`: the pipeline validates code, images, and manifests key-free. Secrets live only at runtime (env vars / K8s Secrets).
- All third-party GitHub Actions are pinned to commit SHAs; `GITHUB_TOKEN` permissions are least-privilege per job.
- **Test containerization policy:** production images ship runtime only — no test suites (attack surface + bloat). The image's smoke test is a health check, not a test suite. The perf harness (`testing/content_factory/perf/harness.py`) is a TOOL imported at runtime by stage 08, so it ships in the factory image. Tests run in CI against the repo; when a future service needs e2e in its exact production environment, use a multi-stage Dockerfile with a dedicated `test` target (FROM the runtime image + copy tests) rather than polluting the runtime image.
- **Monitoring (decided, build at Phase 3 / Day 8 — not before):** Prometheus + Grafana via `kube-prometheus-stack` (pods/nodes/resources, "what is running", load); Grafana's own auth is the admin gate. Loki for centralized logs is P2. Interim tools: `minikube addons enable metrics-server` → `kubectl top pods,nodes`; `docker stats`. Factory per-stage latency telemetry rides on structured logs into the same dashboards.
