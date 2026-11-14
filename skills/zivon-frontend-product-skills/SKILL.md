---
name: zivon-frontend-product-skills
description: Builds and reviews the Zivon full frontend - Field Notes public pages, static generated lessons, server-rendered /app pages, auth, dashboard, lesson shell, practice, speaking, tests and series, progress, SWOT, settings, and admin. Covers static-vs-SSR route placement (no SPA), the 11-state matrix, component patterns, WCAG 2.2 AA, weak-Android budgets, SEO and noindex, and the founder visual-verdict protocol. Use when implementing or changing any Zivon frontend screen, example page, app shell, dashboard, lesson shell, practice or test player, SWOT or progress view, auth or settings UI, or frontend test; when reviewing a frontend PR, debugging a broken state at 360 px, deciding static vs server-rendered, or preparing a localhost example for a founder verdict.
license: MIT
compatibility: Needs a local static server and Playwright Chromium for browser tests. The default path is key-free and offline; no secrets, no live model calls.
metadata:
  owner: zivon
  version: "1.0"
  evidence_date: "2026-11-14"
  source_plan: "tmp/full-frontend/FEATURE-MAP.md (frozen 2026-11-13) and REQUIREMENTS.md"
---

# Zivon Frontend Product Skills

How to build the complete Zivon frontend without drifting from the product,
the design doctrine, or the repo's constraints. This is an **implementation
entry point**, not a visual-style document and not a feature-decision method.

The frontend is three things at once:

1. **Static pages** — landing, catalogue, trust pages, and factory-generated
   lesson pages. Fast, indexable, readable with JavaScript off.
2. **Server-rendered app pages** — `/app/*`, auth screens, and `/admin/*`,
   rendered by the Python service with small vanilla-JS islands.
3. **Islands** — the voice dock, simulations, checks, read-aloud, timers,
   palettes. Small, local, progressively enhanced.

Read the doctrine first, then the frozen product map, then the screen's spec.
There is **no SPA**. No React/Vue runtime, no Node build, no client-side
router, no hydration framework. If a change requires one of those, the change
is wrong for this repo.

## When to use this

Use this skill when any of these is true:

- You are building or changing a Zivon frontend surface: landing, catalogue,
  class page, lesson, dashboard, practice, speaking, tests/series, progress,
  SWOT, doubts, bookmarks, settings, auth, admin.
- You are preparing a standalone example page for the founder's visual verdict.
- You are reviewing a frontend PR, a screen-state matrix, or a component spec.
- A page breaks at 360 px, in reduced motion, offline, with JavaScript off, in
  Hindi/Hinglish, or when the student has no voice consent.
- You must decide whether a surface is static, server-rendered, or an island.
- You are adding a component and need to know whether it belongs in the kit.
- You are writing frontend tests, a11y checks, or perf-budget evidence.

Do **not** use it for: backend or database design (`zivon-systems-design-skills`),
feature decisions (`zivon-product-design-skills`), the voice pipeline itself,
content generation, or pixel-level visual rules — the doctrine owns those.

## Read first

This bundle uses progressive disclosure: the body is the workflow, the
references carry the detail for one job at a time, and the templates are copied
into the PR. Do not read every reference up front; use the reference map at the
bottom of this file.

Read in this order. Do not start a screen before you have read steps 1–4.

