# Runbook: import assessment packs into the hot database

Operator procedure for `scripts/import_assessment_packs.py` — the only write
path from an assessment pack (`factory.assessment` A6 export) into
`question_bank`, `speaking_prompt`, `topic_time_prior`, and the
`assessment_pack` provenance row (db-spec §4.19, revision
`0004_practice_speaking_tests`).

Applies to: bringing practice/speaking content into a dev, staging, or cluster
database; re-importing after a new A6 export. **Never** a scheduled job — the
factory stays manual and so does its import.

Key-free and offline: the script reads tracked files and a database URL, never a
model or a vendor socket.

---

## 1. Prerequisites

| Need | How |
|---|---|
| Schema at head | the DB is at `0004_practice_speaking_tests` (`python -m db.migrate current`, or the cluster's `26-backend-migrate-job`). `--no-migrate` refuses a stale schema; the default runs the idempotent chain first |
| Driver | SQLite needs nothing (stdlib). PostgreSQL needs `psycopg` (`pip install -r backend/requirements.txt` in the checkout) |
| Content | `sources/assessment/packs/<chapter_id>/` contains `manifest.json` + the five data files, byte-identical to what A6 wrote |
| DB URL | `--db-url` or `ZIVON_DB_URL`; the value is a secret in the cluster, so read it from the Secret/env — never paste it into a shell history on a shared host |

The script runs from a repo checkout (it puts the repo root on `sys.path`). It is
an operator bridge like `scripts/publish-frontend.sh`, not part of any image, so
for a cluster database port-forward the Service and run it from the checkout:

```bash
kubectl -n zivon port-forward svc/postgres 5432:5432     # terminal 1
# terminal 2: the DSN is the one in the `zivon-voice-env` Secret (key
# ZIVON_DB_URL) with its host replaced by 127.0.0.1, e.g.
#   postgresql://zivon:<db-password>@127.0.0.1:5432/zivon
# Read the password from the Secret; never echo it into shell history or a log.
ZIVON_DB_URL='postgresql://zivon:<db-password>@127.0.0.1:5432/zivon' \
  python3 scripts/import_assessment_packs.py --no-migrate
```

(`--no-migrate` is for a cluster database whose schema the migrate Job already
moved to head. Without port-forward access, the equivalent is to run the same
command from a pod that mounts the checkout and reaches `postgres` on the
cluster network — the script itself needs only `db/`, `sources/`, and psycopg.)

## 2. Procedure

1. **Verify first (no writes).**

   ```bash
   python3 scripts/import_assessment_packs.py --dry-run
   ```

   Expect one `verified <chapter>` line per pack plus
   `dry run: N pack(s) verified, nothing written`. A refusal here is the gate
   doing its job (see §4); fix the pack, do not bypass the check by hand-editing
   the database.

2. **Confirm the target database is the one you think it is.** For Postgres,
   read `schema_version` and the current row counts:

   ```sql
   SELECT version_num FROM alembic_version;
   SELECT chapter_id, COUNT(*) FROM question_bank GROUP BY chapter_id;
   ```

3. **Import.**

   ```bash
   # dev / local SQLite (gitignored file)
   python3 scripts/import_assessment_packs.py --db-url sqlite:///zivon.db

   # PostgreSQL (cluster: port-forward the Service or use the in-cluster Job shell)
   ZIVON_DB_URL="$ZIVON_DB_URL" python3 scripts/import_assessment_packs.py
   ```

   Expect `imported N pack(s): X question rows, Y speaking rows, Z topic priors
   (schema 0004_practice_speaking_tests)`.

4. **Verify the landing.**

   ```sql
   SELECT chapter_id, language, COUNT(*) AS rows FROM question_bank
    GROUP BY chapter_id, language ORDER BY chapter_id, language;
   SELECT chapter_id, COUNT(DISTINCT prompt_id) AS prompts FROM speaking_prompt
    GROUP BY chapter_id;
   SELECT chapter_id, scope, COUNT(*) AS rows FROM topic_time_prior
    GROUP BY chapter_id, scope;
   SELECT chapter_id, content_hash, imported_at FROM assessment_pack
    ORDER BY imported_at DESC;
   ```

   The tracked packs currently give, per chapter: 45 question rows (15 items ×
   EN/HI/Hinglish), 3 speaking prompts × 3 languages, and 8 topic priors (one
   chapter + seven concepts).

5. **Spot-check that the app can serve it.** A practice candidate set is
   non-empty for a published chapter, and a prompt's model answer is withheld
   from the list endpoint:

   ```bash
   python3 - <<'PY'
   from db.engine import DatabaseEngine
   from backend.assessment import list_speaking_prompts, select_question_ids

   db = DatabaseEngine.from_url("sqlite:///zivon.db", auto_migrate=False)
   print(len(select_question_ids(db, "class-9-describing-motion-around-us", language="en")))
   prompts = list_speaking_prompts(db, language="en")
   print(len(prompts), any({"key_ideas", "model_answer"} & set(prompt) for prompt in prompts))
   PY
   ```

   Expect `15`, then `N False` (prompts exist and neither the key ideas nor the
   model answer is in the list payload).

## 3. Re-import after a new export

1. Build the pack: `python -m factory.assessment --chapter <chapter_id> --export-dir runs/assessment-exports`.
2. Mirror `runs/assessment-exports/<chapter_id>/` into
   `sources/assessment/packs/<chapter_id>/` (replace the six files wholesale).
3. Commit that mirror on its own — the diff is the content change under review.
4. Run §2 again. An unchanged pack is a no-op in row counts; a changed pack
   upserts its rows and adds one `assessment_pack` row keyed by the new content
   hash. Old question ids that the new pack no longer contains stay in place;
   retire them explicitly (`UPDATE question_bank SET status='retired' WHERE
   question_id = '…'`) after checking nothing in a live paper uses them
   (`SELECT … FROM test_question WHERE question_id = '…'`).

## 4. Failure modes and what they mean

| Symptom | Cause | Action |
|---|---|---|
| `refused: … SHA-256 does not match the manifest` | the pack was edited after A6 wrote it | re-export, or restore the file from git; never hand-edit a pack |
| `refused: … content_hash does not match` | same, at the aggregate level | as above |
| `refused: … gate verdict is 'fail'` | A6 refused the pack | fix the upstream stage; a failed pack must not be importable |
| `refused: … chapter_id does not match the directory name` | a pack was copied into the wrong folder | move it; the directory name is the chapter identity |
| `refused: no pack directories` | wrong `--packs-dir` | pass the folder that contains `<chapter_id>/manifest.json` |
| `RuntimeError: Database at unknown revision` (runtime chain) | the DB is older/newer than this code | run `python -m db.migrate upgrade head` (or the cluster migrate Job) and retry |
| `E-…` from the app after import | the row is present but not servable | check `question_bank.status` (`reviewed`/`published` serve) and `speaking_prompt.status` |

**Atomicity.** Each pack is imported in one transaction: a failure mid-pack
writes nothing for that pack. With several packs, an earlier pack stays
imported — re-running is safe because the import is idempotent, so re-run the
same command rather than deleting rows.

**Rollback.** There is no `--revert`. To remove a pack's content, delete its
rows explicitly and deliberately:

```sql
DELETE FROM topic_time_prior WHERE pack_id = '<pack_id>';
DELETE FROM speaking_prompt  WHERE pack_id = '<pack_id>';
DELETE FROM question_bank    WHERE pack_id = '<pack_id>';  -- fails if a paper uses one (RESTRICT)
DELETE FROM assessment_pack  WHERE pack_id = '<pack_id>';
```

A `RESTRICT` failure is information: a paper references the question, so retire
it (`status='retired'`) instead of deleting it.

## 5. What this runbook does not cover

- **Catalogue rows.** `syllabus_chapter`/`concept` are P1/P2's import; until it
  lands, `/v1/catalog` serves F0's fixture and the question rows reference the
  curated chapter ids directly.
- **Test/series content.** P3's exam/series packs will reuse `assessment_pack`
  (`kind='exam'|'series'`) with their own importer step; `0004` ships no
  blueprint/source-paper tables (db-spec §10 Q13).
- **Publish orchestration.** Nothing calls this script automatically after an
  A6 export; wiring that into the publish path is later work
  (`docs/content-factory/assessment.md` §10 debt 6).
