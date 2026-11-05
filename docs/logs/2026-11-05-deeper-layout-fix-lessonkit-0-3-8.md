# Session log — 2026-11-05 — deeper layout fix: the founder's rebuilt example + LessonKit in the shell (factory 0.3.8 + frontend 0.1.4)

## What we set out to do

Founder batch (5 Nov): "still various mistakes. we can try a deeper fix. I had a
better model write some good code version. its in my downloads. it comes with a
centralized js kit for proper alignment. replace the example with that downloaded
file. and merge the kit tools it uses into the centralized js of our frontend
that models get. and then delete the candidates." Plus a process instruction:
commit on `feature/content-factory-pipeline` (the branch recently merged into
`main` via PR #1), not on `main`.

The branch was fast-forwarded to `main` (identical tips) so all new commits build
on top of everything the merge brought in (0.3.6, CodeQL fixes, 0.1.3, 0.3.7).

## The kit and why it is the deeper fix

`lesson-kit.js` (founder's file) flips the alignment model: **never calculate
where a ruled line should be — read where the browser actually put the text and
draw the rule there.**

- anchors = measured baselines of real text lines (`Range.getClientRects` + an
  ascent probe span);
- gaps between neighbouring anchors are cut into a whole number of row steps;
- rules continue above the first / below the last anchor at row pitch;
- `normalize()` nudges each block (`position:relative; top`) so every font's
  baseline lands at the same offset inside its line — the mixed-font drift the
  founder kept seeing is fixed at the root, no per-font constants;
- redraw on MutationObserver + ResizeObserver + font-load events — fonts, zoom,
  fallback glyphs, wrapping, resize can never desync the rules;
- opaque cards hide the rules and their text is skipped as anchors;
- the pen underline is generated and redrawn on re-wrap.

The rebuilt example (`design-doctrine-lesson-example-2-clean.html`, forces
chapter, full ch. 6 coverage) inlines the kit so it stays a standalone
single-file reference, and its CSS embodies the layout rules a model should
copy: one `--row` token (2.25rem), rem for type + space / px only for hairlines,
full-bleed opaque paper with a centred column via a padding trick (no wrapper
div), in-flow sticky language bar, container-query diagram box
(`min(8 rows, round(up, 100cqw × aspect, 1 row))`), `minmax(0,1fr)` grid tracks,
mixed-font inline that never grows the line box.

## What we changed

1. **Example replaced wholesale**: `docs/frontend/design-doctrine-lesson-example.html`
   ← the founder's downloaded file, as-is. `docs/frontend/candidates/` deleted
   (`git rm`) — the downloaded file IS the approved replacement.
2. **Kit merged into `frontend/assets/zivon.js`** verbatim (the old
   background-shift `fit()`, `baselineProbe` and `penUnderline` are gone). One
   deliberate hardening: the pen path is built with `createElementNS` +
   `setAttribute` instead of `innerHTML` — identical output, no HTML sink, keeps
   CodeQL clean. Shell init: paper `.zn-page:not(.zn-home)`, pen `h1.zn-title`,
   skip the opaque cards (`.zn-reveal`, `.zn-sim`, `.zn-check`); the landing page
   no-ops the ruled drawing (§10 scope guard) while the title pen still applies.
3. **`zivon.css` retyped to the kit contract**: `--row` (2.25rem) + `--rule`
   tokens; every lesson-page height/margin/line-height in rows/rem; opaque
   full-bleed lesson paper (padding trick, `--page-w` 47.5rem single column
   until the Day-9 grid); the CSS ruled background stays on the landing shell
   only; container-query diagram box with a fixed-8-row fallback for old
   WebViews; `.uline` hook for the kit's pen; `overflow-x:hidden` removed from
   body (doctrine: fix causes, don't hide). Landing section untouched.
4. **Doctrine v1.4**: §10.2 re-ruled — "**Ruled lines are not CSS**" (the kit
   draws SVG rules from measured baselines; one row token replaces fixed 36 px
   values; layout is CSS, JS only measures; pages use the kit, never re-implement
   it); §10.3 table in rem/rows + the mixed-font-inline rule; §10.5 bar sticky
   in-flow; §10.6 sim + §10.7 diagram rules generalised (the reflection-era
   stroke parameters removed — the example is now the forces chapter); §10.6
   chip quantization via `kit.row()`; §10.11 kit risks (real low-end Android
   WebView verification stays open).
5. **Diagram aspect via the shell, CSP-legal** (see failure below): `zivon.js`
   reads each model diagram's `viewBox` and sets `--dia-ar` on the box via
   CSSOM; CSS consumes it in the container-query height.
6. **Prompts + loader header**: the design-context header, `02-generate`'s frame
   law and `05-interactive`'s contract now state the kit is shell-owned — never
   copy or re-implement ruled lines / baselines / pen underlines in a page.
   `09-review` checklist wording follows the row token.
7. **Budget**: `max_chars_design_context` 68000 → **80000** — composed doctrine
   v1.4 + rebuilt example ≈ 78.4k; verified against the inference server's
   measured `n_ctx = 262144` tokens (worst case ≈ 101k tokens). Rationale dated
   in `config-reference.md`.

## The failure worth writing down: CSP vs markup style attributes

The first integration run after adding `style="--dia-ar:…"` to the diagram div in
`render.py` failed 4/7 integration tests: the perf gate's console-error check
caught `Applying inline style violates … style-src 'self'`. A probe page under
the exact CSP proved the boundary: **CSSOM writes from an allowed script are
legal** (`el.style.cssText`, `style.top`, `setProperty` — zero violations),
**markup style attributes are not** (neither written by hand nor via
`setAttribute`; hashes don't cover them without `unsafe-hashes`). Fix: `render.py`
emits no style attribute; the shell script reads the viewBox and applies the
variable through CSSOM. The kit itself was never the problem — all its style
writes are CSSOM.

## Verification

- ruff check / ruff format / mypy clean.
- Suites in-image (0.3.8): 209 unit + 7 integration + 10 frontend green.
- Factory smoke passed in the 0.3.8 image; frontend image serves its seeded root
  (shell staged at `/opt/zivon-shell`, LessonKit present).
- kubeconform 9/9 strict + kube-linter clean.
- Cluster: gotcha 14 executed in full — deleting the PVC did NOT wipe the
  hostpath dir (confirmed again), manual wipe required; re-applied stack, new
  frontend pod seeded a **byte-identical** shell (md5-matched against the repo),
  published pages restored via `kubectl cp`, landing + course page 200, served
  `zivon.js` carries the kit, `factory-smoke` Complete, startup suite
  `test-startup-121752` green in-cluster (209+10+7).

## Not done / open

- Founder has not yet viewed the new example live on the site — his call.
- Kit verification on a real low-end Android WebView (MutationObserver/
  ResizeObserver, CSS `round()`/container queries, Hindi fallback fonts, user
  font-size zoom) — doctrine §10.11 keeps it open.
- Day-9 shell remainders unchanged: two-column lesson grid (`--page-w` →
  65.75rem), language-bar switching behaviour.
- Any regeneration stays founder-triggered; the new example + doctrine flow into
  the next factory run automatically (they are baked into the 0.3.8 image).

## Next

Founder reviews the rebuilt example on the live site; his trigger decision
starts the next generation run on the new reference. Commits for this batch sit
on `feature/content-factory-pipeline`.
