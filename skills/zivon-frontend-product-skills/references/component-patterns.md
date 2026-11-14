# Component patterns

How to choose, build, and review a UI component without inventing a new visual
language. The kit is the contract: a component that is shared goes into
`frontend/assets/zivon.css` + `zivon.js` first, with its catalog entry, states,
and tests. A page-local copy is a defect.

Read the doctrine first ([design-system.md](design-system.md)). This file is
about behaviour, states, and usage — not pixels.

## 1. The component checklist

Every new or changed component answers all of these. Copy
[templates/component-checklist.md](../templates/component-checklist.md) into the
PR.

| Item | Question |
|---|---|
| Name and family | Is it a kit component (`zn-*`) or a new shared component? What family: navigation, input, card, progress, dialog, media, state, exam, voice, table? |
| File | Where does it live? `zivon.css` catalog, `zivon.js` behaviour, an SSR partial, or an island? |
| Markup contract | What exact HTML does the renderer/template emit? What classes, roles, and data attributes are stable? |
| Variants | Primary/secondary/quiet/danger; selected/unselected; compact/default; the variants the product actually needs. |
| States | default, hover, focus, active, disabled, loading, error, empty, partial, offline, permission, reduced-motion, untranslated, quota, consent — as applicable. |
| Keyboard | Tab order, Enter/Space, arrow keys for radio/tab groups, Esc, focus return. No keyboard trap. |
| ARIA | Role, accessible name, state (`aria-pressed`, `aria-checked`, `aria-expanded`, `aria-live`), described-by for errors. |
| Target size | At least 44 × 44 px for touch, even when the visual is smaller; spacing counts. |
| Reduced motion | What stops, what becomes instant, what static frame remains. |
| i18n | Copy keys, pluralization, number/date format, `lang` changes, never-translate values. |
| Privacy | What data the component reads or emits; no free text, no PII, no raw audio. |
| Performance | DOM node budget, no layout thrash, transform/opacity only, lazy media. |
| Tests | One static/markup test, one behaviour test, one state or a11y assertion. |
| Usage rules | When to use it, when not to, and what it must never become. |

## 2. Navigation and shell

### App bar and public header

- One `<header>` landmark, a wordmark link home, primary nav, and the
  account/guest action.
- Signed-in app bar: dashboard, courses, practice, tests, progress, settings;
  a mobile drawer below the breakpoint; the current section marked with
  `aria-current="page"`.
- Skip link is the first focusable element on every page.
- Sticky bars must not cover a focused control when the page scrolls
  (WCAG 2.4.11); test at 360 px.
- No mega-menu, no hover-only navigation, no hidden focus.

### Drawer

- Used for lesson chapter navigation and mobile app nav.
- Native `<dialog>` or a labelled region with a visible close, Esc to close,
  focus contained only while modal, focus returned to the trigger.
- The lesson page stays scrollable when the drawer is closed.
- Do not use a drawer as a second conversation surface.

### Breadcrumbs

- One `<nav aria-label="Breadcrumb">` with an ordered list; the current page is
  not a link.
- Use on class/chapter/test-series detail pages where hierarchy matters; skip
  on the dashboard and lesson body.

### Tabs and filter bar

- Tabs are a `tablist` with arrow-key movement and one selected tab; filters are
  a group of toggle buttons or a form, not fake tabs.
- The selected state uses fill/border + text, never colour alone.
- On 360 px the bar scrolls horizontally only if it must; the page itself never
  overflows.

## 3. Cards

### Chapter card

- Title, class, chapter number, status (`live`, `in development`, `practice
  coming`, `series available`), language availability, lesson/practice/test
  counts, progress only when signed in.
- The whole card is a link to a real page; a disabled card is not a link.
- No dead “coming soon” link. If the page does not exist, the card says so and
  is not focusable.

### Series card

- Purpose, class, chapters covered, number of papers, length, difficulty,
  language set, and the approved non-affiliation copy for CBSE-style series.
- One primary action: start or resume. No fake “best seller” badges.

### Question card / answer option

- One question stem, options as a `radiogroup` or native radios, a numeric
  input with a declared tolerance, and a Check action.
- Answer options are at least 44 px tall, wrap without clipping, and show
  selected state by fill + `aria-checked`.
- Feedback is a check/cross **plus words**; it is `aria-live="polite"` and
  never a colour-only flash.
- Do not reveal the answer before commit. Hints are one at a time and are
  recorded.

### Stat / report-card row

- Label, value, unit, and a plain-language reading. A number without a meaning
  is decoration.
- No animated counters. No comparison to other students.

## 4. Progress and mastery

- Five states: **Not started**, **Learning**, **Practising**, **Confident**,
  **Needs revision**. Use the words, not only a colour.
- A progress bar has an accessible name and `aria-valuenow/min/max`; a ring is
  decorative unless it also exposes the same text.
- No streak loss, no leaderboard, no public rank, no “you are behind” copy.
- Weekly rhythm is days active + a goal; a missed day is neutral.
- A mastery pill never claims precision the evidence does not support; thin
  evidence is “Unrated” or “Learning”, not “Confident”.

## 5. SWOT quadrant

- A 2×2 labelled grid: Strengths, Weaknesses, Opportunities, Threats
  (watch-outs). Each quadrant has a heading and a short explanation.
- Each chapter card shows the chapter, the quadrant, 2–3 evidence bullets
  (including pace), and one next action.
