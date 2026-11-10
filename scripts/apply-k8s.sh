#!/usr/bin/env bash
# Apply the whole cluster stack from the single infra config (k8s/infra.env),
# then run the full test suite once immediately ("tests on startup" — the
# CronJob's first tick can be up to a full interval away).
#
# Order:
#   1. namespace
#   2. zivon-llm-manager-config, zivon-factory-config, and zivon-voice-config
#      ConfigMaps rendered from k8s/infra.env
#   3. manifests in dependency order (16 = llm-manager, 25 = postgres + PVCs,
#      26 = backend-migrate Job, 27 = core-backend Deployment+Service,
#      28 = backend config, 30/40 = frontend). k8s/20 is deliberately NOT
#      applied: factory generation is manual-only
#      (scripts/trigger-factory-run.sh).
#   4. the test CronJob (50) and retention/sync CronJobs (53) rendered with
#      schedules from infra.env
#   5. one immediate full test run (scripts/trigger-tests.sh startup)
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source k8s/infra.env
# export so envsubst (a child process) can see the values — sourced vars are
# shell-local by default.
export TEST_CRON_SCHEDULE ZIVON_BASE_URL ZIVON_MODEL ZIVON_TIMEOUT_S \
  ZIVON_CALL_DEADLINE_S ZIVON_STREAM ZIVON_STREAM_USAGE ZIVON_JSON_MODE \
  ZIVON_MAX_ATTEMPTS \
  ZIVON_FACTORY_MAX_ATTEMPTS ZIVON_LLM_MANAGER_URL \
  ZIVON_ENV ZIVON_LOG_LEVEL ZIVON_LOG_SYNC_SCHEDULE ZIVON_PUBLIC_BASE_URL \
  ZIVON_GRAFANA_URL \
  ZIVON_VOICE_BRAIN_TRANSPORT ZIVON_VOICE_BRAIN_MODEL \
  COLD_PROVIDER COLD_BUCKET_PRIMARY COLD_BUCKET_SECONDARY \
  TTL_VOICE_TURN_CRON_SCHEDULE SYNC_NIGHTLY_CRON_SCHEDULE BASE_BACKUP_CRON_SCHEDULE

kubectl apply -f k8s/00-namespace.yaml

# The llm-manager NODE's config: its upstream is the router (ZIVON_BASE_URL),
# and it owns the transport-retry budget for the model call.
kubectl create configmap zivon-llm-manager-config -n zivon \
  --from-literal=ZIVON_BASE_URL="$ZIVON_BASE_URL" \
  --from-literal=ZIVON_MODEL="$ZIVON_MODEL" \
  --from-literal=ZIVON_TIMEOUT_S="$ZIVON_TIMEOUT_S" \
  --from-literal=ZIVON_CALL_DEADLINE_S="$ZIVON_CALL_DEADLINE_S" \
  --from-literal=ZIVON_STREAM="$ZIVON_STREAM" \
  --from-literal=ZIVON_STREAM_USAGE="$ZIVON_STREAM_USAGE" \
  --from-literal=ZIVON_JSON_MODE="$ZIVON_JSON_MODE" \
  --from-literal=ZIVON_MAX_ATTEMPTS="$ZIVON_MAX_ATTEMPTS" \
  --dry-run=client -o yaml | kubectl apply -f -

# The FACTORY's config: it talks OpenAI chat-completions to the llm-manager
# Service (ZIVON_LLM_MANAGER_URL rendered as its ZIVON_BASE_URL) and does NOT
# retry transport itself (the node already retried the upstream leg).
kubectl create configmap zivon-factory-config -n zivon \
  --from-literal=ZIVON_BASE_URL="$ZIVON_LLM_MANAGER_URL" \
  --from-literal=ZIVON_MODEL="$ZIVON_MODEL" \
  --from-literal=ZIVON_TIMEOUT_S="$ZIVON_TIMEOUT_S" \
  --from-literal=ZIVON_CALL_DEADLINE_S="$ZIVON_CALL_DEADLINE_S" \
  --from-literal=ZIVON_MAX_ATTEMPTS="$ZIVON_FACTORY_MAX_ATTEMPTS" \
  --from-literal=ZIVON_NARRATION_ENABLED="$ZIVON_NARRATION_ENABLED" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f k8s/28-backend-config.yaml
