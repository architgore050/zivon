# Zivon Vocal Tutor Agent — Architecture Spec

Wave S1 (`SP1-VOICE`) · status: build-ready · target: `voice/` top-level package (backend-spec §4.3
name is binding; never `voice_backend/`).

This spec is a handoff: a reader with no access to the author can build from it. Numbers carry
evidence tags; `[ASSUMPTION]` items appear in the measurement plan (`latency-budget.md`) and are
pinned during EX1's first days. Binding decisions are cited by ID, never re-decided.

---

## 1. Scope and the one-stream law

The vocal tutor is the product runtime loop from `AGENTS.md`: the student speaks a Physics doubt
(Hindi / English / code-mixed Hinglish) anchored to the page they are on; the tutor answers in
spoken Hinglish, step-by-step and Socratic, and highlights what it refers to on the page.

**One-stream law (Gate C):** from end-of-speech to first spoken audio, no hop may buffer more than
its budget row (`latency-budget.md`). The tutor must START SPEAKING before the brain finishes
generating: the brain's stream is chunked at sentence/segment boundaries, each chunk is handed to
Timbre immediately, and Timbre's audio streams back immediately. Anything that must hold every
time (schema checks, tag whitelists, credit caps, T12 guards) lives in the harness, not in prompt
prose (`skills/prompting-and-agent-design/SKILL.md`, control-layer table).

Out of scope for `voice/`: content generation (factory), page rendering (frontend), narration
assets (EX8-NARRATION), the dock's visual design (design-doctrine §10.12, DCR-002 — consumed as-is).

## 2. Pipeline

```
 mic (PTT press, P0)                                   speaker
   │ getUserMedia 16 kHz mono, AEC on                        ▲
   ▼                                                         │ binary WS frames (Opus, 20 ms)
 [audio_io] ──PCM16 100 ms frames──▶ [ws_api]                │
                                        │                    │
                                        ▼                    │
                                 [stt_client] Prisma v3.0 streaming WS
                                        │ partials → UI live; final → below
                                        ▼
                          [session] auth+credit hooks (H1/H2) · [anchoring] snapshot→prompt
                                        │
                                        ▼
                          [brain_client] gemma-4-26b-a4b-it via Gemini API, streaming
                                        │  · thought summaries (flag on) → whitelist → TTS now
                                        │  · content prose → [chunker] sentence/clause chunks
                                        ▼
                                 [tts_client] Timbre v3.0 realtime, tags inline
                                        │
                                        └──▶ [ws_api] ──tts.audio frames + tts.text + highlight──▶ dock
```

Stage notes:

1. **Capture (`audio_io` client-side contract):** `getUserMedia` with an explicit constraint ladder
   `{ echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
   sampleRate: 16000 }`; fall back down the ladder on `OverconstrainedError` and verify real
   settings via `getSettings()` (MediaRecorder silently downmixes to 8 kHz on some WebViews —
   raw AudioWorklet frames are used instead of MediaRecorder for streaming). [V: audio skill §2]
2. **Endpointing (PTT-first):** P0 uses the ADR-0010 PTT contract — end-of-speech is the PTT
   release, which removes the 300–500 ms VAD hangover from the critical path. Hands-free VAD
   endpointing is P1 (same WS contract, `audio.end` emitted by client VAD with 300–500 ms
   hangover). [V: audio skill §3]
3. **STT (`stt_client`):** one Prisma v3.0 streaming session per WS session; partials are forwarded
   to the dock for live display but the brain is called only on the final transcript (correctness
   over cleverness; revisit trigger in `latency-budget.md` §R). Code-mixed Hinglish is normal
   input, not an edge case.
4. **Brain (`brain_client`):** `gemma-4-26b-a4b-it` on the Gemini API with a Google Gemini API key
   (Gate A outcome). Streaming; see §4 for the serving-path decision and the reliability seam.
5. **Chunking (`chunker`):** sentence-boundary streaming chunker per ADR-0019; first chunk is the
   first sentence (or first clause if the first sentence is long); flush deadline 250 ms so a
   missing boundary never stalls audio.
6. **TTS (`tts_client`):** Timbre v3.0 realtime streaming; tutor text carries a whitelisted subset
   of the v3 audio tags inline; output audio frames stream back as binary WS frames with a tiny
   header (ADR-0020). Vendor first-audio claim < 200 ms. [V: vendor claim, verify at build]
