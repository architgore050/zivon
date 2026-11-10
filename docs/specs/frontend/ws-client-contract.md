# WS client contract — voice loop (browser side)

Agent: SP5-FRONT · Status: SPEC of the CLIENT side only.

**Consumes / flags [WS1 RECONCILED]:**

> **Canonical contract is SP1's `docs/specs/voice-agent/ws-contract.md` (server side).** This file is the client-side implementation view of that contract, not a competing protocol. Where names, paths, or codecs differ, SP1 wins and EX5-FRONT must implement SP1 names. Original SP5 proposal names (kept for traceability, do not implement): `session.init` ≡ `session.start`, `partial_transcript` ≡ `stt.partial`, `final_transcript` ≡ `stt.final`, `tutor.text` ≡ `tts.text`, `tts.chunk` ≡ `tts.audio`, `tts.start/tts.end` ≡ `agent.state`+`turn.end`, `client.endpoint` ≡ `audio.end`, `client.interrupt` ≡ `interrupt`, `client.text_input` ≡ text-fallback `audio.end` with typed transcript (SP1 §9 F1), `client.*` prefix dropped. Transport: `wss://<origin>/voice/ws` per SP1/ADR-0003 (not `/ws/tutor`); auth: `session.start.session_token` per API-001 (no anonymous session); audio C→S = PCM16 16 kHz 100 ms frames with 8-byte header per ADR-0020 §3 (not raw client Opus); S→C audio = Opus 20 ms frames with header; envelope is SP1's `type`-keyed WS text frames (not `{v,type,seq,ts,payload}`); client states mirror SP1 §1 (`idle→connecting→listening→thinking→speaking→idle`, `error`, `offline`). Sections 4–8 below (jitter buffer 60–120 ms, capture ladder, VAD/duck tuning, CSP request, latency logging) remain binding client behavior on top of SP1 names.
- `docs/backend/backend-spec.md` + ADR-0010 (ducking), ST-04 (range/transport), ADR-0015 (credit guards) — **now present** on merged main (W0); citations treated as contracts. ADR-0015 credit semantics map to SP1 hooks H1–H4; ST-04 narration transport is EX8-owned.
- The voice backend itself (FastAPI/WebSockets Deployment + Service) is an open
  TIMELINE item — nothing can connect today, which is why the CSP in force
  (`connect-src 'none'`) is currently correct.
- The dock UI is **founder-gated** (doctrine v1.6 has no §10.12 voice dock
  directive — DCR-002 standing guard). This file specifies protocol and client
  behavior, never pixels or copy.

Evidence tags follow the audio skill: [V] verified against MDN/WebRTC/RFC
sources, [C] constrained by an internal decision, [GAP] decided nowhere yet —
SP1/founder must fill it.

---

## 1. Transport

- One WebSocket per tutor session: `wss://<origin>/ws/tutor` (prod, edge-TLS
  termination per the locked HTTPS posture) / `ws://localhost:<port>/ws/tutor`
  (dev). Same-origin path so the scoped CSP change request is `connect-src 'self'`
  (§8) — no third-party host, ever (child-privacy guardrail).
- Subprotocol: `zivon-tutor.v1` offered in the handshake; server picks it or the
  client refuses to start (version guard instead of runtime probing).
- Binary frames: Opus audio [V: RFC 6716]; text frames: JSON (§3). Client sends
  audio as raw Opus frames (20 ms) — **MediaRecorder is not used for the loop**
  (per-platform container unpredictability) [V: audio skill §2]; capture path §5.
- Keepalive: `ping`/`pong` JSON every 15 s in idle/thinking; a missed pong for
  30 s moves the machine to `offline` (§7).

## 2. Client state machine

Extends the method's voice-UX reference (05 §1.1) with the brief's
`error/offline/barge-in` coverage. Every state has defined exits — a state
without an exit is a bug.

