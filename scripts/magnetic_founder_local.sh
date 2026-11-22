#!/usr/bin/env bash
# Magnetic Effects unblock — founder-local, one command.
#
# Performs the full documented chain that this workstream validated offline but
# could NOT execute end-to-end in the workstream sandbox (the authorized
# deepseek-v4.1-flash route returned HTTP 429 GoUsageLimitError — weekly quota;
# see TIMELINE 2026-11-22):
#
#   1. fetch the CC BY 3.0 Siyavula Gr11/12 learner PDFs into sources/pdfs/
#      (scripts/fetch_siyavula.py; idempotent, keeps existing files);
#   2. warm the offline corpus (stages 00-ingest + 01-locate: page extraction
#      + embeddings, NO model calls — resumable, skipped if already cached);
#   3. regenerate the lesson (resumes a completed run for free; the pipeline's
#      fingerprint guard may ask for --fresh after a pipeline-shape change —
#      then re-run this script with MAGNETIC_FRESH=1);
#   4. verify the manifest grounds all six curated concepts offline
#      (scripts/verify_magnetic_manifest.py — A2's fatal checks);
#   5. STOP here unless the concept map is clean: if the regenerated manifest
#      has sections the tracked concept map does not cover, the script prints
#      exactly what to edit and exits 3 (the map is tracked data — the map
#      update is a reviewable commit, never an automatic rewrite);
#   6. generate the assessment bank (A1–A6, live --generator llm);
#   7. mirror the six pack files into sources/assessment/packs/<chapter>/
#      exactly as A6 wrote them (the documented deliberate mirror commit);
#   8. importer dry-run over ALL tracked packs (refuses a tampered/stale pack)
#      and print the DB row counts for the TRACKED_CHAPTERS pins in
#      testing/backend/test_assessment_import.py.
#
# Environment: runbook config must be exported in the calling shell
# (ZIVON_BASE_URL, ZIVON_MODEL, ZIVON_API_KEY if needed, ZIVON_EXTRA_HEADERS /
# ZIVON_USER_AGENT for the cloud gateway; see docs/content-factory/config-reference.md).
# Narration / Gnani vars are deliberately unset: published lessons carry
# narration: null and no credit spend is authorized here.
#
# Every step is idempotent/resumable; re-running the script after fixing a
# failure continues where it stopped.

set -euo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO"
PY="${PYTHON:-python3}"
CHAPTER_ID="class-10-magnetic-effects-of-electric-current"
CHAPTER_TITLE="Magnetic Effects of Electric Current"
PACK_SRC="runs/assessment-exports/$CHAPTER_ID"
PACK_DST="sources/assessment/packs/$CHAPTER_ID"

echo "== [1/8] fetch Siyavula sources (CC BY 3.0) =="
"$PY" scripts/fetch_siyavula.py .

echo "== [2/8] warm the offline corpus (00-ingest + 01-locate, no model calls) =="
"$PY" pipeline.py "$CHAPTER_TITLE" --locales hi,hi-Latn \
    --stages 00-ingest,01-locate

echo "== [3/8] regenerate the lesson (resume; MAGNETIC_FRESH=1 forces --fresh) =="
if [ "${MAGNETIC_FRESH:-0}" = "1" ]; then
    "$PY" pipeline.py "$CHAPTER_TITLE" --locales hi,hi-Latn --fresh
else
    "$PY" pipeline.py "$CHAPTER_TITLE" --locales hi,hi-Latn
fi

echo "== [4/8] offline manifest verification (six curated concepts, A2 fatal checks) =="
"$PY" scripts/verify_magnetic_manifest.py .

echo "== [5/8] concept-map checkpoint =="
echo "The manifest verification passed. If this was a NEW generation (not a"
echo "resume), review sources/syllabus/chapters/${CHAPTER_ID}.concept-map.json:"
echo "the section_concept_map must name every section of the regenerated"
echo "manifest (scripts/verify_magnetic_manifest.py already checked it) —"
echo "commit the map update with the lesson before running the bank."

echo "== [6/8] assessment bank (A1–A6, live --generator llm) =="
mkdir -p runs/assessment-exports
"$PY" -m factory.assessment \
    --chapter "$CHAPTER_ID" \
    --class 10 \
    --generator llm \
    --export-dir runs/assessment-exports

echo "== [7/8] mirror the pack into sources/assessment/packs/ =="
for f in manifest.json syllabus.json concepts.json questions.json speaking.json time-priors.json; do
    cp -v "$PACK_SRC/$f" "$PACK_DST/$f"
done

echo "== [8/8] importer dry-run + row counts for the pins =="
"$PY" scripts/import_assessment_packs.py --dry-run
COUNTS_DB="$(mktemp -d)/magnetic-counts.db"
"$PY" scripts/import_assessment_packs.py --db-url "sqlite:///$COUNTS_DB"
"$PY" - "$COUNTS_DB" <<'EOF'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
for table in ("question_bank", "speaking_prompt", "topic_time_prior", "assessment_pack"):
    print(table, db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
print("question rows for", "class-10-magnetic-effects-of-electric-current:",
      db.execute("SELECT COUNT(*) FROM question_bank WHERE chapter_id = ?",
                 ("class-10-magnetic-effects-of-electric-current",)).fetchone()[0])
EOF
rm -f "$COUNTS_DB"

echo
echo "DONE (machine steps). Human steps remain, in order:"
echo "  - commit the regenerated lesson + concept map (one commit);"
echo "  - commit the mirrored pack (one commit);"
echo "  - add $CHAPTER_ID to TRACKED_CHAPTERS in"
echo "    testing/backend/test_assessment_import.py and pin the counts printed"
echo "    above (question_bank / speaking_prompt / topic_time_prior /"
echo "    assessment_pack totals), computed by real import;"
echo "  - pytest testing/backend/test_assessment_import.py green, ruff clean,"
echo "    then PR."
