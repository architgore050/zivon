# Voice WebSocket Contract

Extends the backend-spec WebSocket catalogue (S0-owned) for the voice loop. Transport decision is
ADR-0003's raw WebSocket (no media server) — this document instantiates it. Echo/ducking and PTT
barge-in semantics implement ADR-0010 + A-11; highlight messages implement ADR-0012 + T7; the
snapshot message implements ADR-0014.

- **Transport:** one WSS connection per dock session (`/voice/ws`), JSON text frames for control,
  binary frames for audio (§3). No cookie; auth via `session.start.session_token` (API-001) —
  tokens never in URLs.
- **Consumer of every S→C message:** the voice dock JS (EX5-FRONT) inside the design-doctrine
  §10.12 dock shell (DCR-002 — states and events only; visual design is not negotiated here).
- **Versioning:** first message both ways carries `v: 1`; mismatch → close 4409. Adding fields is
  backward-compatible; changing meaning is not.

## 1. Client states (dock-visible via `agent.state`)

`idle → connecting → listening → thinking → speaking` (or `speaking_text`) `→ idle`; `error` and
`offline` are entered from any state; `connecting` covers WS handshake + auth. The dock renders
state, never interprets raw events. `speaking_text` = answer visible as text without audio (F2/F4).

## 2. Message catalogue

Dir: C→S = client→server, S→C = server→client. Billable? = Gnani programme credits (OQ-06 units).

| Type | Dir | Schema (JSON unless binary) | Ordering/seq | Idempotent? | On loss | Billable? | Consumer / notes |
|---|---|---|---|---|---|---|---|
| session.start | C→S | `{v, session_token, device, locale, capabilities{ptt,opus?}, resume?, last_turn_id?, anchor?}` | first (and on resume) | yes (resume-safe) | retry until session.ready | no | server: auth (4401), H1 guard, state store |
| session.ready | S→C | `{v, session_id, profile, state, server_time}` | after start | — | client re-requests via resume | no | dock: enable mic UI; `profile` is **server-asserted** (spec.md §11) |
| audio.start | C→S | `{turn_hint?}` | per PTT press | no (each press = new turn intent) | ignore (no press = no turn) | no | server: open mic stream, state listening |
| audio.chunk | C→S | **binary** header+PCM16 (§3) | seq per mic stream, monotonic | n/a | drop old partials; STT tolerates gaps | yes (STT seconds) | stt_client feeds Prisma |
| audio.end | C→S | `{}` | once per press (PTT release) or client-VAD EOS (P1) | no | resend once if no stt.final in 1 s | no | EOS trigger; L0 starts here |
| stt.partial | S→C | `{turn_id, seq, text}` | seq per turn | — | client renders latest only | no | dock: live transcript line |
| stt.final | S→C | `{turn_id, text, lang, confidence?}` | once per turn | — | re-request on resume | no | dock: freeze transcript; server: proceed |
| context.snapshot | C→S | `{topic_id, class, chapter, block_id, block_type, sim_id?, sim_vars?, scroll_pct, lang_pref, ts}` | latest-wins | yes (replace) | stale snapshot → F7 generic answer | no | anchoring: prompt context + REF validation |
| agent.state | S→C | `{state, reason?}` | on every transition | — | resume replays current | no | dock: state chrome |
| tts.text | S→C | `{turn_id, segment_id, kind: speech\|summary\|filler, text}` | per segment, order of speech | — | text panel skips | no | dock transcript panel; caption sync |
| highlight | S→C | `{turn_id, block_ids[]}` | once per turn, **before/with first tts.audio** (T7) | — | highlight may be missed (visual only) | no | page JS: highlight blocks (ADR-0012) |
| tts.audio | S→C | **binary** header+Opus (§3) | (segment_id, seq) monotonic per segment | n/a | client skips to next seq (jitter buffer continues); gap logged in metrics | — | dock: schedule playback |
| interrupt | C→S | `{turn_id?}` | anytime while speaking/thinking | yes (repeat = same intent) | server may have finished; reply is harmless no-op | no | server: barge-in (§5) |
| turn.end | S→C | `{turn_id, end_reason: done\|interrupted\|error, latency_ms{L0..L8}, usage{stt_audio_s, tts_chars, brain_prompt_tokens, brain_completion_tokens, retries}}` | once per turn | — | resume sends it if missed | no | dock resets; server wrote ledger (H4) |
| error | S→C | `{code, message, recoverable}` | anytime | — | logged; codes are stable ids | no | dock: F1–F8 rendering; codes listed in §6 |
| ping / pong | both | `{t}` | keepalive 15 s | — | 2 missed → offline state | no | NAT/idle timeouts |

