#!/usr/bin/env bash
# Publish the cluster-built site into the repo's frontend/ folder.
#
# Truth model (docs/deployment/kubernetes.md): the zivon-frontend PVC is the
# LIVE workspace (factory writes there, frontend Deployment serves there); the
# repo's frontend/ is the PERMANENT, standalone-deployable snapshot. This
# script is the one-way bridge PVC -> repo, run manually by the founder after
# a generation run produced pages worth publishing (same manual discipline as
# the factory trigger).
#
# What it copies: courses/ and courses.js ONLY (the generated output). The
# hand-maintained shell (index.html, assets/) stays repo-owned and is never
# overwritten from the cluster. Version rotation: courses/ is replaced
# wholesale, so the repo copy always mirrors exactly the current site;
# previous versions live in git history. Commit after publishing.
#
# Standalone deploy once published:
#   docker run --rm -p 8081:8080 -v "$PWD/frontend:/usr/share/nginx/html" \
#       zivon-frontend:0.1.5        # no factory, no cluster involved
#
# Usage: scripts/publish-frontend.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ns=zivon

if ! kubectl get deploy/frontend -n "$ns" >/dev/null 2>&1; then
  echo "no frontend Deployment in namespace $ns - nothing to publish from" >&2
  exit 1
fi
if [[ ! -f frontend/index.html ]]; then
  echo "repo frontend/ shell missing (index.html) - refusing to publish" >&2
  exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Pull the generated output from the PVC (the served html root).
kubectl exec -n "$ns" deploy/frontend -c nginx -- \
  tar -C /usr/share/nginx/html -cf - courses courses.js > "$tmp/site.tar"
tar -xf "$tmp/site.tar" -C "$tmp"

if [[ ! -d "$tmp/courses" || ! -f "$tmp/courses.js" ]]; then
  echo "PVC has no generated courses/ + courses.js - nothing to publish" >&2
  exit 1
fi

# Staleness guard (2026-11-06): the PVC mirrors whatever the LAST SUCCESSFUL
# run published, not whatever the last TRIGGERED run attempted. If the PVC
# site is byte-identical to the repo snapshot, the recent run never reached
# stage 11-link (check it: scripts/logs-factory-run.sh) and this script would
# silently "republish" an older topic. Say so loudly instead.
if [[ -d frontend/courses ]] \
   && diff -rq frontend/courses "$tmp/courses" >/dev/null 2>&1 \
   && cmp -s frontend/courses.js "$tmp/courses.js"; then
  echo "NOTHING NEW on the PVC: the site is identical to the repo snapshot." >&2
  echo "The last factory run did not publish a page (it failed before stage" >&2
  echo "11-link). Check it: scripts/logs-factory-run.sh  /  kubectl get jobs -n $ns" >&2
  echo "Repo frontend/ left untouched." >&2
  exit 2
fi

rm -rf frontend/courses
cp -a "$tmp/courses" frontend/courses
cp -a "$tmp/courses.js" frontend/courses.js

count=$(find frontend/courses -mindepth 3 -name index.html | wc -l)
echo "Published $count topic page(s) from $ns/zivon-frontend PVC -> frontend/"
find frontend/courses -mindepth 3 -name index.html | sed 's|/index.html||; s|^|  |'
echo
echo "Next: review the diff and commit - git history is the version rotation:"
echo "  git add frontend/courses frontend/courses.js"
echo "  git commit -m 'feat(site): publish <what changed>'"
