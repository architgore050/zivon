# Deployment docs

Everything about how Zivon is packaged, run, and shipped: containers, orchestration, and the CI/CD pipelines that gate every merge into `main`.

| Doc | Covers |
|---|---|
| [`docker.md`](docker.md) | Containerizing the content factory: image design, build/run workflow, decisions and gotchas |
| [`kubernetes.md`](kubernetes.md) | Running containers on a cluster: object model, our manifests, local minikube workflow |
| [`cicd.md`](cicd.md) | GitHub Actions pipelines: the merge gate, security scans, Dependabot, hardening rules, pending setup steps |

## Status snapshot (2026-11-01)

| Piece | State |
|---|---|
| Content factory image (`Dockerfile`, smoke test, compose) | ✅ v0.2.1 covers the full factory (incl. pdfplumber fix) (19 modules + `pipeline.py`); rebuild + reload after the patch drop |
| Frontend image (`Dockerfile.frontend`, nginx site config, compose `web` service) | ✅ v0.1.0 serves the static site on :8080 (LAN-reachable for kid testing); CI builds + serves + scans it |
| K8s manifests (`k8s/`) — namespace, smoke Job, run Job, frontend PVC + Deployment + Service | ✅ smoke Job verified on local minikube; kubeconform + kube-linter green on all six manifests (verified with the CI-pinned tool versions); run Job needs a configured model server + Secret to run |
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
