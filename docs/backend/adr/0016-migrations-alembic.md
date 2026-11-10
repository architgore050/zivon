# ADR-0016: Migrations = Alembic + SQLAlchemy 2 async + asyncpg; CI runs every migration against a fresh DB and a cold-restore
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session (ref 03 §7: "verify before assuming" — repo has no ORM yet; this ADR picks the stack)
- Driving NFRs / requirements: NFR-27 (rollback ≤ 10 min), maintainability, repo Python conventions (AGENTS.md)

## Context
db-spec defines 20 P0 tables plus target revisions (partitioning, hash-chaining). Migration tool
must pair with the access layer and the restore drill story.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Alembic + SQLAlchemy async + asyncpg** (adopted) | Python-native, pairs with FastAPI; reversible revisions; autogenerate assists review; schema version queryable for `/v1/health` | two libs to learn for new contributors | low | — |
| Raw SQL scripts + version table | zero deps | manual ordering errors, no down-path discipline | low | NFR-27 rollback story |
| Django ORM | mature | importing Django into a FastAPI repo — framework split for one table set | medium | simplicity rule |

## Decision
Alembic. Pattern: expand → backfill → contract (no destructive change in the same release as the
code that stops using it); every revision reversible or documented forward-fix; CI job runs
migrations against (a) fresh Postgres and (b) a restore of the latest cold base backup — the
restore test and the migration test are one job.

## Consequences
Easier: `/v1/health` exposes schema_version; rollback = `alembic downgrade -1` + image tag
rotation (gotcha 9). Harder: CI needs a throwaway DB + a downloaded base backup (small pipeline
addition to `ci.yml`). Monitor: migration duration in CI (> 60 s = index-building smell).

Implementation note (2026-11-10, EX6 weld): the chain runs with the driver the monolith image
actually ships — `psycopg` 3 — so `alembic/env.py` normalizes `postgresql://` and
`postgresql+asyncpg://` DSNs to `postgresql+psycopg://` (SQLAlchemy's default for a bare
`postgresql://` URL is psycopg2, which is not installed; that mismatch used to be swallowed into
a fallback that bypassed the revision files). The schema itself is hand-authored DDL
(`db/schema.py`, no ORM models), so `alembic check`/autogenerate is not applicable; the drift
gate is the idempotent second `upgrade head` plus the schema round-trip test.

## Revisit trigger (measurable)
None anticipated pre-growth; if partition DDL (target revisions) outgrows Alembic ergonomics,
pair it with pg_partman — additive, not a replacement.

## References
db-spec §7; skill ref 03 §7; AGENTS.md coding standards; `.github/workflows/ci.yml` (existing gate).
