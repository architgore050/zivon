---
artifact: adr
version: "1.0"
created: 2026-11-09
status: Accepted
---

# ADR-0018: Hot log store is a day-partitioned Postgres table; PVC JSONL fallback + daily cold sync

## Status

Accepted

**Date:** 2026-11-09
**Deciders:** SP3-OBS spec agent (founder directive, Wave S1); schema co-owned with the backend-db-storage agent (core-backend §6)

## Context

ADR-0017 settles the event format (versioned JSON lines via `logging_manager`). This ADR decides **where those lines live**: the brief's hot-store options were a Postgres table or a file on a PVC, tiered hot-SSD vs cold per `docs/backend/storage-tiering.md` conventions, with retention per data class and sync triggers consistent with `docs/backend/sync-policy.csv`.

Forces:

- **The dashboard is SQL-shaped.** Dashboard v0 (`docs/specs/observability/dashboard-spec.md`) needs: p95 voice latency per day, error feed by class, factory-run status rollups, credit-counter latest values, publish status. These are aggregation queries — natural in Postgres, painful over JSONL files.
- **Writers are heterogeneous.** The factory Job, llm-manager node, voice backend, and dashboard all emit. A single Postgres table gives one queryable sink; stdout/PVC files fragment per pod.
- **Not every writer can always reach Postgres.** The factory Job runs before/without the backend DB in early cluster states; the voice backend must degrade honestly if the DB blips (Zivon failure-mode rule: no silent loss, loud degradation).
- **Volume is trivial.** ≤ 15.8k events/day, ~450 B/line → ≤ ~50 MB/day, ~0.35 GB per 7-day hot window, ~0.6 GB per 90-day cold window at demo-day peak (computed in the ADR-0017 context). Any storage decision here is not capacity-driven; it is query-and-lifecycle-driven.
- **Tiering conventions** (`storage-tiering.md` + `sync-policy.csv` + `data-classification.csv` — the Wave-0 backend docs this spec builds on) put hot queryable data on the backend's SSD-backed Postgres and cold, rarely-queried history on the cold provider (ADR-0004) synced by ADR-0006's batch mechanism. Log events are class-cold-after-7-days data: queried hot for the dashboard's recent windows, retained cold for the challenge's forensics window.
- **A-02 boundary:** transcripts live in their own DB rows with 7-day TTL and are NEVER in log rows; guardian-initiated deletion (DPDP, ADR-0007/0011 pseudonymous identity) must reach log rows too — a queryable store makes deletion executable, an append-only file makes it a rewrite.

**[ASSUMPTION]** ADR-0004's cold provider is an S3-compatible object store reached via the ADR-0006 batch sync mechanism; this ADR defines the interface (NDJSON export files, daily trigger) and defers provider specifics to those ADRs. **[ASSUMPTION]** sync triggers (daily batch + size threshold) align with `sync-policy.csv`; reconcile on merge.

## Decision

1. **Hot store: table `log_events` in the backend's Postgres** (SSD-backed, same instance as the A-02 transcript rows), **day-partitioned** (`PARTITION BY RANGE (ts)`), written ONLY by `logging_manager` (no module hand-writes SQL to it — same discipline as model calls through `llm_manager`).

   Contract (owned by `logging_manager`, migration co-reviewed by the backend-db-storage agent):

   ```sql
   CREATE TABLE log_events (
     id              BIGSERIAL,
     ts              TIMESTAMPTZ NOT NULL,          -- event time, UTC
     schema_version  INT NOT NULL,                  -- JSON line schema version
     severity        TEXT NOT NULL,                 -- DEBUG|INFO|WARNING|ERROR|CRITICAL
     event           TEXT NOT NULL,                 -- dot.namespaced, e.g. voice.turn.e2e_latency
     component       TEXT NOT NULL,                 -- factory|llm_node|voice|translator|frontend|dashboard|credit
     env             TEXT NOT NULL,                 -- dev|cluster|prod
     run_id          TEXT,                          -- factory correlation
     session_id      TEXT,                          -- voice correlation (pseudonymous, ADR-0011)
     turn_id         TEXT,
     request_id      TEXT,
     stage           TEXT,                          -- factory stage id, e.g. 03-check
     latency_ms      BIGINT,                        -- where the event measures a duration
     error_class     TEXT,                          -- taxonomy enum, spec.md §7
     fields          JSONB NOT NULL DEFAULT '{}'::jsonb,  -- redacted payload (ADR-0017)
     trace_id        TEXT,                          -- reserved for ADR-0017 OTel path
     span_id         TEXT,
     PRIMARY KEY (id, ts)
   ) PARTITION BY RANGE (ts);
   -- Indexes per partition:
   --   (event, ts DESC), (run_id), (session_id, ts), (request_id),
   --   (component, severity, ts DESC) WHERE severity IN ('ERROR','CRITICAL')
   ```

   Retention by class (TTL enforced by the daily sweeper Job dropping whole partitions — cheap and exact):

   | Log class (data-classification) | Examples | Hot (SSD, Postgres) | Cold (ADR-0004) | Then |
   |---|---|---|---|---|
   | L1 system/diagnostic | factory stage/call events, node events, heartbeat | 7 days | 90 days | delete |
   | L2 usage/telemetry | frontend `EVT-Fxx`, voice session/turn timings | 7 days | 90 days | delete |
   | L3 security/audit | admin logins, button triggers, auth failures, redaction violations | 30 days | 365 days | delete |
   | credit counters | `credit.*` (ADR-0015) | 7 days | 365 days (trend evidence) | delete |

