# Design system: Field Notes

Anchor: Lo-fi paper (Ilm-Alan "Lo-Fi": paper-yellow, not cream) with Organic honesty. Status: v1.0, **confirmed**
(founder decision 31 Oct 2026): the single visual source of truth for all post visuals and the product UI.
Applied to the Day 0 post kit, the Day 1 post kit, and everything after.
Reference implementation: `design-doctrine-example.html` (same folder) — a working page that applies every token
and rule below. Open it before generating any new page or post visual; match its patterns rather than re-deriving
the look.

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
- Paper texture: flat color only, optional faint ruled lines (graphite at 15% opacity), no grain overlays that
  reduce contrast.
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
| position | stroke centerline = baseline + 0.5em below the text | sits under the descender line |
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
- **Connector arrow**: same stroke generator on a quadratic-bezier shaft (constant 0.045em width); barbs open
  backwards from the tip (reverse tip tangent rotated ±30°, length 0.17em).
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
