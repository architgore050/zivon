#!/usr/bin/env bash
# Apply the whole cluster stack from the single infra config (k8s/infra.env),
# then run the full test suite once immediately ("tests on startup" — the
# CronJob's first tick can be up to a full interval away).
#
# Order:
#   1. namespace
#   2. zivon-factory-config ConfigMap <- ZIVON_BASE_URL / ZIVON_MODEL (infra.env)
#   3. manifests in dependency order. k8s/20 is deliberately NOT applied:
#      factory generation is manual-only (scripts/trigger-factory-run.sh).
#   4. the test CronJob rendered with TEST_CRON_SCHEDULE from infra.env
#   5. one immediate full test run (scripts/trigger-tests.sh startup)
#
# Jobs are immutable: the smoke Job is deleted + re-applied so it re-runs as a
# post-apply health check. The run Job (k8s/20) is a template and never applied.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source k8s/infra.env
# export so envsubst (a child process) can see the values — sourced vars are
# shell-local by default.
export TEST_CRON_SCHEDULE ZIVON_BASE_URL ZIVON_MODEL ZIVON_TIMEOUT_S

kubectl apply -f k8s/00-namespace.yaml

kubectl create configmap zivon-factory-config -n zivon \
  --from-literal=ZIVON_BASE_URL="$ZIVON_BASE_URL" \
  --from-literal=ZIVON_MODEL="$ZIVON_MODEL" \
  --from-literal=ZIVON_TIMEOUT_S="$ZIVON_TIMEOUT_S" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl delete job factory-smoke -n zivon --ignore-not-found
kubectl apply -f k8s/10-factory-smoke-job.yaml
kubectl apply -f k8s/12-hf-cache-pvc.yaml -f k8s/13-sources-pvc.yaml -f k8s/15-frontend-pvc.yaml
kubectl apply -f k8s/30-frontend-deployment.yaml -f k8s/40-frontend-service.yaml

envsubst '${TEST_CRON_SCHEDULE}' < k8s/50-test-cronjob.yaml | kubectl apply -f -

scripts/trigger-tests.sh startup
