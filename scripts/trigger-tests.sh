#!/usr/bin/env bash
# The "button" for the full in-cluster test suite — the stand-in for the Day-8
# admin dashboard button (both trigger commands are documented in TIMELINE.md).
# The suite ALSO runs automatically: on the CronJob cadence (TEST_CRON_SCHEDULE
# in k8s/infra.env) and once on every scripts/apply-k8s.sh (startup run).
#
# Usage: scripts/trigger-tests.sh [name-suffix]
#   scripts/trigger-tests.sh            -> job test-manual-<HHMMSS>
#   scripts/trigger-tests.sh startup    -> job test-startup-<HHMMSS>
set -euo pipefail
suffix="${1:-manual}"
job="test-${suffix}-$(date +%H%M%S)"
kubectl create job "$job" --from=cronjob/test-suite -n zivon
echo "test run started: job/$job"
echo "watch it: kubectl logs -f job/$job -n zivon"
