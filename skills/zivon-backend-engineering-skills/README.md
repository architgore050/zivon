---
name: zivon-backend-engineering-skills
description: Perishable operational backend skills not covered by the vendored systems-design bundle. For EX0-BACKEND (core monolith), EX2-TRANS, EX3-OBS, EX7-GAPS. Covers Alembic discipline, Postgres durability ops (PITR), transactional quota guards, rate limiting, k8s Job/CronJob semantics, and probe patterns.
consumed-by: EX0-BACKEND, EX2-TRANS, EX3-OBS, EX7-GAPS
sources:
  - https://www.postgresql.org/docs/current/continuous-archiving.html
  - https://www.postgresql.org/docs/current/app-pgbasebackup.html
  - https://wal-g.readthedocs.io/ (pg_wal-g-style archiving)
  - https://alembic.sqlalchemy.org/en/latest/
  - https://kubernetes.io/docs/concepts/workloads/controllers/job/
  - https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/
  - https://stripe.com/blog/rate-limiters (practitioner rate limiting)
  - https://blog.cloudflare.com/counting-things-a-lot-of-different-things/
cross-refs:
  - skills/zivon-systems-design-skills (vendored fastapi-expert, postgres-pro — do not duplicate)
---

# Zivon Backend Engineering Skills

The perishable operational parts of backend building that the vendored skills
in `zivon-systems-design-skills` do NOT cover. Cross-reference
`fastapi-expert` / `postgres-pro` from the systems bundle instead of
duplicating them.

## 1. Alembic migration discipline [V]

- Linear history: one head per branch; `alembic heads` must return exactly one
  revision in CI. Merge revisions are banned on the mainline.
- Expand/contract only: additive migrations ship first (new column/table,
  backfill, THEN code switch, THEN drop old) — never a rename-in-place on a
  live table. [V: Alembic docs — autogenerate & batch mode]
- Zero-data-loss rules: every destructive change (drop, type change, NOT NULL
  on existing rows) requires an explicit data-migration plan + reversible
  downgrade; `server_default` before removing client defaults.
- Never use `alembic revision --autogenerate` output unreviewed; autogenerate
  misses renames and will suggest table drops for unmapped models.

## 2. Postgres durability ops [V]

- Base backups: scheduled `pg_basebackup` (or WAL-G `backup-push`) to object
  storage; verify with `pg_verifybackup` (Postgres ≥13). [V: PG docs app-pgbasebackup]
- WAL archiving: `archive_mode=on`, `archive_command` pushing to object storage
  (WAL-G style: `wal-g wal-push`); monitor `pg_stat_archiver` for
  `failed_count` — silent archiving failure = no PITR. This is the mechanism
  backend-spec ADR-0006 assumes. [V: PG docs continuous-archiving] [C: ADR-0006]
- Restore drills: quarterly `wal-g backup-fetch` + PITR to a scratch instance,
  time it, record RPO/RTO. An untested backup is not a backup.
- PITR basics: restore base backup → replay WAL to target time/LSN
  (`recovery_target_time`) → promote. Know the difference between RPO (how much
  WAL you can afford to lose) and RTO (how long replay takes).

## 3. Transactional quota / budget guards [V/C]

- The credit guard (ADR-0015) uses concurrency-safe decrement inside the
  request transaction: `UPDATE quotas SET credits = credits - :cost WHERE id =
  :id AND credits >= :cost RETURNING credits` — the `WHERE credits >= :cost`
  predicate IS the guard; check the rowcount, abort on 0. [C: ADR-0015]
- Reserve-then-commit for long operations: hold a reservation row, commit the
  spend only on success; release reservation in a finally/cleanup path.
- Idempotency keys: unique key per operation, unique index on
  `(key, operation)`, replay returns the original result instead of
  double-spending.
- Never check-then-act in application code (TOCTOU); the constraint must live
  in one atomic statement.

## 4. Rate limiting & abuse middleware [S]

- Token bucket for steady-state limits (user, IP, API key); sliding window only
  when strict burst ceilings matter (it's costlier).
- Layer limits: edge (cheap, coarse) → app (per-user budgets) → resource
  (expensive endpoint guards). Return `429` + `Retry-After`.
- IP privacy: store salted hashes of IPs with rotating salt (e.g. daily); never
  log raw IPs alongside user identity in the same record; honor GDPR-style
  erasure by dropping the salt epoch. [S: Cloudflare counting-things]
- Distinguish 401/403/429 semantics; abuse signals (not just rate) belong in a
  separate signal pipeline. [S: Stripe rate-limiters]

## 5. k8s Job / CronJob ops semantics [V]

- Jobs: `backoffLimit` (retries before marking Failed), `activeDeadlineSeconds`
  (hard wall clock), `ttlSecondsAfterFinished` (garbage-collect finished pods),
  `restartPolicy: Never` + pod failure handled by the Job controller, not the
  kubelet. [V: k8s Job docs]
- CronJobs: `concurrencyPolicy: Forbid|Replace|Allow` (default Allow — usually
  wrong for idempotency-sensitive jobs); `successfulJobsHistoryLimit` /
  `failedJobsHistoryLimit` (default 3/1 — raise for audit); `startingDeadlineSeconds`
  to catch missed starts; timezone is `spec.timeZone` (k8s ≥1.25).
- Jobs must be idempotent: a retried Job re-runs the whole unit; design for
  at-least-once execution.

## 6. Health / readiness probe patterns [V]

- `/healthz`: liveness — cheap, no external deps (fail → restart).
- `/readyz`: readiness — checks DB pool, queue, critical downstreams
  (fail → pull from service endpoints).
- `/startupz` (startup probe) for slow monoliths: shields liveness during boot.
- Keep liveness dumb: a deep liveness check that fails on downstream outage
  causes restart storms.

## Evidence tags

- [V] verified against primary docs (PostgreSQL, Alembic, Kubernetes)
- [S] synthesized from practitioner engineering writing (Stripe, Cloudflare)
- [C] constrained by internal backend-spec (ADR-0006, ADR-0015)

## Licence / vendoring

References are linked, not vendored. No third-party prose copied.
