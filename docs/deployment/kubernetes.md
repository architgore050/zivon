# Kubernetes — running Zivon on a cluster

## Object model (what maps to what)

| K8s object | Semantics | Zivon mapping |
|---|---|---|
| Pod | Smallest unit: 1+ containers sharing network/volumes | any running container |
| **Job** | Run a pod **to completion**, retry per `backoffLimit`, then done | **content factory** (batch pipeline) ✅ |
| **Deployment + Service** | Keep N replicas running forever; stable internal address | **frontend (nginx)** ✅, voice backend (Phase 2) |
| Namespace | Name isolation | `zivon` |
| Secret / ConfigMap | Runtime config & credentials | `ZIVON_API_KEY` at runtime — never in manifests |

Core idea: K8s is declarative. You write desired state in YAML; controllers reconcile reality toward it forever. The daily loop is `apply → observe events → diagnose → fix → recreate`.

## Our manifests (`k8s/`, numeric prefix = apply order)

- `00-namespace.yaml` — the `zivon` namespace.
- `10-factory-smoke-job.yaml` — the K8s twin of `docker run --rm zivon-factory:0.2.2`:
  - `Job` + `restartPolicy: Never` + `backoffLimit: 2` = batch semantics (fresh pod per retry; a failing Job ends `Failed` — CI-detectable).
  - No `command:` — the pod inherits the image's CMD (smoke test). Pipeline runs override it (see next file).
  - `securityContext: runAsNonRoot: true` + `runAsUser: 1000` — see gotcha below.
  - `resources.requests` (scheduler placement) / `limits` (hard ceiling; torch import alone needs several hundred MB → 2 Gi limit). QoS class is `Burstable`, which decides eviction priority under node pressure.
  - `automountServiceAccountToken: false` — the factory needs no K8s API access; pods get no cluster credentials.
- `20-factory-run-job.yaml` — a REAL pipeline run, configured for the dev inference router (see the router section): `ZIVON_BASE_URL=http://192.168.49.1:18080/v1`, `ZIVON_MODEL=qwen3.8-flash-next-iq3_xxs`. The `secretKeyRef` for the API key is `optional: true` — keyless local servers need no Secret; hosted servers: create it.
- `12-hf-cache-pvc.yaml` — the `zivon-hf-cache` PVC: the HuggingFace embedder cache (~90 MB) shared by the run Job and the test CronJob, so the model downloads once per cluster, not once per run (`HF_HOME` is baked into the factory image).
- `15-frontend-pvc.yaml` — the `zivon-frontend` PVC: the shared site volume. The run Job writes generated pages onto it (11-link publishes into `/app/frontend`); the frontend Deployment serves it. Apply order note: the PVC (15) must exist before the Job (20) that mounts it.
- `30-frontend-deployment.yaml` — nginx Deployment serving the site. A no-clobber `initContainer` (`cp -rn /opt/zivon-shell/* ...` — glob form; see gotcha 6) seeds the hand-maintained shell (landing page + assets, baked at `/opt/zivon-shell` in the image) into an empty PVC, so the landing page exists before the first pipeline run and generated content is never overwritten. Non-root (UID 101), capabilities dropped, read-only root fs with writable mounts for nginx's pid/cache/log dirs, probes, resource ceilings.
- `40-frontend-service.yaml` — NodePort `80 → 8080`, fixed `nodePort: 30080`. Stable host URL with no manual command: **http://192.168.49.2:30080** (minikube's fixed node IP). `minikube service frontend -n zivon` is the convenience opener. On a real cluster only the Service `type` changes (ingress/LB decision, TIMELINE.md infra TODO).
- `50-test-cronjob.yaml` — the scheduled full test suite (unit + frontend + integration) using the factory image with a command override. The `schedule:` line is the config value (cron granularity = minutes; see gotcha 7). Manual trigger: `kubectl create job --from=cronjob/test-suite <name> -n zivon` or the Kubernetes Dashboard's Recreate action on the Job.

## Pipeline Run Job pattern (`20-factory-run-job.yaml`)

The pattern every future topic run follows:

- **`command:` override** — replaces the image's CMD with `python pipeline.py "Motion" --class 9`. Same image, different job: smoke vs. work.
- **Secret for the key** — `ZIVON_API_KEY` via `secretKeyRef`, created imperatively (`kubectl create secret generic zivon-factory-env -n zivon --from-literal=...`). Never in a manifest, never in git. kube-linter's `unsecrets` check is exempted in `.kube-linter.yaml` with a documented reason: the manifest only *references* the Secret; the factory reads the key directly from the `ZIVON_API_KEY` env var (all server settings are env-only — see `docs/content-factory/config-reference.md`).
- **`activeDeadlineSeconds: 3600`** — a hung pipeline run dies; Jobs must not run forever.
- **Output split** — `runs/` is an `emptyDir` = EPHEMERAL evidence (dev retrieval: `kubectl cp zivon/<pod> runs -c factory`). `frontend/` is the `zivon-frontend` PVC: published pages land on the site the frontend Deployment serves, surviving the Job. Download caches (PDFs, text) are per-Job `emptyDir`s (re-fetched each run; NCERT downloads are small).
- **Prereq:** the Job's `ZIVON_BASE_URL` + `ZIVON_MODEL` env must point at a reachable server — missing server env (or the `CHANGE-ME` placeholder) is a hard config error by design, so this Job fails loudly until configured. Dev values are filled in (router URL + model ID); the router itself must be up (`docker compose up -d inference-router`).

## Dev inference router (`docker/inference-router.Dockerfile`)

The dev machine's OpenAI-format inference server binds **127.0.0.1 only** — and no container can ever reach a host's loopback (see gotcha 8). The server stays untouched; instead a tiny router bridges the gap:

