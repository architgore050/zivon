#!/usr/bin/env bash
# PL5 — key-free smoke/regression gate for the personalized stack (W5.5).
#
# Runs everything the personalized workstream needs to prove "not broken"
# WITHOUT any API key, model call, or network:
#   1. the PL backend/voice/evals/docs unit suites (hermetic, in-process),
#   2. the deterministic eval smoke with the mock judge (0 model calls),
#   3. the regression gate over the smoke baseline.
#
# The FULL eval suite (judged model calls) is deliberately NOT here: it needs
# the D-PL-07 route with its runtime secret and runs founder-local in an
# authorized window (docs/specs/personalized-learning/evals.md §9-§10, AGENTS.md
# "model routing"). This script is the CI-equivalent merge gate; the live gate
# is a founder step, never a CI step.
#
# Usage: bash scripts/pl-smoke.sh [--fast]
#   --fast skips the two slowest in-process suites (the full evals discovery
#   and the observability map sweep) and runs the personalized-relevant parts.
#
# All run artifacts land in gitignored dirs (/tmp or evals_runs/); nothing in
# the repo tree is written by a passing run.

set -euo pipefail
cd "$(dirname "$0")/.."

FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

PY="${PYTHON:-python3}"

# Keep eval-run artifacts out of the repo tree in local runs.
export ZIVON_EVAL_RUNS_DIR="${ZIVON_EVAL_RUNS_DIR:-/tmp/pl-smoke-evals-runs}"
export ZIVON_RUNS_DIR="${ZIVON_RUNS_DIR:-/tmp/pl-smoke-runs}"
mkdir -p "$ZIVON_EVAL_RUNS_DIR" "$ZIVON_RUNS_DIR"

echo "== PL smoke gate (key-free) =="
echo "   eval runs -> $ZIVON_EVAL_RUNS_DIR"

echo "-- [1/4] personalized backend + voice + evals + docs suites"
$PY -m unittest discover -s testing/backend -t . -k personalized \
  || { echo "FAIL: personalized backend suites"; exit 1; }
$PY -m unittest discover -s testing/voice -t . -k personal -k prompt_safety \
  || { echo "FAIL: voice prompt/parity suites"; exit 1; }
$PY -m unittest discover -s testing/evals -t . -k personalized -k checkers \
  -k models_and_goldens \
  || { echo "FAIL: eval registry/checker suites"; exit 1; }
$PY -m unittest discover -s testing/docs -t . -k personalized \
  || { echo "FAIL: personalized spec contract tests"; exit 1; }

if [[ "$FAST" -eq 0 ]]; then
  echo "-- [2/4] observability contract (map rows resolve, redaction holds)"
  $PY -m unittest discover -s testing/observability -t . \
    || { echo "FAIL: observability contract"; exit 1; }
else
  echo "-- [2/4] observability contract (skipped by --fast)"
fi

echo "-- [3/4] deterministic eval smoke (--mock; 0 model calls)"
$PY -m evals run --suite smoke --mock \
  || { echo "FAIL: eval smoke"; exit 1; }

echo "-- [4/4] regression gate over the smoke baseline"
$PY -m evals run --suite smoke --mock --fail-on-regression \
  || { echo "FAIL: eval regression gate"; exit 1; }

echo "== PL smoke gate: PASS (key-free) =="
echo "Next gate (founder-local, NOT CI): 'python -m evals run --suite full' on the"
echo "configured D-PL-07 route — see docs/specs/personalized-learning/evals.md §9."
