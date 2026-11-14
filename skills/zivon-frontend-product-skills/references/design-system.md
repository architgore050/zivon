# Design system — Field Notes routing

The visual source of truth is **`docs/frontend/design-doctrine.md`**. This
reference tells you which part of it applies, which components already exist,
and how to extend the system without inventing a second one. It deliberately
does **not** restate pixel values, hex codes, font sizes, or spacing: those
live in the doctrine and in `frontend/assets/zivon.css`, and duplicating them
here would create a second, stale authority.

Open the doctrine before any visual decision. Open `frontend/assets/zivon.css`
and `zivon.js` before writing markup. Match the best existing page, not the
average — the published tree mixes pipeline versions.

## 1. Scope split: §1–§9 vs §10

Field Notes is the name of the whole design system, not a lesson-page style.

| Surface | Applies | Reference implementation |
|---|---|---|
| Build-in-public post visuals | §1–§9 | `docs/frontend/design-doctrine-example.html` |
| Public site, catalogue, app pages, auth, admin, any non-lesson surface | §1–§9 | `design-doctrine-example.html` |
| Generated lesson pages | §1–§9 **plus §10** | `design-doctrine-lesson-example.html` |

Two scope errors to catch in review:

- A shell/app page that borrows §10 devices — the 36 px ruled-line grid,
  handwritten Caveat/Kalam body text, taped paper cards, the fixed language
  bar — is wrong. Those belong to lesson pages.
- A lesson page that follows §1–§9 and ignores §10 is equally wrong. Lessons
  are both.

Where §10.9 lists a departure from §1–§9, §10 wins for that rule on lesson
pages only. Nothing in §10.12–§10.14 (dock, read-aloud, consent) leaks into the
public site, auth, or admin.

## 2. Tokens and typography: names, not values

Use the CSS custom properties, not raw values. The canonical values and
contrast checks are in doctrine §3, §5, §10.8, and the `:root` block of
`zivon.css`.

| Token / role | Job | Canonical source |
|---|---|---|
| `--paper` | page background, the majority of every surface | doctrine §3; `zivon.css :root` |
| `--paper-light` | cards, taped surfaces, selected-chip text | doctrine §3 |
| `--ink` | text and outlines; always the primary text colour | doctrine §3 |
| `--graphite` | labels, captions, sources, guides | doctrine §3 |
| `--pen-blue` | the one annotation, focus ring, live/selected quantity | doctrine §3, §4.1, §10.8 |
| `--pencil-red` | gap marks and honest corrections only | doctrine §3 |
| `--tick-green` | done ticks only | doctrine §3 |
| `--display` | Bricolage Grotesque: display, controls, questions | doctrine §5 |
| `--notes` | Courier Prime: typed notes, numbers, body on lesson pages | doctrine §5, §10.3 |
| `--hand` | Caveat/Kalam: titles, headings, annotation labels only | doctrine §5, §10.3 |
| `--row` | the one lesson rhythm token (rem) | doctrine §10.2 |
| `--page-w` | the one lesson content-width token | doctrine §10.2 |
| `--rule`, `--tape`, `--gutter` | ruled line, masking tape, side gutter | `zivon.css :root` |

Rules that follow from the tokens:

- Only **one pen annotation** per post or image; lesson pages allow the
  highlighted statement, the diagram's annotated quantity, and the
  simulation's live state (§10.9).
- Red means honesty (gap, mistake); green means done. They never decorate.
- Meaning is carried by **shape and words**, not hue alone. This is a
  colour-blind, sunlight, and low-quality-screen rule, not a preference.
- Paper is flat. No gradients, glass, blur, grain, drop shadows, or tilted
  cards. The only allowed shadow is the doctrine's hard offset on a taped
  screenshot, and the only allowed rotation is the tape.
- Fonts are local. Devanagari falls back per glyph through the doctrine's
  Hindi stack; set `lang="hi"` when Hindi is active.
- New type sizes, colours, or spacing values are a doctrine change, not a
  component decision. Do not add a token in a page stylesheet.

## 3. Component layers

### 3.1 The kit (already the contract)

`frontend/assets/zivon.css` + `zivon.js` are the single standard toolkit. The
CSS header is the canonical component catalog. The main families:

- **Page chrome**: `.zn-page`, `.zn-header`, `.zn-kicker`, `.zn-title`,
  `.zn-objectives-label`, `.zn-objectives`, `.zn-glossary`, `.zn-footer`.
- **Language bar**: `.zn-lang-bar`, `.zn-lang-in`, `.zn-lang-lab`,
  `.zn-lang-row[role=radiogroup]`, `.zn-chip[role=radio]`.
- **Content**: `.zn-text`, `.zn-example`, `.zn-answer`, `.zn-answer-label`.
- **Taped cards**: `.zn-reveal`, `.zn-check`, `.zn-sim`.
- **Check**: `fieldset` + `legend` (the question), native radios
  `label.zn-opt`, `.zn-check-btn`, `.zn-check-feedback[aria-live]`,
  `details.zn-check-why`; numeric variant with a 1% tolerance compare.
