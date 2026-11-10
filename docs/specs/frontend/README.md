# Frontend implementation spec — SP5-FRONT (wave S1)

The implementation spec an execution agent builds the Zivon static frontend from:
every screen, component, state, event, and API/WS call the frontend owns, mapped to
the repo's binding artifacts. **This folder specifies; it does not build.** No code
ships in this change except the sanity-check script the docs protocol requires.

## Status and an honest scope note

The brief assumed these upstream artifacts exist: the features doc
(`docs/product/features.md`, `ui-element-inventory.csv`, `information-inventory.csv`,
`traceability-matrix.csv`, `decision-log.csv`), the backend spec
(`docs/backend/backend-spec.md`, ADRs 0001–0016), SP1's `ws-contract.md`, and SP3's
event contract. **None of them exist on any branch of the repo as of BASE
`0a43d95`** (each was checked with `git ls-tree -r` across all remote refs). The
base branch the brief names (`feature/backend-db-storage-spec`) does not exist
either; these patches chain from `origin/main`.

This spec therefore keys to what IS binding in the repo today:

| Source | What it binds for this spec |
|---|---|
| `docs/frontend/design-doctrine.md` (Field Notes v1.6) | every visual rule, the kit contract (§10.2), language bar (§10.5), a11y validation (§10.8). **UPDATE 2026-11-10:** §10.12 (voice dock, bottom-sheet shape), §10.13 (read-aloud) and §10.14 (consent gate) now exist. The dock is no longer founder-gated; DCR-002 is closed. §10.12 was self-reviewed against the five candidates and adopted with founder authorisation. |
| `frontend/assets/zivon.css` + `zivon.js` component catalog | the renderer-emitted markup contracts every page composes from |
| `docs/content-factory/blocks-schema.md` (v1, frozen) | the block types a lesson page renders |
| `docs/deployment/*`, `Dockerfile.frontend`, `docker/nginx.conf`, `scripts/publish-frontend.sh` | build/deploy/cache truth |
| `testing/frontend/`, `testing/content_factory/perf/` | the test layout and the current perf budgets |
| `skills/zivon-product-design-skills/…/03-granular-spec-method.md` | the EL-/INF-/NEED-/EVT- id scheme and inventory columns used here |
| `skills/zivon-frontend-skills/seo-optimization.md`, `skills/zivon-audio-engineering-skills/README.md` | SEO rules; browser-audio rules for the voice seam |

Consequently every `EL-`, `INF-`, `NEED-`, `EVT-` id in this folder is
**provisional** (marked `provisional` in the CSV; register tables in
`spec.md` §11). Each row carries a `source_ref` pointing at the binding in-repo
artifact it was derived from, so when the real features doc lands, remapping
provisional ids to the canonical EL-/INF- ids is a mechanical join, not a
re-spec. `open-questions.md` holds the full reconciliation list. **No new
features are specified** — only surfaces the shell and doctrine already show.

## File map

| File | Covers |
|---|---|
| [`spec.md`](spec.md) | the implementation spec: shell architecture, routing, per-screen/component behavior, voice-dock integration seam, locale switcher, event instrumentation, build/deploy/cache, a11y & privacy ground rules |
| [`component-inventory.csv`](component-inventory.csv) | one row per perceivable element (EL-keyed, provisional ids): component name, file location, data read (INF ids), states, a11y, perf, privacy, priority |
| [`ws-client-contract.md`](ws-client-contract.md) | the browser-side WebSocket client contract and state machine for the voice loop; server-side gaps flagged (no backend spec / SP1 contract exists) |
| [`state-matrix.md`](state-matrix.md) | implementation view of the screen-state matrix: rows = screens/regions, columns = the ten canonical states, cells = what the student perceives and which code path renders it |
| [`perf-budget-tests.md`](perf-budget-tests.md) | how CI enforces the page-load / fps / RAM budgets on low-end Android (extends `testing/frontend/`), both budget eras, reduced-motion tests |
| [`seo-plan.md`](seo-plan.md) | static multilingual SEO: meta + hreflang, sitemap/robots generation, JSON-LD, Open Graph, canonical URLs, the child-privacy guardrails that constrain all of it |
| [`shell-injection.md`](shell-injection.md) | binding contract for injecting product chrome (consent, dock, read-aloud, report, notices) into content-only generated pages from the shell kit |
| [`open-questions.md`](open-questions.md) | every unresolved upstream reference, the decision needed, and the reconciliation procedure for provisional ids |

## Binding ground rules (inherited — restated because every section depends on them)

1. **No framework, vanilla JS/CSS only.** Generated visuals are self-contained
   HTML/JS (canvas/SVG) (AGENTS.md "Architecture guidelines"). The shell imports
   nothing; the only dependencies are the bundled fonts.
2. **The kit is the contract.** `zivon.css` + `zivon.js` are the single standard
   toolkit (doctrine v1.6). Generated pages never re-implement, copy, or re-style
   kit chrome; model-authored `page.css` may style only inside `.zn-sim-<id>`
   (lint-enforced at factory stage 05).
3. **Zero network calls from pages.** CSP on generated pages is
   `default-src 'none'; … connect-src 'none'` (locked decision,
   `docs/deployment/README.md`). Anything that needs a network (voice WS, event
   sink) is a scoped CSP change request — see `ws-client-contract.md` §8 and
   `spec.md` §7.
4. **All states, failure first.** default / loading / empty / partial / error /
   offline / permission-denied / reduced-motion / untranslated /
   over-credit-budget — every component's states are enumerated; a state without
   an owner is a defect (state-matrix has no blank cells).
5. **Layer independence.** Core (reading, simulating, checking) works with voice,
   TTS, translation, and personalization all off; a failing add-on never blocks
   the core (AGENTS.md design-method principles).
6. **Low-end Android is the base case.** 360 px frame, ~4 GB RAM, throttled CPU,
   noisy rooms, variable connectivity (repo constraint; budgets in
   `perf-budget-tests.md`).
7. **Children are the users.** Private by default, data minimization, no
   trackers/analytics scripts, no third-party hosts, honest copy (DPDP flags in
   `seo-plan.md` §7 and `spec.md` §10).

## How to consume this spec

- An execution agent (EX5-FRONT) builds from `spec.md` + `component-inventory.csv`
  + the per-area files; each work item cites its source_ref and flags.
- The merge agent reads `open-questions.md` first: it lists every place this spec
  had to stand in for an absent upstream artifact.
- Status of the three formerly gated items: the voice-dock UI is now specified
  (doctrine §10.12–§10.14, 2026-11-10); the CSP `connect-src 'self'` relaxation
  for lesson pages is implemented; the localized route scheme (ADR-0009) remains
  a hook only and is P1.

## Docs sanity pass (the "tests" for this docs-only change, per protocol §4)

Docs-only agents' tests are a sanity pass: every CSV parses, every referenced
path exists, every cross-reference resolves. `scripts/check_specs.py` (shipped
in this patch series) implements it:

```bash
python3 scripts/check_specs.py
```

It asserts, for `docs/specs/frontend/`: every CSV parses with the documented
header; every repo path referenced in `source_ref` columns and file-map tables
exists; every `EL-`/`INF-`/`NEED-`/`EVT-` id used anywhere is defined in the
register tables or the inventory CSV; no placeholder tokens (`TODO`, `TBD`,
`XXX`, `【…】`) remain in the folder; and § anchors named in cross-references
exist in the target file. Exit 0 = green. The script is self-contained
(stdlib only) and keys off `AGENTS.md`'s "docs are tests too" spirit — a doc
that references a missing thing is a failing doc.
