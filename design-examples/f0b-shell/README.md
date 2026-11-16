# F0B — Field Notes shell exploration

**Status:** WIP design exploration for the founder's visual verdict. Not product code, not a PR.
**Branch:** `feature/w1-f0b-design-shell` · **Base:** `main` @ `03fd190`
**Local review:** <http://127.0.0.1:8101/>

This bundle answers one question: **what do the shared Field Notes design system and app shell
look like around the real lesson?** It covers the public shell, the signed-in app shell, the
lesson chrome, the shared components, and the states between them. Everything is standalone
HTML/CSS/JS with mock data; there is no backend, no network request, no microphone, no
localStorage, no analytics, and no build step.

The visual source of truth is `docs/frontend/design-doctrine.md` **§1–§9** for every non-lesson
surface, and **§10** for the lesson excerpt only. No new palette, font, radius, shadow, gradient,
or visual language is introduced. The only new values are shell layout widths and spacing
(`--shell-w`, `--read-w`, `--measure`, `--pad`, `--gap`) — layout, not style — and they are
part of what the verdict decides.

The repeating horizontal rule behind every shell page is the doctrine's §4 paper texture (the
same 2 px graphite rule the live shell uses), not a decorative gradient. The lesson paper draws
the same rule on the 36 px row rhythm.

## Serve it

```bash
cd /home/archit-gore/projects/zivon/tmp/worktrees/w2-f0b
python3 -m http.server 8101 --bind 127.0.0.1 --directory design-examples/f0b-shell
```

Open <http://127.0.0.1:8101/>. The server is already running for review; stop it with the PID in
`/tmp/f0b-server.pid` if needed.

## Start here

