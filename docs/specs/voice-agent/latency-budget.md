# Voice Loop Latency Budget (Gate C)

Gate C bar (`TIMELINE.md`): **< ~4 s from end-of-speech to first spoken audio**, streaming
end-to-end. This table is the per-hop budget that meets it with headroom, and the plan to pin
every `[ASSUMPTION]` with a real measurement. Machine-readable rows:
[`latency-budget.csv`](latency-budget.csv) (parsed by `testing/voice/test_latency_budget.py`,
which asserts the sums below and fails the build if a row loses its owner or measure method).

## P0 warm path (PTT mode) — hops to first spoken audio

| Hop | What | Budget (ms) | Tag | Basis |
|---|---|---|---|---|
| L0 | EOS detection — PTT release → `audio.end` flushed | 20 | [STRONG] | local UI event |
| L1 | STT **final** transcript after EOS | 250 | [ASSUMPTION] | partials streamed during speech; final is a short tail — measure on Prisma v3 |
| L2 | auth + credit check + context assembly | 50 | [ASSUMPTION] | indexed lookups, in-process |
| L3 | brain **first stream event** (network included) | 900 | [ASSUMPTION] | A-09 warm first token < 1.2 s; thinking kept short by prompt scope, not by caps |
| L4 | first speakable segment complete (thought-summary line or first short sentence, ~60–100 tok/s) | 200 | [ASSUMPTION] | streaming after first token |
| L5 | chunker + whitelist handoff | 5 | [STRONG] | in-process string ops |
| L6 | Timbre **first audio byte** | 200 | [MODERATE] | vendor claim < 200 ms (OQ-03) |
| L7 | WS S→C delivery + jitter-buffer fill (60–120 ms) | 180 | [ASSUMPTION] | audio skill jitter target + India mobile RTT/2 |
| L8 | client playback start (low-end Android HAL) | 150 | [MODERATE] | audio skill: output latency 100–300 ms |
| **Σ** | **end-of-speech → first spoken audio** | **1,955** | | **headroom to 4,000: 2,045 ms** |

The two rocks are **L3** (brain first event — thinking is the only unbounded thing in the loop)
and **L1** (STT final). Everything else is engineering discipline (buffer sizes, keepalives).

## Degraded / alternative paths (must also stay under the bar)

| Path | Σ (ms) | Note |
|---|---|---|
| P1 hands-free (VAD hangover replaces L0) | **2,335** | L0h = 400 ms (audio skill 300–500 ms) |
| Brain first-event retry fires once (F2 path) | 2,855 | still under the bar; second breach → text fallback |
| Cold brain (first token ~2 s instead of ~0.9 s) | 3,055 | warm-up policy: first dock-open preheat call (build task, EX1 §14) |
| Thinking summaries armed (B-on) | ≤ P0 | first speech is a summary line — typically lands **inside** the L3 window |

## Where the headroom goes if a row is missed

Fix in this order (cheapest first): L7/L8 buffer tuning (client, no credit cost) → L4 first-sentence
shape (prompt contract: first sentence short) → L3 thinking scope (ADR-0018 falsification path —
founder-signed only) → L1 STT session pre-open (open the Prisma stream on `audio.start`, not on
`audio.end` — costs nothing, hides connect time).

## R — the revisit trigger (measurable)

If pinned L1+L3 > 2,500 ms for a week of real traffic, revisit calling the brain on **partials +
auto-final** (correctness risk: the model answers a possibly-wrong transcript). That change needs
its own ADR amendment and a 20-turn correctness eval; do not silently pre-optimise.

## Measurement plan (EX1, first two days)

1. `turn.end.latency_ms` carries `{L0..L8}` deltas — every live turn lands on this exact grid, so
   budget vs actual is one query.
2. Pin rows L1/L3/L4/L6 with n ≥ 20 turns across Hinglish/Hindi/English; replace tags
   [ASSUMPTION]→[MEASURED] in the CSV in the same commit as the probe results.
3. Gate C verdict = P95 of the Σ column on low-end Android (device matrix per OQ-07), not the mean.
