# ADR-0020: Voice audio transport — raw WS, PCM16 up / Opus down; monolith mount

- Status: accepted (SP1-VOICE, wave S1; instantiates ADR-0003 + backend-spec §4.2)
- Date / deciders: 2026-11-09 · SP1-VOICE (spec)
- Driving NFRs / requirements: Gate C; A-11 (client-side ducking in the gain graph); ADR-0008 (raw
  audio never stored); low-end Android first (audio skill §4); minimal images/manifests before the
  deadline.

## Context

ADR-0003 fixes raw WebSockets as the realtime transport (no media server). This ADR pins the
concrete audio framing, the client→server and server→client formats, and where the voice loop
*lives* at deploy time. Constraints: browser mic capture at 16 kHz mono (Prisma-class STT input
[ASSUMPTION — OQ-02]), Timbre v3 realtime output (format to pin, OQ-03), India cellular links,
and the repo rule that every long-running service is a Deployment + Service with slim images.

## Options considered

| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| 1. **PCM16/16 kHz 100 ms frames up · Opus 20 ms frames down, over one WS — chosen** | zero client encode complexity uplink; 32 kB/s ≪ cellular uplink; Opus downlink = proven speech codec at 20 ms frames (RFC 6716); one connection for control+audio | no FEC/DTX uplink on lossy links (tolerated: STT gaps degrade gracefully) | ~0 | none identified |
| 2. Opus both directions | ~4× less uplink bandwidth; FEC/DTX available | client encode path (AudioWorklet + wasm) = low-end-Android risk for marginal gain at 32 kB/s | medium | deadline (build time) |
| 3. WebRTC media plane via `livekit-plugins-gnani` (allowed by AGENTS.md) | battle-tested AEC/jitter/transport | a media server dependency, SFU ops, and a second realtime stack to debug before Gate C | high | deadline; ops |
| 4. HTTP chunked/streaming polling for audio down | simplest server | latency + no barge-in semantics | — | Gate C |

## Decision

- **Framing:** one WSS connection (`/voice/ws`); JSON text frames for control, binary frames for
  audio with the 8-byte header defined in `docs/specs/voice-agent/ws-contract.md` §3 (magic/version/segment_id/seq/flags).
- **Uplink (C→S):** PCM16 mono 16 kHz, 100 ms frames (3,200 B). Client captures via
  `getUserMedia` constraint ladder + AudioWorklet (never MediaRecorder — per-platform container
  drift), AEC on, ducking via GainNode only (A-11).
- **Downlink (S→C):** Opus 20 ms frames at Timbre's output rate [ASSUMPTION — pinned from OQ-03;
  if Timbre streams PCM, the pinned rate ships and Opus wrapping is added only if bandwidth
  demands]. Jitter buffer 60–120 ms clocked off `AudioContext.currentTime`; never hard-schedule
  < 150 ms ahead (low-end Android output latency 100–300 ms, +100–200 ms on Bluetooth).
- **Barge-in/echo:** per `docs/specs/voice-agent/ws-contract.md` §5 (PTT press = interrupt in P0; VAD barge-in over
  ducked playback in P1; echo guard drops STT within 200 ms of playback stop).
- **Storage boundary:** frames live in WS-handler memory only; nothing audio-shaped is persisted
  or logged (ADR-0008).
- **Deploy mount (P0):** `voice/ws_api.mount_voice(app)` mounts into the **core-backend FastAPI
  monolith** — the backend-spec §4.2 "voice-backend" Deployment + Service is that image with the
  router mounted (manifests 25–27, owner: core-backend agent). **No voice-specific Dockerfile,
  no voice k8s manifests in P0.**
- **Split criteria (if ever):** measured concurrent-WS density × per-connection memory exceeding
  the monolith's replica budget, or a WS-only scaling shape (voice connections idle-waiting while
  HTTP scales separately). Then: dedicated slim image (Dockerfile pattern: slim base,
  deps-before-code, non-root) + **k8s manifest numbers 17–18 reserved** for the split Deployment +
  Service, `voice/requirements.txt` becomes the image's dep list. Until then 17–18 stay unused.

## Consequences

- Easier: one image to build/deploy before the deadline; the dock speaks one protocol; EX5 consumes
  `docs/specs/voice-agent/ws-contract.md` directly; CI's existing pipeline covers the monolith.
- Harder: voice WS connections share the core backend's rollout (drain semantics on deploy —
  resume path F5 must survive pod death; it does, by design: reconnect + replay).
- Monitor: concurrent WS count + per-pod memory; Opus jitter-buffer gap rate; uplink loss rate.

## Revisit trigger (measurable)

Either split criterion above fires for 3 consecutive days, or uplink loss on judge-day network
degrades STT finals > 10% relative — then Option 2 (Opus uplink with FEC) and/or the manifest
split are re-decided with a live-measured delta, not by preference.

## References

- RFC 6716 (Opus) via `skills/zivon-audio-engineering-skills/` §1 (frame sizes, FEC/DTX, jitter)
- `llm_manager/README.md` (keepalive/idle patterns borrowed for ping/pong); `k8s/` numeric-prefix
  convention (apply order); AGENTS.md infra section (Deployment+Service for long-running services)
- `docs/specs/voice-agent/ws-contract.md` §3/§5; spec.md §12 (mount + config); backend-spec §4.2 (per mission brief)
