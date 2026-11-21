# Runbook: import exam/series packs into the hot database

Operator procedure for `scripts/import_series_packs.py` — the write path from
an E4 exam/series pack (`python -m factory.exam`, stage `E4-publish`) into
`test_series`, `test`, `test_question`, and the `assessment_pack` provenance
row with `kind='exam'` (db-spec §4.19, revision `0004_practice_speaking_tests`).
Mirrors `assessment-import.md` for the assessment packs, which own
`question_bank` — the table `test_question` points at.

Applies to: bringing the six test series into a dev, staging, or cluster
database. **Never** a scheduled job — the factory stays manual and so does its
import. **Live import happens at deployment cutover**: no database exists for
the prototype yet (deployment is blocked at cutover), so until then the
verified surface is `--dry-run` plus the committed fixture pack
(`testing/backend/fixtures/series_packs/class-10/`) that the test suite
imports hermetically. Do not invent a database.

Key-free and offline: the script reads tracked files and a database URL, never
a model or a vendor socket.

---

## 1. Prerequisites

| Need | How |
|---|---|
| **question_bank first** | the referenced `(base_item_id, language)` rows must exist — run `scripts/import_assessment_packs.py` (see `assessment-import.md`) before this script. A missing row refuses the pack with the id list; `test_question.question_id` is an FK into the bank (ON DELETE RESTRICT) |
| Schema at head | `0004_practice_speaking_tests` or later (`python -m db.migrate current`, or the cluster's `26-backend-migrate-job`). `--no-migrate` skips the migration step |
| Driver | SQLite needs nothing (stdlib). PostgreSQL needs `psycopg` (`pip install -r backend/requirements.txt`) |
| Pack | a **publishable** pack: `runs/exam-exports/<class>/manifest.json` (+ `papers/blueprint/items/series.json`), byte-identical to what E4 wrote. `--export-dir` is honoured only for a publishable pack; a blocked pack stays under `runs/exam/<run_id>/E4-publish/pack/` as evidence and is never mirrored (SER-13) |
| DB URL | `--db-url`, named explicitly. There is **no env-var fallback** (a deliberate deviation from the assessment importer): an operator cannot silently point the import at whatever `ZIVON_DB_URL` holds. The value is a secret in the cluster — read it from the Secret/env at the shell, never paste it into history or a log |

The script runs from a repo checkout (it puts the repo root on `sys.path`). It
is an operator bridge, not part of any image; for a cluster database
port-forward the Service and run it from the checkout (same shape as
`assessment-import.md` §1):

```bash
kubectl -n zivon port-forward svc/postgres 5432:5432     # terminal 1
# terminal 2: the DSN is the one in the `zivon-voice-env` Secret (key
# ZIVON_DB_URL) with its host replaced by 127.0.0.1. Read the password from
# the Secret; never echo it into shell history or a log.
python3 scripts/import_series_packs.py \
  --db-url 'postgresql://zivon:<db-password>@127.0.0.1:5432/zivon' --no-migrate
```

## 2. Procedure

1. **Verify first (no writes, no DB access).**

   ```bash
   python3 scripts/import_series_packs.py \
     --packs-dir runs/exam-exports --dry-run
   ```

   Expect one `verified class-<n>: X/Y series enabled, T test rows planned,
   Q question rows, sha256:...` line per pack plus
   `dry run: N pack(s) verified, nothing written`. A refusal here is the gate
   doing its job (see §4); fix the pack, do not bypass the check by
   hand-editing the database.

2. **Confirm the target database is the one you think it is.** For Postgres:

   ```sql
   SELECT version_num FROM alembic_version;
   SELECT COUNT(*) FROM question_bank;                     -- the bank landed?
   SELECT series_id, status FROM test_series;              -- before the import
   ```

3. **Import.**

   ```bash
   # dev / local SQLite (gitignored file)
   python3 scripts/import_series_packs.py \
     --packs-dir runs/exam-exports --db-url sqlite:///zivon.db

   # PostgreSQL (cluster: port-forward the Service or use the in-cluster Job shell)
   python3 scripts/import_series_packs.py --packs-dir runs/exam-exports \
     --db-url "$ZIVON_DB_URL"
   ```

   Expect `imported N pack(s): T test rows, Q test_question rows (schema
   0005_personalized_learning)`.

4. **Verify the landing.**

   ```sql
   -- one catalogue row per series; the dark one is draft
   SELECT series_id, kind, status, jsonb_array_length(language_set) AS languages
     FROM test_series ORDER BY series_id;

   -- one test per paper/set per offered language
   SELECT s.kind, t.language, COUNT(*) AS tests
     FROM test t JOIN test_series s ON s.series_id = t.series_id
    GROUP BY s.kind, t.language ORDER BY s.kind, t.language;

   -- the FK holds and the sheet marks are the paper's
   SELECT s.kind, COUNT(*) AS question_rows
     FROM test_question q JOIN test t ON t.test_id = q.test_id
     JOIN test_series s ON s.series_id = t.series_id
    GROUP BY s.kind;

   -- the provenance row
   SELECT pack_id, class_level, content_hash, imported_at FROM assessment_pack
    WHERE kind = 'exam' ORDER BY imported_at DESC;
   ```

   The committed fixture pack (the synthetic Class 10 example) yields 6
   `test_series` rows (5 published + the dark `exact_pyq` draft), 13 `test`
   rows and 18 `test_question` rows. Real packs yield their own counts — the
   `--dry-run` plan line is the number to expect.

5. **Spot-check that the app can serve it.** The catalogue must show the five
   published series (the dark series stays out of the published set) and a
   paper must resolve through the per-language join:

   ```bash
   python3 - <<'PY'
   from db.engine import DatabaseEngine
   from backend.assessment import list_series, list_test_questions, list_tests

   db = DatabaseEngine.from_url("sqlite:///zivon.db", auto_migrate=False)
   print(sorted(row["kind"] for row in list_series(db, class_level=10)))
   tests = list_tests(db, "class-10-board_practice")
   print([(t["test_id"], t["language"]) for t in tests])
   print(list_test_questions(db, tests[0]["test_id"])[0]["marks"])
   PY
   ```

   Expect five kinds without `exact_pyq`, one row per offered language, and
   the sheet marks (which may differ from the bank item's authored marks —
   that is the documented rule, not a bug).

## 3. Re-import after a new export

1. Build the pack: `python -m factory.exam --class 10 --export-dir runs/exam-exports`.
   Only a pack whose gate is `pass` **and** `publish.status` is `ready` is
   mirrored there; the importer re-checks both and refuses otherwise.
2. Run §2 again. An unchanged pack is a no-op in row counts: rows are upserted
   on stable natural keys (`test_series.series_id` =
   `class-<n>-<series_id>`, `test.test_id` =
   `class-<n>-<series>-<paper|set>-<language>`), and `assessment_pack` keeps
   one row per (class, content hash). A changed pack upserts its rows and
   writes a new provenance row keyed by the new content hash.
3. `test_question` rows are **replaced per test** inside the import
   transaction (nothing references them: attempt answers copy `question_id`
   as plain text), so a re-export that reorders a paper lands cleanly instead
   of colliding on `UNIQUE (test_id, order_index)`.
4. Series or papers the new pack no longer carries stay in place (rows are
   updated in place, never deleted, like the assessment import). Retire them
   explicitly after checking nothing uses them:
   `UPDATE test_series SET status='retired' WHERE series_id='…'` /
   `UPDATE test SET status='retired' WHERE test_id='…'`.

## 4. Failure modes and what they mean

| Symptom | Cause | Action |
|---|---|---|
| `refused: … SHA-256 does not match the manifest` | a data file was edited after E4 wrote it | re-export, or restore the file from git; never hand-edit a pack |
| `refused: … content_hash does not match` | same, at the aggregate level | as above |
| `refused: … pack gate verdict is 'fail', not 'pass'` | E1–E4 refused the pack | fix the upstream stage; a failed pack must not be importable |
| `refused: … pack publish status is 'blocked' (N blocker(s): …)` | the volume/coverage gate blocked publish; the pack under `runs/exam/…` is evidence, not importable | grow the banks or fix assembly; the blocker rules name the gap |
| `refused: … verbatim/exact-PYQ … DEC-COMP-001` | the pack carries verbatim rows or an enabled exact-PYQ series without a clearance record | exact-PYQ stays dark until `docs/compliance/decision-log.md#clearance-register` has the row; do not fake clearance |
| `refused: … referenced question_bank row(s) missing` | the P2 assessment import has not run on this database (or the pack references a bank this DB never received) | run `scripts/import_assessment_packs.py` first, then retry |
| `refused: … has type 'short'; the question bank cannot hold it yet` | the pack row is a subjective type the 0004 bank CHECK does not store (exam.md §11 debt 3) | widen `question_bank.type` in a schema change first; the importer refuses rather than truncating |
| `refused: … language policy promises rows that items.json omits` | an enabled series offers a language its items have no rows for — a paper would be unserveable in that language | fix the pack (assembly bug); the importer refuses a half-language paper |
| `refused: no pack directories` | wrong `--packs-dir` | pass the folder that contains `<class>/manifest.json` (`runs/exam-exports`, not the pack dir itself) |
| `RuntimeError: Database at unknown revision` | the DB is older/newer than this code | run `python -m db.migrate upgrade head` (or the cluster migrate Job) and retry |

**Atomicity.** Each pack imports in one transaction after all prerequisites
are checked: a failure mid-pack writes nothing for that pack. With several
packs, all are verified before the first write; an earlier pack stays imported
and re-running is safe because the import is idempotent — re-run the same
command rather than deleting rows.

**Rollback.** There is no `--revert`. To remove a pack's content, delete its
rows explicitly and deliberately (tests first, FK order last):

```sql
DELETE FROM test_question  WHERE test_id IN (SELECT test_id FROM test WHERE series_id LIKE 'class-10-%');
DELETE FROM test           WHERE series_id LIKE 'class-10-%';
DELETE FROM test_series    WHERE series_id LIKE 'class-10-%';
DELETE FROM assessment_pack WHERE kind = 'exam' AND chapter_id = 'class-10';
-- question_bank rows are the ASSESSMENT importer's: retire, do not delete
-- (test_question is ON DELETE RESTRICT — a RESTRICT failure means a paper
-- still uses the question).
```

## 5. What this runbook does not cover

- **The assessment bank.** `question_bank`/`speaking_prompt`/`topic_time_prior`
  and the `kind='assessment'` provenance rows belong to
  `scripts/import_assessment_packs.py` (`assessment-import.md`). This importer
  only reads the bank.
- **Live import.** There is no database for the prototype yet (deployment
  blocked at cutover, no docker locally). The live import against real
  Postgres **is the cutover step**: port-forward or in-cluster Job shell, §2.3
  with the Secret-held DSN, §2.4 verification, §2.5 spot-check. Everything
  before cutover is `--dry-run` plus the committed fixture evidence.
- **Publish orchestration.** Nothing calls this script automatically after an
  E4 export; wiring that into the publish path is later work.
- **Blueprints and paper metadata.** `blueprint.json`/`papers.json` are
  verified (hash, class identity) but not imported: no DB table ships for
  them in `0004` (db-spec §10 Q13); the admin views (F10) read the pack.
