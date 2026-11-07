# ADR-0001: Primary database is PostgreSQL 16 (not SQLite, not a document store)
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session (engine choice is systems-originated; durability posture inherited from method rules)
- Driving NFRs / requirements: NFR-16/17/18 (durability, RPO), consent + credit atomicity (NEED-009/012), content versioning integrity, cold-sync story (WAL archiving)

## Context
The repo has no database today. The voice backend needs transactions: the credit guard decrements
two counters atomically per turn; the consent ledger is append-only legal evidence; content
versioning needs relational integrity (page → version → live pointer → narration assets); block
specs and bundles are JSONB payloads already schema-validated by `factory/schemas.py`.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| SQLite (simplest) | zero infra, trivial dev | single-writer concurrency limits; WAL-to-cold archiving story is weak (no streaming archive); no PITR story | lowest | NFR-17 (RPO via WAL archive), NFR-13 (concurrent writers) |
| **PostgreSQL 16 single node** | transactions, JSONB + relational mix, mature `archive_command`/PITR backup story (the backbone of storage-tiering §3 SYNC-02), Deployment+Service pattern already documented in `docs/deployment/` | one more image + PVC to run | one manifest set + one PVC + Alembic — small | — |
| Document store (Mongo etc.) | schema flexibility | weaker cross-entity integrity (consent↔device↔session FKs), backup/WAL story less standard, new operational surface | medium | integrity requirements of db-spec §4 |
| Key-value (Redis) as primary | fast | no durability semantics for ledgers; wrong tool | — | NFR-16 |

## Decision
**PostgreSQL 16**, single node, in-cluster Deployment + Service + PVC `zivon-db` (U2). JSONB for
specs/bundles/props; relational for everything with integrity needs.

## Consequences
Easier: PITR restore drills, WAL cold archiving, FK-cascaded deletion pipeline, CI migration tests.
Harder: one more stateful workload to operate; PVC lifecycle discipline (gotchas in
`docs/deployment/` apply). Monitor: connection pool saturation, WAL archive lag.

## Revisit trigger (measurable)
Single-node until: sustained > 1 M rows/day on any append-only table, or p95 AP-02/03 > 5 ms, or
read load forces replicas — then evaluate read replicas first (db-spec §7 target list).

## References
Skill ref 03 §2 (engine argument); `docs/deployment/kubernetes.md` (Deployment+Service pattern);
Postgres 16 docs (pg_basebackup / archive_timeout) — official, checked conceptually 2026-11-07.