| State | Entered when | Client contract (dock-neutral) | Exits |
|---|---|---|---|
| `idle` | page loaded, no session | nothing captured, nothing sent; dock shows its entry affordance (founder-gated) | → `requesting-permission` (user activates) |
| `requesting-permission` | user activation | `getUserMedia` with §5 constraints; AudioContext created **suspended** and resumed in the same gesture handler [V: autoplay policy] | → `ready` (granted) / `error:mic-denied` / `error:unsupported-browser` |
| `ready` | permission granted + WS open (`session.ready` received) | no capture yet; session metadata (page anchor: `course_id`, `topic_slug`, `lang`, viewport) available to send | → `listening` (user starts) / `idle` (end) / `offline` (WS drop) |
| `listening` | capture started; audio frames streaming | stream §4 frames; render partial transcripts as they arrive; **capture + WS stay open during `thinking`/`speaking`** so barge-in needs no re-handshake | → `endpointing` (VAD silence) / `error:*` / `offline` |
| `endpointing` | client VAD gate fires (hangover 300–500 ms [V: audio skill §3]) | `client.endpoint` sent; awaiting server transcript | → `thinking` (final transcript received) / `listening` (VAD re-trigger = false endpoint) |
| `thinking` | `server.partial_transcript`/final accepted | request `tutor.text` tokens rendered as they stream; audible/visible "working" cue is founder-gated; per-stage timestamps recorded (§9) | → `speaking` (first `tts.chunk`) / `error:no-match` (low confidence) / `error:quota-exhausted` / `offline` |
| `speaking` | playback scheduled | §4 playback scheduling; **duck mic gain, do not mute** (§6); barge-in armed | → `interrupted` / `ready` (tts.end) / `error:*` |
| `interrupted` (barge-in) | user speech over playback (VAD over agent) OR explicit stop | `client.interrupt` sent; agent stream dropped mid-flight; ducking reversed; tutor's partial sentence is discarded, not resumed (restart-the-turn semantics [GAP: resume-vs-restart is SP1's to confirm]) | → `listening` (capture continues) |
| `error:<code>` | see codes below | copy + recovery path is founder-gated; client guarantees: no silent death, retry never loses session context | → `ready` (recoverable) / `idle` (terminal) |
| `offline` | WS drop / send failure | automatic reconnect §7; lesson stays fully usable (layer independence G5) | → `ready` (reconnected) / `idle` (user gives up) |

Error codes (client-side, emitted as `error:{code}`): `mic-denied`,
`mic-in-use`, `unsupported-browser`, `no-input` (silence timeout 8 s),
`no-match` (low-confidence transcript), `system-error` (5xx/protocol),
`quota-exhausted` (server `error.quota`), `timeout` (no first audio > 12 s
after endpoint → apology + typed fallback per Gate C ladder).

## 3. Message catalogue (JSON text frames)

Envelope (both directions): `{"v": 1, "type": "<name>", "seq": <int>, "ts": <ms
epoch>, "payload": {…}}`. `seq` is per-direction monotonic; a gap = protocol
error → `error:system-error`. Unknown `type` on the client → ignored + counted
(forward compatibility); unknown on the server → `error:system-error`.

| Direction | Type | Payload (fields) | Notes |
|---|---|---|---|
| C→S | `session.init` | `locale`, `page_anchor{course_id, topic_slug, block_id?, lang}`, `capabilities{opus:true, webrtc_vad:true}` | first frame after open |
| S→C | `session.ready` | `session_id`, `limits{max_turn_s, daily_credit_hint?}` | acknowledges; `daily_credit_hint` [GAP: needs ADR-0015 territory] |
| C→S | `audio.chunk` | *(binary frame, no JSON)* | 20 ms Opus; seq carried by WS ordering |
| S→C | `partial_transcript` | `text`, `confidence` | live, may be many |
| S→C | `final_transcript` | `text` | ends `endpointing` |
| S→C | `tutor.text` | `delta` or `final` | streamed tokens; rendered as text (visible tutor text = the honest default; founder may change) |
| S→C | `tts.chunk` | *(binary)* | Opus, scheduled per §4 |
| S→C | `tts.start` / `tts.end` | `{}` | playback boundaries for state machine |
| C→S | `client.endpoint` | `{}` | VAD endpoint hint |
| C→S | `client.interrupt` | `{}` | barge-in: stop generating + stop speaking |
| C→S | `client.text_input` | `text` | degraded fallback §7 |
| C→S / S→C | `ping` / `pong` | `{}` | keepalive |
| S→C | `error` | `code`, `message`, `retryable` | `code` enum mirrors §2 |