Notes: `audio.chunk` loss is tolerated (STT streams; gaps degrade accuracy, never crash);
`tts.audio` gaps are bridged by skipping (jitter buffer logic per the audio skill — never
hard-schedule < 150 ms ahead). Every row above has a consumer; if a merge-time edit removes a
message, its consumer row must be removed in the same PR.

## 3. Binary frame layout (ADR-0020)

8-byte header, big-endian, then payload:

| bytes | field | C→S (audio.chunk) | S→C (tts.audio) |
|---|---|---|---|
| 0 | magic | `0xA5` | `0xA5` |
| 1 | version | 1 | 1 |
| 2–3 | segment_id | mic stream id (1) | TTS segment id (per turn, from 1) |
| 4–5 | seq | monotonic from 0 | monotonic per segment from 0 |
| 6 | flags | bit0 = final (flush) | bit0 = final frame of segment |
| 7 | reserved | 0 | 0 |

Payload: C→S = PCM16 mono 16 kHz, 100 ms (3,200 bytes) per frame — simplest correct thing; cellular
uplink carries 256 kbps, so no codec tax on the client for P0. S→C = Opus 20 ms frames (RFC 6716)
at Timbre's output rate [ASSUMPTION: pin format/rate from OQ-03; if Timbre streams PCM, the rate is
pinned and Opus encoding happens server-side only if bandwidth demands it]. FEC/DTX tuning per the
audio skill happens at EX1 measurement time, not by default.

## 4. State machine (server-enforced truth)

| From | Event | To | Server actions |
|---|---|---|---|
| any | session.start (valid) | connecting→idle or resume | auth, H1, replay state |
| idle | audio.start | listening | open STT stream, stamp L0 candidates |
| listening | audio.end | thinking | EOS: stop mic→Prisma; wait stt.final; H2; snapshot check; brain call; stamp L0 |
| thinking | first tts.text/tts.audio | speaking | stamp L3/L6; highlight precedes first audio (T7) |
| speaking | tts.audio final + turn.end | idle | H4 ledger write |
| thinking/speaking | interrupt | listening | §5 barge-in |
| speaking | F4 | speaking_text | text-only continuation |
| any | error (recoverable) | error → prior state | §9 F-table in spec.md |
| any | WS closed | offline | client backoff-reconnect; resume |

## 5. Interruption / barge-in (ADR-0010) and the echo path

1. Client detects intent to speak while the agent speaks/thinks: **P0 = PTT press** (pressing
   while `speaking`/`thinking` IS the interrupt), **P1 = client VAD over ducked playback**
   (hangover 300–500 ms; duck via GainNode to ~20%, never track muting — muting breaks the AEC
   reference; A-11).
2. On `interrupt`: client ramps agent playback down (~50 ms) and stops scheduled buffers; sends
   `interrupt`; server aborts the brain stream (close upstream — the deadline-close semantics
   free the slot), aborts/cancels pending TTS, drops queued unsent audio, emits `agent.state
   listening`, then `turn.end{end_reason: interrupted}` for the cut turn.
3. **Echo guard:** STT events arriving within 200 ms after playback stop are dropped (loudspeaker
   tail leak; OQ-07 verifies on-device). The dock keeps `echoCancellation: true` through the
   constraint ladder.
4. Credit honesty: an interrupted turn bills only what was actually spoken (H4 reads meters at
   abort, not at turn start).

## 6. Error codes (stable ids; dock maps each to F1–F8 in spec.md §9)

`stt.unavailable` (F1) · `brain.first_event_timeout` (F2) · `brain.midturn_stall` / `brain.deadline`
(F3) · `tts.unavailable` (F4) · `ws.reconnecting` (F5, client-side state) · `credit.over_daily` /
`credit.over_session` (F6) · `context.stale` (F7) · `auth.invalid` (close 4401) · `version.mismatch`
(close 4409).

## 7. Sequences (the three the dock must handle first)

- **Happy path (PTT):** start/ready → press: audio.start → chunks → release: audio.end →
  stt.partial* → stt.final → (highlight · tts.text · tts.audio* — highlight first) → turn.end.
- **Barge-in:** … tts.audio* → press → interrupt → agent.state listening → turn.end{interrupted}
  → new audio.start.
- **Reconnect:** drop → dock offline → session.start{resume, last_turn_id} → session.ready (state
  replayed) → live messages continue, or turn.end{error} for the lost turn.
