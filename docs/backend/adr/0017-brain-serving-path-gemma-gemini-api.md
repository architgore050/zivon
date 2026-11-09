# ADR-0017: Voice-tutor brain serving path — Gemma 4 26B A4B via the Gemini API

- Status: accepted (founder directive 2026-11-09, recorded as the Gate A outcome)
- Date / deciders: 2026-11-09 · founder (directive), SP1-VOICE (spec, wave S1)
- Driving NFRs / requirements: Gate C (< ~4 s end-of-speech → first spoken audio); backend-spec A-09
  (warm brain, first token < 1.2 s); NEED-009 (credit/cost observability); AGENTS.md llm_manager rule
  (see Consequences — this ADR is the documented seam); T12 (never voice a wrong physics half-thought).

## Context

Gate A (Evon v3.3 vs Gemma 4) resolved 2026-11-09 by founder directive: the tutor brain is
**Gemma 4 26B A4B** (`gemma-4-26b-a4b-it` — instruction-tuned MoE, ~4 B active params) **called with
a Google Gemini API key** (the earlier "16B" was a typo; 26B A4B is the A-09-compatible size). A-09's
"warm GPU, first-token < 1.2 s" now means: a warm *serving path* with that first-token SLO. The
cluster's existing model route (llm-manager node → OpenRouter) is request/response-shaped and
factory-oriented; the voice loop needs streaming with sub-second first events and mid-stream abort.

## Options considered

| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| 1. Gemini API direct (`generativelanguage.googleapis.com`, AI Studio key, `google-genai` streaming) — **chosen** | hosted Gemma 4 (model id confirmed on ai.google.dev, checked 2026-11-09); one key; streaming + thinking config; zero GPU ops | new vendor dependency for the runtime; quota limits to probe (OQ-05); data leaves to Google (transcripts are text, 7-day TTL, no audio — DPDP note) | lowest: a key + a client module | none identified |
| 2. OpenRouter route (llm-manager's upstream) via the same `voice/brain_client.py` | already-paid, already-keyed cluster route; proven streaming through the node's SSE semantics | extra hop; model availability/latency there is qwen-tuned today; thought-summary streaming unverified (OQ-04) | low — config switch only (`ZIVON_VOICE_BRAIN_TRANSPORT=openrouter`) | L3 risk if the route's model is slower first-token |
| 3. Route voice calls through the llm-manager node | one model-access chokepoint for the repo | the node is explicitly request/response and scopes voice OUT (`llm_manager/README.md`); a service hop adds latency and cannot express mid-stream abort on barge-in | medium | Gate C (hop + no abort) |
| 4. Self-host 26B A4B on a warm GPU (A-09's original literal shape) | full control, no vendor data egress | GPU rental/ops + quant + warm-pool babysitting in the deadline window | high | deadline (build time), ops |
| 5. Do nothing / simplest = non-streaming complete-then-speak | trivial | end-of-generation silence; Gate C fails by construction | — | Gate C |

## Decision

Option 1 is the P0 serving path, called by `voice/brain_client.py` (spec.md §4) which mirrors
llm_manager's four reliability patterns with voice-domain budgets. Option 2 ships as the
config-selected fallback transport (same client, different base URL + auth header). Option 3 is
rejected for voice (documented seam, not an exception creep: `voice/` never hand-rolls ad-hoc HTTP;
`brain_client.py` is the only module that talks to the inference server). Option 4 stays the
post-challenge cost-optimization path.

## Consequences

- Easier: no GPU ops before the deadline; brain swaps (Gemma↔other) are config + client, not infra.
- Harder: a second external dependency for the runtime (Gnani + Google); its quota/latency must be
  probed (OQ-05) and its usage logged per turn (spec.md §4 usage capture) for the credit ledger.
- Monitor: first-event latency distribution (L3), 4xx/429 rate, per-turn token counts.
- The AGENTS.md "all model calls go through llm_manager" rule is honored at its intent level —
  no hand-rolled HTTP anywhere — with the node itself explicitly not in the voice path, exactly as
  `llm_manager/README.md` scopes it.

## Revisit trigger (measurable)

L3 P95 > 1,200 ms for a week of live traffic, or Gemini API quota blocks demo-day rehearsal →
flip `ZIVON_VOICE_BRAIN_TRANSPORT=openrouter` and re-measure; if both cloud routes fail the SLO,
open the Option 4 spike (GPU warm-pool costed against the deadline) as a new ADR.

## References (checked 2026-11-09)

- ai.google.dev/gemma/docs/core/gemma_on_gemini_api — hosted Gemma 4 ids incl. `gemma-4-26b-a4b-it`,
  SDK/REST usage, thinking-config surface
- ai.google.dev/gemma/docs/core/model_card_4 — family sizes (E2B/E4B/12B/26B A4B/31B), 256K ctx
- aistudio.google.com/docs/openai — OpenAI-compatibility endpoint (the Option 2-style client shape)
- `llm_manager/README.md` — voice exclusion + the four reliability patterns mirrored
- `TIMELINE.md` Gate A row; backend-spec A-09 (per mission brief); `docs/DECISIONS-and-RESEARCH/05-gate-a-brain-decision.md`
