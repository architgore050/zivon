# Design system: Field Notes

Anchor: Lo-fi paper (Ilm-Alan "Lo-Fi": paper-yellow, not cream) with Organic honesty. Status: v1.0, **confirmed**
(founder decision 31 Oct 2026): the single visual source of truth for all post visuals and the product UI.
Applied to the Day 0 post kit, the Day 1 post kit, and everything after.
v1.1 (1 Nov 2026) extends the system to the lesson page of the product (§10); §1–§9 are unchanged.
v1.2 (2 Nov 2026) adds §0: the scope split between the base system and the lesson extension is now explicit.
No visual rule changed.
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

## 10. Lesson page (extension, v1.1)

Scope: **lesson pages only** — the study-material page a learner opens in the product (a topic, its diagram, one
simulation, one question). §1–§9 stay in force for this page and unchanged for every other surface; §10 adds
rules for this page type and lists, in §10.9, every place where it departs from them. Nothing in §10 (ruled
grid, handwritten body, taped cards, language bar) may leak into the site shell or post visuals — see §0.
Reference implementation: `design-doctrine-lesson-example.html` (a working page that applies every rule below).

### 10.1 Intent
- Metaphor: a ruled notebook page. Text is **written** on the lines, diagrams are **sketched** on the paper, and anything
  the learner operates (simulation, question) is a **paper card taped** onto the page.
- **Hand-drawn by default** (added 2026-11-04, founder ruling): every visual element on this page belongs to the
  notebook world. Strokes, rules, borders, arrows, underlines, tape, check marks, dividers — anything drawn follows
  the hand-drawn language (§4.1 pen algorithm for pen marks, §10.7 hand-stroke generator for diagram strokes, ink
  palette and flat tape for structure). Sharp browser-default UI chrome is a defect, not a neutral look. Two
  deliberate exceptions: the typed layer (controls, questions, feedback stay typed per §10.3) and native form
  controls styled only with palette tokens (e.g. the slider `accent-color`). Arrows and underlines are examples of
  this rule, not its limit.
- Feeling at 1 second: "someone wrote this out for me by hand, and I can touch the parts that move."
- Anti-patterns: glass, blur, translucency, gradients, shadows under taped cards, tilted cards, grain (all tried in
  review on 1 Nov and rejected; flat paper-light read as the most honest).

### 10.2 Page grid (36 px rhythm)
- The ruled lines are the page grid. Pitch **36 px**; the lines keep the §4 spec (graphite 40%, 2 px). Every text block
  on the page is a multiple of 36 px tall, and one blank ruled row separates paragraphs.
- Alignment is measured, not assumed: on load (and after fonts load or the window resizes) the page measures where the
  handwriting baseline sits inside a 36 px line and shifts the background so each rule lies directly **under the
  baseline** of the text. The title is measured the same way and nudged (at most 18 px) so its baseline also lands
  on a rule. Different fonts (Caveat, Kalam, fallbacks) therefore align without per-font constants.
- Page: max width 1100 px, 24 px side padding, two columns (text and diagram left; cards right) with 36 px row gap and
  48 px column gap; single column below 820 px. Top padding = language-bar height rounded up to whole rows.

### 10.3 Typography on the lesson page
| Role | Font | Size / line | Notes |
|---|---|---|---|
| Title | **Caveat** 700 | clamp(46px, 7vw, 76px) / 72 | two rows tall, baseline on a rule |
| Body | **Caveat** 500 | 30 / 36 | max 46 characters per line |
| Highlighted statement | Caveat 700 | 30 / 36 | §10.4 |
| Meta line (`Day 03 · Class 10 · Physics`) | Courier Prime 700 | 15 / 36 | top-left, as §6 |
| Caption, readout, labels | Courier Prime 400 / 700 | 14 / 36, 16, 14 | graphite for captions |
| Controls, questions, feedback | Bricolage Grotesque 500 | 15–17 | typed: the thing to operate stays legible |
- Devanagari: Caveat has no Devanagari glyphs, so the stack is `Caveat, Kalam, "Segoe Print", "Bradley Hand", cursive`.
  Kalam (400, 700) is the handwriting face for Hindi; the browser falls back per glyph. Set `lang="hi"` on the page
  when Hindi is active.

### 10.4 Highlighted statement
- The one sentence the learner must keep is its own paragraph in Caveat 700, followed by a blank ruled row.
- Its underline is the **pen underline of §4.1 with unchanged parameters** (centerline = baseline + 0.3em, seeded from
  the sentence, pen-blue). For a statement that wraps, the underline sits under the **last line** and spans that
  line's ink width. The generator measures the baseline of the last line instead of assuming it.
- At most **one** highlighted statement per screen.

### 10.5 Language (page-level setting)
- Languages in v1: English, हिन्दी, Hinglish (Hindi in Latin script). Language belongs to the page, never to a widget:
  one control switches every string: title, body, diagram labels, simulation labels, questions, feedback.
- The control is a bar **fixed to the top edge**: full width, paper-light, 1 px ink bottom border, no shadow, safe-area
  top padding on phones. One label in Courier Prime 14, then one chip per language.
- Chip: Bricolage Grotesque 500 / 15, min height 40 px, 2 px corners, 1 px ink border, transparent fill, ink text.
  Selected: ink fill, paper-light text (15.0:1). Selection is shown by fill, never by colour alone.

### 10.6 Paper cards (things the learner operates)
- Surface: paper-light `#F6F0CF`, 1 px ink border, 2 px corners, padding 24 / 18 / 20, 48 px below. **Flat**: no shadow
  (§6 allows a hard offset only under taped *screenshots*; these are not screenshots), no tilt, no grain, no blur.
