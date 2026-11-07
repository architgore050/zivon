# ADR-0008: Raw child audio is never persisted (T11) — transient buffer only, schema-enforced
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing Stage-1 T11 + handoff §6 ("never — transient buffer only")
- Driving NFRs / requirements: NFR-22 (none, ever), DPDP minimization, F-ADD-VOI-01 AC-6

## Context
Mic frames stream to Prisma for transcription. Keeping even a debug copy creates child-voice data
with no product need. The spec must make non-storage structural, not aspirational.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Stream-and-discard; no audio column/object anywhere; `voice_turn.audio_retained CHECK (false)`; storage audit asserts zero audio objects in U1–U4** | smallest possible blast radius; audit is mechanical; matches T11 exactly | debugging STT failures without audio is harder (mitigated: transcripts + confidence + latency histograms) | none | — |
| Opt-in debug capture ≤ 24–72 h encrypted (starter suggestion in skill ref 02) | helps STT quality work | consent UX complexity (a child-facing "record me?" toggle), encryption key management, an audit surface that must prove expiry — all for a P2 debugging nicety | medium | NFR-22 posture; DPDP minimization |
| Retain for quality/rubric sampling | best debugging | indefensible for children's audio at this product stage | — | NFR-22 |

## Decision
Never persist. `voice/audio` buffers in memory with a hard lifetime bound (frame TTL ≤ turn
lifetime); the DB CHECK makes any contrary row impossible; the nightly storage audit (C7 row)
asserts zero audio objects across all units.

## Consequences
Easier: privacy story is one sentence and provable. Harder: Gate-C rehearsal must rely on
per-stage timers + transcripts for diagnosis (already required by EVT-006). Monitor: storage
audit result (must stay zero).

## Revisit trigger (measurable)
T11 falsification test (features.md): if STT quality debugging demonstrably fails without audio
after real sessions, evaluate opt-in encrypted capture (24–72 h TTL, consent-gated, counsel
review) as a new ADR superseding this one's exception policy — not before.

## References
features.md T11; handoff §6; db-spec §4.3 (CHECK); storage-tiering §2 C7 + §7 test 4.
