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
Reference implementation: `design-doctrine-example.html` (same folder) — a working page that applies every token
and rule below. Open it before generating any new page or post visual; match its patterns rather than re-deriving
the look. Second reference implementation, for lesson pages: `design-doctrine-lesson-example.html` (same folder; §10).

## 0. Scope — which part of this doctrine applies where

**"Field Notes" is the name of the whole design system, not of a lesson-page style.** §1–§9 are the base system
that the entire product and every post follows. §10 is an extension that ONLY lesson pages add on top.

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

### 10.2 Page grid (36 px rhythm) and frame adaptation
- The ruled lines are the page grid. Pitch **36 px**, lines per §4 (graphite 40%, 2 px). **Every block on
  the page is a multiple of 36 px tall**: 36 px line-heights, margins and paddings sum to whole rows (card
  padding + border = one row: 17+17+1+1), visuals occupy whole rows (diagram box 288 px = 8 rows; simulation
  box a whole number of rows - 288 px in the shell, 180 px in the examples), one blank ruled row between
  blocks. Reflow may only then move a block by whole rows, never by 12 or 20 px.
- Alignment is measured, not assumed: on load, after fonts load, and on every resize the page measures
  where the text baseline sits in a 36 px line and shifts the ruled background so each rule lies **under the
  baseline**; the title is nudged (≤18 px) onto a rule too. Fonts and fallbacks align without per-font
  constants.
- **Frame adaptation (added 2026-11-04, founder ruling):** the page must be consciously designed for phones
  (~360 px), tablets and laptops. No fixed pixel widths: visuals scale through `viewBox` or fixed-height
  boxes (width 100%, fixed aspect), text capped in `ch`, chips wrap, touch targets >= 40 px (>= 36 px for
  rows inside cards), no horizontal overflow at any width. Ruled alignment must survive every resize - a
  rule sliding under text after a window change is a defect (founder-caught drift in the example; the 36 px
  block rule is the structural fix, measured re-alignment the local one).
- Page: max width 1100 px, 24 px side padding, two columns (text/diagram left, cards right), 36 px row gap,
  48 px column gap, single column below 820 px. Top padding = language-bar height rounded up to whole rows.

### 10.3 Typography on the lesson page
| Role | Font | Size / line | Notes |
|---|---|---|---|
| Title | **Caveat** 700 | clamp(46px, 7vw, 76px) / 72 | two rows tall |
| Section heading | **Caveat** 700 | 34 / 72 | two rows tall |
| Body | **Courier Prime** 400 | 17 / 36 | max 46 ch; monospace keeps every baseline exactly on its rule |
| Highlighted statement | Courier Prime 700 | 17 / 36 | §10.4 |
| Meta line (`Day 03 · Class 10 · Physics`) | Courier Prime 700 | 15 / 36 | top-left, as §6 |
| Caption, readout, labels | Courier Prime 400 / 700 | 14 / 36, 16, 14 | graphite for captions |
| Worked-example steps, glossary | Courier Prime 400 / 700 | 15 / 36 | typed notes on the paper |
| Controls, questions, feedback | Bricolage Grotesque 500 | 15-17 | typed: operated things stay legible |
| Diagram annotation labels | **Caveat** 700 | 22; key quantity 28 | the handwritten accent of §10.7 |
- Devanagari: Caveat and Courier Prime have no Devanagari glyphs - handwritten stack `Caveat, Kalam, "Segoe
  Print", "Bradley Hand", cursive` (Kalam = Hindi handwriting face); Hindi body falls back per glyph to system
  faces (Nirmala UI, Mangal). Set `lang="hi"` when Hindi is active.

### 10.4 Highlighted statement
- The sentence the learner must keep is its own paragraph in Courier Prime 700 with a pen underline (§4.1),
  followed by a blank ruled row.

### 10.5 Language (page-level setting)
- Languages in v1: English, हिन्दी, Hinglish (Hindi in Latin script). Language belongs to the page, never to a
  widget: one control switches every string - title, body, diagram and simulation labels, questions, feedback.
- The control is a bar **fixed to the top edge**: full width, paper-light, 1 px ink bottom border, no shadow, safe-area
  top padding on phones. One label in Courier Prime 14, then one chip per language.
- Chip: Bricolage Grotesque 500 / 15, min height 40 px, 2 px corners, 1 px ink border, transparent fill, ink
  text. Selected: ink fill, paper-light text (15.0:1). Selection shown by fill, never by colour alone.