| Page | What it proves |
|---|---|
| [`index.html`](http://127.0.0.1:8101/index.html) | Cover sheet, screen index, palette/type specimen, review checklist |
| [`components.html`](http://127.0.0.1:8101/components.html) | Every shared component with its variants and states |
| [`states.html`](http://127.0.0.1:8101/states.html) | The state kit + live 360 px frames + the shell-level 11-state table |

## The screens

### Public shell (§1–§9 only)

| Screen | URL | Notes |
|---|---|---|
| Courses catalogue | [`catalogue.html`](http://127.0.0.1:8101/catalogue.html) | Class tabs, search, honest status; a syllabus/list, not a marketing card grid |
| Class page | [`class.html`](http://127.0.0.1:8101/class.html) | Progress summary, five mastery states, chapter list, one continue action |
| Method / pricing / trust | [`public-info.html`](http://127.0.0.1:8101/public-info.html) | Text-heavy public page with sticky on-page nav |

The public header carries the wordmark, primary nav, log-in and one primary action. Below
1080 px the nav collapses into a left drawer with a 56 px row height and a visible Close.
The skip link is the first focusable element on every page.

### Authenticated app shell

| Screen | URL | Notes |
|---|---|---|
| Dashboard / study log | [`dashboard.html`](http://127.0.0.1:8101/dashboard.html) | Continue, Today, map, SWOT snapshot, weekly rhythm, recent activity |
| Practice question | [`practice.html`](http://127.0.0.1:8101/practice.html) | One question, hint margin, check, feedback and Why? |
| Speaking recorder | [`speaking.html`](http://127.0.0.1:8101/speaking.html) | Prompt, 45 s timer, mic, transcript, rubric, model answer |
| Test player | [`test.html`](http://127.0.0.1:8101/test.html) | Exam-paper header, sections, marks, timer, palette, autosave, submit |
| Results / review | [`results.html`](http://127.0.0.1:8101/results.html) | A marked paper: score, accuracy, pace, chapter breakdown, every question |
| SWOT | [`swot.html`](http://127.0.0.1:8101/swot.html) | Four labelled quadrants with evidence and one next action |
| Settings | [`settings.html`](http://127.0.0.1:8101/settings.html) | Profile, voice, accessibility, privacy, delete/export |

The app bar holds the class/subject context switcher, five primary destinations, a voice-credit
chip, and the user menu. Below 1080 px the nav, credits and user menu move into the menu drawer;
the class context stays visible. The test player uses a compact exam-mode bar with no nav.

### Lesson shell (the §10 exception)

[`lesson.html`](http://127.0.0.1:8101/lesson.html) wraps a copied excerpt of the published
Class 9 lesson **How forces affect motion** in the product chrome:

- app bar, breadcrumb, Contents / Bookmark / Report toolbar;
- sticky language bar with English / हिन्दी / Hinglish;
- §10 ruled paper, typed Courier body, Caveat title, taped check card, clean diagram;
- read-aloud control, end-of-lesson CTA, sources footer;
- the **collapsed** voice-dock strip (§10.12) and the **consent sheet** (§10.14).

The lesson page is the only page that loads `lesson.css`. Nothing from §10 (ruled grid, taped
cards, handwriting) leaks into the public or app shell.

## How to see the states

Every screen has a **State** selector in the dark review strip at the very top. It is example
chrome, not product chrome: it is labelled `NOT PRODUCT CHROME` and loads no product data.

Direct URLs:

- `dashboard.html?state=loading|empty|error|offline|auth|quota`
- `practice.html?state=loading|empty|error|offline|auth|quota`
- `speaking.html?state=recording|transcribing|result|permission|quota|offline`
- `test.html?state=autosave-fail|offline|time-expired|submit|loading`
- `swot.html?state=empty|error|offline|auth`
- `lesson.html?state=offline|quota|untranslated`
- `catalogue.html?state=empty|error|offline`

The **states page** puts the shared state kit on plates with the code path (`[ssr]`, `[island]`,
`[page]`) and the rule that the state enforces. It also embeds the real dashboard and lesson at
**360 px** — iframes, not screenshots. Add `?embed=1` to any page to hide the review strip.

### Interactive behaviours that are real

- Mobile public/app drawers (native `<dialog>`, Esc closes, focus returns).
- Class context and user menus (`<details>`, outside-click/Esc close).
- Catalogue class tabs (arrow keys), search, and filters (Live / practice / test) with a real
  empty state.
- Lesson check (radio, Check, ✓/✗ + words, Why?); practice check and hint recording.
- Lesson bookmark, read-aloud state, language-chip selection (selection only; the production
  kit's i18n stub), reading progress.
- Speaking state machine: mic → consent → recording timer → transcribing → result; re-record,
  save/delete demo actions.
- Test autosave (saving → saved; failure state), submit dialog with the unanswered count, time
  expired state.
- Settings section-scoped saves (toast + inline status), switches, password show/hide.
- Component dialogs, sheet, toast, palette selection, mic toggles.

## The five decisions I need

1. **Public shell weight.** Does the header/footer read as a working notebook rather than a SaaS
   site? Is the wordmark/nav hierarchy right at 360 px and desktop?
2. **App bar density.** Is class/subject context + five nav destinations + voice credits + user
   menu too much chrome? Should the credit chip live only in the dock/lesson?
3. **Dashboard shape.** Does the study-log two-column layout answer “what should I do now?”
   without becoming a KPI dashboard? Is the right rail (week, SWOT, activity) earning its place?
4. **Lesson chrome.** The app bar + lesson toolbar + language bar is three layers before the
   content. Does the lesson still dominate? Should the lesson use the public header instead of the
   signed-in app bar?
5. **State treatment.** Are loading, empty, panel error, offline, auth-required, quota, mic denied,
   untranslated and reduced motion calm and honest? Is any state too loud, too vague, or missing
   an action?

Please also call out anything that feels like a **new visual language** rather than Field Notes.
The doctrine wins; this bundle should be corrected, not the doctrine.

## Component catalogue (proposed for the kit)

The components page shows these with variants/states. The production implementation should add
them to the shared kit rather than copy page-local markup:

- shell: `zn-site-header`, `zn-nav`, `zn-appbar`, `zn-context` (class/subject), `zn-drawer`,
  `zn-breadcrumbs`, `zn-page-head`, `zn-footer`, `zn-app-footer`, `zn-credits`, `zn-user-menu`;
- actions: `zn-btn` (primary/secondary/quiet/danger, busy/disabled), `zn-link`;
- fields: `zn-field`, `zn-input`, `zn-select`, `zn-textarea`, `zn-choice`, `zn-switch`,
  `zn-label`, `zn-help`, `zn-error`, numeric;
- containers: `zn-panel`, `zn-card`, `zn-chapter-card` (catalogue row), `zn-series-card`,
  `zn-question-card`, `zn-stat`;
- navigation: `zn-tabs`, `zn-filter`;
- progress: `zn-progress`, `zn-ring`, `zn-mastery` (five shapes);
- states: `zn-banner`, `zn-empty`, `zn-error-box`, `zn-skeleton`, `zn-untranslated`,
  `zn-auth-card`;
- overlays: `zn-dialog`, `zn-sheet`, `zn-toast`;
- exam: `zn-exam`, `zn-exam-head`, `zn-marks`, `zn-palette`, `zn-timer`, `zn-autosave`,
  `zn-answer-input`, `zn-review-flag`, `zn-legend`;
- insight: `zn-swot`, `zn-quadrant`, `zn-quadrant-card`, `zn-evidence`;
- audio: `zn-audio`, `zn-mic`, `zn-wave`, `zn-transcript`, `zn-rubric`, `zn-ai-label`,
  `zn-ledger`, `zn-stamp`;
- data: `zn-status`, `zn-source-chip`, `zn-copy-flag`, `zn-table`, `zn-mark`.

## What is mocked / deliberately out of scope

- **All data is mock.** Aarav, class 9, the chapter counts, marks, scores, credits and dates are
  invented to exercise the layout. No student data.
- **No backend, auth, database, cookies, network, microphone, audio, or analytics.** Auth screens
  are F2; admin is F10; the full voice-dock state machine is F4 + §10.12. The bundle shows the
  collapsed dock and consent gate so the shell can be judged around them, not a redesign.
- **The lesson is an excerpt** copied from `frontend/courses/class-9-physics/motion/` (published
  2026-11-10) to judge the chrome against real §10 type and blocks. It is not a full lesson.
- **Narration audio is not bundled.** The Listen controls show state changes and progress; the
  README/UI say so.
- **The review strip is example chrome.** It is not a product surface and must not be implemented.
- **No screen spec or state matrix is in this bundle.** Those are PR artifacts for after the
  verdict, per `skills/zivon-frontend-product-skills/templates/`.

## Quality evidence (this run)

- 14 pages, zero console errors at 1280 px and 360 px (Chromium via Playwright).
- No horizontal overflow at 360 px; the only wide elements are tables and the class tab
  strip, each inside its own scroll container.
- One `<h1>` per page; no unlabeled form control; skip link first on every page; native
  dialogs/drawers for focus containment and return.
- Shell bundle: JS ~42 KB raw / ~10 KB gzip; CSS ~109 KB raw / ~20 KB gzip; four local woff2
  fonts (~252 KB total). No external hosts, analytics, storage, network, or microphone.
- This is example evidence, not the product perf/a11y gate; the implementing PR still needs
  axe, keyboard, state-coverage, and weak-Android evidence.

## Kit merge notes (for implementation)

These are the places where the exploration meets the existing kit; resolve them before merging
the components into `frontend/assets/zivon.css`:

- **`.zn-footer` already names the lesson sources footer** in the kit. The public footer here
  uses the same class; rename it (for example `.zn-site-footer`) or scope it so lesson pages
  never inherit the marketing footer.
- `.zn-card` and `.zn-empty` already exist on the landing shell; extend those rules rather than
  forking a second card or empty state.
- `.zn-header`, `.zn-title`, `.zn-kicker` are lesson-header components; the app uses
  `.zn-appbar` + `.zn-page-head` so the two surfaces do not collide.
- `.zn-check` is the lesson quiz card. The app practice question uses `.zn-choice` rows and a
  `.feedback-panel`; do not reuse `.zn-check` outside a lesson.
- The `.review-strip` is example chrome and must not be implemented. The example-only
  `data-state` / template injection is a review harness, not a runtime state machine.
- The public footer copy is a draft; the trust/privacy copy still needs the compliance and
  privacy owners' review.

## Review checklist

- [ ] Public header/footer feel like one Field Notes page, not SaaS.
- [ ] Wordmark/nav/actions survive 360 px without horizontal overflow.
- [ ] App bar: class context, nav, credits, user menu are legible and not competing.
- [ ] Mobile drawer: 44 px rows, Esc/Close, focus returns, no hidden focus.
- [ ] Breadcrumbs and page header establish hierarchy; the dashboard does not need one.
- [ ] Dashboard reads as a study log; one primary action; no KPI wall, streak or rank.
- [ ] Catalogue reads as a syllabus/shelf; status is honest; in-development rows are not links.
- [ ] Lesson content still dominates; the dock is recognisably §10.12, not a chat app.
- [ ] Buttons/fields/cards/tabs/progress/mastery/dialog/toast/exam/SWOT/mic are consistent.
- [ ] Empty/error/loading/offline/auth/quota/permission/untranslated are honest and actionable.
- [ ] Reduced motion removes animation without removing audio, the text path, or status words.
- [ ] 360 px frames: no horizontal overflow, 44 px targets, readable line length.
- [ ] Keyboard: skip link, tabs, menus, dialogs, drawers, checks, switches.
- [ ] No new colour/font/radius/shadow/gradient; no §10 leak into shell pages.
- [ ] No dead links or dead controls; every disabled state says why.
- [ ] No streaks, leaderboards, ranks, parent access, or guilt copy.
- [ ] The five decisions above are answered with approve / approve-with-changes / reject.

## After the verdict (same session)

1. Record the verdict and required changes; if approved, draft the product-surfaces doctrine
   section (new section; do not rewrite §10.12–§10.14).
2. Implement the shell as kit-first components: `frontend/assets/zivon.css` + `zivon.js` for
   shared pieces, and the F0-owned `frontend/assets/app-shell.*` / `design-system.*` for the
   shell. No page-local chrome.
3. Add the SSR templates/routes under `web/` (F0 owns `web/` + shared templates), with typed view
   models and no business logic in templates.
4. Fill a screen spec and 11-state matrix per surface; add deterministic static/browser/a11y tests
   under `testing/frontend/`; keep no-network checks green.
5. Update `docs/specs/frontend/` and `docs/frontend/design-doctrine.md` in the same PR.
6. Open the PR for independent review. Do not merge.

## Files

```
design-examples/f0b-shell/
  index.html              cover sheet + screen index + palette/type + checklist
  catalogue.html          public catalogue
  class.html              public class page
  public-info.html        method / pricing / trust
  dashboard.html          app dashboard / study log
  practice.html           practice question
  speaking.html           speaking recorder
  test.html               test player (exam mode)
  results.html            results / review
  swot.html               SWOT quadrants
  settings.html           settings
  lesson.html             lesson in the product shell
  components.html         component catalogue
  states.html             state plates + 360 px frames
  assets/tokens.css       doctrine tokens, local fonts, base, reduced motion
  assets/shell.css        review strip, public shell, app shell, drawers, menus
  assets/components.css   buttons, fields, cards, states, dialogs, exam, SWOT, audio
  assets/screens.css      page compositions (dashboard, catalogue, practice, speaking, test, results, SWOT, settings, states)
  assets/lesson.css       §10 lesson excerpt only
  assets/shell.js         vanilla behaviour (no network, no storage, no mic)
  assets/fonts/           woff2 + FONTS-LICENSE.md (SIL OFL 1.1)
```

**No files under `frontend/` or `docs/` were modified.** The example is intentionally isolated so
it can be deleted or kept as a reference after the verdict.
