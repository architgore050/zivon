---
name: zivon-systems-design
description: Method for turning a product feature/element inventory into a backend specification, a database specification, and a storage-tiering plan (what lives on the backend's local SSD, what lives in a separate cold-storage provider, and exactly when and how data is synced, verified, evicted and restored). Covers NFRs with numbers, data classification, entity modeling, API and realtime (WebSocket voice) contracts, privacy-by-design for children's data, failure modes, observability, capacity/cost and ADRs. Use whenever you must write or review a backend spec, DB/schema spec, storage or backup design, API contract, or system architecture for Zivon (FastAPI + WebSockets + Gnani Prisma/Evon/Timbre + Kubernetes) or a similar voice-first learning product. Trigger on "backend spec", "db spec", "schema", "cold storage", "SSD", "sync", "tiering", "what goes where", "API for the frontend", even if only one of these is mentioned. Consumes the output of the zivon-product-design skill.
---

# Zivon Systems Design

Turns **what the UI needs** into **what the system stores, serves, moves, and survives**.
It is deliberately a method with guard-rails, not a stack mandate: choose components only
when a numbered requirement demands them, record each choice as an ADR, and phase the build
so the P0 demo is never at risk.

## Inputs you need (stop and ask for them if absent)

From the product-design deliverable: feature cards, UI element inventory, information
inventory, backend handoff list (capability needs `NEED-…`, entity needs `ENT?-…`, realtime
needs, event catalogue `EVT-…`, volume hints, retention/consent hints), content-factory
change proposals. From the repo: `AGENTS.md`, `TIMELINE.md`, `docs/deployment/`,
`docs/content-factory/architecture.md` + `blocks-schema.md`, `docs/DECISIONS-and-RESEARCH/`.

## The pipeline (each phase has an exit test)

| # | Phase | Output | Exit test |
|---|---|---|---|
| 0 | **Orient & ingest** - read repo + handoff; list what already exists (FastAPI plan, K8s manifests, PVCs, content-factory outputs) | Constraints and "exists vs. to-build" table | You can draw today's data flow from memory |
| 1 | **Validate the handoff** - every NEED has a caller; every INF has a source; sizes present | Gap list returned to the product owner or recorded as assumptions | No unowned requirement |
| 2 | **NFRs with numbers** (`references/01-method-and-nfrs.md`) | NFR table: latency, availability, durability, RPO/RTO, capacity, cost, privacy | Each NFR is measurable and tagged `[ASSUMPTION]`/`[MEASURED]` |
| 3 | **Data inventory & classification** (`references/02-data-classification-and-tiering.md`) | One row per data class: owner system, size, mutability, sensitivity, access pattern, retention, tier, sync trigger, deletion path | Every INF/ENT?/EVT lands in exactly one class |
| 4 | **Database spec** (`references/03-database-spec-method.md`) | Entities, relations, keys, constraints, indexes (from access patterns), i18n + versioning pattern, retention jobs, migration strategy | Every column traces to INF/ENT?; every query to a NEED |
| 5 | **API and realtime contract** (`references/04-backend-api-and-realtime.md`) | Endpoint cards, WebSocket message catalogue, error model, auth/consent rules, rate/credit limits | Every NEED is served; every endpoint has a consumer element |
| 6 | **Tiering and sync design** (`references/02-data-classification-and-tiering.md`) | SSD vs cold placement, sync triggers, verification, eviction, restore, provider separation | "Pull the plug" test passes for each class (see below) |
| 7 | **Failure, security, privacy, ops** (`references/05-privacy-security-ops.md`) | Failure-mode table, threat notes, deletion pipeline, SLOs, observability | Every component has a stated user-visible failure behaviour |
| 8 | **Capacity & cost** (`templates/capacity-model.md`) | Back-of-envelope with credits, storage, egress | Numbers reconcile with NFRs |
| 9 | **ADRs and review** (`references/07-self-review-checklist.md`) | One ADR per significant decision; checklist done | No silent defaults |

## Hard rules

1. **Derive, don't invent.** Every endpoint, table and column traces to a `NEED`/`INF`/`ENT?`/`EVT`. Untraceable additions are labelled "systems-originated" with a reason.
2. **Numbers over adjectives.** "Fast" and "durable" are not requirements. Tag each number `[ASSUMPTION]` until measured.
3. **Every data class has all of:** system of record, tier, retention, sync trigger, verification, deletion path, sensitivity.
4. **Nothing leaves the SSD until a verified cold copy exists** (when the SSD holds the only copy). Eviction is a two-phase, DB-recorded act.
5. **Cold storage is a different failure domain**: different provider, account, credentials and (ideally) region from compute and the primary database. The system that writes backups must not be able to delete them (write-only or object-lock credentials).
6. **Children's data is an architecture constraint**, not a later patch: minimization, consent linkage, pseudonymization, deletion paths, no raw audio by default.
7. **Layer independence in the backend**: the content-serving path (Core) must stay up when the voice stack, TTS service, translation runtime or personalization store is down.
8. **Phase it.** Define the target architecture and the smallest P0 slice (the repo says: avoid over-engineering databases and auth early; MVP session memory is in-memory). Each added component cites the NFR that justifies it.
9. **Failure first.** For each component write what the student sees when it fails and how it recovers.
10. **Respect repo conventions**: Python with type hints, small modules, config via env vars, secrets runtime-only, K8s Deployment+Service for long-running services, PR→CI→review flow. Do not contradict `docs/deployment/`; update it when you add infra.
11. **Verify perishable facts at decision time** (provider prices, limits, regions, legal dates). Blog numbers in `sources-and-evidence.md` are orientation only.

## Reference map

| Need | File |
|---|---|
| Method, NFR checklist with starter numbers, capacity method | `references/01-method-and-nfrs.md` |
| Data classes, SSD vs cold placement, sync/verify/evict/restore, provider criteria | `references/02-data-classification-and-tiering.md` |
| Entity modeling, Postgres defaults, i18n/versioning, events, retention, migrations | `references/03-database-spec-method.md` |
| REST + WebSocket contracts, voice-loop latency budget, credit metering, errors | `references/04-backend-api-and-realtime.md` |
| Privacy engineering, security, observability, SLOs, deletion pipeline | `references/05-privacy-security-ops.md` |
| Repo facts and constraints that bind the design | `references/06-zivon-systems-constraints.md` |
| Final quality gate | `references/07-self-review-checklist.md` |
| Citations and verification status | `references/sources-and-evidence.md` |
| Fill-in templates | `templates/` |

## Combine with vendored skills (`../../vendored/`)

`architecture-designer` (patterns, ADR), `develop-adr` (ADR mechanics), `api-designer`
(REST/OpenAPI conventions), `fastapi-expert` (implementation idioms), `websocket-engineer`
(realtime protocol patterns), `postgres-pro` + `database-optimizer` (schema, indexes, tuning),
`sre-engineer` (SLOs, runbooks), `secure-code-guardian` (security checklist),
`measure-instrumentation-spec` (event schemas). Use them for the mechanics; this skill decides
*what* to specify and enforces the rules above. Where they differ, the hard rules win.

## The "pull the plug" test (Phase 6 exit)

For each data class answer: if the SSD is destroyed *now*, what is lost, what is the RPO,
how is it restored, how long is the RTO, and who notices? If the cold provider disappears
*now*? If a bug deletes rows *now*? If a child's guardian requests deletion *now*?