7. **Highlights (`anchoring`):** per ADR-0012 + T7, the tutor's referenced page blocks are
   highlighted **before or atomically with** the first audio frame of the turn (§7).

## 3. Module layout (`voice/` top-level package, sibling of `factory/`)

| Module | Owns | Key contract |
|---|---|---|
| `voice/__init__.py` | package marker; exposes `mount_voice(app)` | the only symbol the core backend imports |
| `voice/config.py` | `VoiceSettings.from_env()` — all `ZIVON_VOICE_*` knobs (§12); no secrets in code | every knob has a default; secrets come from the env only |
| `voice/audio_io.py` | server-side frame validation: PCM16/16 kHz chunk sanity, `tts.audio` header codec (u16 segment_id, u16 seq, u8 flags), drop-stale logic | ADR-0020 |
| `voice/stt_client.py` | Prisma v3.0 streaming WS client: connect/reconnect per session, partial+final events, language hints | OQ-02 contract, verified at build |
| `voice/brain_client.py` | Gemma brain client (§4): streaming, inactivity timeout, first-event deadline, wall-clock deadline, transport retries, mid-stream abort on barge-in, REF-line + tag parsing, usage capture | ADR-0017 |
| `voice/chunker.py` | sentence/clause streaming chunker: boundary rules, max-chars, flush deadline, markdown/LaTeX stripping, tag preservation | ADR-0019 |
| `voice/tts_client.py` | Timbre v3.0 realtime client: stream text in (tag-whitelisted), audio frames out, per-turn char meter for H3 | ADR-0020, OQ-03 |
| `voice/session.py` | session store adapter (ADR-0002): session state, `voice_turn` rows (§6), TTL purge hook, credit ledger + guard checks (§8) | ADR-0002, ADR-0015 |
| `voice/anchoring.py` | context snapshot → tutor prompt context; REF validation against snapshot block ids; highlight message emission | ADR-0012, ADR-0014 |
| `voice/ws_api.py` | FastAPI WebSocket route mounted via `mount_voice(app)`; client state machine, message routing, failure-mode orchestration (§9), auth (§11) | `ws-contract.md` |

Rules: small focused modules, type hints everywhere, basic logging from day one (`AGENTS.md`
coding standards). No module other than `brain_client.py` talks to an inference server; no module
hands-rolls HTTP to it (§4). `voice/` imports nothing from `factory/`; the dependency edge is
one-way (`voice` → `llm_manager` reliability *patterns*, documented in §4 — not a runtime import
of the node client, which is request/response-shaped).

**Dependencies (`voice/requirements.txt`, for the CI/merge agents):**

```
# voice/ mounts into the core-backend image; fastapi/pydantic already present there.
google-genai>=1.0,<2        # Gemini API SDK (brain)  [ASSUMPTION: pin exact at build]
websockets>=12,<16          # Prisma streaming WS client
httpx>=0.27                 # Timbre REST fallback + probes (no ad-hoc raw urllib anywhere)
```

No torch/pdfplumber/playwright (audio brain calls are remote; the image stays slim). Final pins
land with the core-backend agent's lockfile.

## 4. Brain client — serving path and the llm_manager seam

**Decision (ADR-0017):** primary serving path is the **Gemini API directly** (`generativelanguage.googleapis.com`,
model id `gemma-4-26b-a4b-it`, Google AI Studio key, `google-genai` SDK streaming), called by a
dedicated small client `voice/brain_client.py`. The OpenRouter route the cluster already uses for
the llm-manager node (`openrouter.ai/api/v1`, K8s Secret key) is the documented fallback transport,
selected by `ZIVON_VOICE_BRAIN_TRANSPORT=openrouter` — useful if Gemini API quota/latency fails
probe (OQ-05), since it reuses an already-paid, already-keyed route. Both options and the decision
rationale are in ADR-0017.

**The seam vs the AGENTS.md rule ("all model calls go through llm_manager"):** `llm_manager/README.md`
explicitly scopes the voice agent OUT of the node ("voice streaming is a different domain —
real-time audio chunking, barge-in, partial transcripts"). The node's request/response contract
also cannot express voice's needs: mid-stream abort on barge-in (closing the upstream stream to
stop generation and free the slot), a first-event deadline measured in seconds, and per-segment
parsing while tokens flow. Therefore `voice/brain_client.py` is its own small client that mirrors
llm_manager's reliability patterns — the four that make the 2026-11-07 runaway-call incident
class impossible — with voice-domain values:

