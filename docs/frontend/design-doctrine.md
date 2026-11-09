# Design system: Field Notes

Anchor: Lo-fi paper (Ilm-Alan "Lo-Fi": paper-yellow, not cream) with Organic honesty. Status: v1.0, **confirmed**
(founder decision 31 Oct 2026): the single visual source of truth for all post visuals and the product UI.
Applied to the Day 0 post kit, the Day 1 post kit, and everything after.
v1.1 (1 Nov 2026) extends the system to the lesson page of the product (§10); §1–§9 are unchanged.
v1.2 (2 Nov 2026) adds §0: the scope split between the base system and the lesson extension is now explicit.
No visual rule changed.
v1.3 (4 Nov 2026) re-ruled §10 after founder review of the lesson example: **typed page, handwritten accents**
(typed Courier Prime body on a strict 36 px rhythm; handwriting only on titles, headings, pen underlines and
annotation arrows/labels; hand-wobble retired from geometry; frame adaptation 360 px → laptop). §1–§9 unchanged.
v1.4 (5 Nov 2026): the lesson example was rebuilt with sound layout code and the **alignment kit**
(`LessonKit`) became shell-owned (`frontend/assets/zivon.js`): ruled lines are drawn from measured
text baselines, never computed; one row token `--row` (rem) replaces fixed 36 px values. §10.2/§10.3/
§10.5–§10.7 updated to match; §1–§9 unchanged.
v1.5 (5 Nov 2026): founder's second pass on the rebuilt example - **one content-width token**
`--page-w` (47rem) and **no per-block max-widths** (every block fills its column); the kit is
externalised as `lesson-kit.js` beside the example (guard-thrown if missing); diagram labels and the
recoil drawing fixed. §10.2/§10.3/§10.8 updated; §1–§9 unchanged.
v1.6 (9 Nov 2026, **the kit refactor** - the founder's building-blocks directive): §10 stops
re-teaching layout in prose. The shared stylesheet `frontend/assets/zivon.css` + behaviour layer
`frontend/assets/zivon.js` are now the single standard toolkit (component catalog in the CSS
header); §10.2/§10.5/§10.6 name the components and the guarantees the kit carries instead of
re-stating pixel rules. The quiz `<legend>` overflow defect (the border slicing through a wrapped
question - the founder's screenshot, reproduced in a full pipeline run after any model change) is
fixed in the kit with the float-legend rule, so all existing pages are repaired by the CSS alone
without re-render. Model-authored `page.css` is now lens-scoped and canvas-size-free by lint
(05-interactive rejects re-styling kit components - the 2026-11-08 run's invented `.zn-lang-bar`
and `.sim-read` rules are exactly that failure). The language bar is renderer-emitted kit chrome
(§10.5, previously flagged missing on every generated page); next: content i18n. The lesson
example is rebuilt onto the kit's exact classes and local fonts so models copy component patterns,
never hand-rolled structure. §1–§9 unchanged.
Reference implementation: `design-doctrine-example.html` (same folder) — a working page that applies every token
and rule below. Open it before generating any new page or post visual; match its patterns rather than re-deriving
the look. Second reference implementation, for lesson pages: `design-doctrine-lesson-example.html` (same folder; §10).

## 0. Scope — which part of this doctrine applies where

**"Field Notes" is the name of the whole design system, not of a lesson-page style.** §1–§9 are the base system
that the entire product and every post follows. §10 is an extension that ONLY lesson pages add on top.

### 0.1 Every element earns its place (the value-addition filter)
Before any text, section, label, or widget is planned onto a page, ask: **if this element were removed, would
the user lose a capability — read, navigate, answer a question, see sourcing?** If not, the element does not
go on the page. Banned category: *decorative chrome copied from the textbook it comes from* (NCERT's own
framing sections — "Threads of Curiosity", "Bridging Science and Society", "At a Glance", "Ready to Go
Beyond", chapter epigraphs, "Meet a Scientist" side bars), brand text on navigational pages, and duplicated
narration (objectives restated as body text, recaps re-listing key statements already highlighted under
§10.4). The bar is the learner's job, not the author's completeness: coverage is dictated by the source
material, scope is dictated by what a removing-test survives.

| Surface | Rules that apply | Reference implementation |
|---|---|---|
| Build-in-public post visuals (LinkedIn/X) | §1–§9 | `design-doctrine-example.html` |
| Site shell — landing page, course hub, navigation, any product page that is not a lesson | §1–§9 | `design-doctrine-example.html` |
| Lesson pages — generated course material (a topic with its diagram, simulation, question) | §1–§9 **plus §10**; where §10.9 lists a departure, §10 wins for that rule | `design-doctrine-lesson-example.html` |

Two scope errors to watch for, in both directions:

- A shell or post page that borrows the lesson page's distinctive devices — the 36 px ruled-line grid,
  handwritten Caveat/Kalam body text, taped paper cards, the fixed language bar — is a scope error. Those
  devices belong to lesson pages only.
- A lesson page that follows §1–§9 but ignores §10 is the other scope error: lessons are §1–§9 **and** §10.

Everything in §1–§9 (palette, fonts, pen underline algorithm, usage rules, layout, psychology) applies to every
surface, lessons included, except where §10.9 explicitly overrides it.

## 1. Intent
- Style: handwritten-lab-notebook, deliberately unproduced. Tone: candid, a little wry. Differentiator: it looks
  like a page from a working notebook with blue-pen annotations and a red-pencil "not done" mark.
  Anti-patterns: polish, gradients, stock photos, corporate icons, real cream-and-terracotta.
- Feeling at 1 second: "this is real, and nobody is selling me anything."

## 2. Methodology applied
- Category audit: dark/neon AI tools, white/blue LinkedIn, and cream/terracotta "AI brand" aesthetics are all
  avoided. Paper-yellow (a legal-pad yellow, more saturated than cream) with ink and blue pen sits outside them.
- Anchor: an artifact that looks unproduced signals unsold, which counters the "this is an ad" reaction that
  Zivon's checklist worries about. [MODERATE: handmade/imperfect cues raise perceived authenticity; weak
  quantitative evidence; test it]
- Validation: all text pairs on the paper pass 4.5:1; status separated by lightness and shape (circle vs box).

## 3. Color tokens
| Token | Hex | Contrast on paper | Job | Frequency cap |
|---|---|---|---|---|
| paper | `#EFE6B8` | n/a | background (about 70%) | all pages |
| paper-light | `#F6F0CF` | n/a | card / taped surface background (ink on it: 15.0:1) | cards only |
| ink | `#1C1B18` | 13.7:1 | text, outlines | always |
| graphite | `#5A5748` | 5.8:1 | labels, sources | small text only |
| pen-blue | `#1F3A9E` | 7.7:1 | annotation: ONE underline/circle per post | once per post/image |
| pencil-red | `#B3261E` | 5.2:1 | gap marks, "not done" stamp | gap items only |
| tick-green | `#2F6B2F` | 5.1:1 | done ticks | checklists only |
- Rules: pen-blue annotates (circle, underline, arrow) the one thing worth noticing. Pencil-red is reserved for
  honesty (gaps, mistakes). Never both blue and red annotating the same thing.

## 4. Usage rules
- Only ONE pen annotation per image or post. Underlines are never CSS text-underlines or border-bottoms —
  they are generated with the **pen underline algorithm** (§4.1).
- A gap is stamped in pencil-red as a single judgment word in uppercase Courier Prime Bold — `DELAYED`,
  `POSTPONED`, `BLOCKED`, `PENDING` — inside a 2px pencil-red border, rotated -2 deg. The judgment lands on
  the work like a verdict. Never use a `not yet:` prefix or a phrase inside the stamp; the reason belongs
  beside the stamp in ink, not inside it.
- Paper texture: flat color only; ruled lines are graphite `#5A5748` at **40% opacity, 2px thick** at the
  1080px design width (raised 1 Nov: 1px lines at 15-18% were hard to notice — target ~40 luminance contrast
  against the paper). No grain overlays that reduce contrast.
- Proportions: 70% paper, 25% ink/graphite, 5% pen and pencil marks.

### 4.1 Pen underline algorithm (canonical — every underline in the brand comes from this)

One parametric generator produces every pen underline (and its strikethrough variant) so all underlines share
the same character while each instance varies naturally. All parameters are in **em of the underlined text's
font size**, so the look is identical at any scale (1080 px post asset or 88 px web headline).

| Parameter | Value | Meaning |
|---|---|---|
| span | text ink width + 0.09em left + 0.18em right | overshoot; the right tail is the taper run-out |
| control spacing | 0.45em | path sampled every 0.45em |
| wave | sine, amplitude 0.02em, period 4em, phase 0.7 rad | the visible hand wobble |
| jitter | uniform ±0.007em per control point, **seeded from the underlined string** | instance variation; same string always redraws the same underline |
| stroke width | linear taper 0.067em → 0.033em along the path | heavy start, light tail |
| position | stroke centerline = baseline + 0.3em below the text | attaches to the underlined text, clears the descender line (revised 1 Nov from 0.5em by founder: at 0.5em the underline read as detached — closer to the next block than to its own text) |
| color | pen-blue `#1F3A9E` | one annotation per image/post |

Construction: sample the path into control points (x fixed grid, y = baseline offset + wave + jitter); compute
per-point normals; offset left/right by half the local width; emit one closed outline polygon (left side
forward + right side reversed); fill it. Render anti-aliased: raster tools draw at 2x supersampling then scale
down; the web renders the same outline as a single filled SVG path. Reference implementations:
`design-doctrine-example.html` (JS generator, live) and `skills/content-creation/tools.md` (GIMP Python,
post assets).

Variants:
- **Strikethrough**: same generator; span = word width + 0.09em each side; width taper 0.056em → 0.033em;
  centerline through the x-height middle (baseline − 0.26em).
- **Connector arrow**: same stroke generator on a **cubic-bezier** shaft (constant 0.045em width). Shape (founder
  sketch, 1 Nov): a steep descent leaving the note down toward the target's line, curving into a short horizontal
  run whose head points into the title — the angle lives in the descent; the shaft must not run near-parallel to
  text across its length. Barbs open backwards from the tip (reverse tip tangent rotated ±30°, length 0.17em).
- QC rule: a pen mark must have zero near-white pixels in a band around it — a white background means it was
  pasted, not generated.

## 5. Typography
- Display and body: **Bricolage Grotesque** (500, 700, 800). Fallback: Arial, sans-serif.
- Notes and data: **Courier Prime** (400, 700), used as typed-note text for numbers, timestamps, and stamps.
  Fallback: Courier New, monospace.
- Why: Bricolage is a characterful grotesque (distinct from Inter); Courier Prime reads like typed lab notes.
  Handwriting fonts are excluded because they cut reading speed. [MODERATE]
- Scale on 1080 px: hook 120/1.05 800; headline 76/1.1 700; body 46/1.35 500; notes 36/1.3 mono; minimum 32.
- Slight rotation (max 1.5 degrees) allowed on one card element per image, never on text paragraphs.

## 6. Layout and components
- 60 px margins, left aligned, generous empty space. Day counter written as `Day 01` in Courier Prime, top-left.
- Cards: Number (taped label), Decision (two-column notebook entry), Proof (screenshot with tape corners and one
  circle), Gap (red stamp), Recap, Ask (a boxed question).
- Corners square or 4 px. No shadows except a 2 px hard offset on taped screenshots.

## 7. Psychology reasoning
| Decision | Mechanism | Evidence |
|---|---|---|
| Unproduced, notebook look | reduces persuasion-knowledge ("ad" detection) | MODERATE (heuristic; test) |
| Yellow paper, dark ink | high contrast, calm warm background; distinct from white feeds | STRONG (contrast) / WEAK (warmth) |
| One blue annotation | isolation effect directs the eye | STRONG |
| Red reserved for gaps | consistent color code builds fast recognition | STRONG (consistency) |
| Typewriter data | numbers feel logged, not claimed | WEAK / heuristic |

## 8. Validation
All text pairs >= 5.1:1. Fonts have fallbacks. Status uses shape plus color (stamp text, tick mark).

## 9. Risks and open decisions
Yellow can read as sticky-note kitsch if overdone; keep texture flat. Test legibility on phones in sunlight.

## 10. Lesson page (extension, v1.1; retyped accents v1.3)

Scope: **lesson pages only** - the study-material page a learner opens: a chapter taught in full. §1-§9 stay in
force for this page and unchanged for every other surface; §10.9 lists every departure. Nothing in §10 (ruled
grid, handwritten accents, taped cards, language bar) may leak into the site shell or post visuals - see §0.
Reference implementation: `design-doctrine-lesson-example.html` - a **styling and completeness reference**: what
a finished page looks like and how thoroughly a chapter is taught. Its topic and content belong to the example
alone - coverage is dictated by the source material.

### 10.1 Intent
- Metaphor: a ruled notebook page. Text is **typed on the ruled lines**, diagrams are **drawn clean on the
  paper**, and anything the learner operates (simulation, question) is a **paper card taped** onto the page.
- **Typed page, handwritten accents** (founder ruling 2026-11-04): handwritten body text and hand-wobble on
  visuals read as misalignment and broken boxes - retired. Handwritten, because consistently achievable:
  **titles and section headings**, **pen underlines** (§4.1), and **annotations** (the arrows and their Caveat
  labels). Everything else is typed (§10.3) on the ruled lines. Diagram and simulation geometry is clean SVG:
  straight lines, true circles and arcs, one consistent corner style per page - never wobble, never mixed
  corners.
- Feeling at 1 second: "a teacher wrote this out for me on their notebook page, and I can touch the parts
  that move."
- Anti-patterns: glass, blur, translucency, gradients, shadows under taped cards, tilted cards, grain (all
  tried 1 Nov, rejected - flat paper-light read as the most honest); hand-wobble on geometry (retired
  2026-11-04: jittered rectangles read as defective boxes, not handwriting).

### 10.2 Page grid (one row token) and frame adaptation
- The kit is the contract (v1.6): every layout guarantee below is implemented
  once, in `frontend/assets/zivon.css` + `zivon.js`, under the component names
  the renderer emits (see the catalog in the CSS header). A generated page
  never re-implements, copies, or re-styles kit chrome - the model writes only
  inside the `.zn-sim-<id>` scope, enforced by lint.
- ONE rhythm token: `--row` (2.25rem = 36 px at default size; rem so the user's font size scales the whole
  grid). Lines per §4 (graphite 40%, 2 px). **Every block on the page is a whole number of rows tall**:
  line-heights are `var(--row)`, margins and paddings sum to whole rows (card padding + border = one row:
  `calc(--row/2 - 1px)` + 1 px border each side), visuals occupy whole rows (diagram box at most 8 rows,
  shrinking to the drawing's own aspect rounded up to whole rows on narrow screens; simulation box a whole
  number of rows - 8 rows in the shell, 5 in the example), one blank ruled row between blocks. Reflow may
  only then move a block by whole rows, never by 12 or 20 px.
- **Ruled lines are not CSS** (kit ruling 2026-11-05): the shell's alignment kit (`LessonKit`,
  `frontend/assets/zivon.js`) reads where each line of text actually landed (Range client rects + ascent
  probe) and draws an SVG rule **under that measured baseline**; the gap between two neighbouring text
  lines is cut into a whole number of row steps; rules continue above the first and below the last line at
  row pitch; every font's baseline is normalised to the reference offset inside its line; opaque cards hide
  the rules and their text is not anchored. Redrawn on every layout change (MutationObserver,
  ResizeObserver, font-load events) - nothing can drift: fonts, zoom, fallback glyphs, wrapping, resize.
  The paper's height is measured with the rules svg hidden (2026-11-09): the svg is absolutely
  positioned and its fixed height feeds back into scrollHeight, so measuring with it present locks in
  the first draw's height forever - a slower load (pre-font-metrics layout) then keeps a long empty
  ruled scroll tail under the content indefinitely. Rules are sized to the true content height only.
  Layout is CSS; JS only measures. Generated pages use the kit - never re-implement or copy it.
- **Frame adaptation (added 2026-11-04, founder ruling):** the page must be consciously designed for phones
  (~360 px), tablets and laptops. No fixed pixel widths: visuals scale through `viewBox` or fixed-height
  boxes (width 100%, fixed aspect), no per-block max-widths (line length comes from the column, §10.2),
  chips wrap, touch targets >= 40 px (>= one row for
  rows inside cards), no horizontal overflow at any width. No breakpoints where intrinsic sizing works
  (grid `auto-fit`, `clamp()`, `min()`); grid tracks use `minmax(0,1fr)` so they can shrink below content
  size; never hide overflow bugs with `overflow-x:hidden` - fix the cause. Ruled alignment must survive
  every resize - a rule sliding under text after a window change is a defect (founder-caught drift in the
  example; the row-token grid is the structural fix, the measured kit the local one).
- Page: ONE content-width token `--page-w` (47rem = 752 px; change this one token to resize the page); side
  padding `max(1.5rem, safe-area, (100% - --page-w)/2)` - a centred column without a wrapper div, so the
  paper stays full-bleed. Two columns only while each can be >= 22rem (22 + 22 + 3rem gap = 47rem exactly;
  grid `auto-fit minmax(min(100%,22rem),1fr)` - no breakpoint), row gap one row, column gap 3rem.
  **No block sets its own max-width** (v1.5 ruling, 5 Nov): every block fills its column, so text, cards
  and diagrams share `--page-w` - line length is controlled by the column, never by a per-block `ch` cap.

### 10.3 Typography on the lesson page
| Role | Font | Size / line | Notes |
|---|---|---|---|
| Title | **Caveat** 700 | clamp(2.875rem, 7vw, 4.75rem) / 2 rows | |
| Section heading | **Caveat** 700 | 2.125rem / 2 rows | |
| Body | **Courier Prime** 400 | 1.0625rem / 1 row | fills its column (§10.2); monospace keeps every baseline exactly on its rule |
| Highlighted statement | Courier Prime 700 | 1.0625rem / 1 row | §10.4 |
| Meta line (`Class 10 · Physics`) | Courier Prime 700 | .9375rem / 1 row | top-left, as §6. No build-in-public Day counter on lesson pages (§0.1) |
| Caption, readout, labels | Courier Prime 400 / 700 | .875rem / 1 row, 1rem | graphite for captions |
| Worked-example steps, glossary | Courier Prime 400 / 700 | .9375rem / 1 row | typed notes on the paper |
| Controls, questions, feedback | Bricolage Grotesque 500 | .9375-1.0625rem | typed: operated things stay legible |
| Diagram annotation labels | **Caveat** 700 | 20-24 (SVG units); key quantity pen-blue | the handwritten accent of §10.7 |
- Sizes in rem (the user's font size scales the grid); line-heights are whole rows; px only for hairlines.
  Inline mixed-font spans must not grow the line box (e.g. bold display words inside Courier lines).
- Devanagari: Caveat and Courier Prime have no Devanagari glyphs - handwritten stack `Caveat, Kalam, "Segoe
  Print", "Bradley Hand", cursive` (Kalam = Hindi handwriting face); Hindi body falls back per glyph to system
  faces (Nirmala UI, Mangal). Set `lang="hi"` when Hindi is active.

### 10.4 Highlighted statement
- The sentence the learner must keep is its own paragraph in Courier Prime 700 with a pen underline (§4.1),
  followed by a blank ruled row.

### 10.5 Language (page-level setting)
- Languages in v1: English, हिन्दी, Hinglish (Hindi in Latin script). Language belongs to the page, never to a
  widget: one control switches every string - title, body, diagram and simulation labels, questions, feedback.
- The control is a bar **sticky to the top edge, in flow** (its height may change when chips wrap and
  nothing below needs to know): full width, paper-light, 1 px ink bottom border, no shadow, safe-area top
  padding on phones. One label in Courier Prime 14, then one chip per language. **Renderer-emitted kit
  chrome** (v1.6): the renderer emits `.zn-lang-bar` on every lesson page; generated `page.css` must never
  define it (lint enforces the scope). Switching behaviour beyond chrome (string swaps) is shell-owned
  and lands with i18n-aware content generation; until then chips switch `lang` + selected state only -
  the same honest stub the lesson example demonstrates.
- Chip: Bricolage Grotesque 500 / 15, min height 40 px, 2 px corners, 1 px ink border, transparent fill, ink
  text. Selected: ink fill, paper-light text (15.0:1). Selection shown by fill, never by colour alone.


### 10.6 Paper cards (things the learner operates)
- Surface: paper-light `#F6F0CF`, 1 px ink border, 2 px corners (all four, identical), padding
  `calc(--row/2 - 1px)` top and bottom (with the borders: exactly one row, so card height stays a whole
  number of rows), 1.125rem sides, one row below. **Flat**: no shadow (§6's hard offset is only for taped
  *screenshots*), no tilt, no grain, no blur.
- Tape: one strip per card, centred 13 px above the top edge, ~92 x 27 px (second card 84 px), masking-tape
  fill `rgba(196,174,104,0.5)`, torn ends (CSS `clip-path`), rotated -3 deg / +2 deg. Rotation belongs to
  the tape only.
- Inside a card: ink for structure, graphite for guides, pen-blue for the thing that moves or is selected.
- **Simulation**: labelled range sliders (`accent-color` pen-blue, full-row height) above the drawing (SVG
  in the example, canvas in generated pages) with clean 1.5-3 px strokes - sims are precise instruments:
  structure ink 3, guides graphite dashed, the live/net quantity pen-blue 3 with arrowhead, arrow length
  proportional to magnitude. Readout Courier Prime 700 / 1rem, `aria-live`.
- **Question**: stem in Bricolage 500 / 1.0625rem; options as chips (§10.5 style) inside a `radiogroup`, each
  a native `button` with `role="radio"` and correct `aria-checked`, one selected at a time; wrapped option
  chips are quantized to whole rows (`kit.row()`) so card height never breaks the rhythm. Feedback: a check
  or cross plus one sentence in ink (Bricolage 500 / .9375rem). Red and green stay reserved (§3): correctness
  uses shape and words, not hue.
  Kit guarantees (v1.6, mechanical): the stem is a `<legend>` inside the card `fieldset`; the legend
  **floats at 100% width** so the card border always paints OUTSIDE it - a wrapped, multi-line stem can no
  longer overflow the top border and slice through the text (the founder's screenshot defect). The
  tape's absolute position depends on the card being `position:relative` - kit-owned, never overridden
  by generated CSS (lint: `page.css` may only style inside `.zn-sim-<id>`).

### 10.7 Diagrams (drawn clean, annotated by hand)
- Drawn straight onto the paper, no card, in a box at most 8 rows tall that shrinks to the drawing's own
  aspect ratio rounded up to whole rows on narrow screens (container query).
- **Geometry is clean** (founder ruling 2026-11-04, replacing the hand-stroke generator for shapes): straight
  `<line>`s, true circles and arcs, consistent corners - every rectangle uses the same corner style (2 px
  rounded, or all square); three rounded corners and one right angle on a box is a defect. Widths: ground
  3, object outlines 2.6, internal/construction links graphite 2 dashed, quantity arrows 3, arrowheads ~15
  SVG units.
- **Annotations are the handwritten layer**: the arrow pointing at a part is the one hand-drawn stroke left
  on the page - the hand-stroke generator (polyline sampled every ~28 px, seeded jitter +/-0.4-1.2 px,
  quadratic smoothing, round caps) survives for annotation arrows only. Label: Caveat 700 / 20-24 ink; the
  quantity the lesson is about (`F`, `10 N`, `m₁`) pen-blue. Labels are page-language strings. No fills,
  gradients or icons.
- Force/quantity arrows carry honest scale: length proportional to magnitude, stated in the caption. The
  diagram carries an `aria-label` listing its labels.

### 10.8 Validation
- Contrast (computed): ink 15.0:1, pen-blue 8.5:1, graphite 6.3:1 on paper-light; 13.7:1, 7.7:1, 5.8:1 on
  paper; paper-light on ink (selected chip) 15.0:1.
- Keyboard: native `button`/`input` controls; language chips form a `radiogroup`; focus ring 3 px pen-blue,
  3 px offset; touch targets >= 40 px (>= one row in-card rows); no animation, so reduced-motion needs no
  variant.
- Frames: checked at ~360, ~768 and ~1280 px - no horizontal overflow, chips wrap, visuals scale, ruled
  alignment holds after every resize (rules stay under text baselines).
- Works without a server: one HTML file plus the shared `lesson-kit.js` beside it (the example guards:
  no kit loaded, no page), inline CSS and JS, SVG drawn in the browser.
- Rejected after review (do not retry without new evidence): translucent glass, plastic bevel cards, tilted
  cards, drop shadows under taped cards, floating language control, scratch-work scenery, hand-wobble on
  geometry and handwritten body text (both retired by founder ruling 2026-11-04).

### 10.9 Departures from §1-§9 (lesson page only)
| Earlier rule | Lesson page | Why |
|---|---|---|
| §5: no handwriting fonts (reading speed) | Caveat/Kalam for title, section headings and annotation labels; typed fonts for everything read (Courier Prime body, Bricolage controls) | handwritten warmth survives where consistently achievable; legibility first (founder ruling 2026-11-04) |
| §3/§4: one pen annotation per post | one highlighted statement per screen, plus the diagram's annotated quantities and the simulation's live state | a lesson has several things to *do*, not one to *notice*; each blue mark is an annotation or the live state |
| §5: rotation max 1.5 deg, never on text | no card rotation; tape only, -3 deg / +2 deg | tilted simulation cards looked wrong in review |
| §6: 60 px margins on a 1080 px canvas | 1.5rem gutter, `--row` rhythm | a responsive page, not a fixed-size post |
| §4: ruled lines at the 1080 px design width | same 2 px lines, `--row` pitch (36 px at default) | the pitch follows the body line-height |
Unchanged: palette, pen underline algorithm, no gradients/shadows/grain, red and green reserved, ink/paper
ratios.

### 10.10 Psychology reasoning
| Decision | Mechanism | Evidence |
|---|---|---|
| Typed body on the rules (Courier Prime) | legibility first; monospace puts every baseline exactly on its rule at every width | founder review 2026-11-04: handwritten body read as misaligned and slow |
| Handwritten accents only | the "a person made this" warmth survives where achievable | founder review 2026-11-04; WEAK claim - test |
| Text on the rule, not near it | aligned grid reads as calm and intentional; misalignment reads as a bug | MODERATE - the founder's complaints prove the negative half |
| One underlined statement per screen | isolation effect marks the sentence to remember | STRONG |
| Language bar fixed on top | always findable, never confused with a lesson control | MODERATE |
| Flat taped cards | "this part is interactive" affordance with no UI chrome | MODERATE |
| Shape and dash differences, not hue; check/cross plus words | meaning survives colour-blindness and sunlight glare | STRONG |

### 10.11 Risks and open decisions
- Ruled alignment is kit-owned (`LessonKit`): rules are drawn from measured baselines and must hold across
  360-1280 px resizes. The row-token grid + kit are unverified on real low-end Android WebView
  (MutationObserver/ResizeObserver, CSS `round()`/container queries, Hindi fallback fonts, user font-size
  zoom) - check on a real device before calling it done.
- The example used to depend on its sibling `docs/frontend/lesson-kit.js` (the canonical kit source; the shell
  copy lives in `frontend/assets/zivon.js`) - the v1.6 rewrite makes the example load the shared kit files
  directly (`../../frontend/assets/zivon.css` + `zivon.js`), so there is exactly one kit copy to rot.
  `lesson-kit.js` stays in the repo as the legacy source of the kit's LessonKit section - nothing new
  references it.
- Fonts load from Google Fonts in the example; the pipeline must vendor Caveat, Kalam, Bricolage Grotesque
  and Courier Prime into the page folder (no external calls).
- Hindi/Hinglish strings in the example were model-drafted, not reviewed by a native reader. Several
  highlighted statements per screen and multi-line statements are untested.
