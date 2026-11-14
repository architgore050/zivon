# Worked example and anti-patterns

Two walkthroughs: a new server-rendered screen (**SWOT**) and the existing
static lesson shell. The point is the method, not the specific copy. Then the
patterns that get rejected and what to do instead.

## Part A — SWOT (`/app/swot`), a new SSR app screen

### A0. Classify

`/app/swot` is a **server-rendered app surface**, auth required, noindex. It
reads private progress data and must never be statically cached or indexed.
Owner: F8. Features: SWOT-01…SWOT-10 (student-facing 01–07 and 09–10; 08 is the
admin calibration surface). Data: `/v1/swot` and `/v1/swot/explain`; inputs are
the chapter metrics defined in the full-frontend plan §13 (weighted accuracy,
coverage, attempt rate, trend, hint rate, time ratio, speaking score, exam
weight, confidence, last activity).

### A1. Screen spec

Copy [templates/screen-spec.md](../templates/screen-spec.md). Fill:

| Field | Value |
|---|---|
| Screen | SWOT |
| Route | `/app/swot` |
| Surface | SSR, auth required, `noindex` |
| Purpose | Answer “where am I strong/weak, what next?” — not “rank me” |
| Regions | R1 app bar; R2 page header + mode/relative explanation; R3 quadrant grid; R4 unrated row; R5 evidence/next-action link; R6 “How this works” link; R7 footer |
| Components | `zn-appbar`, `zn-page-header`, `zn-swot-quadrant`, `zn-chapter-card`, `zn-mastery-pill`, `zn-button`/`zn-link`, `zn-empty`, `zn-banner` |
| Data | Chapter title, class, quadrant, weighted accuracy, coverage, trend, hint rate, time ratio, exam weight, confidence, last activity, 2–3 evidence strings, next action |
| API | `GET /v1/swot`, `GET /v1/swot/explain` |
| Events | `swot_view`, `swot_card_open`, `swot_action` |
| Auth/privacy | Student-private; no parent/share/public profile; no leaderboard |
| SEO | `noindex, nofollow`; not in sitemap; no canonical public URL |
| i18n | UI chrome + evidence in the student's locale; numbers/units formatted; no silent English |
| Perf | SSR HTML; ≤ 120 KB gzip island; no chart library; CSS grid; no animation |

The `EL-`/`INF-` rows are assigned by the element and information inventories
when the screen is specified. Do not invent IDs; cite the feature and the
inventory row once it exists.

### A2. State matrix

| State | What the student sees | Code path |
|---|---|---|
| default | Four labelled quadrants, chapter cards with 2–3 reasons and one next action, “How this works” | `[ssr]` template + `/v1/swot` |
| loading | Quadrant-shaped skeleton, not a spinner; header already painted | `[ssr]` shell + `[island]` lazy panel |
| empty | “Not enough data yet — do a practice set or a chapter test” + one action | `[ssr]` `zn-empty` |
| partial | Some chapters `unrated`, shown in a separate row, never forced into a quadrant | `[ssr]` |
| error | “Could not build your SWOT — retry” + link to progress; no stale claim | `[ssr]` panel error |
| offline | Cached snapshot + timestamp; recompute disabled with reason | `[ssr]` + cache header |
| permission-denied | n/a (private page, no device permission) | — |
| reduced-motion | Static cards; no quadrant reveal, no count-up | `[ssr]` CSS |
| untranslated | English evidence + visible marker; labels localized | `[ssr]` |
| quota-exhausted | n/a (SWOT does not spend voice credits) | — |
| consent-missing | n/a (SWOT does not use the mic) | — |

### A3. Layout and components

- R1 app bar: dashboard / courses / practice / tests / progress / SWOT /
  settings; current section marked.
- R2 page header: “Your SWOT”, one sentence on relative placement (“compared
  with your other chapters”), and a link to “How this works”.
- R3 grid: Strengths, Weaknesses, Opportunities, Threats (watch-outs). Each
  quadrant is a labelled section with a short definition and a list of cards.
- A card: chapter title, class, 2–3 evidence bullets, one next action, and a
  link to the chapter. Pace evidence is included when it exists (“2.1× expected
  time, high accuracy — exam-pace risk”).