### 10.6 Paper cards (things the learner operates)
- Surface: paper-light `#F6F0CF`, 1 px ink border, 2 px corners (all four, identical), padding 17 px top and
  bottom (with the borders: exactly one ruled row, so card height stays a multiple of 36 px), 18 px sides,
  36 px below. **Flat**: no shadow (§6's hard offset is only for taped *screenshots*), no tilt, no grain,
  no blur.
- Tape: one strip per card, centred 13 px above the top edge, ~92 x 27 px (second card 84 px), masking-tape
  fill `rgba(196,174,104,0.5)`, torn ends (CSS `clip-path`), rotated -3 deg / +2 deg. Rotation belongs to
  the tape only.
- Inside a card: ink for structure, graphite for guides, pen-blue for the thing that moves or is selected.
- **Simulation**: a labelled range slider (`accent-color` pen-blue, 32 px) above the drawing (SVG in the
  example, canvas in generated pages) with clean 1.5-3 px strokes - sims are precise instruments: mirror
  ink 3, normal graphite 1.5 dashed 4/6, incident ray pen-blue 3 solid with arrowhead, reflected ray
  pen-blue 3 **dashed 9/6** with arrowhead. Rays differ by dash, not colour. Readout Courier Prime 700 /
  16, `aria-live`.
- **Question**: stem in Bricolage 500 / 17; options as chips (§10.5 style) inside a `radiogroup`, each a
  native `button` with `role="radio"` and correct `aria-checked`, one selected at a time. Feedback: a check
  or cross plus one sentence in ink (Bricolage 500 / 15). Red and green stay reserved (§3): correctness uses
  shape and words, not hue.

### 10.7 Diagrams (drawn clean, annotated by hand)
- Drawn straight onto the paper, no card, in a fixed-height box (288 px = 8 rows).
- **Geometry is clean** (founder ruling 2026-11-04, replacing the hand-stroke generator for shapes): straight
  `<line>`s, true circles and arcs, consistent corners - every rectangle uses the same corner style (2 px
  rounded, or all square); three rounded corners and one right angle on a box is a defect. Widths: ground
  3, outlines 2.6, construction line graphite 2 dashed 7/8, hatching 2.2 (diagonals every 22 px), angle
  arcs pen-blue 2.2.
- **Annotations are the handwritten layer**: the arrow pointing at a part is the one hand-drawn stroke left
  on the page - the hand-stroke generator (polyline sampled every ~28 px, seeded jitter +/-0.4-1.2 px,
  quadratic smoothing, round caps) survives for annotation arrows only. Label: Caveat 700 / 22 ink; the
  quantity the lesson is about (angles `i`, `r`) pen-blue Caveat 700 / 28. Labels are page-language strings.
  No fills, gradients or icons.
- Force/quantity arrows carry honest scale: length proportional to magnitude, stated in the caption. The
  diagram carries an `aria-label` listing its labels.

### 10.8 Validation
- Contrast (computed): ink 15.0:1, pen-blue 8.5:1, graphite 6.3:1 on paper-light; 13.7:1, 7.7:1, 5.8:1 on
  paper; paper-light on ink (selected chip) 15.0:1.
- Keyboard: native `button`/`input` controls; language chips form a `radiogroup`; focus ring 3 px pen-blue,
  3 px offset; touch targets >= 40 px (>= 36 px in-card rows); no animation, so reduced-motion needs no
  variant.
- Frames: checked at ~360, ~768 and ~1280 px - no horizontal overflow, chips wrap, visuals scale, ruled
  alignment holds after every resize (rules stay under text baselines).
- Works without a server: one HTML file, inline CSS and JS, SVG drawn in the browser.
- Rejected after review (do not retry without new evidence): translucent glass, plastic bevel cards, tilted
  cards, drop shadows under taped cards, floating language control, scratch-work scenery, hand-wobble on
  geometry and handwritten body text (both retired by founder ruling 2026-11-04).

### 10.9 Departures from §1-§9 (lesson page only)
| Earlier rule | Lesson page | Why |
|---|---|---|
| §5: no handwriting fonts (reading speed) | Caveat/Kalam for title, section headings and annotation labels; typed fonts for everything read (Courier Prime body, Bricolage controls) | handwritten warmth survives where consistently achievable; legibility first (founder ruling 2026-11-04) |
| §3/§4: one pen annotation per post | one highlighted statement per screen, plus the diagram's annotated angles and the simulation's active ray | a lesson has several things to *do*, not one to *notice*; each blue mark is an annotation or the live state |
| §5: rotation max 1.5 deg, never on text | no card rotation; tape only, -3 deg / +2 deg | tilted simulation cards looked wrong in review |
| §6: 60 px margins on a 1080 px canvas | 24 px page padding, 36 px rhythm | a responsive page, not a fixed-size post |
| §4: ruled lines at the 1080 px design width | same 2 px lines, 36 px pitch | the pitch follows the body line-height |
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
| Dash, not hue, separates rays; check/cross plus words | meaning survives colour-blindness and sunlight glare | STRONG |

### 10.11 Risks and open decisions
- Ruled alignment is measured in the browser and must hold across 360-1280 px resizes (the founder caught
  drift in the example 2026-11-04). The 36 px block rule is the structural fix but is unverified on every
  phone browser, in Hindi, and with fallback fonts - check on a real low-end Android before calling it done.
- Fonts load from Google Fonts in the example; the pipeline must vendor Caveat, Kalam, Bricolage Grotesque
  and Courier Prime into the page folder (no external calls).
- Hindi/Hinglish strings in the example were model-drafted, not reviewed by a native reader. Several
  highlighted statements per screen and multi-line statements are untested.