| # | Read | Why / load condition |
|---|---|---|
| 1 | `AGENTS.md` and `TIMELINE.md` | Repo law, current phase, decision gates, file ownership. Always. |
| 2 | `docs/frontend/design-doctrine.md` | The single visual source of truth. Read §0 (scope), §1–§9 (all surfaces), §10 (lesson extension), and §10.12–§10.14 (voice dock, read-aloud, consent). Always, before any UI work. |
| 3 | `tmp/full-frontend/FEATURE-MAP.md` + `REQUIREMENTS.md` | Frozen product map and buildable detail. Workspace-local and not committed; if absent, use `docs/product/features.md` + `docs/specs/frontend/`. The map wins over the requirements doc. |
| 4 | `docs/specs/frontend/spec.md`, `state-matrix.md`, `component-inventory.csv`, `ws-client-contract.md`, `shell-injection.md`, `perf-budget-tests.md`, `seo-plan.md` | The binding implementation contracts. Read the files for the surface you own. |
| 5 | `docs/product/features.md`, `ui-element-inventory.csv`, `information-inventory.csv` | Feature IDs, element IDs (`EL-`), information IDs (`INF-`), copy and privacy rules. Read the rows your screen cites. |
| 6 | `docs/backend/backend-spec.md`, `db-spec.md`; `docs/deployment/docker.md`, `cicd.md` | API/WS contracts, cookie/session model, retention, image and CI truth. Read before wiring data or auth. |
| 7 | `frontend/assets/zivon.css`, `zivon.js`; `frontend/index.html`; `frontend/courses/`; `frontend/privacy/`; `docker/nginx.conf`; `testing/frontend/` | The existing kit, shell, generated pages, headers, and tests. Match the best page, not the average — the published tree mixes pipeline versions. |
| 8 | `skills/code-review/code-review/SKILL.md` | Before opening the PR. Then load the matching lens. |

**Voice-dock doctrine guard.** If the task touches the voice dock and
`design-doctrine.md` has no §10.12, stop. Tell the founder. Do not design the
dock, do not improvise it, and do not write that doctrine section. The section
exists in the current doctrine (adopted 2026-11-10); re-check it rather than
assuming.

## Operating stance

1. **Doctrine first, pixels last.** The doctrine decides the look; the kit
   decides the markup. This skill tells you how to build and verify, never
   what colour or size a token should be.
2. **Product decisions are frozen.** Do not re-litigate features, routes,
   languages, auth, or SWOT rules. If a contract is missing, record the gap
   and ask; do not invent product behaviour in a template.
