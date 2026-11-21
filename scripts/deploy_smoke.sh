#!/usr/bin/env bash
# Post-deploy smoke test for the prototype compose path — the machine-checkable
# core of docs/deployment/prototype-deployment.md §6, packaged for the founder
# runbook (docs/deployment/founder-cutover-runbook.md §g).
#
# Checks, over the PUBLIC origin (never the raw backend port):
#   1. /v1/health          200 with "db": "ok"   (the backend reached its DB)
#   2. /healthz            200 with "ok"         (edge -> web -> backend path)
#   3. /                   200                   (static site served)
#   4. /courses/10/physics 301                    (catalogue route redirects)
#   5. /class-10-physics/  200                   (the Class 10 lesson shell)
#   6. /assets/app.css     200                   (a real asset resolves)
#   7. /voice/ws           a WebSocket-shaped answer (101, or the app's
#                          close/403 semantics) — NOT a plain 404/timeout
#
# What it deliberately does NOT prove: a live voice turn (needs the Gnani +
# Gemini keys and a human on a real phone — runbook §g step 3), email delivery,
# or Google sign-in (both founder-input-blocked, runbook §j).
#
# Usage: scripts/deploy_smoke.sh <base-url>
#   scripts/deploy_smoke.sh https://zivon.example.com
# Exit 0 iff every check PASSes; prints one PASS/FAIL line per check.

set -euo pipefail

BASE="${1:-}"
if [[ -z "$BASE" ]]; then
  echo "usage: scripts/deploy_smoke.sh <base-url>   e.g. https://zivon.example.com" >&2
  exit 2
fi
BASE="${BASE%/}"   # tolerate a trailing slash

CURL=(curl -sS --max-time 20 -o /dev/null -w '%{http_code}')
FAILED=0

pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILED=1; }

code_at() {  # code_at <path> [extra curl args...]
  local path="$1"; shift
  "${CURL[@]}" "$@" "$BASE$path"
}

echo "smoke: $BASE"
echo "(machine checks only — after these PASS, do the runbook §g real-phone check)"

# 1. backend health: 200 + db ok (the /readyz semantics through the origin)
body="$(curl -sS --max-time 20 "$BASE/v1/health")" \
  && code="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' "$BASE/v1/health")" \
  || { fail "/v1/health unreachable (connection error)"; body=""; code="000"; }
if [[ "$code" == "200" ]] && grep -Eq '"db"[[:space:]]*:[[:space:]]*"ok"' <<<"$body"; then
  pass "/v1/health 200, db ok"
else
  fail "/v1/health: HTTP $code, db not ok — the backend is up but did not reach its DB; fix before traffic (runbook §i)"
fi

# 2. liveness through the full chain
code="$(code_at /healthz)" || code="000"
if [[ "$code" == "200" ]]; then pass "/healthz 200 (edge -> web -> backend)"; else fail "/healthz: HTTP $code"; fi

# 3. static site root
code="$(code_at /)" || code="000"
if [[ "$code" == "200" ]]; then pass "/ 200 (static site live)"; else fail "/: HTTP $code"; fi

# 4. the catalogue route redirects to the Class 10 page
code="$(code_at /courses/10/physics)" || code="000"
if [[ "$code" == "301" || "$code" == "302" ]]; then
  pass "/courses/10/physics $code (catalogue route redirects)"
else
  fail "/courses/10/physics: HTTP $code (expected a 301 redirect)"
fi

# 5. the Class 10 lesson shell (the prototype's one-class scope)
code="$(code_at /class-10-physics/)" || code="000"
if [[ "$code" == "200" ]]; then pass "/class-10-physics/ 200 (lesson shell live)"; else fail "/class-10-physics/: HTTP $code"; fi

# 6. a real asset resolves
code="$(code_at /assets/app.css)" || code="000"
if [[ "$code" == "200" ]]; then pass "/assets/app.css 200 (assets resolve)"; else fail "/assets/app.css: HTTP $code"; fi

# 7. voice WS reaches the monolith: 101 upgrade, or the app's own close/403
#    semantics (curl completes an upgrade handshake only with real WS support,
#    so any of 101/400/403/426 proves the ROUTE answers — a plain 404, 5xx,
#    000 or timeout does not).
code="$(code_at /voice/ws -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: c2bva2V5')" || code="000"
case "$code" in
  101|200|400|403|426) pass "/voice/ws HTTP $code (WS route answers)" ;;
  *) fail "/voice/ws: HTTP $code — not a WebSocket-shaped response; /voice/ is not proxied (check docker/nginx.conf is in the web image)" ;;
esac

echo "----------------------------------------"
if [[ "$FAILED" -ne 0 ]]; then
  echo "RESULT: FAIL — fix the FAIL lines, then re-run."
  exit 1
fi
echo "RESULT: PASS — now the human check: open a Class 10 lesson on a real phone over HTTPS, grant the mic, speak one doubt (runbook §g)."
