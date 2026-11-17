# Screen-state matrix — implementation view

Agent: SP5-FRONT · Rows = screens / regions / element families (ids from
`component-inventory.csv`); columns = the ten canonical states (method hard
rule 4). Every cell names **what the student perceives AND which code path
renders it** — an implementation view, not a wish list. `n/a (reason)` is a
valid cell; a blank one is a defect. Budgets referenced here are in
`perf-budget-tests.md`.

Legend for code paths: `[shell]` = the hand-maintained public pages
(`frontend/index.html`, `catalogue/`, `class-<N>-physics/`, the trust pages,
`404.html`) + `assets/product.css` / `product.js`; `[kit]` =
`frontend/assets/zivon.js` + `zivon.css`; `[page]` = generated
`courses/<…>/index.html` + `page.js` (renderer + Builder, kit-constrained);
`[web]` = the server-rendered app shell in `web/templates/` + `web/routes/`
(Jinja2, mounted by the core backend).

## APP-01 `/app` shell (F0C, 2026-11-17)

The signed-in shell is specified in `docs/specs/frontend/web-shell.md`: the
route/guard contract (§2, §4), the template slots (§3), the headers/CSP (§5)
and the full state table for `/app` (§8). Its only code path is `[web]`; the
shell renders no §10 lesson device and no static `[shell]` page. The shell
frame's states are answered there — loading (n/a: SSR completes before bytes),
empty (the page body owns it: APP-04/05/06 below), partial (language note),
error (503 shell for unavailable auth; panel errors are the body's), offline
(n/a server-side), permission-denied (303 to `/login?next=`), reduced-motion
(no shell animation), untranslated (English copy + saved-language note),
quota-exhausted and consent-missing (not shell states).

## APP-02 auth screens (`/login`, `/signup`, verify, reset, `/onboarding`) (F2, 2026-11-17)

The full per-screen state table is in
[`identity-settings.md`](identity-settings.md) §6; this row keeps the matrix
complete. Code path is `[web]` only (`web/templates/auth/*`,
`web/routes/auth.py` + `onboarding.py`). No static `[shell]` page and no §10
device is involved.

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| auth card (sign in, sign up, verify, reset, onboarding) | one paper card, fields labelled above, Google link when configured, guest link | n/a (SSR completes before bytes) | n/a (a form is never empty; the verify inbox state is the designed empty) | Google unconfigured → status text and no dead button; resend-not-built → honest status | 401/409/422/429/400/403 branded page or re-render with `role="alert"` + field errors | browser offline page; no server state | signed-in visitor on `/login`/`/signup` → 303 `next`; onboarding guest → 303 `/login?next=/onboarding` | no animation; nothing to reduce | English copy; the saved language is shown as data and noted | n/a (no voice in an auth screen) |
| CSRF boundary | guest forms: signed double-submit cookie + hidden MAC; verify/reset: emailed one-time token; onboarding: session token | n/a | n/a | a stale tab re-renders "This form expired" | 403 branded page, nothing written | n/a | n/a | n/a | n/a | n/a |

## APP-03 settings and privacy (`/app/settings`, `/app/settings/privacy`) (F2, 2026-11-17)

Specified in [`identity-settings.md`](identity-settings.md) §1/§2/§6; code path
`[web]` (`web/templates/app/settings*.html`, `web/routes/settings.py`). The
screen shows the owner's email as an allow-listed field (REQUIREMENTS §10.21);
no other page renders it.

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| profile / password / Google / session cards | facts + three forms + sign-out, all CSRF-protected | n/a (SSR) | n/a | unverified email, Google unlinked, Google unconfigured, password unset (Google-created) each have a row state | 422 field errors, 401 wrong current password, 403 CSRF, 429 rate limit (all with the form still usable) | browser offline page | guest → 303 `/login?next=/app/settings` | no animated toggles; `prefers-reduced-motion` rule is a no-op guard | English labels; saved language as data | n/a |
| privacy / data controls | what is stored, export link, collapsed delete disclosure, consent links | n/a | export may be empty but is valid JSON | delete form needs the exact word + password | 422 wrong confirmation, 401 wrong password, both leave the account intact | browser offline page | guest → 303 | no animation | as above | n/a |
| mobile / a11y floor | one column at 360 px; 48 px inputs and choice rows; 44 px links; visible focus | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## APP-04 `/app` dashboard (F3, 2026-11-17)

Code path `[web]`: `web/templates/app/dashboard.html` + `web/progress_views.py`
reads `/v1/progress/*`'s domain directly (SSR). Contract and copy:
`docs/specs/frontend/dashboard-progress.md` §6.

| State | What the student sees |
|---|---|
| default | greeting + Continue/Today/Physics map/Recent activity; aside = 7-day rhythm, three counts, quick actions (live links + "not live yet") |
| loading | n/a — SSR completes before bytes; a slow DB is the panel error |
| empty | "Nothing here yet — that is honest." + a Start card for the first published chapter (or the catalogue) |
| partial | class with no published chapter -> "No Class N chapter is published yet"; local sync offer when the device has unmerged data |
| error | greeting stays; `notice--error` with "Your study log is unavailable right now." + retry; no invented data |
| offline | n/a server-side; navigation failure is the browser's offline page |
| permission-denied | guest -> 303 `/login?next=/app` (F0C guard) |
| reduced-motion | no page animation (native links/details; the global reduced-motion rule covers any future island) |
| untranslated | English copy + the saved-language note (shell contract) |
| over-credit-budget | n/a — no voice control on this page; credits belong to the dock |

## APP-05 `/app/progress` progress map (F3, 2026-11-17)

Code path `[web]`: `web/templates/app/progress.html` +
`web/progress_views.py`/`backend/progress/stats.py`. Contract:
`docs/specs/frontend/dashboard-progress.md` §3, §7.

| State | What the student sees |
|---|---|
| default | class -> chapter -> concept map; state tags + evidence; "How these states work" publishes the rules |
| loading | n/a — SSR completes before bytes |
| empty | all chapters "Not started" (the map is the content; no fake activity) |
| partial | chapter without concept metadata says so; activity outside the catalogue is grouped under "Other activity"; F0 fixture has no concept lists |
| error | panel `notice--error` + retry (map not rendered with invented states) |
| offline | n/a server-side |
| permission-denied | 303 `/login?next=/app/progress` |
| reduced-motion | `<details>` is native; no animation |
| untranslated | English copy + saved-language note |
| over-credit-budget | n/a — no voice control |

## APP-06 `/app/bookmarks` saved sections (F3, 2026-11-17)

Code path `[web]`: `web/templates/app/bookmarks.html` + the
`frontend/assets/app-progress.js` remove island. Contract:
`docs/specs/frontend/dashboard-progress.md` §8.

| State | What the student sees |
|---|---|
| default | saved list with type, chapter title, deep link, date, Remove |
| loading | n/a — SSR completes before bytes |
| empty | "Nothing saved yet." + lesson Contents -> Save explanation + catalogue link |
| partial | item whose chapter is no longer in the catalogue shows its humanized chapter title and no link |
| error | panel `notice--error` + retry; a failed remove keeps the row and says it is still saved |
| offline | n/a server-side; a failed remove is announced, nothing is optimistically dropped |
| permission-denied | 303 `/login?next=/app/bookmarks` |
| reduced-motion | no animation |
| untranslated | English copy + saved-language note |
| over-credit-budget | n/a — no voice control |

## APP-07 `/app/practice` practice hub (F5, 2026-11-17)

Code path `[web]`: `web/templates/app/practice/hub.html` +
`web/practice_views.py`/`backend/practice/`. Contract:
`docs/specs/frontend/practice.md` §7, §8.

| State | What the student sees |
|---|---|
| default | Daily 5, chapter drills with imported banks, weak topics, retry mistakes, recent sets, honest notes |
| loading | n/a — SSR completes before bytes |
| empty | "No chapter has an imported practice bank yet" + no Start form; Daily 5 reason |
| partial | Daily 5 needs a class; English-only chapter marker; no weak/retry yet |
| error | panel `notice--error` + retry; no invented modes |
| offline | browser offline page (practice needs the server) |
| permission-denied | 303 `/login?next=/app/practice` |
| reduced-motion | no animation; native forms |
| untranslated | English UI copy + saved-language note; question-language fallback stated |
| over-credit-budget | n/a — no voice control |

## APP-08 `/app/practice/{id}` practice player (F5, 2026-11-17)

Code path `[web]` + the `frontend/assets/practice.js` island; server form is the
real path. Contract: `docs/specs/frontend/practice.md` §7, §8.

| State | What the student sees |
|---|---|
| default | one question, options/numeric field, Check, nudge, `aria-live` feedback, Why?, Next/Finish |
| loading | n/a — SSR; the island shows a disabled Check while the answer is in flight |
| empty | n/a — a session always has questions |
| partial | unanswered set; feedback shown for the last answered question when the set is not closed |
| error | numeric parse miss re-renders with the value and a fixable message; 403/409/429/offline copy; feedback never shows a stack trace |
| offline | browser offline page; a failed inline check says the answer was not saved |
| permission-denied | 303 `/login?next=/app/practice/{id}`; another account's id is a branded 404 |
| reduced-motion | no animation; native `<progress>` |
| untranslated | English UI copy + saved-language note; fallback set marked |
| over-credit-budget | n/a — no voice control |

## APP-09 `/app/practice/{id}/summary` practice summary (F5, 2026-11-17)

Code path `[web]`: `web/templates/app/practice/summary.html` +
`web/practice_views.py`. Contract: `docs/specs/frontend/practice.md` §7, §8.

| State | What the student sees |
|---|---|
| default | score, accuracy, first attempts, time, hints, per-concept breakdown, next actions |
| loading | n/a — SSR |
| empty | zero answered: "Nothing was answered in this set"; concepts say Not answered |
| partial | open set: "This set is still open" + Continue; unanswered note |
| error | panel `notice--error` + retry |
| offline | browser offline page |
| permission-denied | 303 `/login?next=…`; foreign id is a branded 404 |
| reduced-motion | no animation |
| untranslated | English copy + fallback note |
| over-credit-budget | n/a — no voice control |

## APP-10 `/app/practice/history` practice history (F5, 2026-11-17)

Code path `[web]`: `web/templates/app/practice/history.html`. Contract:
`docs/specs/frontend/practice.md` §7, §8.

| State | What the student sees |
|---|---|
| default | newest-first sessions: mode, chapter, day, count, score or "still open", link |
| loading | n/a — SSR |
| empty | "No practice sets yet" + Start practising |
| partial | open sets are labelled, not hidden |
| error | panel `notice--error` + retry |
| offline | browser offline page |
| permission-denied | 303 `/login?next=/app/practice/history` |
| reduced-motion | no animation |
| untranslated | English copy + saved-language note |
| over-credit-budget | n/a — no voice control |

## PUB-01 landing / PUB-02 catalogue / PUB-03 class pages (F1, 2026-11-16)

The public discovery surfaces are specified in `docs/frontend/public-site.md`
(route map, data contract, SEO and the full state table). This supersedes the
P0 `SCR-HOME-01` landing/catalogue element rows: `/` is now a landing page with
no course list, and `/courses` is the catalogue served from
`frontend/catalogue/index.html` by an exact nginx location. The catalogue
renderer is `product.js::initCatalogue`; `zivon.js::renderCourses` still serves
the localized hubs `/hi/` and `/hi-Latn/` until P5 replaces them.

Every state column — default, loading, empty, partial, error, offline,
permission-denied, reduced-motion, untranslated, quota-exhausted,
consent-missing — is named with its code path in `public-site.md` "States
(public site)".

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

## SCR-LES-01 — lesson shell (`.R0`, `.R13`, `.R14`, `.R15` — W2 F4)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-LES-01-091..097/109` app bar | `[kit] ZivonLessonShell.buildLessonAppBar`: brand, Courses, Practice/Progress (coming-soon statuses), Contents toggle, Ask | static markup before any fetch; never a spinner | n/a (a published lesson always mounts it) | F2 identity absent -> identity slot hidden (guest-first) | a thrown step is isolated in `ZivonShell.mount`; the lesson stays readable | fully local (no network needed to navigate) | consent declined -> Ask hidden, `body[data-zn-voice=off]` | no animation | shell strings carry `data-i18n="ui.shell.*"` with an English fallback | n/a (nav is never metered) |
| `EL-LES-01-098..102` chapter drawer | `[kit] buildLessonDrawer`: manifest `sections` -> section links, current `aria-current=location`, save toggles, prev/next chapter | renders from the DOM first, re-renders when `manifest.json` arrives | n/a (a page without sections gets no shell at all) | missing manifest -> DOM-derived titles; missing catalogue -> no chapter links | open/close/jump are isolated; a failed catalogue fetch leaves the drawer usable | local-only | n/a (no permission) | jump uses `behavior:auto` | section titles are content; chrome labels have `ui.shell.*` keys | n/a |
| `EL-LES-01-013` per-block "Ask about this" | `[kit] injectAskButtons`: quiet graphite chip per `[data-block-type]` block; press -> explicit anchor + dock expanded + pen-blue ring | n/a | n/a | block without an id gets no chip (nothing to anchor) | chip does nothing but never throws if the block vanished | voice-off copy path is the dock's | consent declined -> no chips rendered; consent missing -> chip focuses the §10.14 gate | n/a | `ui.shell.ask_about_this` | n/a (voice credits are the dock's) |
| `EL-LES-01-103` reading progress | `[kit] buildLessonProgressBar` + rAF-coalesced scroll: `role=progressbar`, `aria-valuenow` = max(scroll %, sections read) | first measurement after load | n/a | without sections the bar stays at the scroll percentage | no throw; storage blocked -> in-memory only | works offline (local store) | n/a | compositor-only transform | `ui.shell.reading_progress` aria-label | n/a |
| `EL-LES-01-104..110` end-of-lesson next steps | `[kit] buildLessonNextSteps`: practise/explain-back coming-soon statuses, next-chapter link, all chapters, back to contents | n/a | n/a | no catalogue -> next-chapter row hidden | isolated; lesson footer unaffected | local links only | n/a | n/a | `ui.shell.*` labels; chapter titles are content | n/a |

## SCR-PRIV-01 (`/privacy/`)

| Row | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | over-credit-budget |
|---|---|---|---|---|---|---|---|---|---|---|
| `EL-PRV-001..005` privacy summary & clear data | `[shell]` / `[kit] ZivonPrivacy`: heading (`EL-PRV-001`), data-class retention table (`EL-PRV-002`), "Clear my data" button (`EL-PRV-003`), confirm dialog (`EL-PRV-004`), back link (`EL-PRV-005`) | confirm dialog `GET /v1/data/challenge` → `DELETE /v1/data` | shows "no consent record on this device" when cleared (`INF-076`) | server-first wipe: local keys are wiped only AFTER the server ack; the device pseudonym is deleted LAST | failed wipe deletes nothing local, keeps the pseudonym and says "Could not reach the server — your data was NOT deleted; retry when online" | `EL-PRV-003` disabled offline with an explanatory title; dialog Esc + focus containment | n/a | n/a | English copy | n/a |

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