- R4 unrated row: “Not enough evidence yet” with the chapters and what would
  raise confidence.
- No radar chart, no gauge, no single “ability score”, no share button.
- On 360 px the quadrants stack; the order is Strengths → Weaknesses →
  Opportunities → Threats, with the heading repeated per block.

### A4. Honesty rules

- Default placement is relative to the student's own chapters; fewer than three
  chapters with evidence → “Not enough data yet”.
- Every card explains itself in plain language, including pace; no black box.
- Exam weight raises priority inside Weakness/Threat; it is not a fifth
  quadrant.
- The absolute-threshold mode is dormant behind `SWOT_MODE`; do not surface it
  as a student setting.
- “Weakness” means effort without results, not “you are bad”. “Threat” is a
  watch-out, not a prediction.
- Delete account deletes the evidence; no parent, share, or public profile.

### A5. Visual example and verdict

Build a standalone example with mock chapters at port **8108**. Show:

- default with 5 chapters;
- `?state=empty` (fewer than 3 with evidence);
- `?state=error` (panel error);
- `?state=unrated` (mixed);
- 360 px, 768 px, 1280 px.

Review note: “Check the quadrant definitions, the evidence wording, and
whether the next action is obvious. The cards use mock data; the real API is
`/v1/swot`.”

Verdict example (record it in
[templates/visual-verdict.md](../templates/visual-verdict.md)):

> Approve with changes. Put the next action at the top of each card. Make the
> unrated row visually separate. Drop the quadrant tint; use the heading and a
> rule. Keep the pace evidence. Add the “How this works” link.

Then implement: Jinja template, route, `zn-swot-quadrant` in the kit, CSS grid,
no chart library, tests for the four quadrants, unrated row, error, offline,
and noindex. Update `docs/frontend/design-doctrine.md` with the approved
SWOT pattern (new section, DCR), and the frontend spec/state matrix.

### A6. Tests

- Static: `noindex`, no external refs, no share controls, headings/landmarks.
- Behaviour: quadrant rendering, unrated row, next action link, error retry.
- A11y: keyboard path, focus ring, 44 px action, no colour-only quadrant.
- Perf: SSR HTML, island bytes, no chart library, 360 px no overflow.
- Privacy: no parent/share/public profile; delete removes evidence.

## Part B — Lesson shell (static generated page)

### B0. Classify

`/courses/class-9-physics/motion/` is a **generated static lesson**: the factory
writes the content; the shell injects the product chrome. It is indexable,
works offline, and is readable with JavaScript off.

### B1. What the factory emits vs what the shell adds

| Factory (content) | Shell (chrome) |
|---|---|
| `<link>` to `zivon.css`, `<script>` to `zivon.js` | Language bar wiring, read-aloud controls |
| Header, objectives, text, diagrams, sims, checks, worked examples, reveals, glossary, sources | Consent gate, voice dock, report form, credit/offline notices |
| Stable `id="b-NN"` on every block; `data-block-type`; `data-element-id`; `manifest.json`; `i18n.js` when translated | Privacy link, locale controls, highlight ring, context snapshot |
| CSP with `connect-src 'self'` | Same-origin `fetch`/`WS`, no external host |

The factory **must not** emit dock, consent, read-aloud, or report markup. The
shell mounts once, idempotently, and every surface is additive. If the manifest
is missing, read-aloud renders no buttons; if consent is declined, the dock
never mounts; if the dock doctrine is absent, the dock stays hidden.

### B2. State matrix

| State | What the student sees |
|---|---|
| default | Ruled paper, text, diagram, sim, check, language bar, “Ask” tab after consent |
| loading | Static HTML first; sim first frame inside budget; no spinner |
| empty | n/a (a published lesson cannot be empty) |
| partial | Some blocks untranslated → English + marker; a missing narration asset → no button |
| error | Broken sim → on-canvas painter + mirror; kit failure → content readable |
| offline | Cached page + read-aloud; dock offline; typed path open |
| permission-denied | `MIC OFF` stamp + “lesson chalta rahega” + typed field |
| reduced-motion | Sim draws once; no bars/caret; caption instant |
| untranslated | English + `.zn-untranslated-notice` per block; units/symbols fixed |
| quota-exhausted | `text_only` dock + ledger line; reading/sims/typing free |
| consent-missing | Consent sheet first; decline hides voice quietly, no re-nag |

