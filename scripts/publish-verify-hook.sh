#!/usr/bin/env bash
# Generic publish-time upload + SHA-256 read-back verification hook (SYNC-01).
#
# Called by:
#   - scripts/publish-frontend.sh (C1 lesson bundles)
#   - EX2-TRANS publish flow (C1/C3 localized bundles)
#   - EX8-NARRATION publish flow (C2 pre-generated Opus narration audio)
#
# Usage:
#   scripts/publish-verify-hook.sh <artifact_path> [C1|C2|C3]
set -euo pipefail
cd "$(dirname "$0")/.."

target_path="${1:-frontend/courses}"
class_id="${2:-C1}"

if [[ ! -e "$target_path" ]]; then
  echo "publish-verify-hook: path '$target_path' does not exist" >&2
  exit 1
fi

python3 -m backend.sync publish-verify "$target_path" --class-id "$class_id"
