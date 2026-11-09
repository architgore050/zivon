# Backend handoff — Zivon product → systems-design stage (Stage 2)

Source of truth: `docs/product/features.md` (feature cards) + the three inventories +
`traceability-matrix.csv` in this folder. This file is the Stage-2 input: capability,
entity, realtime, event, volume, retention, schema, and doc-change needs. It states
*what* the product needs, not *how* to build it.

**ADR flags carried from the tension decisions** (Stage 2 must record these as
architecture decision records): T2 per-string language data model · T3 PTT WebSocket
message contract · T5 data model must preclude child profiling by default · T6
anonymous device-scoped identity with nullable `guardian_ref` · T7 tutor→page message
types (highlight/scroll only in P1) · T8 build-time reviewed translation pipeline ·
T11 voice-pipeline audio buffer lifecycle (never persisted) · T12 context payload +
provenance message design.

## 1. Capability needs (NEED-001…018)

| ID | Purpose | Caller | Request → response (shape) | Latency target | Freshness | Auth / consent | UI on failure |
|---|---|---|---|---|---|---|---|
| NEED-001 | Static delivery of shell + generated pages (exists: nginx image + `zivon-frontend` PVC) | browser | GET page/asset → HTML/JS/JSON/CSS | page load < 2 s weak-android (existing gate) | per generation/publish | none (public) | host 404 page; offline chip |
| NEED-002 | Course catalogue (exists: `courses.js`, never hand-edited) | browser (hub) | GET `courses.js` → `[{course_id, class, title, chapter, generated_at, path}]` | static | per publish | none | hub empty state |
| NEED-003 | Session bootstrap + feature flags | browser (lesson page) | POST `/session` `{device_pseudo_id, lang, consent_state}` → `{session_id (pseudonymous), flags: voice_enabled \| typed_only \| voice_off, consent_required}` | < 300 ms | per page visit | consent state read here | dock system-error copy; Core intact |
| NEED-004 | Voice conversation channel (the core new build) | browser dock | WSS `/voice` — full contract §3 | Gate C: end-of-speech → first audio < 4 s p90 | live | session_id + consent required | full dock failure machine (F-ADD-VOI-01/03) |
| NEED-005 | Page-context payload composition into the LLM prompt | browser → backend (inside NEED-004) | `{page_id, visible_blocks:[{id,type,title}], sim_states:[{block_id, controls:{id:value}, state_text}], last_check:{block_id, correct, option_index}, coverage_summary, lang}` ≤ 4 KB | per turn | per turn | inside voice consent | generic answer + visible "I can't see…" note (never fake anchoring) |
| NEED-006 | Prisma STT (streaming, code-mix) — **verified 2026-11-07**: v2.5 and v3.0 both cover 10 languages (bn/en/gu/hi/kn/ml/mr/pa/ta/te, `*-IN`; en-IN accepts EN-HI mixed audio); v2.5 requires per-request language choice; v3.0 adds `indic-auto` auto-detection (`detected_language_code`). Model version: **founder decision 2026-11-07 — Prisma v3.0 adopted** (`indic-auto` is the STT language mechanism; `detected_language_code` feeds the mirroring rule) | voice backend → Gnani API | audio frames → `{partials[], final, confidence, language_detected}` | final ≤ 1.5 s after end-of-speech | live | Gnani key server-side only | no-match state → re-ask path |
| NEED-007 | Tutor turn generation — **Gemma 4 26B A4B cloud-hosted via Google Gemini API (Gate A outcome 2026-11-07, founder decision, 2026-11-09 cloud confirmation; Evon v3.3 post-challenge aspiration)** — `voice/brain_client.py` streaming client (ADR-0017) | voice backend | `{persona, anchor payload (NEED-005), coverage summary, history window (last N turns), mode: guide\|tell, lang}` → streamed text, optional Timbre tags | first token < 1.2 s; reply ≤ 3 sentences default | per turn | server-side | system-error + retry preserves context |
| NEED-008 | Timbre TTS streaming — **verified 2026-11-07**: v2.5 = 42 voices, one preferred language each (incl. Hinglish voice Poorvi `hi-en`), **no audio tags (stripped before synthesis)**; v3.0 = 13 voices each covering all 10 languages + 13 expressive tags (`<whispers> <excited> <pauses>` …; tags billable as characters; unknown tags stripped silently). Model version: **founder decision 2026-11-07 — Timbre v3.0 adopted** (tags available; harness strips unknown tags; tags billable as characters; voice choice from the 13-voice polyglot catalog — pick a Warm-empathetic or Expressive persona for the tutor) | voice backend | `{text+tags, lang, voice_id, pace}` → audio chunks | first audio byte < 800 ms after text stream starts | per utterance | Gnani key server-side | text floor: transcript shown, audio skipped |
| NEED-009 | Credit metering + budget guard — **founder config 2026-11-07, corrected same day (Stage-2 session)**: global daily tranche **1,000 credits** + **per-user daily cap 30 credits** (free-trial scale; corrected from the earlier 200 [ASSUMPTION — calibrate after first real voice sessions]; keyed on pseudonymous device id) + **togglable guard profile**: `normal` ↔ `demo` (relaxed, still bounded caps for demo-day judge traffic; admin mode flag, logged). **Credits meter ONLY the voice agent** (Prisma STT + tutor Timbre TTS); pre-generated course narration is a build-time budget, never per-student metering | voice backend (meter at NEED-006/008 call points); admin queries | counters `{model, units, amount, bucket}` + per-user daily totals; state push to sessions: `ok \| warn \| exhausted \| reserved_mode` | counting adds < 5 ms per call; flag push ≤ 5 s | live | admin for queries + profile toggle | warn notice before sessions; exhausted → typed_only (per-user exhaustion → that user only); **never cut an in-progress turn** |
| NEED-010 | Telemetry ingestion (schema-validated, pseudonymous) | browser (batched) + voice backend | POST `/events` `{events:[{evt_id, session_id, page_id, block_id, props…}]}` ≤ 20 events / ≤ 5 s | async, < 50 ms added to interaction path | batched | consent-gated catalogue (§4) | client local queue ≤ 200, retry backoff, drop-oldest |
| NEED-011 | Session coverage store (memory) | browser at turn boundaries; backend reads for prompt assembly | PUT `/session/coverage` `{covered:[{block_id, type, status}]}` | < 300 ms | per session, TTL 24 h idle | consent-gated server sync (local-first without) | local continues; "syncing later" |
| NEED-012 | Consent record store | browser overlay; backend reads at bootstrap | PUT `/consent` `{device_pseudo_id, consent_version, guardian_flag, ts}` → `{ok}` | < 300 ms | per consent event | — | voice stays off; retry |
| NEED-013 | Data deletion endpoint (right-to-erasure path) | privacy page clear action | DELETE `/data` scope `{device_pseudo_id}` → `{deleted: {sessions, consents, events}}` | best-effort immediate; DPDP 90-day response posture post-challenge | on demand | identity = device_pseudo_id + confirm | error copy + ops alert |
| NEED-014 | Problem-report submission | browser report form | POST `/reports` `{page_id, block_id, category enum, text?}` → `{report_id}` — no PII fields accepted | < 1 s | on demand | none (pseudonymous) | draft kept + "could not send" copy |
| NEED-015 | Admin data + trigger API (wraps the three sanctioned scripts; parity-tested) | dashboard | GET aggregates (sessions, usage/credits, engagement, run status, reports); POST actions `run-tests`, `generate-topic {chapter, class}`, `watch-run {run_id}` | panels ≤ 5 min lag; actions async | ≤ 5 min | admin auth (cluster-side); no student-facing accounts | per-panel error rows; 403 gate |
| NEED-016 | Language bundle delivery (static, factory-generated; no runtime translation) | browser on first language switch | GET `/bundles/{course_id}.{lang}.json` → `{strings keyed by block_id+field, mt_flag, reviewed_flag, version}` | < 200 ms after first switch (lazy + SW cache) | per generation | none | stay current language + "couldn't load" chip |
| NEED-017 | Block read-aloud narration — **founder direction 2026-11-07 (Stage-2 session): pre-generated at build time and stored (DB asset row + audio object), served statically** — C-051 adopted; Timbre credits burn once at generation, never per student | browser read-aloud button | GET static asset `/audio/{course_id}/{block_id}.{lang}.{content-hash}.opus` (factory/publish-time generation via Timbre v3.0; DB row = asset catalogue entry) | first audio byte < 1.5 s p90 (static delivery, no runtime TTS call) | per generation/publish | none (public static) | INF-089 disabled copy when the asset is absent; text fully usable |
| NEED-018 | Settings persistence | browser settings sheet | **client localStorage primary — no server endpoint in P0/P1**; server mirror is post-challenge only | n/a | per device | none | defaults always safe |