- **Simulation**: `.zn-sim-controls`, `label.zn-sim-control`, range + output,
  `.zn-sim-canvas-wrap > canvas.zn-sim-canvas` (kit-sized 480×320 buffer),
  `.zn-sim-desc`, `.zn-sim-read` live mirror.
- **Diagram**: `.zn-diagram` figure, `.zn-diagram-svg`, `figcaption`; geometry
  clean, annotation arrows hand-drawn, labels in the page language.
- **Behaviour services**: `wireCheck`, `ZivonSim` (rAF, reduced-motion single
  draw, on-canvas error painter), `LessonKit` (measured rules + pen underline),
  the landing course renderer, language-chip wiring.

`docs/frontend/lesson-kit.js` is the legacy source of the `LessonKit` section;
nothing new references it. The live kit is `frontend/assets/zivon.js`.
- **Wave E2 chrome**: voice dock, read-aloud, consent, report, locale bundle,
  telemetry queue, privacy wipe.

**The kit is the only owner of chrome.** Generated `page.css` may style only
inside `.zn-sim-<id>`; factory lint enforces this. A new shared need becomes a
kit component first — catalog entry, CSS, JS, states, tests — never a per-page
invention.

### 3.2 Product surfaces to build (new patterns)

The full product adds patterns the current kit does not yet have. Build them
as reusable `zn-*` components, not as one-off page markup:

- **App shell**: top bar, nav, mobile drawer, breadcrumbs, page header,
  active states, skip link.
- **Auth**: a single paper card with fields, Google button, guest link,
  error/success states — no split-screen marketing.
- **Dashboard**: a study log, not a KPI grid — continue, today, map, SWOT,
  recent activity, one primary action.
- **Practice**: exercise-book layout, one question at a time, hint margin,
  feedback panel, summary.
- **Tests**: exam-paper layout, sections, marks, question palette, timer,
  autosave, review.
- **Progress**: report-card rows, five mastery states, next step.
- **SWOT**: four labelled quadrants with evidence cards and next actions.
- **Settings/forms**: fieldsets, labels, inline errors, delete/export
  confirmation.
- **States**: empty, loading, skeleton, error, offline, permission, quota,
  consent, untranslated.
- **Voice surfaces**: dock, read-aloud, consent — already specified in
  doctrine §10.12–§10.14; do not redesign them.

Every pattern gets the component checklist
([component-checklist.md](../templates/component-checklist.md)) and the
quality floor in
[accessibility-performance-seo.md](accessibility-performance-seo.md).

## 4. Page patterns, in doctrine terms

| Surface | Pattern | What it must feel like |
|---|---|---|
| Landing | notebook page with a real short clip, a live mini-sim, one primary CTA | a working notebook, not a SaaS hero |
| Catalogue | class-grouped chapter cards, honest status, progress only when signed in | a shelf, not a marketing grid |
| Class page | chapter table/list, availability, continue/practise | a syllabus page |
| Lesson | ruled paper, clean diagrams, taped interactive cards, language bar, dock | a teacher wrote it for you |
| Dashboard | study log: continue, today, map, SWOT, recent | a student's desk |
| Practice | exercise book, one question, margin notes | working through sums |
| Test | exam paper: numbers, sections, marks, palette | a paper you can hold |
| Results | report card with evidence, not a score badge | a marked paper |
| Progress | report card + concept map | where you actually are |
| SWOT | four quadrant cards with reasons and one next action | advice, not a rank |
| Series | shelf of papers with purpose, coverage, length, language | an exam shelf |
| Auth | one paper card | a form, not a landing page |
| Admin | dense but calm tables and panels | a staff cockpit |

## 5. Extending the doctrine

The founder's visual verdict finalises a new surface. After the verdict, the
implementing agent may draft or update the product-surfaces doctrine section
(the process is in the full-frontend plan, §5.4, and locked decision 12). Rules:

- Add a new section; do not rewrite §10.12–§10.14 without explicit founder
  authorisation.
- Keep §0's scope split true: state which surfaces the new section applies to.
- Record the change as a doctrine change request (DCR) with date, verdict,
  and what changed.
- Update `docs/frontend/design-doctrine.md` in the same PR as the
  implementation.
- If the doctrine and an example disagree, the doctrine wins; fix the example.

## 6. Review checklist

- [ ] The surface uses the right scope: §1–§9 only, or §1–§9 + §10 for lessons.
- [ ] No §10 device leaked into a shell/app/admin page.
- [ ] No new colour, font, spacing, shadow, gradient, or radius was invented.
- [ ] The component exists in the kit catalog; no page-local chrome.
- [ ] One pen annotation rule respected; red/green meanings intact.
- [ ] Shape + words carry every status; no colour-only meaning.
- [ ] Local fonts only; no external asset request.
- [ ] Voice dock/read-aloud/consent match §10.12–§10.14 exactly, including
      state copy, 44 px targets, and the no-re-nag rule.
- [ ] The visual verdict record exists and its required changes are applied.
