# ADR-0019: Streaming chunking — sentence-boundary with clause fallback and a flush deadline

- Status: accepted (SP1-VOICE, wave S1)
- Date / deciders: 2026-11-09 · SP1-VOICE (spec)
- Driving NFRs / requirements: Gate C (start speaking before generation ends); TTS prosody quality
  (chunks are what Timbre speaks); T12 (a cut never creates a false claim); credit cost (chunk
  boundaries add no characters).

## Context

The one-stream law (spec.md §1) requires handing speakable text to Timbre while Gemma is still
generating. The chunker decides *where* a partial stream becomes speech. Chunk too eagerly and
Timbre speaks broken clauses with wrong prosody or a half-formula; too lazily and first audio
slides past Gate C. Devanagari and Latin-script Hinglish both appear, sometimes in one sentence.

## Options considered

| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| 1. Fixed token/char windows (e.g. every 40 chars) | trivial | splits words, numbers, units, formulas; TTS prosody garbage | ~0 | prosody; T12 (half-numbers) |
| 2. Sentence-only boundaries | clean prosody | long physics sentences delay audio; some streams lack punctuation until late | ~0 | Gate C on long first sentences |
| 3. Embedding/semantic chunking | "smart" breaks | a model call in the hot path; latency + cost + failure mode | high | Gate C (latency) |
| 4. **Sentence boundaries + clause fallback + 250 ms flush deadline — chosen** | prosody-safe and latency-bounded; deterministic, testable | needs careful boundary rules (below) | one pure module | none identified |

## Decision

`voice/chunker.py`, streaming, deterministic rules in priority order:

1. **Strong boundaries:** `।` (danda), `.`, `!`, `?`, `…`, newline — flush at the boundary.
2. **Clause fallback:** if the pending buffer exceeds `MAX_SENT_CHARS` (140) without a strong
   boundary, flush at the last `,` `;` `:` `—` boundary ≥ 40 chars in.
3. **Flush deadline:** if the pending buffer has sat > 250 ms [ASSUMPTION, tuned at EX1] without a
   flushable boundary, flush at a whitespace word edge ≥ 40 chars in (prosody loss buys latency;
   bounded rareness by rules 1–2).
4. **No-split guarantees (harness-tested):** never split inside a number/decimal/unit token, inside
   a Timbre tag `<…>`, inside a `REF:` line, inside a URL; never flush a buffer whose visible text
   is only markdown/LaTeX residue — strip (`**`, `#`, `$…$`, code fences) first; if stripping
   empties the chunk, drop it silently (never speak markup garbage).
5. **First-chunk fast path:** rule 3 applies from the first token, so the first spoken segment is
   at most ~250 ms behind the first boundary; the tutor prompt's "short sentences, one idea each"
   contract keeps rule 1 firing early (prompt shape serving latency, not prose hope).
6. Segments carry monotonic `segment_id`s; `kind: speech|summary|filler` per ADR-0018.

## Consequences

- Easier: Timbre always receives prosody-shaped inputs; the latency contribution of chunking is a
  constant, testable bound; TTS char metering maps 1:1 onto segments (H3).
- Harder: boundary rules are repo law for the voice loop — changes go through
  `testing/voice/test_chunker.py` fixtures (incl. Devanagari + mixed-script cases) before tuning.
- Monitor: flush-deadline firing rate (should be rare; frequent firing = prompt contract drifting
  long) and first-segment length distribution (L4 row of `latency-budget.md`).

## Revisit trigger (measurable)

If pinned L4 > 300 ms P95 over a week, add a "first sentence ≤ 12 words" nudge evaluation per the
prompt authoring loop (baseline → minimal contract → fresh-instance test), not a chunker change.

## References

- `skills/zivon-audio-engineering-skills/` §1 (frame scheduling, jitter buffering — chunks are
  spoken in order, buffered 60–120 ms)
- spec.md §2 stage 5; ws-contract.md §2 (`tts.text`, `tts.audio` segment fields);
  `latency-budget.md` L4
