# Session log — 2026-11-05 — typed page, handwritten accents + frame adaptation (founder design batch #2 of 4 Nov, factory image 0.3.5 + frontend image 0.1.2)

## What we set out to fix

The founder's second design ruling batch (4 Nov 2026), issued after reviewing the v1.2
lesson examples:

1. **Handwriting was hurting the page.** "We can return to normal text… we can quit the
   hand-drawn style entirely from visuals too… whatever we can consistently get right is
   the annotations and underlines." Handwritten body text read as misalignment; the
   hand-stroke geometry generator produced boxes with three rounded corners and one right
   angle. Ruling: from now on **only titles/section headings, pen underlines, and
   annotation arrows + their labels are handwritten**; everything else typed, honestly
   aligned on the ruled lines "as if they were written on the lines".
2. **Inconsistent line spacing** — blocks landing on 12/20/48 px offsets so the ruled
   lines drifted under some text and not others.
3. **Frame adaptation** — "the ruled lines somehow move when the window widens or
   shortens… maybe all the examples need to be checked for this. and the pipeline needs
   to prompt for that specifically too."
4. "You don't just have to edit the example, some changes also have to be made to the
   doctrine."

## What we changed

1. **Doctrine → v1.3** (`docs/frontend/design-doctrine.md`): §10 fully rewritten around
   "Typed page, handwritten accents" — strict 36 px block rhythm (every block a multiple
   of 36 px; card padding + border = exactly one row: 17+17+1+1), measured baseline
   alignment (re-fit on load / font-load / resize), a new **Frame adaptation** rule
   (phone ~360 px → laptop, no fixed pixel widths, no horizontal overflow, alignment
   survives every resize), clean-geometry law for diagrams/sims (straight lines, true
   circles and arcs, one consistent corner style per page), hand-stroke generator
   **survives for annotation arrows only**, and the §10.9/§10.10 departure + psychology
   tables updated. Then compressed twice (prose weight only — every rule and pinned
   phrase kept) to 21,820 chars so the candidate swap still fits the design-context
   budget.
2. **Shell retyped** (`frontend/assets/zivon.css` + `zivon.js`): body / worked-example /
   reveal-step text → Courier Prime 400 17/36 (monospace keeps every baseline exactly on
   its rule at every width), Caveat only on titles and annotation labels, Bricolage on
   controls/questions/feedback; card chrome, glossary, objectives, footer, check rows all
   on the 36 px grid; sim canvas wrapped in a fixed 288 px `.zn-sim-canvas-wrap`;
   `fit()` re-runs on resize.
3. **`handify_svg` retired from `factory/render.py`**: model diagram SVG now renders
   verbatim as authored; sims get the fixed-height canvas wrap. The clean-geometry
   guarantee moved to prompts + reviewer + harness (the doctrine's own principle:
   guarantees in the harness, not in prose).
4. **Prompts**: `02-generate` diagram instruction rewritten (clean geometry, one
   consistent corner style, annotation arrows as the only hand-drawn element, viewBox
   with NO fixed width/height) plus a **Frame law** paragraph; `05-interactive` got the
   fixed 480×320 canvas buffer contract + clean-geometry-on-canvas rule; `09-review`
   checklist gained item 6 "Frame adaptation (doctrine §10.2)".
5. **Perf harness overflow gate** (`testing/content_factory/perf/harness.py`): measures
   `scrollWidth - innerWidth` at each profile's viewport (360 px weak-android, 1280 px
   mid-laptop); > 2 px overflow fails the page.
6. **Both lesson examples converted to v1.3**: the live factory example
   (`design-doctrine-lesson-example.html`) retyped, geometry cleaned (hand() → cl()),
   angle markers replaced with true SVG arcs, sim box fixed at 180 px (5 rows), quiz
   options fixed to `role="radio"` in a `radiogroup`, title gets the pen underline;
   candidate 2 (`candidates/design-doctrine-lesson-example-2.html`) same treatment
   (22 hand() call sites → clean, slider rows on the 36 grid, ARIA fix) — it stays a
   candidate, outside the `doctrine_examples` glob, until the founder approves the swap.
7. **Design-context budget**: `max_chars_design_context` 64000 → 68000 after measuring
   the composed swap context at 65,821 chars — verified safe against the inference
   server's measured `n_ctx = 262144` tokens (`/props`), which the worst case (120k-char
   source pack + 68k design + full generation) fits with room to spare. Rationale dated
   in `docs/content-factory/config-reference.md`.
8. **Docs kept current**: config-reference (cap raise), blocks-schema (worked_example:
   problem numerals verbatim, answer COMPUTED — the 0.3.4 rule_numbers scope),
   architecture (handify retirement + frame-adaptation harness), deployment README
   history lines for 0.3.5 / 0.1.2.

## Verified

- ruff check + format, mypy: clean.
- Suites in-image (209 unit + 7 integration + 10 frontend — unit count shifted 211 → 209
  as the 3 handify tests became 1 authored-diagram test): green locally and green again
  as the in-cluster startup run on 0.3.5.
- kubeconform strict (9/9) + kube-linter (0 findings) on the bumped manifests.
- `zivon-factory:0.3.5` + `zivon-frontend:0.1.2` built; smoke test passed; loaded into
  minikube; stack re-applied via `scripts/apply-k8s.sh`.
- Frontend PVC full re-seed per gotcha 14 (Deployment + PVC + Released PV deleted; the
  host directory SURVIVED the PV deletion — the gotcha's trap confirmed again — wiped
  manually, then the 0.1.2 seed initContainer re-seeded; seeded shell verified
  byte-identical to the repo; published pages restored from the repo snapshot).
- Site live at http://192.168.49.2:30080: landing 200, `assets/zivon.css` 200 serving
  the retyped v1.3 shell, course page 200, `courses.js` 200.
- `factory-smoke` Complete on 0.3.5.

## What this deliberately does NOT do

- **No candidate swap.** Candidate 2 stays in `docs/frontend/candidates/` until the
  founder approves it; the swap composition (≈ 65.9k) is measured to fit the new 68k cap.
- **No generation run.** Regeneration is the founder's `--fresh` trigger, and the failed
  20:50 run `factory-run-motion-205004` (pod lost when the cluster was stopped) was
  deleted as a Job object only — its partial evidence stays on the `zivon-sources` PVC.
- **Visual tiny details deferred** — the founder explicitly parked them ("we will work on
  them next"), including the parked self-audit of candidate 2 (structures the pipeline
  can't render yet: misconceptions panel, At a Glance, NCERT section labels; possible
  grounding slips to re-verify).
- **No architecture change**: the stage graph is frozen; this batch is prompts, doctrine,
  config and harness guarantees only.
- Day-9 §10 shell remainders (two-column page grid, language bar) stay Day-9 work.

## Next

1. Founder views the two v1.3 examples in a browser → decides the candidate swap.
2. Founder triggers `scripts/trigger-factory-run.sh "Motion" 9 --fresh` on 0.3.5; the
   perf gate now enforces frame adaptation on every generated page.
3. The deferred visual tiny-details pass, then Day-9 shell remainders.
