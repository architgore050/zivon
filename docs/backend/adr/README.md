# ADR index — Stage-2 systems decisions (2026-11-07)

16 records. The 8 `**ADR**` flags carried from `docs/product/features.md` §3 map 1:1 below;
the rest are systems-originated decisions (each states its reason in the record).

| ADR | Decision | Traces to |
|---|---|---|
| [0001](0001-primary-db-postgres.md) | Primary DB = PostgreSQL 16 | systems-originated (durability/atomicity requirements) |
| [0002](0002-session-store-memory-postgres.md) | Session store = memory + Postgres, no Redis in P0 | systems-originated (repo MVP rule) |
| [0003](0003-realtime-transport-raw-ws.md) | Raw FastAPI WSS; LiveKit deferred with trigger | systems-originated (AGENTS.md LiveKit option) |
| [0004](0004-cold-provider-b2-primary-r2-secondary.md) | Cold = B2 primary + R2 second copy; split credentials; India-residency open | founder requirement (separate provider) + storage-tiering §5 |
| [0005](0005-modular-monolith-layer-isolation.md) | Modular monolith + Core independence | AGENTS.md module seams + layer-independence rule |
| [0006](0006-sync-outbox-wal-cronjobs.md) | Outbox + WAL archiver + CronJobs; no broker | systems-originated (ref 02 §3) |
| [0007](0007-identity-device-pseudonymity.md) | Anonymous device pseudonymity + guardian seam | **T6** |
| [0008](0008-raw-audio-never-stored.md) | Raw child audio never persisted | **T11** |
| [0009](0009-language-locale-model.md) | 11-locale enum + hinglish mappings + bundle data model | **T2** |
| [0010](0010-ptt-contract-and-echo-path.md) | PTT + server endpointing; client-side ducking | **T3** (+ A-11 echo choice) |
| [0011](0011-no-child-profiling-by-construction.md) | No child profiling — schema preclusion | **T5** |
| [0012](0012-tutor-to-page-messaging.md) | Tutor→page: anchor data P0, `ui.hint` P1 (doctrine-guarded) | **T7** |
| [0013](0013-build-time-translation-pipeline.md) | Build-time reviewed translation (SC-01) | **T8** |
| [0014](0014-context-snapshot-payload.md) | ≤ 4 KB structured context snapshot + provenance | **T12** |
| [0015](0015-credit-guard-architecture.md) | Atomic two-dimension guard + profile toggle | founder config 2026-11-07 (NEED-009) |
| [0016](0016-migrations-alembic.md) | Alembic + SQLAlchemy async; CI migrate-against-restore | systems-originated (ref 03 §7) |

Not yet needed (triggers defined inside the records above): Redis (0002), LiveKit (0003),
message broker (0006), India-residency provider swap (0004), audio-capture exception (0008),
personalization tables (0011), `ui.hint` full spec (0012).