- Tape: one strip per card, centred on the top edge, 13 px above it. About 92 × 27 px (second card 84 px), fill
  `rgba(196,174,104,0.5)` (translucent masking tape: the card border shows faintly through), jagged torn ends (4%
  teeth, CSS `clip-path`), rotated -3° on the first card and +2° on the second. Rotation belongs to the tape only.
- Inside a card: ink for structure, graphite for guides, pen-blue for the thing that moves or is selected.
- **Simulation**: a labelled range slider (`accent-color` pen-blue, height 32 px) above an SVG with 1.5-3 px strokes:
  mirror ink 3, normal graphite 1.5 dashed 4/6, incident ray pen-blue 3 solid with arrowhead, reflected ray pen-blue
  3 **dashed 9/6** with arrowhead. Rays differ by dash, not colour. Readout in Courier Prime 700 / 16 with `aria-live`.
- **Question**: stem in Bricolage 500 / 17 / 1.4, options as chips (§10.5 style), one selected at a time. Feedback is
  a ✓ or ✗ plus one sentence in ink (Bricolage 500 / 15). Pencil-red and tick-green stay reserved (§3): correctness
  uses shape and words, not hue.

### 10.7 Diagrams (sketched, not carded)
- Drawn straight onto the paper, no card, in a fixed-height box (288 px = 8 rows) so the grid is not disturbed.
- Strokes come from the **hand-stroke generator**: a polyline is sampled every ~28 px, each point jittered
  (+/-0.4 to +/-1.2 px depending on stroke type, **seeded** so a redraw is identical), then smoothed with quadratic curves; round
  caps and joins. Widths: ground/mirror 3.8, rays 3.2, arrowheads 3 (16 px barbs), construction line graphite 2.6
  dashed 7/8, hatching 2.2 (diagonals every 22 px), angle arcs pen-blue 2.2.
- Labels: Caveat 700 / 22 ink; the quantity the lesson is about (angles `i`, `r`) in pen-blue Caveat 700 / 28.
  Labels are page-language strings. No fills, no gradients, no icons.
- The diagram carries an `aria-label` that lists its labels.

### 10.8 Validation
- Contrast (computed): ink on paper-light 15.0:1, pen-blue on paper-light 8.5:1, graphite on paper-light 6.3:1, ink on
  paper 13.7:1, pen-blue on paper 7.7:1, graphite on paper 5.8:1; paper-light on ink (selected chip) 15.0:1.
- Keyboard: every control is a native `button` or `input`; language chips form a `radiogroup`; focus ring 3 px
  pen-blue, 3 px offset; touch targets >= 40 px; no animation, so reduced-motion needs no variant.
- Works without a server: one HTML file, inline CSS and JS, SVG drawn in the browser.
- Rejected after review (do not retry without new evidence): dark or light translucent glass, plastic bevel cards,
  tilted cards, drop shadows under taped cards, floating (non-fixed) language control, scratch-work scenery.

### 10.9 Departures from §1–§9 (lesson page only)
| Earlier rule | Lesson page | Why |
|---|---|---|
| §5: handwriting fonts excluded (reading speed) | Caveat/Kalam for title, body, statements, diagram labels; typed fonts for meta, controls, feedback | the notebook metaphor is the product's look; reading speed is the cost (see §10.10) |
| §3/§4: one pen annotation per post | one highlighted statement per screen, plus the diagram's annotated angles and the simulation's active ray | a lesson has several things to *do*, not one thing to *notice*; each blue mark is either an annotation or the live state |
| §5: rotation max 1.5° on one card, never on text | no card rotation; tape only, -3° / +2° | tilted simulation cards looked wrong in review |
| §6: 60 px margins on a 1080 px canvas | 24 px page padding, 36 px rhythm | a responsive page, not a fixed-size post |
| §4: ruled lines 2 px at the 1080 px design width | same 2 px lines, 36 px pitch | the pitch follows the handwriting size |
Unchanged: palette, pen underline algorithm, no gradients/shadows/grain, red and green reserved, ink/paper proportions.

### 10.10 Psychology reasoning
| Decision | Mechanism | Evidence |
|---|---|---|
| Handwritten body | "a person wrote this" warmth, lowers authority distance for a young learner | WEAK / heuristic; test |
| Text on the rule, not near it | an aligned grid reads as intentional and calm; misalignment reads as a bug | MODERATE (visual alignment) |
| One underlined statement per screen | isolation effect marks the sentence to remember | STRONG |
| Global language bar fixed on top | the setting is always findable and never confused with a lesson control | MODERATE |
| Flat taped cards | clear "this part is interactive" affordance with no UI chrome | MODERATE |
| Dash, not hue, separates rays; ✓/✗ plus words | meaning survives colour-blindness and sunlight glare | STRONG |

### 10.11 Risks and open decisions
- Handwriting slows reading, most for Devanagari and for long passages. Keep lessons short; measure comprehension and
  reading time with the test learner before widening handwritten text.
- Fonts load from Google Fonts in the example. The build-time pipeline must vendor Caveat, Kalam, Bricolage Grotesque
  and Courier Prime into the page folder before offline use or any "no external calls" requirement.
- Hindi and Hinglish strings in the example were drafted by the model and are not reviewed by a native reader.
- Baseline alignment is measured in the browser; it has not been checked on every phone browser, in Hindi, or with
  fallback fonts. Check it on a real low-end Android before declaring it done.
- Several highlighted statements per screen and multi-line statements are untested.