## 2. Entity needs (ENT? — proposed, Stage 2 finalizes)

| Entity | Fields (name: type, nullability) | Source info (INF) | Notes |
|---|---|---|---|
| ENT?-Session | session_id: pseudonymous token, req · device_pseudo_id: req · created_at: ts, req · lang: enum, req · consent_ref: →ConsentRecord, **nullable until consent** · flags: {voice_enabled, typed_only} · coverage: list, TTL 24 h · credit_counters · **guardian_ref: nullable by design (T6)** | INF-069 | server record for telemetry/coverage/guard flags; no name, no contact, no device fingerprint beyond pseudo id |
| ENT?-VoiceTurn | turn_seq: int, req · modality: voice\|typed, req · transcript: text, nullable, **log TTL 7 d** · tutor_text: text, req · tags: list (validated set), default [] · anchor: {block_ids[], sim_values{}}, nullable · latency: {eos_ms, stt_final_ms, llm_first_token_ms, tts_first_byte_ms}, req · redirect_flag: bool · mode: guide\|tell · **audio_retained: false — always** | INF-060, 061, 064 | the Gate-C measurement row; free text lives only in ephemeral logs (T11) |
| ENT?-ConsentRecord | device_pseudo_id: req · consent_version: string, req · guardian_flag: bool, req · ts: req · source: overlay\|imported | INF-072…076 | append-only versions; deletable via NEED-013 |
| ENT?-DeviceProfile | device_pseudo_id: req · lang · settings {pace, depth, data_saver} · onboarding_flags · memory_local | INF-077…083 | **client-local primary**; server mirror post-challenge only; precludes profiling fields (T5) |
| ENT?-CreditLedger | model: prisma\|timbre\|evon_gpu, req · units: seconds\|chars\|tokens, req · amount: num, req · bucket: daily\|reserved, req · ts: req | INF-097, 098 | counts only, never content; daily reconciliation vs Gnani dashboard ≤ 2 % drift |
| ENT?-TelemetryEvent | evt_id: enum(18), req · session_id: req · page_id · block_id · props: schema-typed per EVT, req · ts: req | §4 catalogue | schema validation in CI rejects free-text fields |
| ENT?-ProblemReport | report_id: req · page_id: req · block_id · category: enum(4), req · text: nullable (child-safe flagged) · status: open\|fixed\|shipped-next-run · ts: req | INF-104, 105 | no PII fields accepted at the endpoint |
| ENT?-PageMeta | course_id: req · class: int, req · title: req · chapter · generated_at: req · sources[]: req ≥1 · block_counts · translation_flags (post SC-01) · citations exposure (post SC-05) | INF-005, 006, 009…011, 051, 052 | extends the existing `manifest.json` — do not redesign what exists |
| ENT?-RunStatus | run_id: req · topic · class · stage · verdict · stage_durations · ts | INF-100, 101 | read-only view of `runs/` evidence (`status.json`, `run_report.json`) — already produced by the factory |
| ENT?-LanguageBundle | page_id: req · lang: enum (Gnani 10-language set per T2 revision 2026-11-07; demo subset en/hi/hinglish), req · strings: map block_id+field → text, req · mt_flag: bool · reviewed_flag: bool · version: req | INF-014…017, 049, 088 | produced by factory translation stage (SC-01); immutable per page version |

