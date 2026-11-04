#!/usr/bin/env bash
# The "button" for ONE content factory generation run — the stand-in for the
# Day-8 admin dashboard button (documented in TIMELINE.md). Manual-only by
# design: the factory NEVER runs on a schedule; only the test suite does.
#
# Usage: scripts/trigger-factory-run.sh "<chapter>" [class 6-12] [--fresh]
#   scripts/trigger-factory-run.sh "Motion" 9
#   scripts/trigger-factory-run.sh "Light - Reflection and Refraction"
#   scripts/trigger-factory-run.sh "Motion" 9 --fresh    # force clean generation
#
# Renders k8s/20-factory-run-job.yaml (the template): rewrites the Job name to
# factory-run-<chapter-slug>-<HHMMSS> and injects the chapter (+ optional
# --class / --fresh) into the pipeline command. The Job is topic-agnostic: the
# topic is a runtime input, nothing topic-specific is baked into any manifest.
# Run ids inside the Job are deterministic per (chapter+class): re-triggering
# the same topic RESUMES the previous attempt (completed stages reused);
# --fresh wipes it and generates from scratch. Server URL + model come from
# the zivon-factory-config ConfigMap (k8s/infra.env).
# Limitation: chapter names containing quotes or pipes are not supported
# (sed-rendered template).
set -euo pipefail
cd "$(dirname "$0")/.."

chapter="${1:?usage: trigger-factory-run.sh \"<chapter>\" [class 6-12] [--fresh]}"
class="${2:-}"
if [[ -n "$class" && ( ! "$class" =~ ^[0-9]+$ || "$class" -lt 6 || "$class" -gt 12 ) ]]; then
  echo "class must be an integer 6-12 (got: $class)" >&2
  exit 1
fi
if [[ "${3:-}" == "--fresh" ]]; then
  fresh_injection=", \"--fresh\""
elif [[ -n "${3:-}" ]]; then
  echo "unknown option: $3 (usage: trigger-factory-run.sh \"<chapter>\" [class 6-12] [--fresh])" >&2
  exit 1
else
  fresh_injection=""
fi

slug=$(printf '%s' "$chapter" | tr '[:upper:]' '[:lower:]' \
       | sed 's/[^a-z0-9]\{1,\}/-/g; s/^-//; s/-$//' | cut -c1-40)
name="factory-run-${slug}-$(date +%H%M%S)"

if [[ -n "$class" ]]; then
  injection="\"${chapter}\", \"--class\", \"${class}\"${fresh_injection}"
else
  injection="\"${chapter}\"${fresh_injection}"
fi

sed -e "s|factory-run-template|${name}|" \
    -e "s|\"__CHAPTER__\"|${injection}|" \
    k8s/20-factory-run-job.yaml | kubectl apply -f -

echo "generation run started: job/$name (chapter: ${chapter}${class:+, class: $class})"
echo "watch it: scripts/logs-factory-run.sh        # follows the latest run, no name needed"
echo "status:   kubectl get job $name -n zivon"
echo "note:     same topic+class re-triggered RESUMES the previous attempt; add --fresh to force clean"