kubectl create configmap zivon-voice-config -n zivon \
  --from-literal=ZIVON_ENV="cluster" \
  --from-literal=ZIVON_BACKEND_HOST="0.0.0.0" \
  --from-literal=ZIVON_BACKEND_PORT="8000" \
  --from-literal=ZIVON_RUNS_DIR="/app/runs" \
  --from-literal=ZIVON_COLD_STAGING_DIR="/tmp/zivon-cold-staging" \
  --from-literal=ZIVON_VOICE_BRAIN_TRANSPORT="$ZIVON_VOICE_BRAIN_TRANSPORT" \
  --from-literal=ZIVON_VOICE_BRAIN_MODEL="$ZIVON_VOICE_BRAIN_MODEL" \
  --from-literal=COLD_PROVIDER="$COLD_PROVIDER" \
  --from-literal=COLD_BUCKET_PRIMARY="$COLD_BUCKET_PRIMARY" \
  --from-literal=COLD_BUCKET_SECONDARY="$COLD_BUCKET_SECONDARY" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl delete job factory-smoke -n zivon --ignore-not-found
kubectl apply -f k8s/10-factory-smoke-job.yaml
kubectl apply -f k8s/12-hf-cache-pvc.yaml -f k8s/13-sources-pvc.yaml -f k8s/15-frontend-pvc.yaml
kubectl apply -f k8s/16-llm-manager.yaml
kubectl rollout restart deployment/llm-manager -n zivon
kubectl rollout status deployment/llm-manager -n zivon

kubectl apply -f k8s/25-postgres.yaml
kubectl rollout status deployment/postgres -n zivon
kubectl delete job backend-migrate -n zivon --ignore-not-found
kubectl apply -f k8s/26-backend-migrate-job.yaml
kubectl apply -f k8s/27-core-backend.yaml
kubectl rollout restart deployment/core-backend -n zivon
kubectl rollout status deployment/core-backend -n zivon

kubectl apply -f k8s/30-frontend-deployment.yaml -f k8s/40-frontend-service.yaml

# The admin DASHBOARD (k8s/23 + 24): its config is env-only (infra.env);
# ZIVON_ADMIN_TOKEN / ZIVON_LOG_DSN stay in runtime Secrets, never here.
kubectl create configmap zivon-dashboard-config -n zivon \
  --from-literal=ZIVON_ENV="$ZIVON_ENV" \
  --from-literal=ZIVON_LOG_LEVEL="$ZIVON_LOG_LEVEL" \
  --from-literal=ZIVON_PUBLIC_BASE_URL="$ZIVON_PUBLIC_BASE_URL" \
  --from-literal=ZIVON_GRAFANA_URL="$ZIVON_GRAFANA_URL" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/23-dashboard-deployment.yaml -f k8s/24-dashboard-service.yaml

# The log-retention CronJob (k8s/51): render its schedule from infra.env
# (same pattern as the test CronJob; the raw placeholder is not a cron expr).
envsubst '${ZIVON_LOG_SYNC_SCHEDULE}' < k8s/51-log-retention-cronjob.yaml | kubectl apply -f -

envsubst '${TEST_CRON_SCHEDULE}' < k8s/50-test-cronjob.yaml | kubectl apply -f -
envsubst '${TTL_VOICE_TURN_CRON_SCHEDULE} ${SYNC_NIGHTLY_CRON_SCHEDULE} ${BASE_BACKUP_CRON_SCHEDULE}' < k8s/53-sync-cronjobs.yaml | kubectl apply -f -

scripts/trigger-tests.sh startup