## 3. Realtime needs — voice channel contract (NEED-004)

**Channel.** WSS `/voice`, opened after bootstrap (NEED-003) and consent (F-XCT-CON-01);
one channel per lesson-page visit; closes on navigation. Auth: short-lived session token.
Mic opens only between `ptt.start` and endpointing (battery + privacy).

**Message types** (turn_seq monotonic per session):

| Dir | Type | Payload | Semantics |
|---|---|---|---|
| up | `ptt.start` | {turn_seq} | begin listening; dock → listening (earcon) |
| up | `audio.frame` | {seq, opus 16 kHz mono, ≤ 20 ms} | only while listening; **buffered transiently, never persisted (T11)** |
| up | `context.snapshot` | NEED-005 payload | sent with each turn start |
| up | `ptt.stop` | {turn_seq} | user ends speech (server endpointing may fire first) |
| up | `typed.doubt` | {turn_seq, text} | typed path — same pipeline minus STT; works when STT/TTS down |
| up | `interrupt` | {turn_seq} | barge-in (dock tap or detected user speech); server stops TTS ≤ 300 ms, flushes queue |
| down | `stt.partial` | {text, confidence} | only if user opted into live partials (EL-LES-01-048) |
| down | `stt.final` | {text, confidence, language_detected} | low confidence → `no-match` error event instead of showing garbled text |
| down | `tutor.text.delta` | {chunk} | streamed reply text; may precede audio (Gate-C enabler) |
| down | `tts.chunk` | {seq, audio} | Timbre chunks; unknown tags already stripped server-side |
| down | `tts.done` | {seq} | utterance complete |
| down | `turn.cancelled` | {turn_seq} | interrupt acknowledged |
| down | `turn.meta` | {latency stages} | EVT-006 source; also drives dock "thinking" cue ≤ 300 ms |
| down | `state` | {voice_enabled \| typed_only \| voice_off, reason} | guard-state push mid-session (NEED-009); in-progress turn always completes |

