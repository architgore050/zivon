# Backend, API and realtime contract method

## 1. From NEEDs to endpoints
For each `NEED-…`: decide transport (HTTP request/response, server-sent updates, WebSocket stream), resource or action name, auth/consent requirement, idempotency, caching, and error model. Group into **resource families** and check coverage against this non-binding list (add/remove by need):
content delivery (lesson bundle by topic·class·locale·version, manifest, narration asset index) · localization (UI strings, glossary, fallback info) · sessions & profile (create/resume, preferences, memory view/reset) · voice realtime (stream) · text-tutor fallback · feedback/report problem · consent & guardian (status, grant, withdraw, export, delete) · events ingestion (batched, offline-tolerant) · health/version · admin/ops (release status, credit meter, run status; separately authenticated).

## 2. Endpoint card (template `templates/api-endpoint-card.md`)
Name, purpose, **serves NEED ids / consumed by EL ids**, method+path, auth + consent scope, request schema, response schema, status codes and error shapes, idempotency, caching (ETag/immutable), rate limit, p95 latency target, data touched (entities/classes), events emitted, credit cost, failure behaviour visible to the UI, version.

## 3. REST conventions to apply (details in vendored `api-designer`)
Nouns for resources, verbs only for true actions; stable versioning strategy stated; consistent pagination; **problem-details error body** (machine code + human message key for i18n + trace id, never raw model/stack text); conditional requests; **long-lived immutable caching** for content-addressed bundles and narration audio (`Cache-Control: immutable`, hash in path); idempotency keys for POSTs that cost credits or write ledgers; OpenAPI as the single source of truth, used to generate frontend types; deprecation policy. Errors must include a user-facing message **key**, not English prose, so translation works.

## 4. Realtime voice loop

### 4.1 Pipeline (from `AGENTS.md`)
mic → streaming STT (Prisma) → reasoning (Evon or Gate-A fallback) with page-context anchoring → streaming TTS (Timbre, expressive tags) → client playback. Keep modules separable: audio/session management · Gnani API clients · LLM prompting incl. tag emission · tutor personality and Physics logic · page-context anchoring · usage/session logging.

### 4.2 Latency budget (starter, `[ASSUMPTION]` - replace with measurements)
| Stage | Budget (ms) | Lever |
|---|---|---|
| Capture + client VAD/endpointing | 300-500 | tune silence window; push-to-talk removes it |
| Network up (audio chunks stream continuously) | overlap | small chunks (20-60 ms), keep-alive WS |
| STT final result after end-of-speech | 300-600 | stream partials; ask STT for fast finalization |
| LLM time-to-first-token | 500-1200 | pre-warm, short prompts, cached page context |
| First speakable sentence boundary | 300-500 | prompt for short first sentence; chunk by punctuation |
| TTS time-to-first-byte | 300-600 | stream; reuse connection; avoid cold start |
| Network down + playback start | 100-300 | small first chunk, decode ahead |
| **Total target** | **≤ ~3-4 s** | per-stage histograms identify the long pole |
Overlap stages (pipeline, don't serialize): start LLM on stable partial transcripts only if accuracy allows; start TTS on the first sentence while the LLM continues.

### 4.3 WebSocket protocol (catalogue template `templates/ws-message-catalog.md`)
Envelope: `{v, type, id, seq, ts, session_id, payload}`; binary frames for audio with a small header (codec, rate, seq). Define for **each message**: direction, schema, ordering guarantees, idempotency, what happens on loss, and whether it is billable.
Client→server (examples): `session.start` (device, locale, anchor, capabilities), `context.update` (current block, sim values, last check result), `audio.chunk`, `audio.end`, `text.input`, `interrupt`, `session.end`, `ping`.
Server→client (examples): `state` (listening/thinking/speaking), `stt.partial`, `stt.final`, `tutor.text.delta`, `tutor.audio.chunk`, `tutor.audio.end`, `ui.hint` (highlight block/sim control - only if product permits), `usage` (remaining budget), `error` (code + message key + retry-ability), `session.resume.token`.
Rules: barge-in = `interrupt` stops server generation and TTS immediately and flushes buffered audio; sequence numbers allow dedupe and resume after reconnect within a short window; **backpressure** (bounded queues; drop partials, never final messages); max message sizes; heartbeat/idle timeout; auth at connect and re-validated at resume; origin checks; per-session and per-IP rate limits; graceful fallback to text-only on audio failure.

### 4.4 Credit metering and budgets
Meter every billable unit (STT seconds, TTS characters, LLM tokens) at the point of use; enforce budgets *before* a turn starts (cheap read of `budget`) and *during* long turns; show remaining allowance honestly; degrade in steps (shorter replies → text-only → read-only) rather than a hard wall; global reserve (~40 %) for demo/judge traffic is an enforced budget, not a note. Log usage daily (repo rule).

### 4.5 Safety and quality hooks on the server
Input/output moderation appropriate for minors; anchor-grounded answering (include page block ids as citations); refusal/redirect templates; prompt-injection hygiene for any page or transcript text fed to the model (treat as data, not instructions); log prompts/responses without PII per policy; a "report this answer" endpoint feeding review.

## 5. Content delivery path
Static, immutable, cacheable, independent of the voice stack. Serve from the frontend volume/nginx (repo) with a CDN/edge cache in front when needed; content-addressed paths; manifest per (topic, class, locale) giving block list, asset hashes, narration availability, and `version`. A client with a stale manifest must still work. Lesson JS is generated code: apply a strict CSP (no inline eval, no third-party hosts) consistent with the Code Reviewer's rules.

## 6. Deliverable structure for the backend spec
1. Scope, assumptions, phase plan, glossary (SSD, cold, SoR…). 2. Architecture overview + diagram (Mermaid) + module boundaries. 3. NFR table. 4. Data classification & tier table (`02`). 5. Sync/eviction/restore policy table. 6. API catalogue (cards) with NEED traceability. 7. WebSocket catalogue. 8. Auth, consent, rate limits, budgets. 9. Failure-mode table. 10. Security/privacy design. 11. Observability and SLOs. 12. Deployment topology (K8s objects, volumes, secrets - consistent with `docs/deployment/`). 13. Capacity & cost model. 14. ADR index. 15. Open questions. 16. Traceability: NEED ↔ endpoint ↔ entity ↔ class ↔ EVT.
