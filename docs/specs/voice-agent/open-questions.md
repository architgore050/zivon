# Open Questions — voice agent spec

Statuses: **resolved** (answer recorded here; doc owners flagged), **open** (needs a build-time
measurement or an owner decision; each carries a resolution vehicle and a deadline).

Evidence tags: `[STRONG] / [MODERATE] / [WEAK] / [ASSUMPTION]` per the design-doctrine convention.
Perishable facts were checked on 2026-11-09; re-verify at build time.

---

## OQ-00 (process) — S0 branch cross-references [resolved for S1, verify at merge]

The named base branch `feature/backend-db-storage-spec` (post-S0 tip) was **not reachable** from
`origin` at spec time (2026-11-09: `git ls-remote` lists only `main`, `prod`, two feature branches,
six dependabot branches). `docs/backend/backend-spec.md`, `docs/backend/adr/0001–0016`,
`docs/product/features.md`, `docs/product/backend-handoff.md` and `docs/product/decision-log.csv`
were therefore not readable when this spec was written.

- **What S1 did:** every S0-owned contract is cited **by ID only, exactly as the mission brief
  quotes it** (ADR-0002/0003/0008/0010/0012/0014/0015, A-02, A-09, A-11, NEED-009, T7, T12,
  DCR-002, API-001, §4.2, §4.3, manifests 25–27). S1 did not restate, renumber, or re-decide any
  of them. The few places this spec needed a concrete payload shape of its own (e.g. the
  context-snapshot JSON) are marked "proposed payload — reconcile with ADR-0014 wording".
- **What the merge agent must do:** diff this spec against the real `docs/backend/` +
  `docs/product/` and resolve any ID/wording drift before EX1 starts; the reconciliation table
  below lists every cross-reference to check.
- **Cross-reference checklist (verify each resolves on the S0 tip):**

| ID cited here | Claimed here as | Where cited |
|---|---|---|
| ADR-0002 | session store owns session state | spec.md §6 |
| ADR-0003 | raw WebSocket (no media server) is the transport decision | ADR-0020, ws-contract.md header |
| ADR-0008 | raw audio is never persisted | spec.md §6, failure modes |
| ADR-0010 | PTT contract + echo path; barge-in semantics | spec.md §2/§8, ws-contract.md §4 |
| ADR-0012 | tutor→page messaging; T7 "highlight first" | spec.md §7, ws-contract.md §3 |
| ADR-0014 | context snapshot payload page→tutor | spec.md §7, ws-contract.md §2 |
| ADR-0015 | credit guard design (NEED-009) | spec.md §8 |
| A-02 | voice transcripts 7-day TTL, never in structured logs | spec.md §6 |
| A-09 | warm brain, first token < 1.2 s | latency-budget.md, ADR-0017 |
| A-11 | client-side ducking in the gain graph | ADR-0020, ws-contract.md §4 |
| API-001 (§6.1/§7) | `session_token` auth for realtime endpoints | spec.md §9, ws-contract.md §2 |
| NEED-009 | credit metering for the voice agent | spec.md §8 |
| T7 | highlight before/at speech onset | ws-contract.md §3 |
| T12 | never voice a wrong physics half-thought | spec.md §5, ADR-0018 |
| DCR-002 | dock design home = design-doctrine §10.12 | README.md, ws-contract.md §1 |
| §4.2 | voice-backend FastAPI Deployment + Service, manifests 25–27 | spec.md §9 |
| §4.3 | `voice/` top-level package name (binding) | spec.md §3 |

## OQ-01 (resolved) — Prisma/Timbre version contradiction

`AGENTS.md` says **Prisma v2.5 / Timbre v2.5**; backend-spec says **v3.0** (per the mission brief).

**Answer: v3.0 is correct.** Checked against current Gnani material on 2026-11-09:

- **Timbre v3.0** launched 2026-10-14 — 13 voices, 10 Indian languages, 13 inline audio tags
  (`<whispers> <laugh> <sigh> <pauses> <slow> <clears throat> <coughs> <excited> <giggle>
  <exhales> <shouting> <sniffles> <chuckle>`), first audio in under 200 ms, streams before
  synthesis finishes (`gnani.ai/resources/blogs/introducing-gnani-timbre-v3-0-with-audio-tags-for-indian-languages`,
  `gnani.ai/resources/timbre-v3`; also a "Text-to-Speech (Realtime)" page on the Gnani docs site). [STRONG]
- **Prisma v3.0** launched ~2026-10-29 — 12 languages, dialect variation, ambient-noise robustness,
  natural code-switching (`gnani.ai` launch coverage/product pages). [MODERATE — launch coverage read;
  re-verify endpoint details from the Gnani developer docs at build time]
- The v2.5 strings predate both launches (repo snapshot 7 Nov 2026 in
  `skills/zivon-systems-design-skills/skills/zivon-systems-design/references/06-zivon-systems-constraints.md` still says v2.5).

**Consequence for this spec:** voice-loop contracts target **Prisma v3.0 (STT)** and **Timbre v3.0
(TTS, audio tags, realtime streaming)**. The non-negotiable in `AGENTS.md` is the *model choice*,
which is unchanged; only the version strings are stale.

**Docs needing the version-string update [WS1 update: AGENTS.md + README.md now v3.0 on merged main 2026-11-09; remaining rows unchanged]:**

| File | Location | Stale | Update to |
|---|---|---|---|
| `AGENTS.md` | §Non-negotiable constraints | "Prisma v2.5 (STT) and Timbre v2.5 (TTS)" | v3.0 |
| `README.md` | tagline (§7 loop), architecture diagram, Tech Stack table, "Built on Gnani's Models" | v2.5 ×4 | v3.0 |
| `docs/DECISIONS-and-RESEARCH/02-all-about-gnani.md` | wherever versions are pinned (check) | v2.5 | v3.0 |
| `k8s/infra.env` comment block | if it pins versions (check) | v2.5 | v3.0 |

## OQ-02 (RESOLVED 2026-11-10) — Prisma v3.0 streaming endpoint shape

**Live contract, verified against docs.gnani.ai and a real call:**
`wss://api.vachana.ai/stt/v3/stream`; auth + config are upgrade headers —
`x-api-key-id: <GNANI key>`, `model: prisma-v3.0`, `language_code: indic-auto` (or a
comma list), `x-sample-rate: 16000`. Binary PCM16 mono frames (docs recommend 1024-byte
frames). End-of-speech is the JSON frame `{"type":"commit"}`. Server events are JSON
`{"type":"transcript","text":...,"detected_language_code":...,"segment_id":...,"latency":...}`
— **one transcript per VAD segment, no separate partial stream**; the client maps a
transcript to the turn's `stt.final`. A 5.1 s Hinglish clip transcribed correctly
(`hi-IN`). The earlier "[ASSUMPTION]" (bearer auth, in-band `config`, `audio_end`,
partial/final events) was wrong and has been replaced in `voice/stt_client.py`.

## OQ-03 (RESOLVED 2026-11-10) — Timbre v3.0 realtime endpoint + voice

**Live contract, verified against docs.gnani.ai and a real call:**
`wss://api.vachana.ai/api/v1/tts`; key as the `X-API-Key-ID` upgrade header. One JSON
synthesis request per segment: `{text, voice, model: "timbre-v3.0", language: "hi-en",
speed, audio_config:{sample_rate, num_channels, sample_width, encoding:"linear_pcm",
container:"raw"}}`. Audio comes back **base64 inside JSON** (`{"type":"audio",
"data":{"audio":...,"is_final":...}}`), terminated by `{"type":"complete"}` — not binary
Opus frames. First audio arrived at **0.27 s** on the probe; the tutor voice used for
the first turn is `Shivani`. The founder's by-ear voice pick is still open; the 13-tag
v3.0 catalog is available and the harness whitelist is unchanged.

## OQ-04 (RESOLVED 2026-11-10) — Gemma 4 thinking on the Gemini API