2. **Fallback sink: JSONL on the `zivon-sources` PVC** (`runs/logs/YYYYMMDD-<component>.jsonl`), byte-identical schema. `logging_manager` writes Postgres when `ZIVON_LOG_DSN` is set, else the JSONL path, and **loudly emits `log.store_fallback` (WARNING)** on switch — no silent degradation. Deletion in fallback mode: rewrite the file (guardian deletion wins over append-only purity).

3. **Sync to cold: daily `log-sync` Job** — exports the previous UTC day's partitions (and ingests any PVC JSONL written in fallback mode) to the cold provider per ADR-0006's batch mechanism, then verifies (row-count + byte checksum) before the sweeper may drop a hot partition. Sync triggers: daily 03:30 IST batch + a 200 MB per-file size cap; a failed sync **blocks** hot deletion for that day (retain-until-synced rule).

4. **Deletion paths:** (a) TTL sweeper above; (b) **guardian deletion** — `logging_manager.delete_subject(session_id)` cascades over `log_events` (and fallback JSONL + cold export manifests) for that subject's pseudonymous session IDs within 24 h of the guardian request, logging one L3 `privacy.subject_deleted` audit event (IDs only, nothing personal); transcripts are the backend's rows (A-02, 7-day TTL) and raw audio is never referenced in logs, so no other path exists by construction.

5. **k8s shape:** the sweeper+sync is one CronJob (`ZIVON_LOG_SYNC_SCHEDULE`, `k8s/infra.env` line-edit) — manifest number assigned by the infra agent in the next free prefix; no image change (runs in the factory image, which already carries `psycopg` for the DB path — **[ASSUMPTION]** driver choice follows the backend agent's; pinned in `logging_manager/requirements.txt` when the module lands).

## Consequences

### Positive

- Dashboard v0 is plain SQL over one table; percentile queries are window functions, not file scans.
- Retention/TTL is partition dropping — exact, fast, and compatible with the A-02 spirit (logs expire on schedule; transcripts expire by their own TTL).
- Guardian deletion is a bounded `DELETE ... WHERE session_id = ...` + cold-manifest sweep, auditable as an L3 event.
- Writers stay dependency-light: one module, one env var, honest fallback.

### Negative

- Postgres becomes a logging dependency: a DB outage degrades the voice backend's log path to PVC JSONL (loud, by design) until the daily sync reconciles.
- The daily sync Job is a new moving part (retry on failure, verify-then-drop ordering must be correct).

### Neutral

- Volume numbers make tuning unnecessary this window; partition granularity (daily) is already the finest the sweeper needs.
- Loki (P2, `docs/deployment/README.md`) remains the infra-log plane; `log_events` is the product-event plane. Do not merge them this window.

### Model Choice

| Consequence | This decision |
|-------------|---------------|
| **Build, buy, or prompt** | Build (one table + one Job) on the already-decided backend Postgres; buy (log SaaS) ruled out (cost, egress, DPDP); Loki/OTel-file stacks deferred per ADR-0017 |
| **What is now coupled to it** | `logging_manager`'s writer, the dashboard's queries, the sweeper/sync Job, and the table DDL above |
| **Operating cost accepted** | ≤ ~0.35 GB hot / ~0.6 GB cold per 90-day window at demo-day peak; one CronJob |
| **Reversal cost** | Moderate: the JSON line schema is the stable interface; the store behind it can be swapped by changing one writer + one reader |
| **What would reopen this** | Backend DB sizing turns out to prohibit logging tenancy, or sync-policy.csv forbids log data on the cold provider |

## Alternatives Considered

### JSONL files on a PVC as the primary store

Rejected as primary (kept as fallback): the dashboard's aggregation queries become full-file scans; concurrent writers need append coordination; guardian deletion becomes file rewrite. PVC JSONL remains valuable as the always-works degradation path and the sync source.

### Only stdout (k8s logs), no store

Rejected: query-lifecycle (TTL, deletion, cold tier) is unimplementable on pod stdout; log rotation would silently destroy the dashboard's data source.

### Separate Postgres instance just for logs

Rejected: volume (≤ 50 MB/day) does not justify a second instance; tenancy on the backend's instance with its own partitions and roles is enough. Reopen if the backend agent's isolation NFRs say otherwise (OQ-7 in `docs/specs/observability/open-questions.md`).

## References

- ADR-0017 (stdlib JSON logging decision), ADR-0019 (admin auth)
- ADR-0004 (cold provider), ADR-0006 (sync mechanism) — interface only
- ADR-0007 / ADR-0011 (identity, pseudonymous IDs) — guardian deletion path
- ADR-0015 (credit counters) — retention row above
- `docs/backend/storage-tiering.md`, `docs/backend/sync-policy.csv`, `docs/backend/data-classification.csv` — tier/retention conventions
- backend-spec A-02 (transcripts = DB rows, 7-day TTL, never in logs)
- `docs/specs/observability/spec.md` §6 (lifecycle detail), `logging-api.md` (writer contract)
- `TIMELINE.md` Day-8
