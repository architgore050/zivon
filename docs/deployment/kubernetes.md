# Kubernetes — running Zivon on a cluster

## Object model (what maps to what)

| K8s object | Semantics | Zivon mapping |
|---|---|---|
| Pod | Smallest unit: 1+ containers sharing network/volumes | any running container |
| **Job** | Run a pod **to completion**, retry per `backoffLimit`, then done | **content factory** (batch pipeline) ✅ |
| **Deployment + Service** | Keep N replicas running forever; stable internal address | voice backend, nginx frontend (Phase 2+) |
| Namespace | Name isolation | `zivon` |
| Secret / ConfigMap | Runtime config & credentials | `ZIVON_API_KEY` at runtime — never in manifests |

Core idea: K8s is declarative. You write desired state in YAML; controllers reconcile reality toward it forever. The daily loop is `apply → observe events → diagnose → fix → recreate`.

## Our manifests (`k8s/`, numeric prefix = apply order)

- `00-namespace.yaml` — the `zivon` namespace.
- `10-factory-smoke-job.yaml` — the K8s twin of `docker run --rm zivon-factory:0.2.0`:
  - `Job` + `restartPolicy: Never` + `backoffLimit: 2` = batch semantics (fresh pod per retry; a failing Job ends `Failed` — CI-detectable).
  - No `command:` — the pod inherits the image's CMD (smoke test). Pipeline runs override it (see next file).
  - `securityContext: runAsNonRoot: true` + `runAsUser: 1000` — see gotcha below.
  - `resources.requests` (scheduler placement) / `limits` (hard ceiling; torch import alone needs several hundred MB → 2 Gi limit). QoS class is `Burstable`, which decides eviction priority under node pressure.
  - `automountServiceAccountToken: false` — the factory needs no K8s API access; pods get no cluster credentials.
- `20-factory-run-job.yaml` — a REAL pipeline run (template): see next section.

## Pipeline Run Job pattern (`20-factory-run-job.yaml`)

The pattern every future topic run follows:

- **`command:` override** — replaces the image's CMD with `python pipeline.py "Motion" --class 9`. Same image, different job: smoke vs. work.
- **Secret for the key** — `ZIVON_API_KEY` via `secretKeyRef`, created imperatively (`kubectl create secret generic zivon-factory-env -n zivon --from-literal=...`). Never in a manifest, never in git. kube-linter's `unsecrets` check is exempted in `.kube-linter.yaml` with a documented reason: the manifest only *references* the Secret; the factory reads the key directly from the `ZIVON_API_KEY` env var (all server settings are env-only — see `docs/content-factory/config-reference.md`).
- **`activeDeadlineSeconds: 3600`** — a hung pipeline run dies; Jobs must not run forever.
- **Output is ephemeral** — `runs/` on an `emptyDir` vanishes with the pod. Dev retrieval: `kubectl cp zivon/<pod> runs -c factory`. Persistent output (generated pages, caches) needs a PVC — part of the hosting decision below.
- **Prereq:** the Job's `ZIVON_BASE_URL` + `ZIVON_MODEL` env must point at a reachable server — missing server env (or the `CHANGE-ME` placeholder) is a hard config error by design, so this Job fails loudly until configured.

## Local cluster: minikube (docker driver)

Single-node cluster running as a Docker container on the dev machine. Setup (one-time):

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl

minikube start --driver=docker
minikube image load zivon-factory:0.2.0   # see gotcha 2
kubectl apply -f k8s/00-namespace.yaml -f k8s/10-factory-smoke-job.yaml
# 20-factory-run-job.yaml is a template: apply it only once its env points at a
# reachable model server AND the zivon-factory-env Secret exists — otherwise it fails loudly.
kubectl get jobs,pods -n zivon
kubectl logs job/factory-smoke -n zivon
kubectl describe pod -n zivon -l app=zivon-factory   # the Events section is the debugging gold
```

## Gotchas already paid for (learn from them)

1. **`runAsNonRoot` needs a numeric UID.** With only `USER app` in the image, kubelets refuse: *"image has non-numeric user (app), cannot verify user is non-root"* → `CreateContainerConfigError`. Fix: `runAsUser: 1000` in the manifest (or numeric `USER` in the image). kube-linter in CI now catches this class of mistake pre-cluster.
2. **minikube has its own image store.** Local images must be injected with `minikube image load` or pods sit in `ImagePullBackOff`. Once CI publishes to `ghcr.io`, clusters pull from the registry and this disappears.
3. **Jobs are immutable.** Editing a Job manifest requires `kubectl delete job ... && kubectl apply` — never apply-over.
4. **Group permissions after `usermod -aG docker`** only apply to new login sessions; GNOME terminals inherit the stale systemd user manager until reboot.
5. **Reused tags mean stale images.** The cluster keeps whatever bytes were loaded under a tag. New code → new tag (`0.1.0` → `0.2.0`) → `minikube image load` again → delete + re-apply the Job. Never re-tag different content the same version.

## Hosting decision (open)

Local minikube is dev-only. A real cluster (managed Kubernetes or a small VM host running k3s) is a Phase-3 decision; the deploy pipeline waits on it.