**Ordering / backpressure.** Server ignores `audio.frame` after `stt.final` for a turn.
Client buffers ≤ 2 s of down-audio; overflow → drop chunks, show transcript (text floor).
Client up-buffer > 1 s → stop mic, system-error state with retry (context preserved).
Echo path (tutor speaker → mic) must be handled — Stage 2 chooses client ducking vs
server-side gate; device-tested before Gate C rehearsal.

**Degraded rungs.** STT down → typed path only. LLM down → system-error + retry. TTS
down → text floor (transcript + captions). Guard exhausted → `typed_only` state.
Offline → channel closed, dock disabled with reason.

## 4. Event catalogue (EVT-001…018 — capped; tied to metrics M1–M7)

| ID | Event | Trigger | Properties | Privacy class |
|---|---|---|---|---|
| EVT-001 | page_view | lesson page load | page_id, lang | pseudonymous aggregate |
| EVT-002 | block_interaction | block focus/first interaction | block_id, type, duration bucket | pseudonymous |
| EVT-003 | sim_interaction | control change | block_id, control_id, value-range bucket, count | pseudonymous |
| EVT-004 | check_attempt | Check pressed | block_id, format, correct bool, attempt_n, option_index | pseudonymous (no free text) |
| EVT-005 | voice_turn | turn complete/abandoned | modality, anchor_source, intent bucket, language_detected, turns count | pseudonymous — **transcript text never in EVT** |
| EVT-006 | voice_latency | per turn | eos_ms, stt_final_ms, llm_first_token_ms, tts_first_byte_ms | operational |
| EVT-007 | credit_usage | per session end | stt_seconds, tts_chars, llm_tokens | operational |
| EVT-008 | budget_state | guard transitions | from, to | operational |
| EVT-009 | error | component error caught | component, error_class (never message/free text) | operational |
| EVT-010 | voice_abandon | dock closed during failure states | state at abandon, failure_count | pseudonymous |
| EVT-011 | language_switch | bar/settings change | from, to | pseudonymous |
| EVT-012 | tts_play | read-aloud complete/skip | block_id, lang, completed bool | pseudonymous |
| EVT-013 | consent_event | overlay shown / acked / declined / identity line shown | outcome | **child-data flagged; minimal fields** |
| EVT-014 | report_submitted | report sent | page_id, block_id, category | pseudonymous (text goes to report store, not EVT) |
| EVT-015 | settings_change | any setting change | key, from, to | pseudonymous |
| EVT-016 | offline_state | connectivity lost/restored | duration bucket | operational |
| EVT-017 | hub_view / topic_open | hub load / card tap | course_id | pseudonymous |
| EVT-018 | memory_cleared | clear action completed | outcome only (no content) | pseudonymous |

Consent gate: pre-consent only EVT-001, 016, 017 (aggregate-safe, flagged for legal
review). Post-consent: full catalogue. No event carries raw child free text, ever.

## 5. Volume hints

- Lesson page today: ~150–400 KB total (perf-gate measured); hub < 50 KB; language
  bundle 10–30 KB per page-language; dock JS ≤ 60 KB lazy-loaded on first mic tap.
- Voice turn: up audio 2–10 s speech ≈ 4–20 KB Opus; context ≤ 4 KB; reply ≤ 600 chars;
  TTS audio 10–30 s ≈ 30–90 KB → **< 150 KB per turn total**.
- Read-aloud paragraph: 30–90 s audio ≈ 90–270 KB, **pre-generated per block+lang+version** (founder direction 2026-11-07, C-051 adopted), stored as DB asset row + audio object, served statically.
- Credit model per 20-turn session: ≈ 5 min Prisma + ≈ 10 000 Timbre chars (calibrate
  against Gnani dashboard daily, ≤ 2 % drift).
- Expected traffic (challenge window): ≤ 500 sessions/day, ≤ 10 concurrent voice
  sessions (Stage 2 sizes the backend to this, not beyond).
- Events: ≤ 30 per session; batches ≤ 20 events / ≤ 5 s; local queue ≤ 200.

## 6. Retention & consent hints

