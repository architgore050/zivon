# ADR-0012: Tutor→page messaging = structured anchor data in P0; UI-hint message types (highlight/scroll) deferred to P1 (T7)
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing Stage-1 T7 ("highlight/scroll only in P1")
- Driving NFRs / requirements: NEED-004/005, F-ADD-VOI-01 (dock states), voice-dock doctrine guard (founder authors design-doctrine §10.12)

## Context
The tutor's answer references page blocks (anchor chip "Asking about: <block>", provenance).
Whether the tutor can *command the page* (highlight a block, scroll to a sim) is a product-scope
and design-doctrine question, and the dock's design home is founder-authored (§10.12 guard).

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **P0: anchor resolution + provenance data inside existing messages (`stt.final`, `turn.meta`, anchor chip data); no new S→C control types. P1: add `ui.hint` (highlight/scroll only) once the dock doctrine §10.12 exists and the P1 ladder allows it** (adopted) | P0 message catalogue stays exactly the handoff §3 set; no UI-control surface before the doctrine defines it; respects the founder guard (no improvised dock behaviour) | P0 answers reference blocks verbally/textually only | none | — |
| Full `ui.hint` in P0 (highlight, scroll, sim nudge) | richer demo moments | un-decided dock behaviour (doctrine guard), prompt-injection surface (model → arbitrary UI commands), Gate D freeze violation | medium | Gate D + doctrine guard |
| Never (no UI hints ever) | simplest | forfeits a decided P1 product feature | — | product decision T7 |

## Decision
As adopted. `ui.hint` is catalogued as a **P1 message type** (backend-spec §7 lists only the P0
set); when built, its payload is an allow-listed `{action: highlight|scroll, block_id}` validated
against the page manifest — the model never emits free-form UI commands.

## Consequences
Easier: P0 WS contract is frozen and testable. Harder: two-stage message catalogue (P0/P1) must
be kept straight in frontend code. Monitor: none.

## Revisit trigger (measurable)
P1 build start + design-doctrine §10.12 published by founder → spec `ui.hint` fully (and only
then).

## References
features.md T7 + C-029; handoff §3; AGENTS.md voice-dock guard (2026-11-07 founder note).
