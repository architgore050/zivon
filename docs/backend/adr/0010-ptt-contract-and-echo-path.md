# ADR-0010: Voice-turn control = push-to-talk with server endpointing allowed to fire first; echo path = client-side ducking (T3)
- Status: accepted — echo choice device-tested before Gate-C rehearsal (A-11)
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing handoff §3 ("Stage 2 chooses client ducking vs server-side gate")
- Driving NFRs / requirements: NFR-01/02/05/06, F-ADD-VOI-01 (14 dock states, battery + privacy: mic opens only between ptt.start and endpointing)

## Context
The message contract (ptt.start/frame/context.snapshot/ptt.stop/typed.doubt/interrupt) is fixed
by Stage 1. Two open control decisions: (a) who ends the turn — the student releasing the button
or server endpointing; (b) how the tutor's own speaker output re-entering the mic is handled.

## Options considered
| Option (a: endpointing) | Pros | Cons | Fails which NFR? |
|---|---|---|---|
| **PTT primary; server endpointing may fire first** (adopted) | battery/privacy (mic window bounded); Gate-C clock can start before button release (latency lever §7.3); explicit states map 1:1 onto the dock state machine | requires server-side silence/VAD handling on partials | — |
| Continuous listening + VAD | hands-free | mic always on (privacy posture + battery), false triggers in noisy Indian classrooms — the product explicitly treats noise as normal | NFR-05 (false barge-ins) |
| PTT strict (endpoint only on ptt.stop) | simplest | wastes ~300–500 ms per turn | NFR-01 p90 |

| Option (b: echo) | Pros | Cons |
|---|---|---|
| **Client-side ducking** (adopted): pause read-aloud/media while dock speaks; server-side gate flag as fallback | zero server audio processing; works offline-first | must be device-tested on low-end Android (A-11 trigger) |
| Server-side echo gate | central control | server can't hear the client's speaker; needs client cooperation anyway — strictly more complex for the same result |

## Decision
As adopted above; `interrupt` (barge-in) remains client-signalled with ≤ 300 ms server effect
(NFR-05); `turn.cancelled` acks it. Guard exhaustion never cuts an in-progress turn.

## Consequences
Easier: deterministic turn boundaries make the latency budget measurable. Harder: ducking quality
is a frontend/device test item; low-end devices with aggressive audio focus need the fallback
flag. Monitor: no-match rate vs interrupt rate (echo symptoms show up as phantom interrupts).

## Revisit trigger (measurable)
Device test (pre-Gate-C) fails on ≥ 1 demo device, or phantom-interrupt rate > 2 % of turns →
enable the server-side gate flag.

## References
handoff §3; backend-spec §7.1/§7.3; features.md T3 + F-ADD-VOI-01 AC-3.