**GAPs the server side must close** (recorded, not resolved here): auth/session
identity (device pseudonym per the brief's ADR-0007 — absent), credit/quota
signal semantics, resume-vs-restart after interrupt, transcript retention
signals (DPDP), codec bitrate/FEC settings per network profile.

## 4. Playback scheduling (jitter buffer) [V: audio skill §1]

- Buffer ≥ 2–3 Opus frames before starting playback; target 60–120 ms buffered;
  top up per frame arrival; schedule off `AudioContext.currentTime`, never wall
  time. Never hard-schedule < 150 ms ahead (low-end Android output latency
  100–300 ms) [V: audio skill §4].
- `speak.end`-to-`ready` transition requires the buffer drained, not the last
  frame received.
- **Implementation status (2026-11-10):** `frontend/assets/zivon.js` implements
  this section's frame/sequence bookkeeping and the `speaking` transition ONLY.
  It does not decode Opus or schedule AudioContext playback, and its gain nodes
  are bookkeeping values, not a connected output graph. The earlier "jitter
  buffer / ducking playback" claim was removed from the client header and
  TIMELINE; real playback lands with the voice backend.

## 5. Capture constraints [V: audio skill §2]

- Explicit constraints: `{echoCancellation: true, noiseSuppression: true,
  autoGainControl: true, channelCount: 1, sampleRate: 16000}` (Prisma's expected
  rate [GAP: confirm exact rate in Gnani docs before build]).
- `OverconstrainedError` → ladder: drop `sampleRate`, then `channelCount` —
  never fail the session on a constraint.
- Verify actual track settings via `getSettings()` (older Android WebViews
  downmix silently); log a mismatch as a `zivon.audio` console warning.
- Latency probe (founder-gated placement): play a tick, measure round-trip, use
  it only to tune the buffer — never shown as raw numbers to a student.

## 6. Barge-in and ducking [C: audio skill §3's A-11/ADR-0010 intent]

- Client VAD gate (energy + WebRTC VAD) armed during `speaking`; hangover
  300–500 ms; two consecutive triggers inside 1 s → `client.interrupt`.
- Ducking in the gain graph: agent `GainNode` ducked (e.g. ×0.15) while user
  speech energy is high; mic path ducked during agent playback. **Never
  `track.enabled = false` / mute — it breaks the AEC reference** [V: WebRTC AEC
  material].
- On `client.interrupt`: client stops scheduling further `tts.chunk`s
  immediately and drops buffered frames.

## 7. Degraded fallback to text input

The brief binds the fallback to features.md, which is absent — the fallback is
therefore specified as the layer-independence rule (G5) applied here, and
flagged Q6:

1. A text path exists whenever the dock exists (founder-gated placement); it
   sends `client.text_input` and the loop proceeds from `thinking` — the tutor
   reply path is identical, so the fallback is real, not a stub.
2. Triggers that surface it: `error:mic-denied`, `error:unsupported-browser`,
   `error:quota-exhausted`, repeated `error:timeout`, `offline`, or an explicit
   "type instead" affordance (founder-gated copy).
3. Never destroys context: the page anchor and session survive; the transcript
   of the failed turn is preserved read-only.
4. Offline: the lesson itself is unaffected (static page); the dock shows the
   offline state; typed input is queued ONLY in memory and cleared with an
   honest message on unload — nothing pretends to have sent.

## 8. CSP relaxation (GRANTED 2026-11-10 — applied at P0 wire-up)

The locked CSP (`connect-src 'none'`) forbade the WebSocket. The founder
authorised the scoped relaxation at P0 wire-up, and it is now APPLIED:

```text
connect-src 'self'          (was: connect-src 'none')
```

- Core pages (no dock) KEEP `'none'` — the relaxation is opt-in per page, which
  keeps G5 mechanically enforced. Only generated lesson pages opt in.
- **Applied in two places, both narrow:** `factory/render.py` emits
  `connect-src 'self'` in the lesson-page `<meta>` CSP, and `docker/nginx.conf`
  repeats the full header set for the `location ^~ /courses/` block. Every
  other location inherits the server-level `connect-src 'none'`, so the
  landing page, catalogue, and 404 stay locked. `default-src 'none'` /
  `base-uri 'none'` are unchanged in the page meta.
- **Proxy:** the same-origin dial `wss://<origin>/voice/ws` is proxied by
  `location /voice/` to `core-backend:8000` (identical upstream name in compose
  and cluster; compose network alias `core-backend`). Upgrade headers and a
  600 s read timeout are set; buffering is off.
- The call site that opens the socket is `window.ZivonVoiceClient.create()`
  (zivon.js §7 header notes the granted CSP).

## 9. Latency measurement (Gate C: end-of-speech → first audio < ~4 s)

Every turn stamps: `t_endpoint` (client VAD), `t_final_transcript`,
`t_first_token` (first `tutor.text`), `t_first_audio` (first scheduled
`tts.chunk`). The turn summary is one `console.debug` line behind the
`zivon.evtdebug` flag and one `EVT-tutor_turn_completed`-shaped event in the
§9 queue of `spec.md` — measurable from day one, shippable to a sink later
(NEED-003), zero CSP impact now.

## 10. What SP1 must decide (the gap list, in one place)

1. Server message names/semantics confirmation against §3 (this file is the
   client's counterparty proposal).
2. Session identity + the device-pseudonym model (ADR-0007 absent).
3. Interrupt semantics: resume, restart, or drop the tutor turn.
4. Quota/credit signaling shape (ADR-0015 territory).
5. Transcript/audio retention signals the client must surface (DPDP flags,
   method reference 06 §4).
6. Opus bitrate/FEC/DTX settings per network profile (audio skill §1 defaults:
   20 ms frames, `useinbandfec=1`, `usedtx=1` for turn-taking).
7. Subprotocol/version negotiation confirmation (`zivon-tutor.v1`).
