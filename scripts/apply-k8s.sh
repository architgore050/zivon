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
#   3b. the Wave-E reserved manifests (17-18, 21-29, 51-53 per the GAP-017
#      map in docs/deployment/kubernetes.md) — each applied ONLY if the file
#      has landed, so the apply flow works unchanged between Wave-E merges.
#   4. the test CronJob rendered with TEST_CRON_SCHEDULE from infra.env
#   5. one immediate full test run (scripts/trigger-tests.sh startup)
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
export TEST_CRON_SCHEDULE ZIVON_BASE_URL ZIVON_MODEL ZIVON_TIMEOUT_S \
  ZIVON_CALL_DEADLINE_S ZIVON_STREAM ZIVON_STREAM_USAGE ZIVON_JSON_MODE \
  ZIVON_MAX_ATTEMPTS \
  ZIVON_FACTORY_MAX_ATTEMPTS ZIVON_LLM_MANAGER_URL \
  ZIVON_ENV ZIVON_LOG_LEVEL ZIVON_LOG_SYNC_SCHEDULE ZIVON_PUBLIC_BASE_URL \
  ZIVON_GRAFANA_URL ZIVON_NARRATION_ENABLED \
  EVAL_CRON_SCHEDULE ZIVON_EVAL_JUDGE_MODEL \
  ZIVON_VOICE_BRAIN_TRANSPORT ZIVON_VOICE_BRAIN_MODEL \
  ZIVON_NARRATION_BUILD_BUDGET COLD_PROVIDER
# ZIVON_LOG_DSN is intentionally absent: it carries DB credentials and lives
# only in the runtime Secret (never exported from this file).

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

# ---------------------------------------------------------------------------
# Wave-E reserved manifests (GAP-017 map: docs/deployment/kubernetes.md).
# Each reservation is applied only when its file exists — a reservation whose
# owner (EX0/EX3/EX4/EX8) has not merged yet is SKIPPED loudly, so this script
# works unchanged between the Wave-E merges and the new services enter the
# apply order automatically the day they land. Numeric order = dependency
# order. k8s/20 stays excluded (factory generation is manual-only) and the
# always-present manifests above stay explicit — that is why 23/24 (dashboard)
# and 51 (log retention, already rendered from infra.env) are NOT in this
# loop: they are applied by the explicit steps above, and re-applying them
# here would only duplicate work.
for f in k8s/17-*.yaml k8s/18-*.yaml k8s/21-*.yaml k8s/22-*.yaml \
         k8s/25-*.yaml k8s/26-*.yaml \
         k8s/27-*.yaml k8s/28-*.yaml k8s/29-*.yaml \
         k8s/52-*.yaml k8s/53-*.yaml; do
  if compgen -G "$f" > /dev/null; then
    echo "apply: $f"
    # Schedule-bearing CronJobs get their cadence from infra.env exactly like
    # k8s/50 above (never hardcoded in the YAML). The render list grows with
    # the bundle owner's placeholders.
    case "$f" in
      k8s/52-*) envsubst '${EVAL_CRON_SCHEDULE}' < "$f" | kubectl apply -f - ;;
      *)       kubectl apply -f "$f" ;;
    esac
  else
    echo "skip (reservation not landed yet): $f"
  fi
done

# Same gotcha-18 rule as the llm-manager restart above: pods read env/ConfigMaps
# only at start, so an infra.env knob change must reach the running Wave-E
# deployments. Guarded: a reserved deployment that has not landed yet is skipped.
for dep in dashboard core-backend; do
  if kubectl get deployment "$dep" -n zivon > /dev/null 2>&1; then
    kubectl rollout restart "deployment/$dep" -n zivon
  else
    echo "skip rollout restart (not deployed yet): $dep"
  fi
done

scripts/trigger-tests.sh startup
