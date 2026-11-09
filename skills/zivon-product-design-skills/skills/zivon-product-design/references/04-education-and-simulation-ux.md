# Education and simulation UX

Applies to Core surfaces and to anything a wrapper/add-on touches inside a lesson.
Sources: PhET interface research (E), Mayer (D), physics-education research (F). Evidence tags in `01`.

## 1. Lesson-page shape (what must exist on screen)

The repo's block schema (`docs/content-factory/blocks-schema.md`) fixes the content
types: `text`, `worked_example`, `check`, `reveal`, `diagram`, `simulation`; first block
`text`, last block `check`, ≥3 checks spread through the page. Specify, per type, every
perceivable element and state. Starting points:

| Block | Elements to inventory (non-exhaustive) | Key states |
|---|---|---|
| text | paragraphs, key-term highlights (signaling), term-gloss on demand, formula + spoken form, per-paragraph TTS handle, per-paragraph "ask about this" handle | default, translated, untranslated, speaking-now |
| worked_example | problem, numbered steps with titles, answer, step-reveal control, units | collapsed, step-n revealed, all revealed |
| check (mcq / numeric) | question, options or numeric field + unit, submit, feedback (correct / incorrect / partial), explanation, hint ladder, retry, attempt counter, skip, confidence prompt (optional) | unanswered, answered-correct, answered-incorrect, revealed, skipped |
| reveal | title, `<details>` steps (works with zero JS) | closed, open |
| diagram | inline SVG, caption, legend/colour key, alt + long description, zoom | default, zoomed |
| simulation | canvas, controls, readouts, tools, reset, play/pause/step/speed, trace, prediction prompt, accessible state text, error painter | start-still, running, paused, at-limit, error |

Progress: show block position ("3 of 9") and what remains; let the learner move at their own pace (segmenting). Decide how completion of checks is represented without turning it into a points game.

## 2. Simulation interaction rules (from PhET research - treat as defaults)

1. **Start still.** Load in the simplest view with no autonomous motion. Motion begins from the student's action. `[STRONG]`
2. **Direct manipulation first.** Make the key object draggable; put its controls on/next to it (contiguity). Use a global control panel only for global parameters (gravity, mass of everything, view mode). `[STRONG]`
3. **Control vocabulary**: slider (with typed-value box for exact entry), radio buttons, checkboxes (students rarely uncheck - give pop-ups a ✕), grabbable objects. Avoid mode-switching tool palettes. `[STRONG]`
4. **Limits**: ≤ ~3 groups of ≈3 controls visible; extras behind an "Advanced" disclosure. Labels one to three words, no abbreviations; units visible beside values. `[STRONG]`
5. **Representation discipline**: one object = one look across all sims; consistent colour for each physical quantity (e.g. force arrows). Remove incidental artifacts (asymmetries, stray pixels) - novices will read meaning into them. `[STRONG]`
6. **Wiggle-me**: only if the key object isn't obviously grabbable; one short phrase, enters calmly, stays still, disappears on first interaction anywhere. `[STRONG]`
7. **Play/pause/step/speed/reset**: placed consistently (bottom centre of the play area) and *made visible*; students don't find them unprompted. Slow-motion and trace/path are high-value ("see it slowly, see the path"). `[STRONG]`
8. **Meaningful extremes**: behave plausibly at limits; show a clear "out of range" cue rather than silence. `[STRONG]`
9. **Real-world anchors**: use familiar objects (bicycle pump, cannon, ramp) with deliberately cartoon-like emphasis on what matters. `[STRONG]`
10. **Help**: avoid needing it; request-only; ≤ four short lines near the item; never science explanations in help. `[STRONG]`
11. **Predict-Observe-Explain wrapper**: before the first interaction on important sims, offer an optional "what do you think will happen?" (tap/speak) and afterwards "what changed?". This is where the voice agent adds the most value. `[STRONG for prediction/IE; ASSUMPTION for exact UX]`
12. **Reduced motion** and **keyboard operation** are base requirements; every canvas needs a text mirror of its current state (also what the TTS and the tutor can read).

The simulation's runtime already provides: control wiring, rAF loop, reduced-motion support, an on-canvas error painter, and per-simulation `controls` (`id`, `label`, `min`, `max`, `step`, `initial`) and `default_behaviour`. Specify what the *frontend shell* shows beyond that, and flag any schema field the product now needs (e.g. `unit`, `readout_format`, `prediction_prompt`, `narration_text`, `state_text_template`) as a **schema change proposal** for the content-factory owners - do not silently assume it exists.

## 3. Checks and feedback

- Distractors should map to listed misconceptions where possible (the block schema already encourages this); the feedback for a wrong option should address *that* misconception, not just say "wrong". `[STRONG]`
- Prefer retrieval over recognition: for key concepts offer a "say it first" step (voice) or a typed attempt before options are shown. `[MODERATE-STRONG]`
- Feedback is immediate, specific, and kind; allow retry; never shame. Show the explanation after commitment, not before.
- Hint ladder (3 rungs max): nudge → targeted hint → worked step. Each rung is a distinct, loggable state.
- Do not let a wrong answer lock the learner; progress should not hinge on a single check.

## 4. Metrics that reflect learning (not engagement)

Candidate events/metrics, to be refined by the author: first-attempt correctness per check; misconception selected (which distractor); hint rung reached; prediction-vs-outcome match; time-to-first-interaction with a sim; controls touched per sim; return-visit review correctness; "explain-back" quality (voice); tutor turns per resolved doubt; abandonment point. Avoid vanity metrics (time-on-site, streak length) as success measures for children.

## 5. What the content factory can and cannot supply

Check `docs/content-factory/` before asking the frontend for anything the pipeline cannot generate. Wherever the product needs *new content fields* (narration scripts, glosses, translations, pronunciation hints, prediction prompts), list them as content-factory requirements; they carry cost in the build pipeline, not just the UI.
