# ADR-0011: Personalization precludes child profiling by construction (T5) — coverage memory only, no behavioural columns
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing Stage-1 T5 + handoff §2 note ("precludes profiling fields")
- Driving NFRs / requirements: NFR-22/23, DPDP children's provisions (tracking/behavioural monitoring restriction — secondary source, counsel), product J5 (session memory without profiling)

## Context
The tutor needs *some* memory (coverage summary for anchoring, J5) but the product decision
forbids behavioural profiles of children. The systems guarantee must live in the schema, not in
policy prose.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Coverage-only memory: `session.coverage` JSONB (≤ 32 items, 24 h idle TTL, student-visible, clearable via EVT-018/NEED-013); `device` table has zero behavioural columns; no preference/inference tables exist** | the forbidden data has nowhere to be written; audit = schema inspection | tutor adaptation is session-scoped, not long-term (accepted product posture) | none | — |
| Preference table (pace/depth per device, server-side) | continuity across sessions | server-side behavioural attributes about a child = exactly the DPDP-restricted class; settings already live client-local (NEED-018) | low | privacy posture |
| Inferred-ability model (per-topic mastery) | best adaptive UX | profiling of minors; needs counsel + consent architecture + explanation/deletion machinery | high | privacy posture + Gate D scope |

## Decision
Option 1. The `preference` table pattern from skill ref 03 §3 is **explicitly not instantiated**
("table exists only if T5/T6 decisions permit" — they don't, for inferred items). Any future
personalization must arrive via a new ADR + counsel + the explanation/deletable rules.

## Consequences
Easier: the privacy claim "we do not profile children" is mechanically checkable. Harder: the
tutor re-derives context every session (that's what the ≤ 4 KB context snapshot + coverage summary
are for — ADR-0014). Monitor: none needed structurally; CI schema review blocks new columns
matching behavioural patterns.

## Revisit trigger (measurable)
Post-challenge product decision to personalize + counsel clearance → new ADR; the seam is
`language`/`mode` columns (settings, not behaviour) which may mirror server-side then.

## References
features.md T5 + J5; handoff §2 ENT?-DeviceProfile note; db-spec §4.1/§4.2; ref 05 §1 (minimize/pseudonymize).
