#!/usr/bin/env bash
# The "button" for the in-cluster evaluation & reviewer-calibration suite
# (stand-in for the Day-8 admin dashboard button).
# The suite ALSO runs on the EVAL_CRON_SCHEDULE cadence in k8s/infra.env.
#
# Usage: scripts/trigger-evals.sh [suite_or_suffix]
#   scripts/trigger-evals.sh            -> job eval-manual-<HHMMSS>
#   scripts/trigger-evals.sh smoke      -> job eval-smoke-<HHMMSS>
#   scripts/trigger-evals.sh calibrate  -> job eval-calibrate-<HHMMSS>
set -euo pipefail
suffix="${1:-manual}"
job="eval-${suffix}-$(date +%H%M%S)"
kubectl create job "$job" --from=cronjob/eval-suite -n zivon
echo "eval run started: job/$job"
echo "watch it: kubectl logs -f job/$job -n zivon"
