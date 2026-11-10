#!/usr/bin/env bash
# The "button" for the in-cluster evaluation & reviewer-calibration suite
# (stand-in for the Day-8 admin dashboard button).
# The full suite ALSO runs on the EVAL_CRON_SCHEDULE cadence in k8s/infra.env.
#
# Usage:
#   scripts/trigger-evals.sh                  -> full suite, job eval-full-manual-<HHMMSS>
#   scripts/trigger-evals.sh smoke            -> one-off smoke job (0 model calls)
#   scripts/trigger-evals.sh calibrate        -> reviewer calibration only
#   scripts/trigger-evals.sh smoke startup    -> smoke job with an explicit suffix
set -euo pipefail

case "${1:-full}" in
  smoke|full|calibrate)
    suite="$1"
    suffix="${2:-manual}"
    ;;
  *)
    echo "usage: $0 [smoke|full|calibrate] [suffix]" >&2
    exit 2
    ;;
esac

job="eval-${suite}-${suffix}-$(date +%H%M%S)"

if [[ "$suite" == "full" ]]; then
  # The CronJob's own command already runs the full suite with
  # --fail-on-regression; clone it verbatim.
  kubectl create job "$job" --from=cronjob/eval-suite -n zivon
else
  kubectl create job "$job" --from=cronjob/eval-suite -n zivon \
    --dry-run=client -o json \
    | python3 -c '
import json, sys
obj = json.load(sys.stdin)
obj["spec"]["template"]["spec"]["containers"][0]["command"] = [
    "python", "-m", "evals", "run", "--suite", sys.argv[1],
    "--fail-on-regression",
]
print(json.dumps(obj))
' "$suite" | kubectl apply -f -
fi

echo "eval run started: job/$job (suite=$suite)"
echo "watch it: kubectl logs -f job/$job -n zivon"
