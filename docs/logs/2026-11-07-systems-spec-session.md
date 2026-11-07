# Session log — 2026-11-07 · Stage-2 systems design (backend + DB + storage specs)

Branch `feature/backend-db-storage-spec` (local, commits-only per founder choice — no push, no
PR). Consumed Stage 1 (`docs/product/`) without re-deriving it. Docs-only: no product code was
written. Method: `skills/zivon-systems-design-skills/` 10-phase pipeline, commit per phase.

## Done

- **Founder corrections recorded into Stage-1 docs** (`4c4f32f`): per-user credit cap 200 → **30/day**
  (free-trial scale); credits meter **only the voice agent**; course narration **pre-generated at
  build time, stored** (C-051 DEFER → ADOPTED, NEED-017 rewritten); everything but the voice agent
  login-free with **IP-keyed abuse prevention**; **three distinct storage units** (backend cache /
  hot DB / cold provider).
- **`docs/backend/` created** — folder README + five deliverables + ADR folder:
  - `backend-spec.md` (§1–16): scope + assumptions register A-01…A-15, storage-unit glossary
    U1–U4, P0-vs-target phase plan, topology + module seams (`voice/` package), NFR-01…30,
    API catalogue (9 student endpoints + 4 static contracts + 10 admin routes with script-parity),
    WS catalogue (7 C→S + 10 S→C), per-hop latency budget summing to Gate C (≤ 4.0 s p90 with
    named overlap levers), error model (problem-details + message keys), session token,
    server-side consent gating, IP-hash rate limits, two-dimension credit guard + profiles,
    failure-mode table (20 rows), security/privacy design (processors, STRIDE pass, breach
    readiness), observability + 7 SLOs + 12 runbooks RB-01…12, K8s deployment topology,
    consolidated open questions, NEED↔endpoint↔table↔class↔EVT roll-up.
  - `db-spec.md` + `db-traceability.csv`: Postgres 16, 20 tables, every column cites an
    INF/ENT?/EVT/NEED ID or is tagged systems-originated; 15 access patterns each naming its
    index; retention & deletion matrix; Alembic plan; seed data; 6 open questions.
  - `storage-tiering.md` + `data-classification.csv` + `sync-policy.csv`: 20 data classes C1–C20
    with all dimensions; 6 sync rules + scrub/drill/evict/redelete; provider criteria matrix
    filled from **official pages fetched 2026-11-07** (Backblaze B2 pricing; Cloudflare R2 pricing
    + data-location) with unverified cells flagged (Wasabi page unreachable; AWS/GCS region tables
    unparseable — no blog numbers used); decision: **B2 primary + R2 second copy**, three separate
    cold credentials (writer cannot delete), encrypt-then-upload for child-adjacent archives;
    restore paths (RPO ≤ 5 min / RTO ≤ 4 h), 8-step deletion pipeline, 11 retention jobs,
    pull-the-plug answers per failure.
  - `capacity-and-cost.md`: units × 3 load levels; storage/egress ≈ $0 through the challenge
    (B2+R2 free tiers); **binding constraint = Gnani credits** (10 000 total · 1 000/day tranche ·
    30/user/day · ~40 % demo reserve · ≤ 1 500 narration build budget).
  - `adr/` — **16 ADRs**: all 8 features.md ADR flags resolved 1:1 (T2→0009, T3→0010, T5→0011,
    T6→0007, T7→0012, T8→0013, T11→0008, T12→0014) + 8 systems-origin decisions (Postgres,
    session store, raw WSS vs LiveKit, cold provider, monolith topology, outbox/WAL/CronJobs,
    guard architecture, Alembic). Each carries options, consequences, measurable revisit triggers.
- **Quality gates passed:** zero-orphans mechanical check (NEED 18/18, EVT 18/18, INF 105/105,
  ENT? 10/10, WS 14/14, classes 20/20, sync rules 10/10) + pull-the-plug answers per data class.
- **Docs map updated same PR:** AGENTS.md (docs/backend/ bullet + skill-bundle note), README docs
  table row.

## Not done (deliberate)

- No product code (Stage 2 is specs; the voice backend build is Stage 3 / TIMELINE Phase 2 work).
- No push / PR / merge (founder chose commits-only for this branch).
- Cold-provider [verify] cells (Wasabi, AWS/GCS region prices, B2 Object Lock feature page) —
  re-verify only if ADR-0004's revisit trigger fires.

## Next

1. Founder read-through of `docs/backend/` — calibration items are flagged inline: demo-profile
   numbers (A-05), narration build budget (A-15), Q-L1 India-residency counsel question.
2. Stage-3 build starts from the P0 slice: `voice/` package + Postgres manifests + B2 bucket +
   Alembic initial revision (backend-spec §3 + §12, db-spec §7).
3. Before Gate-C rehearsal: Gnani dashboard credit-price calibration (A-01), 30-min v3.0 language
   smoke test (A-04), one timed restore drill (DRILL-01 P0 form).
4. Counsel questions packaged: Q-L1 (residency), Q-L2 (DPDP clocks), Q-V1 (Gnani-side retention).
