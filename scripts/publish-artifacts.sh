#!/usr/bin/env bash
# Mirror the cluster's pipeline evidence (runs/) from the zivon-sources PVC
# into the repo's gitignored runs/ folder.
#
# Why: in the cluster every factory run writes full stage evidence (requests,
# responses, retries, reports) under runs/ on the zivon-sources PVC, so it
# survives pod death and resumable runs. This script is the read-only human
# bridge PVC -> host: inspect what a run actually did without kubectl
# spelunking. It never writes to the cluster, and runs/ is gitignored -
# evidence stays on the host, out of git (repo rule).
#
# Merge semantics: each run directory on the PVC replaces its same-named
# local copy (the cluster copy is authoritative); local run dirs that are not
# on the PVC are left alone.
#
# Usage: scripts/publish-artifacts.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ns=zivon
pod=zivon-artifacts-peek

if ! kubectl get pvc zivon-sources -n "$ns" >/dev/null 2>&1; then
  echo "no zivon-sources PVC in namespace $ns - nothing to mirror" >&2
  exit 1
fi

cleanup() { kubectl delete pod "$pod" -n "$ns" --ignore-not-found >/dev/null 2>&1; }
trap cleanup EXIT
cleanup

# One-shot reader pod mounting the whole PVC at /peek (same pattern as the
# cache-purge pod in docs/deployment/kubernetes.md gotcha 13). The factory
# writes its evidence under the PVC's 'runs' directory (subPath in k8s/20).
kubectl apply -f - >/dev/null <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: zivon-artifacts-peek
  namespace: zivon
spec:
  restartPolicy: Never
  containers:
    - name: peek
      image: busybox:1.36
      command: ["sleep", "300"]
      volumeMounts:
        - name: sources
          mountPath: /peek
      resources:
        requests: { cpu: 50m, memory: 32Mi }
        limits: { cpu: 100m, memory: 64Mi }
  volumes:
    - name: sources
      persistentVolumeClaim:
        claimName: zivon-sources
EOF

kubectl wait --for=condition=Ready "pod/$pod" -n "$ns" --timeout=120s >/dev/null

if ! kubectl exec "$pod" -n "$ns" -- test -d /peek/runs; then
  echo "PVC has no runs/ evidence yet - nothing to mirror" >&2
  exit 1
fi

tarfile=$(mktemp)
trap 'rm -f "$tarfile"; cleanup' EXIT
kubectl exec "$pod" -n "$ns" -- tar -C /peek/runs -cf - . > "$tarfile"

mkdir -p runs
# Replace same-named run dirs wholesale, keep local-only dirs.
tar -tf "$tarfile" | awk -F/ 'NF>1 && $2!="" {print $2}' | sort -u | while read -r d; do
  rm -rf "runs/$d"
done
tar -xf "$tarfile" -C runs

count=$(find runs -mindepth 1 -maxdepth 1 -type d | wc -l)
echo "Mirrored evidence: $count run dir(s) in runs/ from $ns/zivon-sources PVC"
find runs -mindepth 1 -maxdepth 1 -type d | sort | sed 's|^|  |'
echo
echo "runs/ is gitignored - review freely, nothing to commit."