- Default is relative placement; do not label a chapter “weak” from one attempt.
- Fewer than three chapters with evidence → “Not enough data yet” row.
- No share, parent, public profile, or cohort comparison controls.
- On narrow screens the quadrants stack in a readable order, not a squeezed
  2×2.

## 6. Forms

- One paper card for auth; labels above fields; placeholders are examples, not
  labels.
- Every input has a visible label, an `id`, and an error tied with
  `aria-describedby`; the error text says how to fix it.
- `autocomplete` is set for email, current-password, new-password, name.
- Password fields have a show/hide control with an accessible name; no
  composition rules theatre (length + blocklist, not “one symbol”).
- Submit shows a submitting state, disables double submits, and keeps the
  entered values on error.
- No timeout without a warning; no CAPTCHA for a child audience unless legally
  required.
- Delete/export confirmations state exactly what will be deleted or exported;
  the destructive action is not the default focus.

## 7. Dialogs, sheets, toasts

### Dialog

- Use for a blocking decision: consent, delete confirmation, submit
  confirmation.
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby`; focus moves in,
  is contained, and returns to the trigger; Esc closes unless the action is
  destructive and incomplete (then it asks).
- The page behind is inert while open; scroll lock only for a modal.
- The consent sheet is specified by doctrine §10.14; do not redesign it.

### Sheet

- The voice dock is the canonical bottom sheet; doctrine §10.12 owns it.
- A generic sheet (settings, filters) is not a second dialog and not a route.
- It respects `env(safe-area-inset-bottom)`, never covers the language bar, and
  never locks page scroll unless it is modal.

### Toast and banner

- A toast is for a transient confirmation, not for an error that needs a
  decision.
- One toast at a time; `role="status"`; it does not steal focus; it disappears
  without taking the only copy of the message with it.
- A banner is persistent: offline, voice-limited, typed-only, email-unverified.
  It has a dismiss only if the condition is not ongoing.

## 8. Empty, loading, error, offline

- **Empty**: say what is missing, why, and one action. “No doubts yet — ask one
  from a lesson.”
- **Loading**: server-rendered pages paint content first; islands use a quiet
  inline status or skeleton shaped like the content. No full-page spinner.
- **Error**: one sentence, a retry, and a way back. No stack trace, no raw
  model text, no “unknown error”.
- **Offline**: keep the readable content; disable the network action with a
  reason. Never fake a success.
- **Partial**: render what exists, label the missing part, and do not link to a
  page that is not published.
- **Skeleton**: same size as the final block so the layout does not jump; no
  shimmer under reduced motion.

## 9. Exam paper, timer, palette

- Paper header: title, class, sections, total marks, duration. Sections A–E
  where the pattern has them.
- Question numbers are stable; marks sit next to the question, not in a
  separate legend only.
- Palette: one cell per question with answered / unanswered / marked-for-review
  / current states, each identified by shape + text or an accessible label, not
  colour alone. Arrow keys move; Enter opens.
- Timer: text, announced sparingly (not every second), with a warning before
  expiry; expiry auto-submits and says so.
- Autosave indicator: “saving”, “saved”, “could not save — retrying”; never
  claim saved when the request failed.
- Full-paper mode and chapter-test mode share the same components; the
  structure differs, not the interaction language.

## 10. Audio, voice, transcript

- The voice dock, mic button, read-aloud, consent, and transcript follow
  doctrine §10.12–§10.14 exactly. Copy is in the F-table; do not invent state
  names.
- Mic is a toggle/hold control with `aria-pressed`; a playing narration stops
  when the mic is pressed (echo guard).
- Transcript is `aria-live="polite"` but throttled; the partial caption is
  optional and off by default.
- Audio never autoplays. A play control has a visible label, not a bare icon.
- Waveform is decorative if the transcript and state words carry the meaning.
- Every audio surface has a text path; voice failure never blocks the lesson.
- 44 px minimum for mic, stop, play, chips, and dock controls.

## 11. Tables and status

- Tables use `<caption>`, `<th scope>`, and a responsive overflow container;
  the page itself does not overflow.
- Status pills use words + shape; colour is secondary. No green/red as the only
  signal.
- Source chips name the source and licence; they are not decorative.
- Copy flags (“close to the paper pattern”, “not an official CBSE paper”) are
  part of the component, not a footnote someone can delete.

## 12. Naming and extension rules

- Shared classes use the existing `zn-` prefix and the kit's flat naming; do
  not introduce a second prefix or a CSS-in-JS pattern.
- A new component starts in the kit catalog with its markup contract, states,
  and tests. A page may compose it; a page may not fork it.
- A one-off layout is CSS on a page; a repeated behaviour is a component.
- Never restyle a kit component from a generated `page.css`; only
  `.zn-sim-<id>` is in scope for generated pages.
- A component that needs a new colour, font, or spacing token is a doctrine
  change; stop and ask.

## 13. Review checklist

- [ ] The component exists in the kit (or a justified SSR partial), not a
      page-local copy.
- [ ] Every applicable state is designed and tested.
- [ ] Keyboard and screen-reader paths are complete.
- [ ] 44 px targets, visible focus, no focus trap except a modal.
- [ ] Reduced motion is honoured.
- [ ] Copy is keyed and translatable; units/symbols are not translated.
- [ ] No colour-only meaning; no dead control.
- [ ] No external asset, font, or script.
- [ ] DOM/JS budget respected.
- [ ] The visual verdict record covers the component.
