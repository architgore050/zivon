#!/usr/bin/env bash
# Watch the LATEST content factory generation run — no job-name timestamp
# needed. Every run Job carries label task=factory-run (k8s/20 template), so
# this script resolves "the latest factory run" itself and follows its logs.
#
# Usage:
#   scripts/logs-factory-run.sh            # status of latest run, then follow logs
#   scripts/logs-factory-run.sh --status   # just the status line (no following)
#   scripts/logs-factory-run.sh --list     # every factory run, oldest -> newest
set -euo pipefail

ns=zivon
sel=task=factory-run

jobs=$(kubectl get job -n "$ns" -l "$sel" \
       --sort-by=.metadata.creationTimestamp \
       -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n')

if [[ -z "$jobs" ]]; then
  echo "no factory runs found in namespace $ns (start one: scripts/trigger-factory-run.sh \"<chapter>\" [class])" >&2
  exit 1
fi

if [[ "${1:-}" == "--list" ]]; then
  kubectl get job -n "$ns" -l "$sel" --sort-by=.metadata.creationTimestamp
  exit 0
fi

latest=$(printf '%s\n' "$jobs" | tail -1)
echo "latest run: job/$latest"
kubectl get job "$latest" -n "$ns"

if [[ "${1:-}" == "--status" ]]; then
  exit 0
fi

echo "--- logs (Ctrl-C detaches; the Job keeps running) ---"
kubectl logs -f "job/$latest" -n "$ns"
