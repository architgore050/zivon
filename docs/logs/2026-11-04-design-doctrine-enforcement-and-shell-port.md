# Session log — 2026-11-04 — design doctrine enforcement + §10 lesson-shell port (founder batch, images 0.3.3 / 0.1.1)

## What we set out to fix

After the first real generated page (Motion) went live, the founder looked at it and named
what felt wrong: diagrams mixed hand-drawn with razor-sharp straight strokes, cards and quiz
chrome that looked like default UI instead of notebook paper, body text that read as typeset
rather than written, no tape anywhere. His diagnosis instinct: "the doctrine only made arrows
and underlines hand-drawn — the instruction was too specific, not generalized — and the main
example page's different style may be bleeding in." He asked for three adjustments:
clarify the doctrine, drop the main example from the factory, and give the doctrine + the
lesson-page example to **anybody who reviews, writes or edits the page code**.

Our own autopsy agreed with part of it and found the rest was deeper than prompts:

- Diagram sharpness was real and prompt-shaped — but diagrams arrive as model-authored SVG
  (`spec["svg"]`) injected verbatim by `render.py`, so prose coaching was a hope, not a guarantee.
- Fonts, cards, tape, ruled-grid alignment are SHELL decisions: `render.py` + `zivon.css` wrote
  the page skeleton and the model never touches them. The shell still implemented the pre-§10
  doctrine — the §10 lesson-page rules (36 px grid, Caveat body, taped cards, uncarded sketched
  diagrams) had been deliberately deferred to Phase 4/Day 9 ("Accepted gap" in
  `2026-11-02-design-doctrine-flow.md`). The founder was seeing that deferred gap surface.
- 08-fixloop and 10-reviewfix — two of the three stages that rewrite page code — had **zero**
  design context. The reviewer had doctrine text but no reference implementation.

Founder decision (question round): do all three adjustments AND pull the §10 shell port forward
into this batch, then one `--fresh` Motion run to see the full intended look.

## What we changed

1. **Doctrine §10.1 — "Hand-drawn by default" (founder ruling).** Every visual element on a
   lesson page belongs to the notebook world; sharp browser-default UI chrome is a defect. Two
   deliberate exceptions: the typed layer (controls/questions/feedback stay typed per §10.3) and
   native controls styled only via palette tokens. Arrows and underlines are examples of the
   rule, not its limit.
2. **Main example out of factory context.** `paths.doctrine_examples` narrowed from
   `design-doctrine*.html` to `design-doctrine-lesson*.html`. The post/brand example remains a
   docs asset (it still governs post visuals) but can no longer bleed its single-file demo
   style into generated pages.
3. **Design context for every code-touching stage.** 09-review now gets doctrine + lesson
   example (was doctrine-only). 08-fixloop and 10-reviewfix got doctrine + example + palette
   with explicit "fix toward the reference, never restyle while repairing" framing (they had
   neither before). 02-generate/03-check stay doctrine-text-only — they never touch HTML
   (founder-confirmed).
4. **§10 lesson shell ported into the deterministic skeleton** (pulled forward from Day 9):
   `zivon.css` rewritten wholesale — 36 px ruled rhythm, Caveat 30/36 handwritten lesson body
   (46 ch), taped `paper-light` cards (torn-end tape pseudo-element, -3°/+2°, rotation on the
   tape only) for the things the learner operates (sim/quiz/reveal), worked examples written on
   the paper instead of carded, diagrams uncarded in a fixed 288 px box with handwritten SVG
   labels, ✓/✗ quiz feedback carried by shape + words instead of hue, typed layer preserved
   for controls/questions/feedback/numeric answers. Every §10 rule is scoped to topic-page
   classes; the landing shell is untouched (the doctrine's own scope guard).
5. **`handify_svg` in `render.py` — the §10.7 guarantee moved into the harness.** Model
   diagram primitives (`<line>`, `<polyline>`, plain absolute M/L `<path>`) are resampled every
   ~28 px, jittered with the lesson example's mulberry32 rng (ported 1:1), and smoothed with
   quadratic curves — seeded by block id + primitive index, so re-renders are byte-identical
   and already-handified markup (fix-loop body reuse) is left alone. Arcs, curves, circles,
   text, rects are never rewritten. Sims stay straight-stroked on purpose (§10.6: sims are
   precise instruments; §10.7 sketches the diagrams).
6. **`fit()` baseline alignment ported into `zivon.js`** (defensive: only lesson pages with
   `.zn-text` align; the landing never does) + quiz feedback now writes `\u2713`/`\u2717`
   escapes so rendering is charset-proof regardless of how the page embeds the script.
7. **Tests + docs + release**: new `TestHandifySvg` (conversion, determinism, idempotence,
   authored-attrs survival), review/fixloop prompt assertions that the lesson example is
   present AND the main example is absent, `test_design.py` pins the lesson-only glob, fake
   trees renamed. `config-reference.md` + `architecture.md` carry the new stage composition;
   `kubernetes.md` got gotcha 14 (a shell update never propagates into a seeded frontend PVC —
   `cp -rn` is no-clobber; re-seed procedure recorded). Factory image 0.3.2 → **0.3.3**,
   frontend image 0.1.0 → **0.1.1** (also fixed a stale 0.2.2 example tag in `docker.md`).

## Verified

- 206 content-factory unit + 10 frontend + 7 integration tests green (locally, against the
  mounted repo in-image); ruff check + format + mypy clean.
- Cluster (see TIMELINE Done entry 2026-11-04): images built + loaded, frontend PVC re-seeded
  with the new shell (md5-verified byte-identical to the repo), Motion page restored from the
  repo snapshot, smoke Job + startup suite Complete on 0.3.3, site 200 at
  http://192.168.49.2:30080 serving the §10 CSS. The re-seed itself exposed a second trap -
  minikube's hostpath provisioner reuses the claim-named backing directory, so a naive PVC
  delete/recreate kept the old data alive; the full procedure is now gotcha 14.

## What this deliberately does NOT do

- No two-column page grid and no language bar yet — remaining §10 shell items, Day 9.
- No Hindi/Kalam work (Caveat has no Devanagari; Kalam stays unvendored until Hindi pages exist).
- No sim code was re-touched — sims were already the hand-drawn-mostly part of the page.
- The founder's "text inside cards sitting outside the cards" symptom: to be re-checked on the
  regenerated page against the new shell (the suspect was the misaligned pre-§10 grid).

## Next

Founder triggers: `scripts/trigger-factory-run.sh "Motion" 9 --fresh` — the regenerated page
is the test of this whole batch. Read the result with the founder's eye, then decide what is
still off. Day 9 carries the rest of §10 (grid + language bar).
