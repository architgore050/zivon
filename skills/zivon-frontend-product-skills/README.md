# zivon-frontend-product-skills (bundle)

Skills for **building and reviewing the full Zivon frontend**: the public Field
Notes site, the static generated lesson pages, the server-rendered `/app`
product, auth, admin, and the states, accessibility, performance, SEO, and
visual-verdict discipline that hold them together.

This bundle is the **implementation entry point**. It does not decide product
features (that is `zivon-product-design-skills`), it does not design the backend
(`zivon-systems-design-skills`), and it does not own the visual language — the
visual source of truth is `docs/frontend/design-doctrine.md`. The existing
`skills/zivon-frontend-skills/seo-optimization.md` remains the **SEO reference**;
this bundle is where a frontend agent starts.

Status: **v1.0**, evidence date **2026-11-14**, written against `main` @
`57147bb` and the frozen full-frontend map of **2026-11-13**.

## Read order for an agent

1. This README (2 min).
2. [`SKILL.md`](SKILL.md) — the workflow. **Always.**
3. `docs/frontend/design-doctrine.md` — the visual source of truth, including
   §0 scope and §10.12–§10.14. **Before any UI work.**
4. `tmp/full-frontend/FEATURE-MAP.md` and `REQUIREMENTS.md` — the frozen
   product map and the buildable detail. Workspace-local; if absent, use
   `docs/product/features.md` and `docs/specs/frontend/`.
5. The one reference in [`SKILL.md`](SKILL.md) that matches your task; do not
   read the whole bundle up front.
6. `skills/code-review/code-review/SKILL.md` before opening the PR.

## Layout

```
zivon-frontend-product-skills/
├── README.md                         this file: layout, scope, provenance
├── SKILL.md                          the workflow and trigger surface
├── references/
│   ├── design-system.md              doctrine routing, tokens, kit, scope split
│   ├── app-shell-and-routing.md      static vs SSR, nginx, cookies, i18n, SEO
│   ├── screens-and-states.md         screen inventory + 11-state matrix
│   ├── component-patterns.md         component checklist + usage rules
│   ├── accessibility-performance-seo.md  WCAG 2.2 AA, budgets, metadata
│   ├── visual-review-protocol.md     example page, port, verdict, doctrine
│   ├── frontend-testing.md           static/browser/state/a11y/perf tests
│   └── worked-example.md             SWOT + lesson shell + anti-patterns
└── templates/
    ├── screen-spec.md                one screen, ready to build
    ├── state-matrix.md               the 11-state completeness artifact
    ├── component-checklist.md        one component, ready to review
    └── visual-verdict.md             the founder decision record
```

## Scope

**In scope**

- Public pages: landing, catalogue, class/course page, method, about, pricing,
  trust pages, 404, public search.
- Generated lesson pages and the lesson shell around them: drawer, progress,
  bookmarks, ask-about-this, read-aloud, language bar, voice dock, consent.
- Server-rendered app pages: dashboard, practice, speaking, tests/series,
  progress, SWOT, doubts, bookmarks, settings, privacy controls.
- Auth screens and flows: login, signup, verification, reset, onboarding,
  Google linking, guest merge.
- Admin surfaces: content coverage, question bank, series, blueprints, users,
  credits, reports, flags, evals, content debt.
- Cross-cutting: app shell, routing, cookies, i18n, state coverage, components,
  WCAG 2.2 AA, weak-Android performance, SEO/noindex, testing, and the
  founder visual-verdict protocol.

**Out of scope**

- Feature selection, PRDs, or re-deciding the frozen map.
- Backend, database, storage-tiering, auth-protocol internals, or deployment
  topology.
- The voice pipeline (Prisma/Timbre/Gemma), content generation, translation
  generation, and evals content.
- Pixel-level visual rules; the doctrine is the only authority.
- Any framework, SPA, Node build, or third-party UI library.

## Precedence

When two documents disagree, use this order and record the conflict:

