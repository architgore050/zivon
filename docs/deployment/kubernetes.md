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
- `10-factory-smoke-job.yaml` — the K8s twin of `docker run --rm zivon-factory:0.1.0`:
  - `Job` + `restartPolicy: Never` + `backoffLimit: 2` = batch semantics (fresh pod per retry; a failing Job ends `Failed` — CI-detectable).
  - No `command:` — the pod inherits the image's CMD (smoke test). Pipeline runs will override it.
  - `securityContext: runAsNonRoot: true` + `runAsUser: 1000` — see gotcha below.
  - `resources.requests` (scheduler placement) / `limits` (hard ceiling; torch import alone needs several hundred MB → 2 Gi limit). QoS class is `Burstable`, which decides eviction priority under node pressure.

## Local cluster: minikube (docker driver)

Single-node cluster running as a Docker container on the dev machine. Setup (one-time):

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl

minikube start --driver=docker
minikube image load zivon-factory:0.1.0   # see gotcha 2
kubectl apply -f k8s/
kubectl get jobs,pods -n zivon
kubectl logs job/factory-smoke -n zivon
kubectl describe pod -n zivon -l app=zivon-factory   # the Events section is the debugging gold
```

## Gotchas already paid for (learn from them)

1. **`runAsNonRoot` needs a numeric UID.** With only `USER app` in the image, kubelets refuse: *"image has non-numeric user (app), cannot verify user is non-root"* → `CreateContainerConfigError`. Fix: `runAsUser: 1000` in the manifest (or numeric `USER` in the image). kube-linter in CI now catches this class of mistake pre-cluster.
2. **minikube has its own image store.** Local images must be injected with `minikube image load` or pods sit in `ImagePullBackOff`. Once CI publishes to `ghcr.io`, clusters pull from the registry and this disappears.
3. **Jobs are immutable.** Editing a Job manifest requires `kubectl delete job ... && kubectl apply` — never apply-over.
4. **Group permissions after `usermod -aG docker`** only apply to new login sessions; GNOME terminals inherit the stale systemd user manager until reboot.

## Hosting decision (open)

Local minikube is dev-only. A real cluster (managed Kubernetes or a small VM host running k3s) is a Phase-3 decision; the deploy pipeline waits on it.
