# docs/backend/ — systems-design specs (Stage 2)

Buildable specifications derived from the Stage-1 product spec (`docs/product/`):
**what the system stores, serves, moves, and survives.** Written 2026-11-07 (Day 8→9,
Gate D frozen) by the Stage-2 systems-design session. These are specifications, not code —
the voice backend is greenfield and nothing here contradicts `docs/deployment/`.

Requirements source (consumed, not re-derived): `docs/product/features.md`,
`docs/product/backend-handoff.md` (18 NEEDs, 10 ENT?, voice channel contract, 18 EVTs,
volumes, retention), the three inventories, `traceability-matrix.csv`, plus the founder
corrections of 2026-11-07 recorded in that stage's commits (per-user credit cap 30/day;
credits meter only the voice agent; narration pre-generated at build time; three distinct
storage units; IP-based abuse prevention).

| File | What it is |
|---|---|
| [`backend-spec.md`](backend-spec.md) | Services & processes, NFR table, API endpoint catalogue, WebSocket/voice-loop contract (incl. per-hop latency budget), error model, auth/consent/rate limits, credit metering & guard, failure-mode table, observability & SLOs, deployment topology, P0 slice vs target architecture |
| [`db-spec.md`](db-spec.md) | PostgreSQL schema: entities, keys, constraints, indexes (each justified by a named access pattern), i18n + content-versioning pattern, retention jobs, migration strategy; every column traces to INF-/ENT? IDs |
| [`storage-tiering.md`](storage-tiering.md) | The three storage units (backend cache / hot DB / cold provider), data-class placement, sync triggers & schedules, checksum verification, two-phase eviction, restore, deletion pipeline, cold-provider selection, per-class "pull the plug" answers |
| [`data-classification.csv`](data-classification.csv) | One row per data class (machine-readable twin of storage-tiering §2) |
| [`sync-policy.csv`](sync-policy.csv) | One row per sync rule: trigger, mechanism, verification, on-failure, SLO, runbook |
| [`capacity-and-cost.md`](capacity-and-cost.md) | Storage / egress / Gnani-credit capacity model reconciled against the 10,000-credit budget, the 1,000-credit daily tranche, the 30-credit per-user cap, and the demo profile |
| [`adr/`](adr/) | Architecture Decision Records — one per significant decision; maps 1:1 to the 8 `**ADR**` flags in `features.md` §3 (T2, T3, T5, T6, T7, T8, T11, T12) plus systems-origin decisions (primary DB, session store, realtime transport, cold provider, layer isolation, sync schedule, guard architecture, migrations) |

Method: `skills/zivon-systems-design-skills/skills/zivon-systems-design/` 10-phase pipeline
(0 Orient → 9 ADRs+review). Traceability rule throughout: every endpoint, table, column,
WS message, and event cites a `NEED-`/`INF-`/`ENT?-`/`EVT-` ID from Stage 1, or is labelled
*systems-originated* with a reason. Numbers are tagged `[ASSUMPTION]` until measured.

Related repo docs: `docs/deployment/` (infra stack, locked decisions — respected, not
reshaped), `docs/content-factory/architecture.md` (run evidence + publish flow),
`TIMELINE.md` (gates, scope ladder, infra TODO), `docs/product/backend-handoff.md` (input).
