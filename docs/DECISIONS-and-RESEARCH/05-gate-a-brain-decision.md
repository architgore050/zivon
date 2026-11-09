# 05 — Gate A outcome: the tutor brain is Gemma 4 26B A4B via the Gemini API

**Date:** 2026-11-09 (directive issued and corrected the same day — the earlier "16B" was a typo)
**Decider:** founder · **Recorded by:** SP1-VOICE (wave S1) per the mission brief
**Gate A question (TIMELINE.md):** is Evon v3.3 strong enough as the tutor brain, vs the Gemma 4 fallback?

## Decision

The vocal tutor's reasoning brain is **Gemma 4 26B A4B** — model id `gemma-4-26b-a4b-it` on the
**Google Gemini API**, called with a Google Gemini API key. Serving-path options, the llm_manager
seam, and the measurable revisit trigger are recorded in **ADR-0017**; the tutor-facing contract is
spec.md §4 of `docs/specs/voice-agent/`.

## Why this counts as the Gate A outcome

Gate A's pass bar was "compare published benchmark data for Evon vs Gemma 4; public data not
enough to prove Evon's competence → adopt Gemma 4". The founder resolved the gate by directive on
the day voice-agent work started (the gate's own rescheduled trigger point, 1 Nov: "runs when
voice agent work starts"): the runtime LLM is the Gemma 4 fallback, without spending build days or
credits on an Evon eval. Prisma (STT) and Timbre (TTS) are untouched — the challenge's ≥1-Gnani-model
rule is satisfied twice over, and the public story keeps the full three-model loop as the goal
(AGENTS.md non-negotiables; TIMELINE guiding rule 4).

## Consequences

- Evon v3.3 remains the intended brain and the post-challenge goal; Gemma 4 26B A4B is the runtime
  choice for the challenge window, behind `ZIVON_VOICE_BRAIN_MODEL` (a config value, not a rewrite).
- Backend-spec A-09 ("warm brain, first token < 1.2 s") now reads as a **warm serving-path SLO** —
  met by the Gemini API route and pinned by measurement (`docs/specs/voice-agent/latency-budget.md` L3), not by a
  self-hosted GPU.
- The factory (build-time) keeps using whatever the llm-manager node serves; this decision changes
  the product runtime only (TIMELINE guiding rule 4 — build-time vs runtime split).
- Cost/limits of the Gemini API route become demo-day dependencies (probe: OQ-05); usage is logged
  per turn for the credit ledger.

## Cross-references

- `docs/backend/adr/0017-brain-serving-path-gemma-gemini-api.md` — serving path ADR
- `docs/specs/voice-agent/spec.md` §4 — brain client + reliability seam
- `TIMELINE.md` — Gate A row (Decision Gates table) + dated Done entry
- `docs/DECISIONS-and-RESEARCH/02-all-about-gnani.md` — "what they need vs what we deliver"
  (the ≥1-model compliance argument lives there; unchanged by this decision)