| Pattern (from `llm_manager/README.md`) | Voice value | Why it differs from the node's 600/1800 |
|---|---|---|
| Streaming default | always stream | first-token latency is the product |
| Inactivity timeout | **4.0 s** between stream events [ASSUMPTION, measure] | a tutor turn that goes silent > 4 s mid-answer is a stall; the node tolerates minutes because factory calls think for tens of minutes |
| Wall-clock deadline | **45 s** per turn (hard close mid-stream) | tutor answers are short; closing frees the stream exactly like the node's deadline abort |
| Transport retries | **2**, only **before any audio reached the client** | after speech starts, a retry would cut mid-word; post-audio failures degrade (§9) instead |
| (voice-only) first-event deadline | **3.0 s** to first stream event (thought summary or content token) [ASSUMPTION] | Gate C's biggest rock; breach → one retry → text fallback |

No silent fallbacks, ever (llm_manager failure semantics): every timeout/retry/degrade emits an
`agent.state` + `error` message so the dock can show the honest state, and the turn's usage row
records what happened (§6).

**Request shape (contract, both transports):** system prompt (Appendix A) + bounded page context
(§7) + last ≤ 6 turns of `voice_turn` text (7-day-TTL rows, §6) + the new transcript. No
`max_tokens` (repo law: thinking models — a cap is a truncation risk), no `enable_thinking=false`;
`thinking_level` stays at the model default unless the Gate C falsification path in ADR-0018
fires (founder-signed change only).

**Usage capture:** every turn records prompt/completion (and thinking-token counts where the
transport reports them) into `voice_turn.usage_json` for the credit ledger (§8) — noting OpenRouter
may report `usage: null` (known node caveat), in which case latency/first-event metrics still land.

## 5. Thinking out loud (decision summary — full rationale in ADR-0018)

**Decision: Option B with a strict harness whitelist, plus Option A as the dead-air fallback.**

- **B (primary, flag `ZIVON_VOICE_THINKING_SUMMARIES`, default off until probed):** when the
  transport surfaces thinking/thought-summary events (OQ-04), the harness speaks the model's own
  one-line reasoning summaries **during** the thinking gap — this is perceived-latency gold and
  Socratic modeling ("let me recall what the question asks…") for learners. Fallback when the
  transport cannot surface summaries: the tutor is instructed to prefix at most 2 procedural
  summary lines with the mechanical marker `>> ` inside the answer stream; the harness extracts,
  strips them from spoken text, and speaks them as they arrive. A mechanical marker — not prose
  promises — because contracts are enforceable only in the harness layer.
