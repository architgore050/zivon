#!/usr/bin/env bash
# Shared smoke pattern for service images — the llm-manager CI job pattern
# (boot-with-config -> /healthz poll -> refuses-without-config), extracted so
# every Wave-E image job (core-backend monolith, dashboard, ...) reuses one
# audited implementation instead of copy-pasting the inline check per job.
#
#   1. boot-with-config (default):
#        docker/smoke_http_service.sh --image IMG --name N --port H:C \
#            --boot-env VAR=VAL [--boot-env VAR2=VAL2 ...] [--healthz /healthz]
#      runs the image with its config env, polls the health endpoint until it
#      answers; dumps the container log and fails otherwise.
#   2. refuses-without-config (--refuse-without-config):
#        docker/smoke_http_service.sh --image IMG --refuse-without-config \
#            [--config-error-pattern REGEX]
#      runs the image with NO config env and expects a loud nonzero exit
#      INSIDE the timeout — AND that the output names the missing config.
#      A nonzero exit alone proves nothing (a crashed importer also exits 1);
#      the container's stdout+stderr must match the config-error pattern
#      (default: config|required|missing|not set|must be set|ZIVON_).
#      Repo rule: config via env, no silent defaults.
#      Note this is stricter than the llm-manager job's original inline check:
#      a container that hangs without config exits 124 from `timeout` and is
#      treated as a FAILURE here (a hang is not a refusal).
#
# Everything runs key-free: the --boot-env values are dummy config (dead DSNs,
# dev env names) — product secrets never enter CI (AGENTS.md non-negotiable).
#
# Per-image expectations live in the CI jobs (.github/workflows/ci.yml):
# which --boot-env values a service needs to boot, and whether it must refuse
# without them. When an execution agent lands its service, adjust the job's
# arguments there — this script stays generic.
set -euo pipefail

IMAGE=""
NAME="smoke-http-service"
PORT_MAP=""
HEALTHZ="/healthz"
TIMEOUT=30
REFUSE=false
BOOT_ENVS=()
# A refusal must NAME the missing config, not merely exit nonzero.
CONFIG_ERROR_PATTERN='config|required|missing|not set|must be set|ZIVON_'

usage() {
  sed -n '2,31p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --image) IMAGE="${2:?--image needs a value}"; shift 2 ;;
    --name) NAME="${2:?--name needs a value}"; shift 2 ;;
    --port) PORT_MAP="${2:?--port needs host:container}"; shift 2 ;;
    --healthz) HEALTHZ="${2:?--healthz needs a path}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout needs seconds}"; shift 2 ;;
    --refuse-without-config) REFUSE=true; shift ;;
    --config-error-pattern) CONFIG_ERROR_PATTERN="${2:?--config-error-pattern needs a regex}"; shift 2 ;;
    --boot-env) BOOT_ENVS+=("${2:?--boot-env needs VAR=VAL}"); shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done

if [ -z "$IMAGE" ]; then
  echo "ERROR: --image is required" >&2
  usage
fi

# ---- refuses-without-config -------------------------------------------------
if [ "$REFUSE" = true ]; then
  echo "refuse-without-config: running $IMAGE with no config env (timeout ${TIMEOUT}s)"
  out=$(mktemp)
  trap 'rm -f "$out"' EXIT
  started=$(date +%s)
  set +e
  timeout "$TIMEOUT" docker run --rm "$IMAGE" >"$out" 2>&1
  rc=$?
  set -e
  elapsed=$(( $(date +%s) - started ))
  if [ "$rc" -eq 124 ]; then
    echo "ERROR: $IMAGE was still running after ${TIMEOUT}s — it booted without config and served." >&2
    echo "A hang is not a refusal: the service must exit loudly and fast without its config env." >&2
    exit 1
  fi
  if [ "$rc" -eq 0 ]; then
    echo "ERROR: $IMAGE exited 0 without config — silent defaults are forbidden (config via env only)." >&2
    exit 1
  fi
  if ! grep -Eiq -- "$CONFIG_ERROR_PATTERN" "$out"; then
    echo "ERROR: $IMAGE exited $rc but its output carries no config-error marker." >&2
    echo "Expected a match for: $CONFIG_ERROR_PATTERN" >&2
    echo "A bare nonzero exit can be a crash, not a refusal — captured output:" >&2
    cat "$out" >&2
    exit 1
  fi
  echo "OK: refused without config (exit $rc after ${elapsed}s; output names the config error)"
  exit 0
fi

# ---- boot-with-config --------------------------------------------------------
if [ -z "$PORT_MAP" ]; then
  echo "ERROR: --port host:container is required for the boot check" >&2
  usage
fi

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "boot-with-config: starting $NAME from $IMAGE (port $PORT_MAP, healthz $HEALTHZ)"
run_args=(docker run -d --name "$NAME" -p "$PORT_MAP")
for e in "${BOOT_ENVS[@]}"; do run_args+=(-e "$e"); done
run_args+=("$IMAGE")
"${run_args[@]}"

host_port="${PORT_MAP%%:*}"
for _ in $(seq 1 "$TIMEOUT"); do
  if curl -sf "http://127.0.0.1:${host_port}${HEALTHZ}" > /dev/null; then
    echo "OK: $IMAGE answered ${HEALTHZ} (boot-with-config)"
    exit 0
  fi
  sleep 1
done

echo "ERROR: ${HEALTHZ} did not answer within ${TIMEOUT}s — container logs:" >&2
docker logs "$NAME" >&2 || true
exit 1
