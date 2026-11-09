# Voice Agent Spec — docs/specs/voice-agent/

Build-ready architecture for Zivon's **vocal tutor agent** (Wave S1, agent `SP1-VOICE`).
An execution agent should be able to build the `voice/` package from these files alone,
without asking anything. Where a number is not yet measured it carries an evidence tag
(`[STRONG] / [MODERATE] / [WEAK] / [ASSUMPTION]`) and appears in the measurement plan.

## Binding inputs

- **Founder directive (2026-11-09, corrected same day):** the tutor brain is
  **Gemma 4 26B A4B, called with a Google Gemini API key** — recorded as the Gate A outcome
  in `TIMELINE.md` (Gate A row + dated entry) and `docs/DECISIONS-and-RESEARCH/05-gate-a-brain-decision.md`.
  The earlier "16B" was a typo; 26B A4B matches backend-spec A-09 (warm brain, first token < 1.2 s).
- **Gnani models are non-negotiable for the voice loop** (`AGENTS.md`): Prisma (STT) and
  Timbre (TTS). Versions reconciled against current Gnani docs in `open-questions.md` (OQ-01).
- **Gate C** (`TIMELINE.md`): < ~4 s from end-of-speech to first spoken audio, streaming end-to-end.
  `latency-budget.md` is the per-hop budget that meets it.
- **Binding decisions:** ADR-0002 (session store), ADR-0003 (raw WS), ADR-0008 (raw audio never
  stored), ADR-0010 (PTT contract + echo path), ADR-0012 (tutor→page messaging; T7 highlight first),
  ADR-0014 (context snapshot), ADR-0015 (credit guard / NEED-009), backend-spec A-02 (transcript
  TTL), A-09 (brain first-token), A-11 (client-side ducking), API-001 (`session_token` auth),
  backend-spec §4.2 (voice-backend Deployment + Service, manifests 25–27) and §4.3 (`voice/`
  top-level package — this name is binding; the package is NOT `voice_backend/`).
- **The voice dock's design home is `docs/frontend/design-doctrine.md` §10.12, founder-authored
  (DCR-002) — never redesigned here.** This spec only defines the state and message set the dock consumes.

## Files (read in this order)

| File | Contents | Consumer |
|---|---|---|
| [`spec.md`](spec.md) | The architecture: pipeline, `voice/` module layout, brain client seam, thinking-out-loud, session & memory, credit guard hooks, failure modes, anchoring, test strategy, deployment mount, tutor prompt draft (Appendix A) | EX1-VOICE (execution agent), core-backend agent, merge agent |
| [`ws-contract.md`](ws-contract.md) | WebSocket message catalogue (every row has a consumer), client state machine, barge-in/interruption semantics, reconnection, sequences | EX1-VOICE, EX5-FRONT (voice dock JS) |
| [`latency-budget.md`](latency-budget.md) | Per-hop latency budget meeting Gate C, evidence tags, measurement plan, degraded-path budgets | EX1-VOICE, review agents, Gate C judge |
| [`latency-budget.csv`](latency-budget.csv) | Machine-readable budget rows (parsed by `testing/voice/test_latency_budget.py`) | EX1-VOICE tests |
| [`open-questions.md`](open-questions.md) | Resolved + open questions incl. the Prisma/Timbre version reconciliation and the S0-branch cross-references | Merge agent, founder |
| New ADRs: `docs/backend/adr/0017`–`0020` | Brain serving path · thinking-out-loud approach · chunking strategy · audio transport | Merge agent, reviewers |

## Related docs this spec does NOT duplicate

- Backend/DB/storage foundations: `docs/backend/backend-spec.md` + `docs/backend/adr/0001–0016`
  (S0 output). This spec extends the WS catalogue and cites ADR IDs; it never re-decides them.
- Voice features + dock: `docs/product/features.md` (voice features, voice dock DCR-002).
- Prompting rules: `skills/prompting-and-agent-design/SKILL.md` — the tutor prompt and the
  thinking-out-loud contract follow it (contracts over coercion; harness guarantees in code).
- Audio fundamentals: `skills/zivon-audio-engineering-skills/` — Opus transport, capture/playback,
  echo/ducking, low-end Android quirks. `ws-contract.md` and ADR-0020 apply them as concrete values.

## Status

- Wave S1 spec complete; ready for EX1-VOICE to implement against.
- Cross-references to S0-owned docs (`docs/backend/…`, `docs/product/…`) are cited by ID from the
  mission brief because the `feature/backend-db-storage-spec` branch was not reachable at spec time —
  see `open-questions.md` (OQ-00) before treating any quoted definition as authoritative.
