# ADR-0003: Realtime transport is raw FastAPI WebSockets (LiveKit deferred)
- Status: accepted (revisit trigger defined)
- Date / deciders: 2026-11-07, Stage-2 systems session; AGENTS.md permits LiveKit "if it reduces complexity"
- Driving NFRs / requirements: NFR-01…05 (Gate C), handoff §3 (the message contract is already decided product-side), repo simplicity rules

## Context
The voice channel contract (PTT, audio.frame, context.snapshot, interrupt, typed fallback, guard
state push) is fully specified in handoff §3 and rendered in backend-spec §7. The question is the
transport stack: raw WSS inside the FastAPI monolith vs LiveKit rooms + `livekit-plugins-gnani`.

## Options considered
| Option | Pros | Pros/cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Raw FastAPI WSS** | the contract is custom anyway (PTT semantics, guard `state` push, typed path); no room lifecycle, no SFU, no extra image; audio is 20 ms Opus frames — LiveKit's strengths (routing, simulcast, server VAD) are not needed at 10 concurrent | barge-in detection is client-signalled (`interrupt`), not server-side; we own heartbeat/backpressure code (small, well-understood) | none beyond the app | — |
| LiveKit + gnani plugin | official plugin wraps Prisma/Timbre; server-side VAD/barge-in; scales sessions | room server to run + token issuing + plugin coupling; our PTT-first contract maps awkwardly onto participant tracks; more moving parts for a 60-second-demo reliability bar | medium-high | risks NFR-01 (extra hops) at demo scale; contradicts "simplest thing that meets the NFRs" |
| SSE + HTTP chunk uploads | firewall-friendly | bidirectional latency + chunking complexity; strictly worse | — | NFR-01/05 |

## Decision
Raw FastAPI WebSocket endpoint `/v1/voice` inside the voice monolith, per §7 catalogue. Gnani
clients are called server-side from `voice/gnani` (keys never client-side).

## Consequences
Easier: one image, one Service, full control of ordering/backpressure rules; demo path is minimal.
Harder: we implement heartbeat, resume window, and (later) server-side speech-start detection
ourselves. Monitor: reconnect rate, dropped-frame rate.

## Revisit trigger (measurable)
Server-side VAD/barge-in becomes a product requirement (hands-free mode), OR > 50 concurrent
sessions sustained, OR multi-region edge — any one → re-evaluate LiveKit (its plugin then saves
the STT/TTS plumbing we wrote by hand).

## References
AGENTS.md (LiveKit allowed option); handoff §3; vendored `websocket-engineer` patterns;
livekit-plugins-gnani existence per docs.gnani.ai (addendum 12).
