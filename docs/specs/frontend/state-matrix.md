# Screen-state matrix — implementation view

Agent: SP5-FRONT · Rows = screens / regions / element families (ids from
`component-inventory.csv`); columns = the ten canonical states (method hard
rule 4). Every cell names **what the student perceives AND which code path
renders it** — an implementation view, not a wish list. `n/a (reason)` is a
valid cell; a blank one is a defect. Budgets referenced here are in
`perf-budget-tests.md`.

Legend for code paths: `[shell]` = `frontend/index.html` / `404.html`;
`[kit]` = `frontend/assets/zivon.js` + `zivon.css`; `[page]` = generated
`courses/<…>/index.html` + `page.js` (renderer + Builder, kit-constrained).

## SCR-HOME-01 (landing / catalogue)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-HOME-01-001..004` head+header | `[shell]` static markup, first paint | n/a (all content inline — no fetch, nothing to await) | n/a (header is static copy, never data-driven) | n/a (no partial source exists) | n/a (no network, no runtime parser) | n/a (works from cache by construction — G2) | n/a (no permission consumed) | n/a (no animation; pen underline is static after draw) | English-only until localized routes land (§3.2 spec.md) — page stays English, `lang=en` correct | n/a (no credits consumed) |
| `EL-HOME-01-005/006` course list + cards | `[kit] renderCourses()` builds one `a.zn-card` per entry | n/a (`courses.js` is a synchronous script tag — parse time only; perf budget covers it) | `#zn-courses` stays empty; **see empty row below** | renders the entries that exist; `partial` is the NORMAL catalogue state (a topic in progress is simply absent — the factory publishes only complete pages) | if `courses.js` fails to parse: list stays empty AND console error — surfaced by CI's clean-load test, never visible to a student (publish smoke re-serves the file) | n/a (same-origin inline script; served from cache) | n/a | n/a (hover/focus transitions are colour-only, no motion) | card fields as shipped by the factory (`INF-010`); English today | n/a |
| `EL-HOME-01-007` empty state | hidden (`[hidden]`, `[shell]`) | n/a | `[kit] renderCourses()` removes `hidden` when `ZIVON_COURSES.length === 0`; honest copy: factory has not run yet | n/a (state is boolean by definition) | n/a (a broken `courses.js` is a CI failure, not a UI state) | n/a | n/a | n/a | English today | n/a |
| `EL-HOME-01-008` footer | `[shell]` static | n/a | n/a | n/a | n/a | n/a | n/a | n/a | English today | n/a |

