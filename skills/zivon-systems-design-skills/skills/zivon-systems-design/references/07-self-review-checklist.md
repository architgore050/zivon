# Self-review checklist - systems design

Mark ✅ / ❌(owner, reason). No silent ❌.

## Traceability and scope
- [ ] Every endpoint cites NEED ids and consuming element ids; every NEED is served or explicitly deferred.
- [ ] Every table/column cites INF/ENT? ids or is tagged "systems-originated" with a reason.
- [ ] Every data class has: SoR, tier, retention, sync trigger, verification, deletion path, sensitivity.
- [ ] P0/P1/P2/post-challenge labelled; P0 matches the repo ladder; "out of scope" collisions are called out.

## Numbers
- [ ] NFR table has numeric targets tagged `[ASSUMPTION]`/`[MEASURED]`.
- [ ] Capacity model reconciles with NFRs; binding constraint identified.
- [ ] Voice latency budget sums to the < ~4 s gate with named levers.

## Tiering and durability
- [ ] SSD vs cold placement stated for every class; sync trigger and mechanism stated for every class that needs cold copies.
- [ ] Eviction invariant present; eviction never touches un-verified data.
- [ ] Cold provider is a separate failure domain with separate, least-privilege credentials; archival writers cannot delete.
- [ ] Restore path, RPO/RTO and drill cadence defined; "pull the plug" test answered per class.
- [ ] Provider choice is an ADR with a criteria matrix filled from official sources (not blogs).

## Privacy and safety
- [ ] No raw child audio by default; any exception has consent, TTL and encryption.
- [ ] Consent is enforced server-side; deletion pipeline covers DB, SSD, cold, caches, logs, backups.
- [ ] Personalization/memory storage exists only if the product decision (T5/T6) permits; otherwise absent.
- [ ] Sub-processors and regions listed; legal questions listed as open.

## Resilience and ops
- [ ] Failure-mode table covers each component incl. what the student sees.
- [ ] Layer independence: Core content path survives voice/TTS/translation/personalization outages.
- [ ] SLOs, alerts and runbooks listed; metrics for outbox lag, WAL lag, SSD usage, drift, last restore drill.
- [ ] Security checklist run; secrets handling matches repo rules.

## Decisions
- [ ] ADR per significant choice (engine, cold provider, outbox vs broker, realtime transport, auth model, region).
- [ ] Open questions and unverifiable facts listed; none smoothed over.
- [ ] No contradiction with `docs/deployment/` or `AGENTS.md`, or a doc-change proposal is attached.