**Measured:** `gemma-4-26b-a4b-it` on the Gemini API thinks unconditionally. It exposes
`thought=True` parts; `ThinkingConfig(thinking_budget=0)` and `thinking_level` are both
rejected (`400 INVALID_ARGUMENT: not supported for this model`). On the full tutor prompt
its first **content** token arrived at **~20 s** (and at ~45 s on a longer prompt, hitting
the turn deadline with thoughts only). Raising `max_output_tokens` is required or the
thinking consumes the budget and the reply truncates. **Consequence for P0:** the deployed
demo uses `gemini-2.5-flash` with `thinking_budget=0` (first content **~1.6 s**) via
deployment env; Gemma 4 26B A4B remains the code default and a one-env-var switch. This
is a recorded deviation from Gate A, not a silent model swap. Thought-summary streaming
stays off (ADR-0018 B-on) — the thought stream is real but not yet filtered into speech.

## OQ-05 (open) — Gemini API limits for the tutor's traffic shape

Question: free-tier/paid rate limits (RPM/TPM) and streaming SSE support for
`gemma-4-26b-a4b-it`; whether the OpenAI-compatibility endpoint streams thought summaries.
Best current answer: Gemini API documents an OpenAI-compat endpoint and hosted Gemma 4; judge
traffic (demo day) is bursty but tiny (~1 concurrent session); still pin limits before demo. [ASSUMPTION]
Owner: EX1-VOICE. Vehicle: console quota page + a 20-call burst probe. Deadline: EX1 day 1.

## OQ-06 (open) — credit accounting units for Gnani programme credits

Question: how programme credits map to Prisma audio-seconds and Timbre characters (per-minute?
per-second? per-character bundles?), so ADR-0015's tranche math uses the vendor's own unit.
Best current answer: brief says "Timbre tags bill as characters"; STT is per-audio-second/minute. [MODERATE]

Implementation status (EX1-VOICE, 2026-11-10): the guard counts **credit points**, defined as
`1 point = 30 s Prisma audio = 300 Timbre characters` (`ZIVON_VOICE_CREDIT_STT_SECONDS_PER_POINT`
/ `ZIVON_VOICE_CREDIT_TTS_CHARS_PER_POINT`, `voice/config.py`). That makes the A-07 turn estimate
≈ 3 points against the founder's 30/day per-user cap (~10 voice turns; ~33 under the 100-point
demo session cap) instead of 615 raw units against 30 — the pre-fix default denied every turn.
When the dashboard pins the real unit, only these two factors change; caps, reservations and
actuals all share the unit already.
Owner: founder (dashboard shows usage). Vehicle: read credit pricing on the Gnani dashboard
(TIMELINE Day-0 item), then finalize `ZIVON_VOICE_CREDIT_*` defaults in spec.md §8.
Deadline: before the credit guard is wired (EX1 day 3).

## OQ-07 (open) — barge-in echo on loudspeaker phones

Question: on low-end Android loudspeaker, does the residual tutor-audio tail (≤ ~100 ms after an
interrupt) leak into STT and echo a tutor phrase back?
Best current answer: browser AEC + ducking (A-11) plus a server-side echo guard (drop STT events
within 200 ms of playback stop, `ws-contract.md` §4) covers it; must be verified on real hardware. [WEAK]
Owner: EX1-VOICE. Vehicle: device matrix session (TIMELINE Day-6 style) with loudspeaker + BT.
Deadline: Gate C rehearsal.

## OQ-08 (resolved) — does the voice backend get its own service?

**No (P0).** The voice loop mounts into the core-backend FastAPI app as a router
(`voice/ws_api.py`); the "voice-backend" Deployment + Service of backend-spec §4.2 is the
core-backend image with the voice router mounted, k8s manifests 25–27 reserved to its owner.
No separate Dockerfile/k8s manifests are added by S1. If load ever forces a split, ADR-0020 §Split
defines the criteria and the reserved manifest numbers 17–18. Decision rationale: one image to
deploy before the deadline; voice scales by replica like the rest of the core backend.