| Information class | Retention we want | Why | Consent basis |
|---|---|---|---|
| Raw audio | **never — transient buffer only (T11)** | child privacy; DPDP minimization | n/a |
| Transcripts (student + tutor text) | server logs TTL 7 d, child-data flagged | debugging + M3 rubric sampling | voice consent |
| Session coverage memory | TTL 24 h idle; clearable on demand | J5 without profiling | local-first; server sync consent-gated |
| Consent records | until deletion request | legal basis | self |
| Device profile / settings | local until cleared | continuity without accounts | n/a (local) |
| Telemetry events | 90 d aggregates | engagement tuning (M4/M6) | consent-gated catalogue |
| Credit ledger | 90 d | cost control (M7) | n/a (no content) |
| Problem reports | until resolved + 90 d | correctness loop (T12) | none required; text child-safe flagged |
| Run evidence (`runs/`) | repo rule (PVC + git rotation) | factory audit | n/a |
| Pre-generated narration audio | forever per version (immutable asset) | build-time TTS output; regenerable but credit-costly — cold origin copy | n/a (no student data involved) |

Consent gates the ADD layer only: voice input, transcripts, coverage server sync.
Reading, simulating, checking, reporting work without consent (pseudonymous aggregates
only). Self-declared guardian confirmation is **not** verifiable parental consent —
flagged for counsel before any scale-up (C-087; DPDP children's-data provisions in
force 13 May 2027 per the G.S.R. 843(E) commencement batch — verified 2026-11-07 via
secondary sources, counsel still required).

## 7. Content-factory / schema change proposals

| ID | Change | Needed by | Build cost | Priority |
|---|---|---|---|---|
| SC-01 | Per-language string sets per block (body, diagram labels, sim labels, check strings, feedback) + mt_flag/reviewed_flag + glossary-controlled glosses — **separate second-layer pipeline** (founder-confirmed 2026-11-07; factory produces English natively), scales to the full Gnani language set | F-WRP-LAN-01 (T8) | new factory translation stage + per-language reviewer gate + bundle storage | P1 |
| SC-02 | Sim controls gain `unit`, `readout_format`, `state_text_template` | F-COR-SIM-01 mirror; tutor/TTS reading sim state honestly | small: prompt + schema + renderer template | P0-quality (ship with next runs) |
| SC-03 | `option_feedback[]` per check option (misconception-targeted) | F-COR-CHK-01 P1 slice | moderate: prompt + reviewer burden + schema | P1 |
| SC-04 | Optional `prediction_prompt` on sims | deferred C-023 (tutor-delivered first) | small | P2 |
| SC-05 | Per-block `citations` exposure in manifest/page | provenance surfaces (T12; dock chips first, page chips C-029) | small | P1 |
| SC-06 | Per-block `spoken_form` (narration text ≠ on-screen text; unit pronunciation) | F-WRP-TTS-01 quality; pre-generated audio (C-051) later | moderate | P2 |
| SC-07 | `draggable` control type + WCAG 2.5.7 keyboard/single-pointer alternative requirement | F-COR-SIM-01 P1 (C-021), F-XCT-A11Y-01 | factory sim-code guidance + reviewer checklist item | P1 |

Also proposed (not schema): axe-core scan added to the factory Code Reviewer gate /
perf-gate test set (F-XCT-A11Y-01 AC-1).

## 8. Doc Change Proposals

- **DCR-001** (from T4): `docs/frontend/design-doctrine.md` §10 gains a Devanagari
  rendering verification clause — zero tofu at 360 px, ruled-line rhythm holds under
  Hindi strings, canvas `fillText` font stack pinned to the §10.3 fallback chain;
  perf-gate extension test. Owner: doctrine owner (founder).
  **Status 2026-11-07: deferred by founder** — the clause + fix land with the
  translation-engine build; founder's direction: per-script / per-text-size vertical
  text offset to align glyphs with the ruled lines (or another technical fix chosen
  at build time). Revisit trigger: translation-engine build start.
- **DCR-002**: `docs/frontend/design-doctrine.md` gains §10.12 "Voice dock" — the dock
  as a paper-card lesson-page component: state visuals per dock state, earcon policy
  (≤ 3 non-speech sounds), chip styling, lazy-load rule, focus order after block text.
  Owner: doctrine owner (founder).
  **Status 2026-11-07: adopted by founder** — the founder authors §10.12 manually;
  product docs reference it as the dock's design home. **Agent guard:** if the doctrine
  does not yet explicitly contain the voice dock directive, inform the founder and halt
  frontend work on the dock UI (standing note in AGENTS.md).