### B3. Visual example and verdict

Port **8104**. Use a content-only fixture with a header, text, diagram,
simulation, check, and sources; no factory run. Show the default, JS-off,
missing-manifest, consent-declined, and 360 px states. The verdict is usually
about the shell chrome, not the lesson content.

After approval, the implementation is: a renderer hook if a hook is missing
(factory owner), a kit change if the chrome needs a component, and shell tests.
Do not re-render the whole pipeline to fix a shell detail.

## Part C — Anti-patterns

| Anti-pattern | Why it fails here | Do instead |
|---|---|---|
| **SaaS dashboard** | KPI cards, gradients, and “engagement” charts sell a tool, not a study room. The doctrine's anti-pattern list names polish, gradients, stock photos, and corporate icons. | A study log: continue, today, map, SWOT, recent, one action. |
| **Gradients, glass, blur, drop shadows** | Rejected in doctrine §10.1 and §10.8: flat paper read as the most honest. | Flat `--paper`/`--paper-light`, 1 px ink borders, tape only. |
| **Leaderboards, ranks, streaks, badges** | The product is private to the student; no parent, no share, no public profile. Streak loss is a dark pattern. | Weekly rhythm: days active + a goal; private evidence. |
| **SPA / client router / hydration framework** | Breaks SEO, low-end Android, offline reading, and the no-framework rule. | Static pages + SSR + small vanilla islands. |
| **Colour-only mastery** | Fails colour-blind and sunlight; the doctrine requires shape + words. | Words + shape + fill; `aria-label`. |
| **Fake data in product code** | A dead page that looks alive is worse than an empty state. | Fixtures only in examples; honest empty/error states in product. |
| **Dead controls** | “Coming soon” buttons and disabled links train students to distrust the page. | Render nothing or a non-interactive status with a reason. |
| **Modal everything** | Dialog fatigue; focus traps and scroll locks on a phone. | Inline disclosure, sheet only where doctrine says, dialog for decisions. |
| **Autoplay audio/video** | Fails WCAG 1.4.2 and the doctrine; startling for a child. | A play control with a transcript; audio on user action only. |
| **Hidden or removed focus** | Fails 2.4.7 and keyboard use. | 3 px pen-blue ring, 3 px offset, always visible. |
| **Placeholder as label** | The label disappears as soon as the student types. | Visible label above the field; placeholder as an example. |
| **External fonts/CDN/analytics** | Violates CSP, privacy, offline, and the child-data rule. | Local fonts, no third-party host, first-party telemetry. |
| **Inline scripts / `eval`** | CSP forbids them; they are an XSS surface. | External files, `defer`, strict CSP. |
| **Translating units/symbols** | Physics notation is not prose; units are fixed. | Translate labels; never translate units, symbols, equations, autonyms. |
| **Silent language fallback** | The student cannot tell which language they are reading; unreviewed content looks reviewed. | English + visible “not available yet” marker. |
| **“Mark complete” button** | The lesson's job is learning, not compliance; progress is derived. | Derive progress from view/scroll/check evidence; no button. |
| **Chat-bubble dock / second chat surface** | The doctrine's dock is a paper slip, one conversation, one transcript. | Follow §10.12 exactly; no floating dark bubble, no second surface. |
| **Progress bar or timer in the dock** | Gamifies a 20-second help surface; the doctrine forbids it. | State words, caption, mic, transcript, typed path. |
| **“Official CBSE paper”** | False affiliation and a legal risk. | “Close to the paper pattern”, “built for practice”, “not an official CBSE paper”. |
| **Reading the whole page to find the CTA** | The dashboard's job is one next action. | One primary CTA; secondary actions below. |
| **Charts without a reading** | A number or quadrant without a plain-language reason is a black box. | 2–3 evidence bullets + one next action. |
| **A new colour to signal a state** | It breaks the palette and the colour-blind rule. | Use the doctrine tokens and a word/shape. |
