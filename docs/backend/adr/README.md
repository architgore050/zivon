# ADR index — Stage-2 systems decisions (2026-11-07)

28 records (0001–0028). The 8 `**ADR**` flags carried from `docs/product/features.md` §3 map 1:1 below (0001–0016); 0017–0028 were added by Wave S1 spec agents (SP1 voice 0017–0020, SP2 translation 0021–0023, SP3 observability 0024–0026, SP4 evals 0027–0028 — numbering reconciled by the WS1 merge agent after parallel-agent collisions on 0017+). [WS1/SP6 update 2026-11-09]
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
| [0017](0017-brain-serving-path-gemma-gemini-api.md) | Brain serving = Gemma 4 26B A4B via Gemini API (cloud) | SP1-VOICE (Gate A) |
| [0018](0018-thinking-out-loud-approach.md) | Thinking-out-loud = whitelisted summaries + filler fallback (flag off) | SP1-VOICE (T12) |
| [0019](0019-streaming-chunking-strategy.md) | Sentence/clause streaming chunker (250 ms flush) | SP1-VOICE (Gate C) |
| [0020](0020-voice-audio-transport-and-mount.md) | Voice mounts into monolith (no separate voice image) | SP1-VOICE (ADR-0003/0005) |
| [0021](0021-translation-stage-placement-and-resumability.md) | Translation stages 10a–10d between 10-reviewfix and 11-link | SP2-TRANS (ADR-0013) |
| [0022](0022-translation-memory-and-cache-architecture.md) | Two-tier Translation Memory (PVC + Postgres C3) | SP2-TRANS |
| [0023](0023-physics-terminology-and-script-rendering-policy.md) | Bilingual glossary + immutable numerals/SI + script offsets | SP2-TRANS (DCR-001) |
| [0024](0024-structured-logging-over-otel.md) | Stdlib JSON logging over OTel (OTel deferred) | SP3-OBS |
| [0025](0025-hot-log-store.md) | Hot log store = day-partitioned Postgres + PVC JSONL fallback | SP3-OBS (ADR-0004/0006) |
| [0026](0026-admin-auth.md) | Minimal admin auth (single-admin bearer Secret) | SP3-OBS |
| [0027](0027-eval-result-store-and-tiering.md) | Eval store dual-write (PVC JSONL + Postgres, C4) | SP4-EVALS |
| [0028](0028-eval-judge-model-and-calibration.md) | Judge model via llm_manager + calibration anchors | SP4-EVALS |


Not yet needed (triggers defined inside the records above): Redis (0002), LiveKit (0003),
message broker (0006), India-residency provider swap (0004), audio-capture exception (0008),
personalization tables (0011), `ui.hint` full spec (0012).