- An `alpine` + `socat` container with `network_mode: host` — inside it, `127.0.0.1` IS the host loopback where the server lives.
- It listens on **`192.168.49.1:18080`** — minikube's host-side bridge gateway IP, deliberately NOT `0.0.0.0` (the server chose loopback-only privacy; the router re-exposes it only to the cluster, not the LAN).
- Every connection is forwarded to `127.0.0.1:8080`. The factory treats `http://192.168.49.1:18080/v1` as a normal OpenAI-format server — zero code changes.
- Start: `docker compose up -d inference-router` (`restart: unless-stopped`). Verified from the host AND from inside a cluster pod (`/v1/models` answers through the router).
- Dev tool only: not a product image, not in CI, not deployed to real clusters.

## Local cluster: minikube (docker driver)

Single-node cluster running as a Docker container on the dev machine. Setup (one-time):

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl

minikube start --driver=docker
minikube addons enable dashboard      # cluster UI (the CronJob/Job "Recreate" action)
minikube addons enable metrics-server # makes kubectl top nodes/pods work
minikube image load zivon-factory:0.2.2   # see gotcha 2
minikube image load zivon-frontend:0.1.0  # frontend hosting (see gotcha 2)
kubectl apply -f k8s/00-namespace.yaml -f k8s/10-factory-smoke-job.yaml
# Frontend hosting (site volume + nginx + NodePort service):
kubectl apply -f k8s/12-hf-cache-pvc.yaml -f k8s/15-frontend-pvc.yaml -f k8s/30-frontend-deployment.yaml -f k8s/40-frontend-service.yaml
# → open http://192.168.49.2:30080 (no extra command needed)
# Scheduled full test suite + manual trigger:
kubectl apply -f k8s/50-test-cronjob.yaml
kubectl create job --from=cronjob/test-suite test-manual-1 -n zivon
kubectl logs job/test-manual-1 -n zivon
# 20-factory-run-job.yaml is a template: apply it only once its env points at a
# reachable model server AND the zivon-factory-env Secret exists — otherwise it fails loudly.
kubectl get jobs,pods,deploy,svc,cronjob,pvc -n zivon
kubectl logs job/factory-smoke -n zivon
kubectl describe pod -n zivon -l app=zivon-factory   # the Events section is the debugging gold
```

## Gotchas already paid for (learn from them)

1. **`runAsNonRoot` needs a numeric UID.** With only `USER app` in the image, kubelets refuse: *"image has non-numeric user (app), cannot verify user is non-root"* → `CreateContainerConfigError`. Fix: `runAsUser: 1000` in the manifest (or numeric `USER` in the image). kube-linter in CI now catches this class of mistake pre-cluster.
2. **minikube has its own image store.** Local images must be injected with `minikube image load` or pods sit in `ImagePullBackOff`. Once CI publishes to `ghcr.io`, clusters pull from the registry and this disappears.
3. **Jobs are immutable.** Editing a Job manifest requires `kubectl delete job ... && kubectl apply` — never apply-over.
4. **Group permissions after `usermod -aG docker`** only apply to new login sessions; GNOME terminals inherit the stale systemd user manager until reboot.
5. **Reused tags mean stale images.** The cluster keeps whatever bytes were loaded under a tag. New code → new tag (`0.2.0` → `0.2.1` after the pdfplumber fix) → `minikube image load` again → delete + re-apply the Job. Never re-tag different content the same version.
6. **busybox `cp` silently no-ops on a `/.` source.** The seed initContainer used `cp -rn /opt/zivon-shell/. <dest>/` — on Alpine (busybox) that exits 0 and copies *nothing*; GNU `cp` on your laptop would have worked. Symptom: nginx up, `/healthz` 200, but `/` → 403 (empty root, no index). Fix: glob form `cp -rn /opt/zivon-shell/* <dest>/`. Related lesson: **initContainers only run at pod start** — after fixing the manifest, `kubectl delete pod` (or a template change) is what re-runs the seed. CI image smokes don't catch this class: it's cluster-path behavior, verified on-cluster.
7. **Cron granularity is minutes, not seconds.** K8s CronJob `schedule:` is cron syntax (min hour day month weekday); "every x seconds" is not expressible. The schedule line in `50-test-cronjob.yaml` is the config value; smallest sane unit is every few minutes. If sub-minute test loops are ever needed, the pattern is a runner Deployment with a sleep loop — deliberately not built (P2).
8. **A host's `127.0.0.1` is invisible to every container.** Containers reach the host only through bridge gateway IPs (`172.17.0.1`, `192.168.49.1`), never loopback — so a server bound to `127.0.0.1` is unreachable from Docker and cluster pods. Fix without touching the server: the inference router (section above) or rebind the server to `0.0.0.0`. Also: pointing containers at the host's LAN IP fails too when the listen socket is loopback-only.
9. **Cluster runs run IMAGES, not your working tree.** A test fix in the repo does nothing in-cluster until a new tag is built + `minikube image load`ed + manifests bumped (0.2.1 → 0.2.2 for the read-only-safe test fix). The CronJob failing twice on the stale `tmp-bad.json` test, then going green on 0.2.2, is this loop in action.

## Hosting decision (partially closed)

Closed by the frontend objects (15/30/40): generated pages persist on a PVC, nginx serves them as a Deployment + Service, and locally the NodePort gives a stable URL (http://192.168.49.2:30080) with `docker compose up web` serving the same site on :8080 (LAN-reachable for kid testing).

Still open (Phase-3): **which real cluster** runs this (managed Kubernetes vs a small VM host running k3s), and the **public domain** piece (ingress vs load balancer, TLS, DNS — the local NodePort is a dev convenience, not the public answer). The deploy pipeline waits on those.