## SCR-LES-01 — language bar (`.R1`)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-LES-01-001..003` bar + label + group | `[page]` renderer emits `.zn-lang-bar`; `[kit]` positions it (sticky, in flow) | n/a (emitted in initial HTML) | n/a (always emitted on lesson pages) | n/a | n/a | n/a | n/a | n/a (sticky = compositor; no animation) | label stays "Language"/per-locale when i18n lands; the bar itself is chrome and is the control FOR translation — it never shows the untranslated state itself | n/a |
| `EL-LES-01-004` chips | `[kit] wireLangChips()`: one chip per doctrine §10.5 language; English preselected; selection = `aria-checked` + ink fill | n/a | n/a (3 chips ship per doctrine) | n/a | n/a | n/a (activation is local-only) | n/a | n/a | **v1 honest stub**: switching sets the selected chip ONLY (no content or lang change yet — the shell's `wireLangChips` sets `aria-checked`, verified); document-lang switching and the untranslated notice land with i18n generation (spec.md §8) — chip states gain `untranslated` styling then | n/a |
| persistence (`localStorage["zivon_locale"]`, spec C3; `zivon.lang` read-only legacy — Q11) | read on load → preselect; written on explicit activation | n/a | n/a | n/a | storage unavailable (private mode) → read fails silently, default English — degrade, never break | n/a | n/a | n/a | n/a | n/a — pseudonymous, local-only until ADR-0007 (flag Q3) |

## SCR-LES-01 — page header + footer (`.R2`, `.R4`)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-LES-01-005..008` header | `[page]` static markup from `manifest.json` fields (`INF-001/002/007`) | n/a (inline HTML) | n/a (publish smoke guarantees manifest + title — `test_published_catalogue_entries_resolve`) | objectives may be absent (renderer omits label + list together — `partial` is authored-in, not a failure) | n/a (page would not have published) | n/a | n/a | pen underline draws once, static | build-time translation (factory); the PAGE is the unit of translation — no mixed runtime state | n/a |
| `EL-LES-01-070` sources footer | `[page]` from `manifest.sources` | n/a | n/a (required field) | n/a | n/a | n/a | n/a | n/a | license names never translated | n/a |

## SCR-LES-01 — block stream (`.R3`)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-LES-01-010` text | `[page]` paragraphs on the ruled lines (`[kit]` anchors them) | n/a | n/a (schema: first block is text — a page without it cannot publish) | n/a | n/a | n/a | n/a | n/a (no animation) | i18n era: English + notice (spec.md §8) | n/a |
| `EL-LES-01-020` worked example | `[page]` `.zn-example` | n/a | n/a | n/a | n/a | n/a | n/a | n/a | as above | n/a |
| `EL-LES-01-030/031/032/033` checks | `[kit] wireCheck()`: unanswered → feedback empty; correct → "✓ Correct."; wrong → "✗ Not yet - try again." + retry allowed | n/a | n/a (every check ships with options/answer — schema hard rule) | n/a | **numeric parse failure → treated as wrong answer + retry** (`firstNumber` returns null → correct=false path) — wrong-but-recoverable, never a crash | n/a (client-only logic) | n/a | n/a (feedback is instant text) | build-time translation | n/a |
| `EL-LES-01-040` reveal | `[page]` native `<details>` closed | n/a | n/a (steps required) | n/a | n/a | n/a | n/a | n/a (zero-JS, no animation) | as above | n/a |
| `EL-LES-01-050` diagram | `[page]` inlined SVG (lint-validated: no script/style/external) | n/a | n/a | n/a | **n/a (by construction)** — a diagram that passed factory lint cannot execute or fetch anything; `test_self_contained_no_network_refs` re-checks the published snapshot | n/a | n/a | static SVG | labels are build-time strings | n/a |
| `EL-LES-01-060` simulation | `[kit] ZivonSim`: rAF loop, slider values in `ctx.values` | n/a (canvas + page.js inline; first frame inside the load budget) | n/a (a sim block always has ≥ its `default_behaviour`) | zero-control sims = animation (a designed variant, not partial) | **on-canvas error painter** (`paintError`): paper background, "simulation error:" + message, `console.error` — loud, never blank; page keeps working (G5) | n/a (no network) | n/a | **exactly one static draw, no rAF loop** (`prefers-reduced-motion` check in `startSim`) — asserted by the perf spec's test | labels build-time | n/a |
| `EL-LES-01-061` sim read mirror | `[page]` `page.js` sets `.zn-sim-read` text each draw | n/a | **empty mirror = Builder defect** — caught by 09-review (040410 finding) and by the perf spec's mirror test; student-visible symptom: silent live region | n/a | error painter message IS the announced state | n/a | n/a | announces the static state once | build-time | n/a |
| `EL-LES-01-080/081` rules + underline | `[kit]` measured redraw on: font load, resize, DOM mutations, `<details>` toggle | first draw after `DOMContentLoaded` + `fonts.ready` (inside load budget) | n/a (paper always has text) | n/a | **kit failure → rules/underline absent, content fully readable** (progressive enhancement by design; console error caught in CI clean-load test) | n/a | n/a | redraw is layout work, not motion — unchanged | n/a (visual) | n/a |

## SCR-LES-01 — voice dock, read-aloud, consent, report & notices (`.R2`, `.R3`, `.R8`, `.R9`, `.R10`, `global` — Wave E2)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-LES-01-006..009` (`EL-LES-01-001..004`) language bar & chips | `[kit] wireLangChips()`: `en` enabled; locales with `window.ZIVON_I18N` / localized route enabled; others `aria-disabled="true"` with honest title | bundle switch < 200 ms | English-only enabled when no locale bundles exist | fallback blocks show `.zn-untranslated-notice` (`INF-087`) | storage blocked → in-memory selection only | cached page/bundle works | n/a | n/a | `.zn-untranslated-notice` per untranslated block | n/a |
| `EL-LES-01-012` read-aloud button (§10.13) | `[kit] ZivonReadAloud`: 44 px "सुनो / Listen" pill per speakable block in `manifest.json` `narration.blocks` | `preload="none"`, fetches `/audio/{course_id}/{block_id}.{lang}.{hash}.opus` on press | **no button rendered** when manifest or block asset is absent (never a dead control) | only blocks with `available: true` get a button | audio error → button resets + status notice; lesson text unaffected | disabled when offline and uncached | user-gesture initiated | 2 px progress rule skips transform animation | hidden if active locale has no narration | n/a (build-time Timbre v3.0, zero runtime credits) |
| `EL-LES-01-040..041` provenance report (`F-COR-PROV-01`) | `[kit] ZivonReport`: quiet graphite "Report a problem" button in `.zn-footer` | `sending` state on submit (`POST /v1/reports`) | optional text blank allowed | draft preserved on error | "Could not send — try again" + draft kept | button disabled with offline reason | n/a (no PII, no permissions) | n/a | English chrome fallback | n/a |
| `EL-LES-01-057..061` consent gate (§10.14) | `[kit] ZivonConsent`: one-time sheet before dock; Continue (with guardian checkbox) / Decline | `PUT /v1/consent` async sync (local-first) | n/a | local consent works if server unreachable | server sync retried; local record gates UI | works locally offline | Decline → dock stays off quietly, **no re-nag** | instant show/hide | English copy (`INF-072..075`) | n/a |
| `EL-LES-01-042..056` (`EL-LES-01-090`) voice dock (§10.12 bottom sheet) | `[kit] ZivonVoiceDock`: `hidden` (44 px "Ask" tab) / `collapsed` (92 px strip, first-visit default after consent) / `expanded` (≤60 dvh sheet); `localStorage["zivon.dock"]`; silence-close 5 s after `idle` | `connecting` ("jud rahe hain…", 2 px dotted rule) / `thinking` (2 px sweep, no timer) | fresh transcript (`EL-LES-01-047`) + one-time AI identity line (`EL-LES-01-051`) | `speaking_text` ("TUTOR · TEXT" chip, no bars/caret); `interrupted` ("▍cut off" mark) | `error:mic-in-use` / `error:no-match` / `error:system-error` / `error:auth.invalid` / `error:version.mismatch` → plain sentence + retry + typed fallback (`EL-LES-01-052`) + help chips (`EL-LES-01-053`) | "connection gaya — jo type karoge woh safe hai", text path open | `error:mic-denied` → `MIC OFF` stamp + "lesson chalta rahega" + typed field focused (never a red toast) | static "soch rahe hain…" line, instant caption text, no bar animation | Hinglish/English dock microcopy per §10.12 | `text_only` → mic disabled with ledger line ("30 credits/day · voice resets 00:00 · reading, sims, typing free"), typed input active |
| `EL-LES-01-070..072`, `EL-HUB-008` global notices | hidden when online and `credit_state == "ok"` | n/a | n/a | `warn` (`EL-LES-01-071`): "Voice is limited today" | n/a | `offline` (`EL-LES-01-070`, `EL-HUB-008`) shown | n/a | n/a | English copy | `exhausted` / `text_only` (`EL-LES-01-072`): "Voice is resting (daily limit). Type your doubt." (never cuts in-progress turn) |

## SCR-PRIV-01 (`/privacy/`)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-PRV-001..005` privacy summary & clear data | `[shell]` / `[kit] ZivonPrivacy`: heading (`EL-PRV-001`), data-class retention table (`EL-PRV-002`), "Clear my data" button (`EL-PRV-003`), confirm dialog (`EL-PRV-004`), back link (`EL-PRV-005`) | confirm dialog `GET /v1/data/challenge` → `DELETE /v1/data` | shows "no consent record on this device" when cleared (`INF-076`) | local `localStorage` wiped even if server unreachable | server error message shown + local wipe confirmed | `EL-PRV-003` disabled for server wipe when offline (local clear still available) | n/a | n/a | English copy | n/a |

## SCR-404-01

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-404-01-001..003` | `[shell]` static page served by nginx `error_page 404 /404.html` (spec C1) | n/a (static) | n/a | n/a | n/a — it IS the error surface; no nested error state exists | n/a (cached) | n/a | n/a | English until localized routes (§3.2 spec.md) | n/a |

## Cross-cutting rows (every screen)

| Concern | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| Fonts | local `@font-face` with `font-display: swap` + system fallbacks (`[kit]` tokens) | swap shows fallback first — counted in FCP budget, not a spinner | n/a | n/a | missing font file → fallback stack renders; CI smoke asserts assets resolve | n/a | n/a | n/a | Devanagari falls back per glyph (Kalam/Nirmala stack, doctrine §10.3) | n/a |
| JS failure (any) | content fully readable (HTML-first: text, examples, reveals, diagrams, check markup all ship as HTML) | n/a | n/a | n/a | checks/sims inert — the reading core survives (G5); CI clean-load test prevents shipping this | n/a | n/a | n/a | n/a | n/a |

**Completeness check**: 10 canonical states × 15 rows — no blank cells; every
`n/a` carries its reason. States that cannot occur on static pages (loading,
permission-denied, over-credit-budget) concentrate in the two networked
add-ons (voice dock, future event sink), which is exactly where the brief
wants them.
