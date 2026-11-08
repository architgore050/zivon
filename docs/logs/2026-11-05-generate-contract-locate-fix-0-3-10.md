# Session log — 2026-11-05 — why the class-11 run stumbled: locate contamination + a broken output contract (factory 0.3.10)

## What we set out to do

Founder killed the factory run for "Motion in a Straight Line" (class 11) mid
02-generate: "the model is stumbling on basic problems. something is going wrong
in our instructing. its a very smart model. the problme is most likely with the
harness and prompt engineering." This session forensicked the killed run and
fixed the harness. His diagnosis was right in full: **every failure found was a
harness/prompt bug, not a model bug.** Regeneration stays founder-triggered;
this batch changes no stage graph — only prompts, schema budget, and harness
guarantees.

## The killed run, reconstructed

Run `motion-in-a-straight-line-c11` (job deleted after the kill; evidence
mirrored to the host's `runs/` via `scripts/publish-artifacts.sh`):

- 00-ingest ok, 01-locate ok, 02-generate died twice and was killed mid-third.
- **Attempt 1** (3006 s, 75,818 completion tokens): 70 blocks as a flat array
  → rejected `at 'blocks': [...] is not of type 'object'` (the 55k-char
  rejected instance was embedded in the error message itself).
- **Attempt 2** (2178 s, 30,955 tokens): blocks wrapped as `{"items": [...]}` —
  the model guessed the wrapper key wrong → rejected `at 'blocks': 'blocks' is
  a required property`. Prompt had ballooned 110k → 243k characters.
- Attempt 1's block distribution: 27 check + 20 worked_example + 13 text +
  6 diagram + 3 reveal + 1 simulation = 70 — exactly what the prompt's coverage
  contract demands, against a schema cap of 18.
- The content anomaly: the model wrote LAWS OF MOTION material (football kicks,
  Aristotle, Galileo, inertia) for a kinematics chapter. It was **faithful** —
  the source pack itself was contaminated (below).

## Root cause 1 — 01-locate silently picked the wrong chapter

The requested chapter EXISTS in the library: the rationalised NCERT edition's
`keph102.pdf` opens with "CHAPTER TWO — MOTION IN A STRAIGHT LINE". But the
matcher inverted the tiers:

- The real title hit — the opener line `MOTION IN A STRAIGHT LINE 15` (trailing
  book-page number) — passed `titles_equivalent` (containment) but failed the
  `==` used for the exact/partial split → demoted to **partial**.
- A Newton's-first-law sentence in ch04's BODY prose ("...continues in uniform
  motion in a straight line unless compelled...") fired the blob fallback,
  which set `found = query` — making `exact` **always true** → the fake hit was
  the single "exact" match and won. Partial was never consulted.

The source pack header echoed the query while carrying Laws-of-Motion text; the
model grounded on it faithfully. Fix (factory/locate.py): EXACT now means a
**title candidate** (title-shaped lines from the opener: the line after a
`CHAPTER <number-or-word>` line — NCERT prints "CHAPTER TWO" — inline
`CHAPTER N Title`, or a standalone display-caps line; trailing page numbers
stripped). Body prose can never claim exactness; a body-phrase-only match is a
demoted partial that prints a loud warning and records `matched_via`
(`title_line` / `body_phrase`) in the pack. Ambiguity and no-match errors list
real chapter titles.

**Verified against the real class-11 cache** (copied off the PVC): ch02 now
wins with a clean exact title `MOTION IN A STRAIGHT LINE`; ch04 and ch06 are
body-phrase-only partials; nothing else matches.

## Root cause 2 — the prompt's shape example contradicted the schema

The GENERATED schema nests `blocks` as `_sub(BLOCKS)` — an object whose single
key `blocks` holds the array — the canonical artifact shape across
render/interactive/review. The prompt's SHAPE example (carried over from the
graph-v1 era, commit `2b4b3ca`) showed `"blocks": [...]` flat. The model obeyed
the example (attempt 1), then guessed `"items"` as the wrapper key (attempt 2).
Fix (factory/agents.py): DELIVERABLE line, LAYER 3 intro, and the shape example
all show the wrapper. The example IS the contract — a unit test now pins its
wrapper form.

## Root cause 3 — coverage law vs maxItems 18

The founder's 2026-11-04 coverage contract (every inventory item mapped;
nothing dropped) and the original 18-block cap are unsatisfiable together for a
real NCERT chapter; the model resolved the contradiction by writing 70 blocks.
Fix: `maxItems` 18 → **45** (the founder's own rebuilt example carries ~28
content blocks for one chapter; a literal class-11 mapping lands ~40 with the
fold rule), the prompt states "4-45 blocks", and a fold rule was added: same-type
repetitive drills share one representative block — every concept and every
exercise TYPE must appear. 03-check's coverage gate + fatal severity were
reworded to the same type-level law. A unit test pins prompt budget == schema
maxItems. **This is a founder-reviewable product call.**

## Root cause 4 — validator errors dumped the whole instance

jsonschema's message embeds the rejected instance: a 55k-character repr of 70
blocks entered the retry transcript (110k → 243k chars). Fix (factory/llm.py):
compact errors — `at '<path>': expected <what>, got <what arrived> [of N
items]` — with dedicated branches for type / maxItems / minItems / maxLength /
minLength, 240-char cap on any other message, best-match violation + up to 3
more reported in ONE feedback turn (the run burned one 50-minute attempt per
error), total feedback capped at 1200 chars.

## Root cause 5 — finish_reason was discarded

meta.json never recorded `finish_reason`, so a context-limit truncation would
have looked like a mysterious parse failure. Now recorded per attempt; a
`length` cut is rejected with plain advice ("make the page more compact")
before the model chases broken JSON.

## Resume guard

`PIPELINE_VERSION` 3 → 4 (factory/stages.py). The fingerprint includes it, so
the contaminated run dir — and every version-3 run dir — is refused by resume
even without `--fresh`. Guarantee in the harness, not in prose.

## Verification

- New fixtures: `kinem-ch02.pdf` / `kinem-ch04.pdf` (the contamination pair,
  NCERT-style openers) added to `make_pdfs.py`.
- 7 new tests: 3 locate (title beats body-phrase; body-phrase demoted + loud;
  loose query → ambiguity error), 3 llm (compact error < 1200 chars with no
  instance repr; multi-violation one turn; finish_reason recorded + `length`
  rejected), 1 prompt contract (wrapper in example + budget == maxItems).
- Suites: 216 unit + 10 integration + 10 frontend green in-image; ruff,
  ruff format, mypy clean.
- Real-cache matcher proof (above) against the exact incident data.

## Not done / open

- **Founder review pending**: maxItems 45 + the fold rule are product-level
  calls (his coverage law demanded the raise; the numbers are ours).
- Re-triggering the chapter needs `scripts/trigger-factory-run.sh "motion in a
  straight line" 11 --fresh` — the fingerprint guard refuses the old run dir.
- The contaminated run dir stays on the PVC as evidence (mirrored to host
  `runs/`, gitignored).
- The catalog's `chapter_numbers` for class-11 Part I are `chapters_verified:
  false` and the rationalised-edition titles are now known live (ch02 = Motion
  in a Straight Line, ch03 = Motion in a Plane, ch04 = Laws of Motion) — worth
  marking verified in a later catalog pass.

## Next

Release factory 0.3.10 (frontend stays 0.1.5 — no shell change), cluster
re-apply, then founder's review + trigger decision. Commits sit on
`feature/content-factory-pipeline`.