- **Whitelist (harness-enforced, the T12 guard):** only **procedural** summary kinds may be
  voiced — recalling the question, restating given data, naming the relation/formula from the page
  that will be used, announcing the step order, checking against the page. Anything **substantive**
  (a physics claim, a number not yet verified against the page, a causal assertion) is **dropped
  silently from speech** (it may remain in the visible transcript panel as text). T12 — never
  voice a wrong physics half-thought — is a harness guarantee, not a prompt plea. Filter = kind
  classifier over the summary line (starts-with patterns + "contains a number or a noun-phrase
  claim ⇒ substantive ⇒ drop-voice"), tuned in `testing/voice/test_ws_api.py` fixtures.
- **A (fallback, always armed):** if no speakable audio has started within `ZIVON_VOICE_FILLER_SILENCE_MS`
  (default 2000 ms [ASSUMPTION]) of `thinking` state onset, the harness speaks one short randomized
  filler from a fixed safe list ("ek second…", "achha sawaal…", "sochte hain…") — max 1 per turn,
  drawn without repetition across the last 3 turns. Fillers are voiced by the same TTS path and
  count toward its credit meter.
- **Mayer check:** summaries + fillers are short, spoken, and non-parallel to visual reading —
  they fill dead air without adding a second simultaneous narration channel; highlight (§7) stays
  visual-only. (Multimedia principle: don't talk over the thing the student is reading; the dock
  ducks, the tutor never narrates the sim while the student manipulates it.)
- **Credit cost:** Timbre bills characters including tag characters; summaries/fillers are capped
  (≤ 2 summaries/turn voiced, ≤ 1 filler/turn, ≤ 120 chars each) in the harness (H3), so the
  dead-air policy cannot blow the tranche (§8).
- **Falsification test (recorded in ADR-0018, run by EX1):** 20-turn scripted physics eval per
  mode (B-on, A-only, silence). Pass B-on only if: (a) voiced substantive-wrong claims = 0,
  (b) judged perceived responsiveness improves vs A-only, (c) added TTS character cost per turn
  ≤ 15%. Failure on (a) → B is disabled at the flag until the classifier is fixed; failure on
  (b) → drop to A-only permanently for the demo.

## 6. Session, memory, and data boundaries

Per ADR-0002 (session store) and backend-spec A-02, with voice-specific rows:

- **Session state** (auth identity, profile normal|demo, current anchor, credit counters, brain
  stream handle) lives in the session store the core backend owns; `voice/session.py` is the
  adapter. Voice adds no new store.
- **Transcripts** are persisted as `voice_turn` rows (Appendix B) with the A-02 **7-day TTL** —
  a daily purge deletes expired rows (hook `voice.purge_expired` on the core backend's scheduler).
  Transcripts never appear in structured logs; logs carry ids, latencies, and counters only.
- **Raw audio is never stored** (ADR-0008): PCM frames exist only in the WS handler's memory;
  there is no audio ring buffer on disk, no audio field in any row, no audio in any log line.
  The "pull the plug" test: kill -9 the pod mid-turn → the student loses the current spoken turn,
  the transcript row for the half-turn is simply never written; nothing else is lost (RPO = one
  turn, RTO = reconnect).
- **Per-turn context window:** the brain sees the page snapshot (§7) + last ≤ 6 turns of text.
  Nothing older is loaded (latency + minimization; a child's history is not a profiling asset —
  DPDP posture from the systems-design constraints).

## 7. Anchoring — the tutor knows what is on screen

- **Snapshot in (ADR-0014):** the dock sends `context.snapshot` on block change (debounced 500 ms)
  and with `session.start`/turn start when stale (> 2 s). Proposed payload (reconcile with
  ADR-0014 wording at merge): `{ topic_id, class, chapter, block_id, block_type, sim_id?,
  sim_vars?, scroll_pct, lang_pref, ts }`. Stored in session state (memory), one per session.
- **Prompt context out (`anchoring.py`):** builds a bounded block: topic/chapter title, the text
  of the current block (≤ 600 chars), the sim's current variables (names + values only), the list
  of block ids on the page (for REF validation). The grounding law in the tutor prompt (Appendix
  A): the page context is the universe of the answer; NCERT-correct physics beyond it must be
  generic method, never new claims.
- **Highlights out (ADR-0012 + T7):** the brain's optional first line `REF: <block_id>[,<block_id>]`
  is parsed, validated against the snapshot's block list (unknown ids dropped), stripped from
  speech, and emitted as `highlight` **before or atomically with** the first `tts.audio` frame.
  Missing/garbled REF degrades to no-highlight (never an error, never spoken).

## 8. Credit guard — hook points for NEED-009 / ADR-0015

Credits meter the voice agent only. Units: Prisma audio-seconds, Timbre characters (including
audio-tag characters — tags bill as characters), brain tokens (Gemini API is billed outside Gnani
credits but logged per turn for cost observability). Daily tranche resets 00:00 IST; per-user cap
on top; `demo` profile = separate tranche + stricter per-session cap for demo-day/judge traffic
(`TIMELINE.md` Day-0 rule: reserve ~40% of programme credits for demo day).

| Hook | Site | Check | On breach |
|---|---|---|---|
| H1 | `ws_api` on `session.start` | remaining tranche (profile-aware) vs 0 | close with `error.over_credit` (profile normal) or auto-downgrade to `text_only` (profile demo: judge still gets text answers, never silence) |
| H2 | `ws_api` after `stt.final`, before brain call | estimated turn cost (STT seconds already spent + expected TTS chars ≤ per-turn estimate) vs remaining | reply with the fixed over-credit line (TTS, ≤ 15 chars of speech), state `error.over_credit`, end turn |
| H3 | `tts_client` before each outbound text chunk | per-turn TTS char cap (`ZIVON_VOICE_TTS_CHAR_CAP_TURN`, default 1200) and tag cap (≤ 1 tag / 2 sentences, ≤ 8/turn) | strip excess tags; truncate beyond cap with a fixed closing line — the cap is a harness guarantee, not prompt prose |
| H4 | `session` on `turn.end` | write `voice_turn.credit_cost` + decrement counters | — |

Config knobs (defaults are placeholders until OQ-06 pins the vendor unit): `ZIVON_VOICE_CREDIT_DAILY_TRANCHE`,
`ZIVON_VOICE_CREDIT_PER_USER_CAP`, `ZIVON_VOICE_CREDIT_DEMO_TRANCHE`, `ZIVON_VOICE_CREDIT_DEMO_SESSION_CAP`.
The guard reads only these; no credit logic anywhere else.

## 9. Failure modes — what the student sees (all states first)

| # | Failure | Detection | Student sees (dock) | `agent.state` | Recovery / degraded path | Credit impact |
|---|---|---|---|---|---|---|
| F1 | STT down / WS to Prisma fails | `stt_client` connect/reconnect error | text input enabled in dock ("type your doubt — voice is resting"), partials banner "voice input unavailable" | `error` → `listening_text` | text turn: same brain + TTS path, no STT | no STT spend; brain/TTS continue |
| F2 | Brain first-event deadline breached (3 s) ×2 | `brain_client` | "ho gaya restart" beat; then text-only answer in dock | `thinking` → `error` → `speaking_text` | text fallback with the answer prose (no TTS) | brain tokens logged; no TTS spend |
| F3 | Brain mid-turn inactivity (4 s) / wall-clock (45 s) | `brain_client` | partial answer already spoken stays; dock shows "answer cut short" + full partial text | `speaking` → `error` | no retry after speech started (§4); turn ends with partial + written remainder if any | per-usage |
| F4 | TTS down / Timbre errors | `tts_client` error before/while streaming | reply text appears in dock immediately (transcript panel), no audio | `speaking_text` | text-only mode for the turn; browser SpeechSynthesis is **not** used (product story = Gnani voice; flagged as founder's demo-day contingency decision, consistent with the no-replacement rule) | no TTS spend |
| F5 | WS drop mid-turn | `ws_api` disconnect | dock state `offline` ("connection thin thi — reconnecting…"), typed input kept client-side | `offline` | auto-reconnect (exp backoff ≤ 3 tries) → `session.start resume:true` with `session_token` + `last_turn_id`; server replays `agent.state` + continues or aborts turn honestly (F3 semantics) | per-usage (no double-bill: turn id idempotent in ledger) |
| F6 | Over-credit (H1/H2) | guard hook | over-credit line spoken/typed once; text-only mode for the rest of the day (normal profile) or session (demo profile) | `error.over_credit` | text turns keep working (brain only) until brain budget line also hit | stops voice spend |
| F7 | Page/context missing (stale page, no snapshot) | `anchoring` | tutor answers generically and says it cannot see the page ("page ka context nahi mil raha — page refresh karein") | normal | generic method answer, no page-specific claims (grounding law) | normal |
| F8 | Interrupt storm (barge-in spam) | > 3 `interrupt`s / 10 s | dock shows listening state; tutor waits quietly | `listening` | ignore further interrupts until next `audio.start` | no new spend |

Layer-independence rule (product law): with voice fully down, the page's core (read, simulate,
check) keeps working; the dock's text path is the only voice-adjacent fallback and it reuses the
same turn pipeline, so no parallel brain code exists.

## 10. WebSocket contract

Full message catalogue, client state machine, binary frame layout, ordering/idempotency/loss
semantics, barge-in + echo guard, and reconnection: [`ws-contract.md`](ws-contract.md).
Summary: control = JSON text frames; audio = binary frames with an 8-byte header (ADR-0020);
states = `idle/connecting/listening/thinking/speaking/speaking_text/error/offline`.

## 11. Auth (API-001)

Realtime endpoints consume the core backend's `session_token` (backend-spec §6.1/§7, API-001):
the first WS message MUST be `session.start` carrying `session_token`; the server validates via
the core backend's auth dependency before any component spins up. Invalid/expired → close 4401
with `error.auth`. Tokens never appear in URLs, query strings, or logs (they arrive inside the WS
session, after upgrade). Demo profile activation is a server-side flag on the session row, never
a client-asserted role.

## 12. Deployment mount and configuration

- **Mount:** `voice/ws_api.mount_voice(app)` is called by the core-backend FastAPI app at startup.
  The backend-spec §4.2 "voice-backend" Deployment + Service (k8s manifests 25–27, owned by the
  core-backend agent) is this image with the router mounted — **no separate Dockerfile and no k8s
  manifests are added for voice in P0**. If a split is ever forced (measured WS connection density
  vs CPU budget, revisit trigger in ADR-0020), manifest numbers 17–18 are reserved for it.
- **Config (env only, `ZIVON_VOICE_*` family per infra.env convention):** `ZIVON_VOICE_BRAIN_MODEL`
  (default `gemma-4-26b-a4b-it`), `ZIVON_VOICE_BRAIN_TRANSPORT` (`gemini-direct` | `openrouter`),
  `ZIVON_VOICE_STT_URL`, `ZIVON_VOICE_TTS_URL`, `ZIVON_VOICE_TTS_VOICE`, `ZIVON_VOICE_TTS_TAG_MAX_PER_TURN`,
  `ZIVON_VOICE_TTS_CHAR_CAP_TURN`, `ZIVON_VOICE_THINKING_SUMMARIES` (`on|off`), `ZIVON_VOICE_FILLER_SILENCE_MS`,
  `ZIVON_VOICE_BRAIN_INACTIVITY_S`, `ZIVON_VOICE_BRAIN_FIRST_EVENT_S`, `ZIVON_VOICE_BRAIN_TURN_DEADLINE_S`,
  `ZIVON_VOICE_CREDIT_*` (§8). Secrets (`GEMINI_API_KEY`, `GNANI_API_KEY`) are K8s Secrets, runtime
  env only — never in code, manifests, or workflows; CI stays key-free.
- **infra.env line-edits** (owner: core-backend agent; S1 proposes names only, matching the
  `ZIVON_*` family rule): the two `ZIVON_VOICE_*` lines that must render into the voice-backend
  ConfigMap. No image tags in infra.env (existing rule).

## 13. Test strategy (build-ready)

Layout mirrors the repo: `testing/voice/` (unit, mocked components — no network anywhere in CI):

| Test file | Asserts |
|---|---|
| `testing/voice/test_chunker.py` | sentence boundaries incl. `।`/`?`/`!` + Latin-script Hinglish; no split inside numbers/units/tags; max-chars + 250 ms flush deadline; markdown/LaTeX stripped; first-chunk fast path |
| `testing/voice/test_brain_client.py` | mock SSE: inactivity 4 s fires; first-event 3 s deadline fires; wall-clock 45 s closes mid-stream; 2 retries then degrade; mid-stream abort on barge-in closes upstream; REF-line parse + unknown-id drop; usage capture |
| `testing/voice/test_stt_client.py` | mock WS: partial/final mapping, reconnect with resume, code-mixed text passthrough, echo-guard window (§F8/OQ-07) |
| `testing/voice/test_tts_client.py` | mock Timbre: tag whitelist (13 v3 tags → allowed subset), tag caps (H3), char cap + closing line, audio header codec round-trip, char meter |
| `testing/voice/test_session.py` | `voice_turn` rows written; 7-day TTL purge deletes only expired; credit H1–H4 paths incl. demo profile; no raw-audio field anywhere (schema assertion) |
| `testing/voice/test_anchoring.py` | snapshot → bounded prompt context (≤ 600 chars); debounced staleness; highlight unknown-id drop; missing-snapshot F7 path |
| `testing/voice/test_ws_api.py` | full state machine incl. every F1–F8 row of §9 (mocked components scripted to fail); T12 classifier fixtures (procedural passes, substantive dropped from speech); auth 4401 |
| `testing/voice/test_latency_budget.py` | parses `docs/specs/voice-agent/latency-budget.csv`; asserts P0 warm-path sum ≤ 4000 ms, every row has an owner + measure method, hands-free row substitution keeps the sum ≤ 4000 |

Mocks live at the module seams (`MockPrisma`, `MockBrain`, `MockTimbre` fixtures under
`testing/voice/mocks/`) so EX1 can run the whole suite key-free, exactly like the factory's
mock-inference-server tests. Latency instrumentation: `turn.end.latency_ms` carries per-hop deltas
(L0–L8 ids of `latency-budget.md`) so live runs map 1:1 onto the budget table.

## 14. Build checklist for EX1-VOICE (the order that de-risks Gate C)

1. Probe the three live contracts with 20-line scripts, record results as amendments:
   Prisma streaming shape (OQ-02), Timbre realtime + voice pick (OQ-03), Gemma thought-summary
   streaming + first-token timing on both transports (OQ-04/OQ-05). Pin the measured numbers into
   `latency-budget.md` rows (replace [ASSUMPTION] tags).
2. `voice/chunker.py` + `test_chunker.py` first (pure, no network) — the chunker is the Gate C keystone.
3. `voice/brain_client.py` against the real Gemini API with the Appendix A prompt; measure
   first-event latency distribution (n ≥ 20 turns).
4. `voice/tts_client.py` + `stt_client.py` behind their mocks; then a CLI loop (TIMELINE Day-5
   pattern) before any browser work.
5. `voice/ws_api.py` + state machine + failure modes; dock integration against `ws-contract.md`
   with EX5-FRONT; Gate C rehearsal on low-end Android (OQ-07 device matrix).
6. Credit hooks H1–H4 last (they wrap, not block, the loop).

---

## Appendix A — tutor system prompt (draft, follows skills/prompting-and-agent-design)

```
You are Zivon, a patient Physics tutor for a Class 9–12 student in India, speaking out loud.
The student hears you; they may be reading the page you are anchored to.

Goal: the student leaves this turn able to explain the idea in their own words — clear,
encouraging, step-by-step, in the student's language (Hindi, English, or the mix they used).

The page context below is the universe of this answer: teach from what is on the page. If a step
needs physics beyond the page, use generic method ("energy is conserved") and say the page will
cover it — never introduce a new claim or number you cannot see verified. If you are not sure a
step is right, say what you are checking instead of asserting it.

Spoken contract (the harness enforces parts of this mechanically):
- First line, only if you refer to page elements: `REF: <block_id>,<block_id>` using ids from the
  context's block list. Never put REF anywhere else; never mention it.
- Plain spoken words: no markdown, no LaTeX, no code blocks. Say formulas in words and numbers
  as digits ("x squared plus one", "3.06 metre per second squared").
- Short sentences — one idea each, ≤ ~15 words. Prefer 4–8 sentences per turn; end with ONE short
  Socratic follow-up question when the student is close to a step, not every turn.
- Where delivery helps, use at most these cues inline: <pauses> <slow> <excited> <whispers>.
  Nothing else; at most one cue per two sentences.
Match the student's language mix; keep proper nouns and technical terms in English.
```

Prompt notes (why it is shaped this way): goal-first, one grounding law with motivation instead
of scattered prohibitions, contract items the harness re-validates kept short, no thinking
micromanagement and no token caps (repo law), examples omitted deliberately — the SHAPE lever that
matters here is the REF line and the tag list, both stated as contracts. If live transcripts show
a recurring violation class, fix it with a harness check + feedback per the authoring loop, not
by adding adjectives.

## Appendix B — proposed data shapes (reconcile with S0 wording at merge)

`voice_turn` (extends the A-02 transcript decision; exact DDL belongs to the DB spec owner):

| column | type | notes |
|---|---|---|
| id | uuid PK | |
| session_id | uuid FK → sessions (ADR-0002) | |
| turn_idx | int | monotonic per session; idempotency key with session_id |
| role | enum(student, tutor, event) | event rows record F1–F8 incidents, never audio |
| text | text | transcript text only |
| lang | varchar | detected mix tag e.g. `hi-en` |
| stt_confidence | real? | nullable |
| block_ids_ref | jsonb | validated REF targets (may be []) |
| latency_ms | jsonb | `{ "L0": …, "L1": … }` per-hop deltas |
| usage_json | jsonb | `{ stt_audio_s, tts_chars, brain_prompt_tokens, brain_completion_tokens, thinking_tokens?, retries }` |
| credit_cost | numeric | vendor-unit cost (OQ-06) |
| profile | enum(normal, demo) | |
| created_at | timestamptz | TTL 7 days (A-02) — purged by `voice.purge_expired` |

Context snapshot (client→server, ADR-0014): see §7. Audio frame header (ADR-0020): see
`ws-contract.md` §3.
