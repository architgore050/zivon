#!/usr/bin/env bash
# Nightly (or on-demand) logical backup of the prototype Postgres database —
# the host-side default for docs/deployment/founder-cutover-runbook.md §h.
#
# What it does, in order:
#   1. pg_dump the DB via the RUNNING postgres container (unix-socket trust
#      inside the container, the same pattern prototype-deployment.md §7 uses),
#   2. gzip it on the HOST and land it OUTSIDE the repo (default
#      ~/zivon-backups — a dump must never risk being committed),
#   3. verify the file is non-empty and the gzip stream is intact,
#   4. delete dumps older than ZIVON_BACKUP_RETENTION_DAYS (default 14),
#   5. exit 0 only if every step succeeded; any failure exits non-zero
#      (so a cron line / systemd unit can alert on it).
#
# Dump format: plain SQL, gzipped (pg_dump without -Fc). Restores with psql
# only — no pg_restore — which keeps the founder restore drill one command.
# The in-volume `-Fc` cron variant in prototype-deployment.md §7 remains the
# cluster-parity alternative; this script is the simpler, off-host default.
#
# Usage:
#   scripts/backup_db.sh                      # defaults: .env.prod, ~/zivon-backups, 14 d
#   scripts/backup_db.sh -e /path/.env.prod -o /var/backups/zivon -r 30
#
# Env overrides (CLI flags win):
#   ZIVON_ENV_FILE              env file for docker compose (default .env.prod)
#   ZIVON_BACKUP_DIR            where dumps land (default ~/zivon-backups)
#   ZIVON_BACKUP_RETENTION_DAYS keep dumps this many days (default 14)
#
# Scheduling (host cron, as the user that runs the stack):
#   15 21 * * *  cd /path/to/zivon && scripts/backup_db.sh >> ~/zivon-backups/backup.log 2>&1
# See the founder runbook §h for the systemd-timer equivalent.

set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ZIVON_ENV_FILE:-.env.prod}"
BACKUP_DIR="${ZIVON_BACKUP_DIR:-$HOME/zivon-backups}"
RETENTION_DAYS="${ZIVON_BACKUP_RETENTION_DAYS:-14}"

while getopts "e:o:r:h" opt; do
  case "$opt" in
    e) ENV_FILE="$OPTARG" ;;
    o) BACKUP_DIR="$OPTARG" ;;
    r) RETENTION_DAYS="$OPTARG" ;;
    h) grep -E '^# (Usage|  scripts|Env |ZIVON_|Sched|  15 )' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag; see the header of scripts/backup_db.sh" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "FAIL backup: env file not found: $ENV_FILE" >&2
  echo "       pass -e /path/to/.env.prod (the file docker compose runs with)." >&2
  exit 1
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)

STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT_DIR="$BACKUP_DIR"
OUT_FILE="$OUT_DIR/zivon-db-$STAMP.sql.gz"
TMP_FILE="$OUT_DIR/.zivon-db-$STAMP.sql.gz.partial"

mkdir -p "$OUT_DIR"
trap 'rm -f "$TMP_FILE"' EXIT

echo "backup: dumping the zivon database (postgres container) -> $OUT_FILE"

# pg_dump inside the container (its own $POSTGRES_USER/$POSTGRES_DB), gzip on
# the host. pipefail makes a pg_dump failure fail THIS script, not just the
# pipeline. -T disables pseudo-tty allocation so the pipe is binary-clean.
if ! "${COMPOSE[@]}" exec -T postgres \
  sh -c 'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip -c > "$TMP_FILE"; then
  echo "FAIL backup: pg_dump/gzip pipeline failed (is the postgres container up?" >&2
  echo "       check: docker compose --env-file $ENV_FILE -f docker-compose.prod.yml ps)" >&2
  exit 1
fi

if [[ ! -s "$TMP_FILE" ]]; then
  echo "FAIL backup: the dump is empty (0 bytes) — refusing to count it as a backup." >&2
  exit 1
fi
if ! gzip -t "$TMP_FILE" 2>/dev/null; then
  echo "FAIL backup: gzip integrity check failed on the dump — it is corrupt." >&2
  exit 1
fi

mv "$TMP_FILE" "$OUT_FILE"
chmod 600 "$OUT_FILE"

# Retention: prune dumps older than the window (mtime, UTC-ish host clock).
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  PRUNED="$(find "$OUT_DIR" -maxdepth 1 -name 'zivon-db-*.sql.gz' -mtime "+$RETENTION_DAYS" -print -delete | wc -l)"
  if [[ "$PRUNED" -gt 0 ]]; then
    echo "backup: pruned $PRUNED dump(s) older than $RETENTION_DAYS days"
  fi
else
  echo "WARN backup: ZIVON_BACKUP_RETENTION_DAYS='$RETENTION_DAYS' is not a number — kept all dumps" >&2
fi

SIZE="$(du -h "$OUT_FILE" | cut -f1)"
echo "PASS backup: $OUT_FILE ($SIZE, gzip-verified)"
echo "next: keep at least one copy OFF this host (object store / second disk),"
echo "and rehearse the restore per the founder runbook §h — an untested backup is not a backup."
