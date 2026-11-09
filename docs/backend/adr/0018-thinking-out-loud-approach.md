# ADR-0018: Thinking out loud — speak whitelisted thinking summaries (B), fillers as dead-air fallback (A)

- Status: accepted (SP1-VOICE, wave S1, per the founder-delegated brief: "evaluate both founder
  options and pick one"; falsification test below governs, founder ratifies results)
- Date / deciders: 2026-11-09 · SP1-VOICE (spec), founder (original two options)
- Driving NFRs / requirements: Gate C perceived latency; T12 (never voice a wrong physics
  half-thought); Mayer multimedia principles (no competing narration channels); credit cost (Timbre
  bills characters incl. tag characters); prompt complexity (contracts over coercion,
  `skills/prompting-and-agent-design/SKILL.md`).

## Context

During the brain's generation there is a gap before the first answer sentence. The founder offered
two ways to fill it: (A) short, safe, randomized "thinking" filler phrases; (B) structured thinking
blocks, each carrying a one-line summary/title of that reasoning step, spoken by the harness. The
tutor teaches children physics; wrong spoken claims cost more than silence (T12), and dead air
longer than ~2 s reads as "broken" (Gate C is a perceived-latency gate).

## Options considered

| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| A only (randomized fillers) | trivially safe (fixed string list); zero prompt complexity | no Socratic value; repetitive; fills time without teaching | ~0 | Socratic value (weak) |
| B only (speak thinking summaries, no fallback) | models reasoning aloud (Socratic value); perceived latency drops during thinking | correctness risk if summaries carry substantive claims (T12); needs the transport to surface summaries (OQ-04) | classifier + fixtures | T12 if unwhitelisted |
| **B + A fallback (whitelist-enforced) — chosen** | best of both: summaries when available, safe fillers when silent; T12 enforced in harness | most moving parts of the three | flag + classifier + falsification eval | none identified |
| Silence (do nothing) | zero cost | perceived latency at its worst; Gate C jury reads silence as failure | — | Gate C (perceived) |

## Decision

**B with a strict whitelist + A as the always-armed dead-air fallback** (spec.md §5):

- Summaries may be voiced **only** when they are procedural: recalling the question, restating
  given data, naming the relation/formula to be used from the page, announcing step order,
  checking against the page. Substantive summaries (physics claims, unverified numbers, causal
  assertions) are **dropped from speech** by the harness classifier — they stay visible in the
  transcript panel as text. This is a harness guarantee, not prompt prose (control-layer rule).
- Mechanical surface: transport-surfaced thought summaries when available (OQ-04); otherwise the
  tutor emits ≤ 2 marker-prefixed (`>> `) summary lines inside the answer stream, which the harness
  extracts and strips from speech. A marker the harness can validate beats a prose promise.
- Fillers: fixed safe list ("ek second…", "achha sawaal…", "sochte hain…"), randomized without
  repetition across the last 3 turns, max 1/turn, spoken only if no audio within
  `ZIVON_VOICE_FILLER_SILENCE_MS` (default 2,000 ms [ASSUMPTION]).
- Budgets (harness-enforced): ≤ 2 voiced summaries/turn, ≤ 120 chars each; fillers and summaries
  share the turn's TTS char cap (H3) — the dead-air policy cannot blow the tranche.
- Mayer check: speech is sequential (summary → answer), never simultaneous with sim narration;
  the dock ducks during speech (A-11) — no competing channel.
- Flag: `ZIVON_VOICE_THINKING_SUMMARIES=on|off`, default **off** until OQ-04 probe + falsification
  test pass; `off` = A-only.

## Consequences

- Easier: the thinking gap becomes content instead of silence; T12 has a single enforcement site.
- Harder: one more classifier to keep calibrated; prompt carries the marker contract (one line).
- Monitor: voiced-substantive incidents (must stay 0), filler repetition complaints, TTS chars/turn.

## Falsification test (governs this ADR; run by EX1, judge = founder)

20-turn scripted physics eval per mode (B-on / A-only / silence). **B stays on only if:**
(a) voiced substantive-wrong claims = 0; (b) blind listener rates perceived responsiveness ≥ A-only;
(c) added TTS characters ≤ 15% per turn vs A-only. Fail (a) → flag stays off, classifier fixed,
re-run; fail (b) → permanent A-only for the demo; fail (c) → cap tightens (H3), re-run.

## Revisit trigger (measurable)

OQ-04 probe shows no thought-summary surface AND `>> ` marker compliance < 95% over 50 live turns
→ A-only until a better contract exists (recorded as an amendment here, not a silent flag flip).

## References

- `skills/prompting-and-agent-design/SKILL.md` (control layers; contracts over coercion; no
  thinking micromanagement — summaries are *spoken by the harness*, never scripted reasoning)
- `TIMELINE.md` Gate C; mission brief T12; spec.md §5 (implementation contract); Mayer multimedia
  principles via the systems-design skill's method refs
