#!/usr/bin/env bash
# Apply the whole cluster stack from the single infra config (k8s/infra.env),
# then run the full test suite once immediately ("tests on startup" — the
# CronJob's first tick can be up to a full interval away).
#
# Order:
#   1. namespace
#   2. zivon-llm-manager-config ConfigMap <- the llm-manager NODE's upstream
#      (ZIVON_BASE_URL = the inference router, model, streaming/deadline knobs)
#      and zivon-factory-config ConfigMap <- the FACTORY's view (its
#      ZIVON_BASE_URL = the llm-manager Service, ZIVON_LLM_MANAGER_URL below)
#   3. manifests in dependency order (16 = the llm-manager Deployment+Service,
#      applied before anything that talks to it). k8s/20 is deliberately NOT
#      applied: factory generation is manual-only
#      (scripts/trigger-factory-run.sh).
#   4. the test CronJob rendered with TEST_CRON_SCHEDULE from infra.env
#   5. one immediate full test run (scripts/trigger-tests.sh startup) and one
#      smoke eval run (scripts/trigger-evals.sh smoke startup)
#
# ConfigMaps are read by pods ONLY at start: after the ConfigMaps are applied,
# the llm-manager Deployment is rollout-restarted so an endpoint/model/knob
# change in infra.env actually reaches the running node (an unchanged
# Deployment manifest alone never restarts it - the node would keep the old
# env and refuse calls naming the new model; gotcha 18).
#
# Jobs are immutable: the smoke Job is deleted + re-applied so it re-runs as a
# post-apply health check. The run Job (k8s/20) is a template and never applied.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source k8s/infra.env
# export so envsubst (a child process) can see the values — sourced vars are
# shell-local by default.
export TEST_CRON_SCHEDULE EVAL_CRON_SCHEDULE ZIVON_BASE_URL ZIVON_MODEL ZIVON_TIMEOUT_S \
  ZIVON_CALL_DEADLINE_S ZIVON_STREAM ZIVON_STREAM_USAGE ZIVON_JSON_MODE \
  ZIVON_MAX_ATTEMPTS ZIVON_EXTRA_HEADERS ZIVON_USER_AGENT \
  ZIVON_REASONING_EFFORT \
  ZIVON_FACTORY_MAX_ATTEMPTS ZIVON_LLM_MANAGER_URL \
  ZIVON_ENV ZIVON_LOG_LEVEL ZIVON_LOG_SYNC_SCHEDULE ZIVON_PUBLIC_BASE_URL \
  ZIVON_GRAFANA_URL

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
  --from-literal=ZIVON_EXTRA_HEADERS="$ZIVON_EXTRA_HEADERS" \
  --from-literal=ZIVON_USER_AGENT="$ZIVON_USER_AGENT" \
  --from-literal=ZIVON_REASONING_EFFORT="$ZIVON_REASONING_EFFORT" \
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

kubectl delete job factory-smoke -n zivon --ignore-not-found
kubectl apply -f k8s/10-factory-smoke-job.yaml
kubectl apply -f k8s/12-hf-cache-pvc.yaml -f k8s/13-sources-pvc.yaml -f k8s/15-frontend-pvc.yaml
kubectl apply -f k8s/16-llm-manager.yaml
# The node reads its env (endpoint/model/knobs) ONLY at pod start: applying
# an updated ConfigMap above does NOT restart the node, and the stale-env
# node refuses requests naming the new model (found live 2026-11-08: the
# 02-generate call asked for 'stealth/crouton-alpha' while the node pod,
# started before the config change, still served the old local model).
kubectl rollout restart deployment/llm-manager -n zivon
kubectl rollout status deployment/llm-manager -n zivon
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
envsubst '${EVAL_CRON_SCHEDULE}' < k8s/52-eval-cronjob.yaml | kubectl apply -f -

scripts/trigger-tests.sh startup
# One immediate smoke eval (0 model calls) so the apply is also an eval
# health check; the full suite stays on the EVAL_CRON_SCHEDULE cadence
# (OQ-EVAL-01).
scripts/trigger-evals.sh smoke startup