3. **Static first, server when the page's content is private.** Public discovery
   and lesson reading stay static. A page whose primary content needs a cookie,
   a private row, or a per-student computation is server-rendered. A public
   page may add a private *decoration* (the catalogue's signed-in progress)
   through a scoped same-origin island; the page itself stays static.
4. **Failure first.** Every component ships its loading, empty, partial,
   error, offline, permission, reduced-motion, untranslated, quota, and
   consent states — or an `n/a` with a reason.
5. **The child is the user.** No trackers, no leaderboards, no dark patterns,
   no raw audio, no public profile. Delete and export are product features,
   not afterthoughts.
6. **Visual exploration before implementation.** Build a runnable example,
   serve it on your assigned port, and wait for the founder's verdict. The
   same agent session implements it.

## The workflow

### 0. Classify the surface and check the gate

Write one line: *"`<screen>` is a `<static | generated lesson | SSR app | auth | admin>` surface at `<route>` for `<user>`."*

Then check the gates:

- Dock/read-aloud/consent work → doctrine §10.12–§10.14 exists.
- New product feature → a surviving decision-log row and feature card exist.
- New API/data → `backend-spec.md`/`db-spec.md` defines it, or the screen uses
  a fixture and the gap is recorded.
- New route → the route map in `REQUIREMENTS.md` §3.3 or `spec.md` §3 names it.

If a gate fails, stop and report. A mock example is still allowed; product code
is not.

### 1. Write the screen spec before the markup

Copy [templates/screen-spec.md](templates/screen-spec.md). Fill purpose,
route, surface type, regions, components, `EL-`/`INF-`/`NEED-`/`EVT-` refs,
data, API, events, all 11 states, a11y, perf, SEO, i18n, and privacy. A screen
with a blank state cell is not ready to build.

### 2. Decide the render mode and route

Use the table below. Do not "just make it a client component".

| Surface | Render | Examples | Rule |
|---|---|---|---|
| Public discovery | Static HTML | `/`, `/courses`, `/courses/{class}/physics`, `/method`, `/about`, `/pricing`, `/privacy`, `/terms`, `/contact`, `/status`, `/404` | Indexable, cacheable, works without JS. Generated at build/publish time. |
| Generated lesson | Static HTML + shell islands | `/courses/{class}-physics/{chapter}/` | Factory owns content; shell injects chrome (`shell-injection.md`). Indexable. |
| Authenticated app | Server-rendered HTML (FastAPI + Jinja) | `/app`, `/app/practice/*`, `/app/speaking/*`, `/app/tests/*`, `/app/series/*`, `/app/progress`, `/app/swot`, `/app/doubts/*`, `/app/bookmarks`, `/app/settings` | Private data, cookies, noindex. Small JS islands only. |
| Auth | Server-rendered | `/login`, `/signup`, `/verify-email`, `/forgot-password`, `/reset-password`, `/onboarding`, `/auth/google/*` | One paper card, no split-screen marketing, noindex. |
| Admin | Server-rendered, staff auth | `/admin/*` | Separate staff session, aggregate-only, noindex, never student-facing. |

The full route map and API namespace are in
[references/app-shell-and-routing.md](references/app-shell-and-routing.md).

### 3. Build the standalone example first

One HTML file or a small folder, real fonts, mock data, no backend, no
secrets. Show the default, empty, error, loading, offline, 360 px, 768 px, and
1280 px states that matter for the verdict. Serve it on your assigned port and
write a short review note. The protocol is
[references/visual-review-protocol.md](references/visual-review-protocol.md);
the verdict record is [templates/visual-verdict.md](templates/visual-verdict.md).

**Do not open a product PR before the verdict** unless the founder explicitly
waives it in writing.

### 4. Implement in the repo, kit-first

- New shared component → add it to `frontend/assets/zivon.css` (catalog) and
  `zivon.js`, then use it. Never invent page-local chrome.
- Generated page → render only content blocks; the shell injects dock,
  read-aloud, consent, report, and notices.
- SSR page → a Jinja template + a route that passes a typed view model. Keep
  the template dumb; compute in Python.
- Island → a single vanilla-JS script (no framework, no build step; modern
  syntax is fine, matching `zivon.js`) with a named global, an idempotent
  mount, and a no-op when its root is absent.
- Copy → a copy key or a UI string bundle. Never hard-code English inside a
  localized page.

### 5. Cover the states, not just the happy path

Use [references/screens-and-states.md](references/screens-and-states.md) and
[templates/state-matrix.md](templates/state-matrix.md). Every screen and every
region gets a row; every state cell names what the student sees and which code
path renders it. `n/a` is allowed only with a reason.

### 6. Apply the quality floor

Accessibility, performance, SEO, privacy, and i18n are part of the component,
not a later pass. The floor is in
[references/accessibility-performance-seo.md](references/accessibility-performance-seo.md)
and the component checklist in
[references/component-patterns.md](references/component-patterns.md).

### 7. Test deterministically

Static shell tests, browser behaviour tests, state coverage, a11y checks,
perf budgets, and no-network fixtures. Run
`python -m unittest discover -s testing/frontend -t .`. The test map is
[references/frontend-testing.md](references/frontend-testing.md).

### 8. Docs, review, PR

Update the doc that describes the change in the same PR: `docs/frontend/`,
`docs/specs/frontend/`, `docs/product/`, `docs/backend/`, or `AGENTS.md` if a
folder or rule changed. Run `ruff check .` and `ruff format --check .`. Open
the PR; a review agent merges. Never merge your own PR.

## Static vs SSR in one paragraph

If a stranger can see the page's primary content without signing in, it is
static and indexable. If the primary content needs a session cookie, a private
row, or a per-student computation, it is server-rendered and noindex. If it
only needs local interaction (a sim, a check, the dock, a timer), it is a
static page plus an island. A private decoration on a public page (signed-in
catalogue progress) is a scoped island, not a reason to move the page to SSR.
There is no third category called "client app".

## The 11-state rule

Every component and region accounts for:

`default`, `loading`, `empty`, `partial`, `error`, `offline`,
`permission-denied`, `reduced-motion`, `untranslated`, `quota-exhausted`,
`consent-missing`.

The matrix is the review artifact. A blank cell is a defect. A state that
cannot occur gets `n/a (reason)`, not silence. The screen-by-screen matrix is
in [references/screens-and-states.md](references/screens-and-states.md).

## Output contract

A frontend change is complete only when the PR contains all of these:

- **Screen spec** — [templates/screen-spec.md](templates/screen-spec.md).
- **State matrix** — [templates/state-matrix.md](templates/state-matrix.md),
  no blank cells.
- **Component checklist** — [templates/component-checklist.md](templates/component-checklist.md)
  for every new or changed component.
- **Visual verdict** — [templates/visual-verdict.md](templates/visual-verdict.md),
  including the founder's decision and what changed because of it.
- **Tests** — deterministic, key-free, offline; a regression test for every
  bug fixed.
- **Docs** — the doc that describes the surface is true after the change.
- **Evidence** — a11y, perf, and state-coverage results in the PR body.

## Worked example and anti-patterns

[references/worked-example.md](references/worked-example.md) walks the SWOT
screen from route to verdict, then contrasts the lesson shell (static + shell
injection). It also lists the anti-patterns that get rejected: the SaaS
dashboard, gradients and glass, leaderboards and streaks, the SPA, colour-only
mastery, dead controls, and the chat-bubble dock.

## Reference map

| Read this | When |
|---|---|
| [references/design-system.md](references/design-system.md) | Before any visual decision; to know which doctrine section applies and which kit component to compose |
| [references/app-shell-and-routing.md](references/app-shell-and-routing.md) | Before adding a route, proxy, cookie, auth screen, locale path, or SEO/noindex rule |
| [references/screens-and-states.md](references/screens-and-states.md) | Before writing a screen spec; to fill the 11-state matrix |
| [references/component-patterns.md](references/component-patterns.md) | Before adding or changing any UI component; to pick the right pattern and its states |
| [references/accessibility-performance-seo.md](references/accessibility-performance-seo.md) | Before calling a screen done; to check WCAG 2.2 AA, budgets, and metadata |
| [references/visual-review-protocol.md](references/visual-review-protocol.md) | Before building the example page, while waiting for the verdict, and when recording it |
| [references/frontend-testing.md](references/frontend-testing.md) | Before writing tests; to choose static, browser, state, a11y, perf, or auth coverage |
| [references/worked-example.md](references/worked-example.md) | First time through; to see the whole method on SWOT and the lesson shell, and the rejected patterns |

Templates: [screen spec](templates/screen-spec.md),
[state matrix](templates/state-matrix.md),
[component checklist](templates/component-checklist.md),
[visual verdict](templates/visual-verdict.md).

## Failure handling

| Situation | Do this |
|---|---|
| Doctrine has no §10.12 and the task is the dock | Stop; inform the founder; no dock UI work. |
| The frozen map and the requirements doc disagree | The map wins; record the conflict in the PR and raise it. |
| A screen needs a component the kit does not have | Add it to the kit first, with states and a11y; then use it. |
| The API does not exist | Build the example on fixtures; record the backend need; do not fake it in product code. |
| The founder has not given a verdict | Keep the example; do not open the product PR. |
| A perf or a11y budget fails | Fix the cause. Do not raise the threshold without a founder ruling. |
| The auth/security contract is unclear | Stop and ask. Never store a session token in `localStorage`. |

## Non-negotiables

- No SPA, no framework runtime, no Node build step, no client-side router.
- No external hosts, CDNs, third-party fonts, analytics scripts, or trackers.
- No secrets, API keys, DSNs, or tokens in frontend code, fixtures, or tests.
- Authenticated session state lives in `HttpOnly`, `Secure`, `SameSite=Lax`
  cookies — never a session token in `localStorage`. Device-local preferences,
  consent, dock state, and guest progress may use `localStorage` as specified
  in `docs/specs/frontend/shell-injection.md`.
- Voice consent is per device and gates the microphone; declining never blocks
  reading, simulations, checks, or typing.
- Never use colour alone for meaning; pair it with shape and words.
- Never ship a dead control; if the data or permission is absent, render
  nothing and say why.
- Never claim a CBSE paper is official or exact; use the approved copy.
- Never merge your own PR; the review agent merges.
