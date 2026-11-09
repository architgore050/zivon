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
# What it copies: courses/ and courses.js (the generated pages) plus the
# pre-generated narration audio (audio/, stage 12-narration) when present.
# The hand-maintained shell (index.html, assets/) stays repo-owned and is
# never overwritten from the cluster. Version rotation: courses/ is replaced
# wholesale, so the repo copy always mirrors exactly the current site;
# previous versions live in git history. audio/ is mirrored ADDITIVELY (the
# content-hash filenames are immutable addresses - GAP-015: old audio stays
# addressable until eviction), and every asset is synchronously uploaded to
# the cold provider and sha256-read-back-verified when the coldstore env is
# configured (backend-spec SYNC-01 P0 form, class C2). Commit after publishing.
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
# Narration audio (audio/) arrived with 12-narration builds only, so it is
# pulled conditionally: an older PVC without it must not fail the tar.
if kubectl exec -n "$ns" deploy/frontend -c nginx -- \
    test -d /usr/share/nginx/html/audio >/dev/null 2>&1; then
  kubectl exec -n "$ns" deploy/frontend -c nginx -- \
    tar -C /usr/share/nginx/html -cf - courses courses.js audio > "$tmp/site.tar"
else
  kubectl exec -n "$ns" deploy/frontend -c nginx -- \
    tar -C /usr/share/nginx/html -cf - courses courses.js > "$tmp/site.tar"
fi
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

# Narration audio: additive mirror (content-addressed, immutable - existing
# hashes stay addressable; GAP-015), then the SYNC-01 P0 cold gate.
# NOTE: this block only runs when the staleness guard above passed, i.e. the
# pages changed. A narration-ONLY re-publish (pages identical) exits 2
# before reaching here - the live site is unaffected (it serves from the
# PVC); re-trigger the topic if you want a fresh repo snapshot.
if [[ -d "$tmp/audio" ]]; then
  mkdir -p frontend/audio
  cp -a "$tmp/audio"/. frontend/audio/
  audio_count=$(find frontend/audio -name '*.opus' | wc -l)
  echo "Mirrored narration audio: $audio_count opus asset(s) now under frontend/audio"
  echo
  # Publish-time synchronous cold upload + sha256 read-back verify
  # (backend-spec SYNC-01 P0 form for class C2). Unconfigured = loud skip.
  if python3 -m factory.narration.publish --root frontend/audio --cold; then
    :
  else
    echo "WARNING: cold upload+verify FAILED - narration serves from the" >&2
    echo "PVC but the C2 durability gate is unsatisfied (see frontend/audio/" >&2
    echo "cold-verify.json). Fix the provider and re-run this script." >&2
  fi
fi

count=$(find frontend/courses -mindepth 3 -name index.html | wc -l)
echo "Published $count topic page(s) from $ns/zivon-frontend PVC -> frontend/"
find frontend/courses -mindepth 3 -name index.html | sed 's|/index.html||; s|^|  |'
echo
echo "Next: review the diff and commit - git history is the version rotation:"
echo "  git add frontend/courses frontend/courses.js"
echo "  git commit -m 'feat(site): publish <what changed>'"
