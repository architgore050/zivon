# Design system: Field Notes

Anchor: Lo-fi paper (Ilm-Alan "Lo-Fi": paper-yellow, not cream) with Organic honesty. Status: v0.1, proposal.

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
| ink | `#1C1B18` | 13.7:1 | text, outlines | always |
| graphite | `#5A5748` | 5.8:1 | labels, sources | small text only |
| pen-blue | `#1F3A9E` | 7.7:1 | annotation: ONE underline/circle per post | once per post/image |
| pencil-red | `#B3261E` | 5.2:1 | gap marks, "not done" stamp | gap items only |
| tick-green | `#2F6B2F` | 5.1:1 | done ticks | checklists only |
- Rules: pen-blue annotates (circle, underline, arrow) the one thing worth noticing. Pencil-red is reserved for
  honesty (gaps, mistakes). Never both blue and red annotating the same thing.

## 4. Usage rules
- Only ONE pen annotation per image or post; hand-drawn feel via slightly uneven SVG strokes, 3-4 px.
- A gap is stamped in pencil-red as `not yet` or `blocked`, with the reason beside it in ink.
- Paper texture: flat color only, optional faint ruled lines (graphite at 15% opacity), no grain overlays that
  reduce contrast.
- Proportions: 70% paper, 25% ink/graphite, 5% pen and pencil marks.

## 5. Typography
- Display and body: **Bricolage Grotesque** (500, 700, 800). Fallback: Arial, sans-serif.
- Notes and data: **Courier Prime** (400, 700), used as typed-note text for numbers, timestamps, and stamps.
  Fallback: Courier New, monospace.
- Why: Bricolage is a characterful grotesque (distinct from Inter); Courier Prime reads like typed lab notes.
  Handwriting is excluded from all content because it cuts reading speed; it is allowed only for annotations (boundary below). [MODERATE]
- Scale on 1080 px: hook 120/1.05 800; headline 76/1.1 700; body 46/1.35 500; notes 36/1.3 mono; minimum 32.
- Slight rotation (max 1.5 degrees) allowed on one card element per image, never on text paragraphs.

### Handwriting boundary (exact)
Font: **Caveat** 700, 28-34 px on a 1080 px canvas (never below 26 px), color pen-blue `#1F3A9E` (7.7:1 on paper).
- **Handwritten = annotation only.** An annotation is a note of 6 words or fewer, attached to a drawn mark (arrow,
  underline, or circle) that points AT typed content. It comments on the content; it is never the content.
- **Allowed uses:** a pointer note on the one number or phrase to remember ("the one to remember"); a note on a
  gap or decision that explains intent ("left on purpose"); a note beside a proof screenshot.
- **Never handwritten:** headlines, body text, list rows, status tags and stamps (`done`, `not yet` stay in Courier
  Prime), numbers, the day counter, buttons, captions, the ask/question, and anything inside a sentence.
- **Limits:** at most 2 annotations per image or page; the same drawn arrow style each time; slight rotation
  (-3 to -1 degrees); no mixing handwriting and typed text within one line.
- The one pen-blue annotation rule from section 4 now counts per annotation pair: underline plus its note is ONE
  annotation, so a post can carry two such pairs at most.
- **Annotations are overlays.** They are absolutely positioned on top of the design and occupy no space: they never
  push, resize, or re-space any typed element. Delete every annotation and the layout must be pixel-identical.
  The layout reserves at least 56 px of empty space directly below any element that may be annotated; the note sits in that reserved space, anchored to the element it points at. If no space is reserved, drop the note.
- Annotations are decorative to screen readers (`aria-hidden`); anything important must also appear in typed text.
- Example: field-notes-handwritten-example.html.

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