1. `AGENTS.md` + `TIMELINE.md`.
2. `tmp/full-frontend/FEATURE-MAP.md` (frozen 2026-11-13).
3. `docs/specs/*` and `docs/backend/adr/`.
4. `docs/content-factory/*`.
5. The agent handshake (process and allocation only).
6. `tmp/full-frontend/REQUIREMENTS.md`.

The frozen map wins over the requirements doc. The doctrine wins over any
example or mockup. The kit wins over any page-local invention.

## Provenance and sources

This bundle is original writing. It paraphrases repo decisions and public
standards; it copies no third-party prose. The external sources below were
checked on 2026-11-14 and are used for stable, testable rules only.

| Source | URL | Used for |
|---|---|---|
| W3C, *Web Content Accessibility Guidelines (WCAG) 2.2* (Recommendation, 12 Dec 2024) | https://www.w3.org/TR/WCAG22/ | AA target, success-criterion numbers, focus/target/reflow rules |
| MDN, *Using HTTP cookies* | https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies | `HttpOnly`/`Secure`/`SameSite`, session fixation, cookie scope |
| MDN, *Content Security Policy (CSP)* | https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP | strict CSP, no inline/eval, same-origin policy |
| web.dev, *Web Vitals* (updated 31 Oct 2024) | https://web.dev/articles/vitals | LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 at p75 |
| schema.org, *LearningResource* | https://schema.org/LearningResource | lesson-page JSON-LD type and properties |

Repo sources that bind this bundle:

| Source | Version / date | Binds |
|---|---|---|
| `docs/frontend/design-doctrine.md` | Field Notes v1.6; §10.12–§10.14 adopted 2026-11-10 | every visual rule, scope split, lesson extension, dock/read-aloud/consent |
| `docs/specs/frontend/` | SP5-FRONT wave S1, 2026-11-10 | routes, screens, states, components, WS client, perf, SEO, shell injection |
| `docs/product/features.md` + inventories | 2026-11-07 | feature cards, `EL-`/`INF-`/`NEED-`/`EVT-` IDs, privacy classes |
| `docs/backend/backend-spec.md`, `db-spec.md` | Stage 2 | API/WS contracts, cookies, retention, deletion |
| `docs/deployment/docker.md`, `cicd.md` | current | frontend image, nginx, CI jobs, smoke tests |
| `frontend/assets/zivon.css`, `zivon.js`; `frontend/index.html`; `frontend/courses/`; `frontend/privacy/`; `docker/nginx.conf`; `testing/frontend/` | current tree | the kit, shell, generated output, headers, tests |
| `tmp/full-frontend/FEATURE-MAP.md`, `REQUIREMENTS.md` | map frozen 2026-11-13; requirements draft | full-product scope, routes, screens, states, data, API, workstreams, acceptance |

The full-frontend plan lives in the workspace's gitignored `tmp/` folder. It is
cited as the planning artifact, not as a durable repo file. Everything this
bundle relies on is restated here or traceable to the committed docs above;
exact content-volume counts and the workstream briefs stay in the planning
artifact.

## Maintenance

Re-check this bundle when any of these changes:

- the doctrine version or any §10.12–§10.14 rule;
- the frozen feature map, route map, auth model, or language rules;
- `docs/specs/frontend/` component inventory, state matrix, WS contract, or
  perf/SEO plan;
- the enforced performance profile or the Era-2 re-tighten;
- WCAG, CSP, cookie, or Core Web Vitals guidance;
- the frontend test layout or CI jobs.

Cadence: review at every frontend wave boundary and at least quarterly. A stale
skill is worse than no skill because it teaches yesterday's contract.

## Validation

```bash
python3 scripts/check_skills.py --strict --bundle skills/zivon-frontend-product-skills
python -m unittest discover -s testing/skills -t .
python -m unittest discover -s testing/frontend -t .   # needs Playwright Chromium
ruff check . && ruff format --check .
```

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-14 | First release: full-frontend implementation skill, 8 references, 4 templates, worked SWOT/lesson example, anti-patterns, validator test |
