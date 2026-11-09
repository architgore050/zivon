# ADR-0007: Identity = anonymous device-scoped pseudonymity with a nullable guardian_ref seam (T6)
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing the Stage-1 T6 decision (TIMELINE: accounts out of scope)
- Driving NFRs / requirements: NFR-22/23/24 (privacy), NEED-003/012/013, founder correction 3 (login-free), C-087 (counsel flag)

## Context
No accounts, no student auth (repo out-of-scope list). Yet consent, per-user credit caps, coverage,
and deletion all need a stable handle. DPDP will eventually require verifiable guardian consent —
a scale-up question, not a challenge-window question.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Client-generated `device_pseudo_id` (UUIDv4) + server anchor row + nullable `guardian_ref` text column (dormant)** | zero auth infra; consent/deletion keyed on device possession; seam exists so adding guardian verification later is a column + flow, not a migration | possession-based identity is spoofable (A-03 — accepted: caps are budget hygiene); deletion identity is weak until counsel design | none | — |
| Accounts (email/password or OTP) | strong identity, guardian verification possible | contradicts TIMELINE out-of-scope + founder correction 3; auth UX kills the demo; password infra for children — worst option | high | scope + simplicity |
| Server-issued device cookie/fingerprint | tamper-resistant | fingerprinting children — DPDP posture violation (ref 05 §1 "no device fingerprinting") | medium | privacy posture |

## Decision
Option 1. `guardian_ref` stays NULL in P0 (db-spec Q3); any use is gated by the counsel decision
(C-087). DELETE /v1/data identity = device_pseudo_id + one-time confirm token (possession proof,
friction only).

## Consequences
Easier: login-free product exactly as founder specified; minimal PII surface. Harder: a cleared
browser can re-register as "new" (accepted trade-off — tombstones keyed on the old id still
protect the old data; a new device id starts clean by design). Monitor: abuse-bucket patterns on
consent/deletion endpoints.

## Revisit trigger (measurable)
Any scale-up beyond the challenge demo, monetization, or the counsel answer on verifiable
guardian consent → design the guardian flow against the existing seam (post-challenge).

## References
features.md T6; backend-handoff ENT?-Session (guardian_ref nullable by design); db-spec §4.1/§4.2;
AGENTS.md out-of-scope list.
