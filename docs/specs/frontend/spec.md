# Zivon frontend implementation spec

Agent: SP5-FRONT (wave S1, docs-only) · Status: SPEC (no product code in this change)
Consumes: `docs/frontend/design-doctrine.md` v1.6 (binding visual style),
`frontend/assets/zivon.css` + `zivon.js` (the kit), `docs/content-factory/blocks-schema.md`
v1, `docs/deployment/`, `Dockerfile.frontend`, `docker/nginx.conf`,
`scripts/publish-frontend.sh`, `testing/frontend/`, `testing/content_factory/perf/`.
Missing upstream (flagged, not worked around): `docs/product/features.md` + inventories +
decision log, `docs/backend/backend-spec.md` + ADRs, SP1 `ws-contract.md`, SP3 event
contract — see `open-questions.md`. All `EL-/INF-/NEED-/EVT-` ids here are provisional.

---

## 1. Ground rules

Inherited from `AGENTS.md`, the doctrine, and the deployment docs; restated as
testable rules because every section below depends on them:

| # | Rule | Enforcement today |
|---|---|---|
| G1 | Vanilla HTML/CSS/JS only; no framework, no build step, no bundler | repo convention; `testing/frontend/test_shell.py::test_self_contained_no_network_refs` |
| G2 | Pages make zero external calls; CSP `default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'none'; base-uri 'none'` on generated pages | meta CSP on every generated page; re-verified on published snapshots in CI |
| G3 | The kit (`zivon.css`/`zivon.js`) is the only owner of chrome; generated `page.css` styles only inside `.zn-sim-<id>` | factory lint at stage 05 (doctrine v1.6) |
| G4 | All ten states specified per component: default, loading, empty, partial, error, offline, permission-denied, reduced-motion, untranslated, over-credit-budget | `state-matrix.md` (no blank cells) |
| G5 | Layer independence: core (read/simulate/check) never depends on voice, TTS, translation, personalization | core pages carry `connect-src 'none'` and no mic code |
| G6 | Low-end Android is the base case: 360 px frame, ~4 GB RAM, 4× CPU throttle | perf budgets, `perf-budget-tests.md` |
| G7 | Child privacy: no trackers, no third-party hosts, no behavioural profiling; analytics pseudonymous and free of child free-text | CSP G2 + `seo-plan.md` §7 |

---

## 2. Shell architecture (static-site structure)

### 2.1 The two kinds of content

| Kind | Location | Owner | Deployed |
|---|---|---|---|
| Hand-maintained shell | `frontend/index.html`, `frontend/assets/*` (css, js, fonts, `FONTS-LICENSE.md`) | humans/agents edit in repo | baked into `Dockerfile.frontend` at `/opt/zivon-shell`, seeded to the served root by the `seed-shell` initContainer (`cp -rn`, no-clobber) — `k8s/30-frontend-deployment.yaml` |
| Generated pages | `frontend/courses/<course_id>/<topic_slug>/` (`index.html`, `page.js`, optional `page.css`, `manifest.json`) + catalogue `frontend/courses.js` | the content factory (stage 11-link writes the PVC; `scripts/publish-frontend.sh` mirrors PVC → repo) | never baked into an image; arrive at runtime on a volume (compose) or the `zivon-frontend` PVC (cluster), mounted at the html root |

Rules the execution agent must not break:

- The shell stays repo-owned; `publish-frontend.sh` copies `courses/` + `courses.js`
  ONLY and refuses to touch the shell. A re-publish wholesale-replaces a topic's
  previous version (git history is the version rotation).
- `courses.js` is generated (`do not edit by hand` header) and holds the catalogue
  array `window.ZIVON_COURSES`; the landing renderer (`zivon.js::renderCourses`) is
  the only consumer. Field contract: `href`, `course_id`, `class`, `title`,
  `chapter`, `generated_at` (all strings/int as in the current file).
- Every page (shell AND generated) is offline-capable: one HTML file + the shared
  shell assets + local fonts. No CDN, no Google Fonts at runtime (doctrine §10.11:
  the pipeline must vendor fonts into the page folder — already true for the shell's
  `assets/fonts/`).

### 2.2 The kit as the component system

`zivon.css`'s header catalog is the canonical component list. The spec-level
contract an implementer works against:

- **Page chrome**: `.zn-page` (paper) → `.zn-header` (`.zn-kicker`, `.zn-title`,
  `.zn-objectives-label`, `.zn-objectives`), `.zn-glossary`, `.zn-footer`.
- **Language bar**: `.zn-lang-bar` (sticky top, in flow, renderer-emitted) →
  `.zn-lang-in` → `.zn-lang-lab` + `.zn-lang-row[role=radiogroup]` →
  `.zn-chip[role=radio]`.
- **Content blocks**: `.zn-text`, `.zn-example` (worked example), `.zn-answer`.
- **Taped cards** (things the learner operates): `.zn-reveal` (native `<details>`
  steps), `.zn-check` (quiz fieldset: `legend` question with the float rule,
  `label.zn-opt` native radios, `.zn-check-btn`, `.zn-check-feedback[aria-live]`,
  `details.zn-check-why`), `.zn-sim` (controls: `label.zn-sim-control` = `span` +
  `range` + `output`; `.zn-sim-canvas-wrap` > `canvas.zn-sim-canvas` sized by the
  kit at 480×320 buffer; `.zn-sim-desc`).
- **Diagram**: `.zn-diagram` figure → `.zn-diagram-svg` (≤ 8 rows, aspect read
  from the model SVG `viewBox` via CSSOM — markup style attributes stay banned by
  CSP) + `figcaption`.
- **Behaviour services** (`zivon.js`): quiz wiring (`wireCheck`, shape+words
  feedback ✓/✗), `ZivonSim` runtime (registration, rAF loop, reduced-motion
  single-draw, on-canvas error painter — a broken simulation is loud, never
  blank), landing course renderer, `LessonKit` (measured ruled lines SVG +
  baseline normalisation + pen underline §4.1 on `h1.zn-title`), language chip
  wiring (visual toggle only until i18n-aware generation lands).

Anything new the frontend needs MUST become a kit component first (add to
`zivon.css` catalog + `zivon.js`), never a per-page invention. This is the
v1.6 doctrine's building-blocks directive.

### 2.3 Screens that exist today (the full list — nothing else is in scope)

| Screen id (provisional) | Route | Files |
|---|---|---|
| `SCR-HOME-01` — course catalogue / landing | `/` (`index.html`) | shell only |
| `SCR-LES-01` — lesson page | `/courses/<course_id>/<topic_slug>/` (`index.html`) | generated page + kit |
| `SCR-404-01` — not found | any unmatched URL | nginx `=404` today (unbranded; §6 specifies the branded page) |

Non-page surfaces owned by the shell today: none (no toasts, no dialogs, no
consent flow — the voice add-on introduces the first ones; §7).

---

## 3. Routing model

### 3.1 Today: file-path routing on nginx

- nginx `try_files $uri $uri/ =404` (`docker/nginx.conf`); directory URLs serve
  `index.html`; `autoindex off`.
- Canonical URL shape (from the catalogue): `/courses/<course_id>/<topic_slug>/`,
  where `course_id` is `class-<N>-physics` and `topic_slug` is the factory's slug.
  These path segments are stable publish-to-publish (the run id and
  `generated_at` live in `manifest.json`, not the URL) — crawlers and links can
  rely on them.
- The landing page is the catalogue: `index.html` + `courses.js` render the list
  client-side from the inline `window.ZIVON_COURSES` (no fetch; the file is a
  `<script src>` — `courses.js` is `no-store` cached so a pipeline re-run shows
  immediately, per the nginx cache map).

### 3.2 Future localized routes — the reserved hook (DCR-001 deferred; ADR-0009 absent)

The brief says: note the hook, do not build it. The hook, specified so a later
agent can build it without re-working anything:

1. **URL scheme reserved**: localized variants live under a single path prefix
   `/{locale}/…` (e.g. `/hi/courses/class-9-physics/motion/index.html`); the
   unprefixed tree stays the English canonical. `locale` is constrained to the
   ADR-0009 language list (absent — provisionally `en`, `hi`, `hi-Latn` per
   doctrine §10.5's English / हिन्दी / Hinglish). No wildcard-locale routing in
   nginx until the scheme is decided — the hook is a naming convention, not code.
2. **Document hook already present**: every page carries `<html lang="…">` and
   the lesson bar chips toggle it (`zivon.js::wireLangChips` toggles the selected
   chip; doctrine §10.5: switching `lang` + selected state only). A localized
   route is the same page with `lang` and content swapped at publish time — no
   runtime router, ever (G1).
3. **Generation hook**: localized trees can only be produced by i18n-aware
   content generation (factory side) and mirrored by the publish flow; the
   frontend never translates at runtime. This is a factory/publish work item,
   not a frontend one — tracked in `open-questions.md` Q7.
4. **SEO hook**: hreflang pairs + per-locale sitemap entries are specified in
   `seo-plan.md` §3 but marked do-not-build until ADR-0009 lands.

---

## 4. Screen & region list (provisional)

Regions follow the method's `SCR-<AREA>-NN.R<n>` scheme; they define the
walk-through order for the inventory (top-left → bottom-right, every state).

| Screen | Region | Contents (element ids in `component-inventory.csv`) |
|---|---|---|
| `SCR-HOME-01` | `.R1` document head | `EL-HOME-01-001` |
| `SCR-HOME-01` | `.R2` header | `EL-HOME-01-002..004` |
| `SCR-HOME-01` | `.R3` course list | `EL-HOME-01-005..007` |
| `SCR-HOME-01` | `.R4` footer | `EL-HOME-01-008` |
| `SCR-LES-01` | `.R1` language bar | `EL-LES-01-001..004` |
| `SCR-LES-01` | `.R2` page header | `EL-LES-01-005..008` |
| `SCR-LES-01` | `.R3` block stream (repeats per block) | `EL-LES-01-010..060` (one family per block type) |
| `SCR-LES-01` | `.R4` page footer / sources | `EL-LES-01-070` |
| `SCR-LES-01` | `.R9` reserved: voice dock region | `EL-LES-01-090` (founder-gated, empty today) |
| `SCR-404-01` | `.R1..R2` | `EL-404-01-001..003` |

---

## 5. Lesson page: block → component mapping (the kit in practice)

`blocks-schema.md` v1 is frozen; the mapping below is the frontend's half of
that contract. Every generated page renders exactly these shapes, composed from
kit components only (G3).

| Block `type` | Rendered as | Component (kit) | Interactive elements | State contract (see `state-matrix.md`) |
|---|---|---|---|---|
| `text` | paragraph stream on the ruled lines | `.zn-text > p` | none | default; untranslated (§8) |
| `worked_example` | typed worked example | `.zn-example` (problem, decimal `steps`, `.zn-answer` + `.zn-answer-label`) | none | default; untranslated |
| `check` (mcq) | quiz card | `.zn-check` fieldset: `legend`, `label.zn-opt` × options (native radios `name=check-<block-id>`), `.zn-check-btn`, `.zn-check-feedback[aria-live=polite]`, `details.zn-check-why` | radio select; Check; retry allowed (learning, not testing) | default; unanswered (feedback empty); answered-correct (✓ + words, tick-green reserved); answered-wrong (✗ + words, pencil-red reserved); numeric variant: `.zn-numeric-input` + 1%-tolerance compare (first number in `data-answer`) |
| `reveal` | expandable steps card | `.zn-reveal > details.zn-reveal-step > summary + p` | native `<details>` toggle (zero JS) | closed / open; reduced-motion n/a (no animation) |
| `diagram` | clean-geometry SVG on the paper, no card | `.zn-diagram` figure → `.zn-diagram-svg` + `figcaption` | none (constructive geometry only — graphs/areas are `simulation` blocks per the 0.3.17 computed-geometry routing) | default; error: factory lint forbids script/style/external URLs in the SVG, so a page that passed lint cannot render a broken diagram — no client error state required (asserted by `test_self_contained_no_network_refs`) |
| `simulation` | taped sim card | `.zn-sim`: title, `.zn-sim-controls` (labelled ranges + `output` readouts), `.zn-sim-canvas-wrap > canvas.zn-sim-canvas`, `.zn-sim-desc` | slider input (label + value + units per control); zero controls = animation | default/running; **error: on-canvas painter** (`paintError`: paper background, `simulation error:` + message, console.error) — loud, never blank; reduced-motion: exactly one static draw, no rAF loop; **`.zn-sim-read` text mirror: kit wires the live region, the Builder's `page.js` must populate it each draw** (040410 live-validation finding) |

Registration contract (unchanged from `blocks-schema.md`):

```js
ZivonSim.register("<BLOCK_ID>", { init: function (ctx) {…}, draw: function (ctx) {…} });
// ctx: {canvas, g, width, height, values, t}   values: control id → parseFloat(input.value)
```

Hard rules for `page.js` authors (factory prompts already carry these; listed
here because the frontend owns the runtime): no `eval`, no network, no kit-chrome
re-styling, every derived number computed in JS from the cited equations (never
hand-placed), update `.zn-sim-read` inside `draw`, throw early in `init` — the
error painter is the designed failure surface.

---

## 6. Screen spec: `SCR-404-01` (branded not-found — new, shell-owned)

Today an unmatched URL returns nginx's default `404` page (off-brand, English
only, no way back). Spec:

- `frontend/404.html`, shell-owned, §1–§9 doctrine look (NO §10 devices — scope
  guard), one screen: `EL-404-01-001` title ("Page not found" copy key
  `notfound.title`), `EL-404-01-002` one-sentence body (`notfound.body`), a link
  back to `/` (`notfound.back`). No locale switcher (shell pages stay English
  until localized routes land — §8).
- nginx: `error_page 404 /404.html;` in `docker/nginx.conf` — the ONLY nginx
  config change in this spec, listed in §12's change list. Cache: `no-store`
  (matches the `.html` map rule).
- States: default only. It is a dead end by definition; no JS.

---

## 7. Voice dock integration (the seam — UI is founder-gated)

**Standing guard (DCR-002): `design-doctrine.md` v1.6 contains NO §10.12 voice
dock directive** (§10 ends at 10.11; verified against the file). Therefore: the
dock's visual design, placement, and copy are **founder-authored, founder-gated
work — this spec does not design them**. What the frontend CAN specify today is
the integration seam a dock plugs into:

1. **Reserved region**: `.R9` at the end of the lesson page body (after the
   footer, inside `.zn-page` so the kit's rules/observers own it when it
   appears). Today it renders nothing. Any dock implementation must mount here
   and MUST be a kit component first (G3).
2. **WS client contract**: `ws-client-contract.md` specifies the browser-side
   state machine (`idle → requesting-permission → ready → listening →
   endpointing → thinking → speaking → interrupted → ready/ended`, plus
   `error/offline` and the named failure branches), the message catalogue, and
   barge-in/ducking behavior — consuming `skills/zivon-audio-engineering-skills/`
   for the audio rules. The server side is a **flagged gap**: SP1's
   `ws-contract.md` and `docs/backend/backend-spec.md` do not exist; the voice
   backend itself is still an open TIMELINE item (⬜ FastAPI/WebSockets
   Deployment + Service).
3. **Degraded fallback to text input**: specified as CLIENT behavior in
   `ws-client-contract.md` §7 (typed input path, session-preserving retry,
   offline message that preserves the lesson) because the features doc that
   would bind the product behavior is absent — the fallback is the
   layer-independence rule (G5) applied to the voice add-on.
4. **CSP change request (gated)**: a page hosting the dock needs
   `connect-src 'self'` + wss — today's locked `connect-src 'none'` forbids it.
   This is a deliberate, scoped relaxation request to the founder
   (`ws-client-contract.md` §8): the dock page's CSP relaxes ONLY `connect-src`;
   generated core pages never carry a mic and keep `'none'` (G5's enforcement).
5. **Gate C budget**: end-of-speech → first spoken audio < ~4 s, streaming;
   the contract's messages carry per-stage timestamps so the 0–300 ms /
   0.3–2 s / 2–4 s / >4 s UX ladder (acknowledge → thinking → filler →
   apology+typed option) is measurable, not vibes.

## 8. Locale switcher

- **UI (v1, ships today)**: the doctrine §10.5 language bar — renderer-emitted
  kit chrome on lesson pages ONLY (`.zn-lang-bar`; §0 scope guard: it never
  leaks to the shell or post visuals). One label ("Language") + one chip per
  language: **English, हिन्दी, Hinglish** (the doctrine's v1 list; the brief's
  ADR-0009 language list is absent — flag Q4 in `open-questions.md`). Chip
  anatomy: Bricolage 500/15, min-height 40 px, 2 px corners, 1 px ink border,
  `role=radio` in a `role=radiogroup`; selection by ink fill + paper-light text
  (15.0:1) — never colour alone.
- **Behavior (v1, honest stub)**: chips switch the selected state and
  `document.documentElement.lang` only — string swaps are shell-owned and land
  with i18n-aware content generation (doctrine v1.6 §10.5 ruling; factory work
  item, Q7). The UI must not pretend: no chip implies translated content that
  does not exist.
- **Persistence (device pseudonym per the brief's ADR-0007 — ABSENT, flag Q3)**:
  until that ADR exists, the only sanctioned persistence is local-only:
  `localStorage["zivon.lang"] = <locale>` written on explicit chip activation,
  read on load to preselect a chip; no server write, no identifier, cleared by
  the platform's storage controls. When ADR-0007 lands, the same key becomes the
  device-pseudonym-scoped preference — the read/write site does not move.
- **Untranslated state (per the method's translation rules)**: when i18n-aware
  generation lands and a block lacks a translation for the selected language,
  show the English string AND a visible notice (copy key
  `lesson.untranslated.notice`) — never mix silently, never imply the missing
  string was reviewed. Machine-translated vs reviewed content must be
  distinguishable (honesty rule; method reference 05 §2.2).
- **Never translated**: SI units, symbols (`v`, `a`, `F`, `Δ`), equations;
  numerals stay Western Arabic until an audience decision says otherwise
  (recorded per language when it happens).

## 9. Event instrumentation

**Flag (Q5): SP3's event contract does not exist**, so this section defines the
client-side catalogue the frontend owns and marks the alignment debt. Events
follow the method's `EVT-<verb_noun>` scheme; each names its privacy class and
its trigger; the full table lives in the register below (§14.3).

| Event (provisional) | Emitted by | Properties (beyond `ts`, `locale`, `screen`) |
|---|---|---|
| `EVT-lesson_viewed` | lesson page load (kit boot, after first paint) | `course_id`, `topic_slug`, `generated_at`, `block_count` |
| `EVT-lesson_opened` | catalogue card click (`SCR-HOME-01.R3`) | `href`, `course_id` |
| `EVT-sim_control_changed` | sim slider input | `block_id`, `control_id`, `value_bucket` (quantised; raw values may encode nothing sensitive but keep the bucket discipline) |
| `EVT-check_answered` | Check button | `block_id`, `format`, `correct` (bool) — never the option text |
| `EVT-check_retried` | Check after a wrong answer | `block_id`, `attempt_no` |
| `EVT-reveal_opened` | `details` toggle open | `block_id` |
| `EVT-lang_switched` | chip activation | `from`, `to` |
| `EVT-sim_error` | error painter | `block_id`, `message_hash` (not the raw message) |
| `EVT-mic_pressed` / tutor-session events | voice dock (founder-gated) | specified in `ws-client-contract.md` §6 |

Transport — the hard constraint: **G2 (`connect-src 'none'`) forbids any sink
today.** The spec'd design keeps the layer honest without violating CSP:

1. `zivon.js` gains a `ZivonEvents` queue (in-memory, session-scoped, capped —
   e.g. 200 events, oldest dropped) with a no-op default sink. Events are
   structured (`{v, evt, ts, screen, props}`), never free-text child input.
2. The sink is filled ONLY when both (a) a same-origin collector endpoint exists
   (backend need `NEED-003`, §14.2) and (b) the founder approves the scoped CSP
   change (`connect-src 'self'` on pages that opt in — same request shape as the
   voice dock's, one change request covers both). Until then events are
   observable in `console.debug` behind a `zivon.evtdebug` flag, which is
   already useful for the Day-9 telemetry work and burns zero credits.
3. Privacy class per event is in the register; `child-voice` events (mic) are
   founder-gated with the dock. No third-party analytics, ever (G7).

## 10. Accessibility & motion

- **Target**: WCAG 2.2 AA (method reference 06). Concrete, already-decided
  mechanics: contrast tokens validated in doctrine §10.8; native
  `button`/`input`/`details` controls; `radiogroup` semantics for the language
  bar; focus ring 3 px pen-blue + 3 px offset; touch targets ≥ 40 px (≥ one row
  in-card); `aria-live=polite` on check feedback and the sim read mirror;
  `lang` attributes per block when scripts mix (Devanagari vs Latin).
- **Reduced motion**: the lesson chrome has no animation (doctrine §10.8), so
  the only motion source is `ZivonSim`: `prefers-reduced-motion: reduce` →
  exactly one static draw per sim (already implemented, tested — see
  `perf-budget-tests.md` §5). Any future kit animation MUST gate on the same
  media query at the kit level.
- **Canvas a11y**: every sim carries a text mirror (`.zn-sim-read`,
  `aria-live=polite`) the Builder populates; diagrams carry `aria-label`
  listing their labels (doctrine §10.7). Drag alternatives (WCAG 2.2
  single-pointer rule): any future draggable sim object ships a non-drag path
  (arrow-key nudge or ± buttons) — spec'd now so the Builder prompts inherit it.
- **Focus**: no focus traps; focus order follows DOM order; the sticky language
  bar must never cover the focused control on scroll (check at 360 px).

## 11. Performance (pointer) and budgets

The enforcement design (CI wiring, thresholds for both budget eras, reduced-
motion and long-task tests, font-payload findings — the shell ships ~940 KB of
variable TTFs today, the single biggest budget risk) lives in
`perf-budget-tests.md`. Budget summary: page load < 2 s and ~60 fps (24 fps
under 4× throttle) are the Phase-4 re-tighten targets; the currently-enforced
gate is the founder-loosened profile (`weak-android.json`: load 6.0 s, FCP
3.5 s, RAM 750 MB) until real measurements exist.

## 12. Build, deploy, cache & versioning

### 12.1 Image and serving (unchanged contracts)

- `Dockerfile.frontend` bakes shell + nginx site config only; generated pages
  arrive via volume/PVC. `k8s/30-frontend-deployment.yaml` seeds the shell
  no-clobber (`cp -rn`) and runs nginx as UID 1000 (the PVC writer). The
  execution agent changes none of this for the frontend spec items below.
- Serve smoke in CI (`frontend-image` job): container up on :8080, `/healthz`
  answers, landing renders, CSP/nosniff/no-store headers present — the branded
  404 joins this smoke (assert `/definitely-missing` returns the branded page).

### 12.2 Change list for the execution agent (all shell/nginx-side, no CI edits)

| # | Change | Where | Why |
|---|---|---|---|
| C1 | Branded 404 page + `error_page 404 /404.html;` | `frontend/404.html` (new), `docker/nginx.conf` | §6; demo polish, off-brand default today |
| C2 | `ZivonEvents` queue + no-op sink + `zivon.evtdebug` | `frontend/assets/zivon.js` | §9; Day-9 telemetry groundwork, zero CSP impact |
| C3 | Locale persistence `localStorage["zivon.lang"]` + chip preselect | `frontend/assets/zivon.js` (`wireLangChips`) | §8 |
| C4 | Font payload reduction: subset + convert the four TTFs to woff2 (keep TTF fallbacks), `preload` the two above-the-fold faces (Bricolage variable, Courier Prime regular) | `frontend/assets/fonts/`, `zivon.css` | §11; ~940 KB → est. <300 KB, the only realistic path inside the <2 s re-tighten on 3G-class networks. Keep `FONTS-LICENSE.md` accurate; re-run the perf gate before/after |
| C5 | Reserved voice-dock mount region + lazy loader stub (loads NOTHING until the founder's dock lands) | `zivon.js` boot + `spec.md` §7 | §7 seam |

Not in this list (explicitly): any CI workflow edit (integration_notes for the
merge agent: `perf-budget-tests.md` §6 describes the `tests`-job extension and
the Lighthouse-CI job the CI/CD agent must add); any factory/renderer change
(JSON-LD emission — `seo-plan.md` §4 assigns it); any CSP relaxation (founder).

### 12.3 Cache & versioning strategy for generated pages

- Status quo (keep): HTML + `courses.js` `no-store` (demo freshness — a
  re-run shows immediately); everything else `public, max-age=300` + gzip.
- The pages themselves are versioned by git (the publish flow commits the
  snapshot; `manifest.json` carries `run_id` + `generated_at` per page) — no
  cache-busting query strings needed while HTML is `no-store`.
- **Immutable assets are optional, not required, for the demo; specified for
  the post-challenge path**: if the factory starts content-hashing per-page
  assets (`page.<hash>.js`), nginx needs no change (map default 300 s; the
  audio-skill's `max-age=31536000, immutable` rule applies to content-hash
  names if/when static narration audio lands). Until then, 300 s revalidation
  is the correct trade — correctness over cleverness (the nginx header
  comment's own rule).
- `robots.txt` + `sitemap.xml` (static files at the root) are generated at
  publish time — `seo-plan.md` §5; they ride the same no-store/300 s map
  (`.xml` under the 300 s default is fine; keep `robots.txt` at 300 s too).

## 13. SEO & discoverability (pointer)

Full plan in `seo-plan.md`: per-locale meta + hreflang (gated on ADR-0009),
canonical URLs (`ZIVON_PUBLIC_BASE_URL`), sitemap.xml + robots.txt generation
hooked into the publish flow, JSON-LD (`LearningResource`/`Course`) per lesson
page from `manifest.json`, Open Graph cards for demo/build-in-public sharing,
Core Web Vitals riding the existing budget — all under the child-privacy
guardrail (no third-party SEO tools, trackers, or hosts; CSP-safe by
construction).

## 14. Traceability: provisional registers

### 14.1 Information items (INF-, provisional)

| id | Name | Source (real file/field) | Shown in | Nullability & fallback | Localization |
|---|---|---|---|---|---|
| `INF-001` | Lesson title | `courses/<…>/manifest.json:.title` | `EL-LES-01-006`, card title, `<title>` | required (publish smoke requires manifest) | translate at build time |
| `INF-002` | Course id | `manifest.json:.course_id` | kicker, card meta | required | never |
| `INF-003` | Class level | `manifest.json:.class` | card meta, JSON-LD | required | numerals per §8 |
| `INF-004` | Chapter name | `manifest.json:.chapter.title` | card chapter line | required | translate at build time |
| `INF-005` | Generated-at timestamp | `manifest.json:.generated_at` (ISO 8601) | card meta | required | ISO, never translated |
| `INF-006` | Sources + licenses | `manifest.json:.sources[]` | page footer/sources line | required | license names never translated |
| `INF-007` | Learning objectives | rendered `.zn-objectives` list | `EL-LES-01-008` | optional (renderer emits when authored) | translate |
| `INF-008` | Block stream (typed content) | `manifest.json:.block_counts` + rendered blocks | `.R3` | required ≥1 block | translate; units/symbols never |
| `INF-009` | Sim live state | `page.js` computation | `.zn-sim-read`, `output`s | live; error → painter | numerals; units never |
| `INF-010` | Catalogue entries | `frontend/courses.js` (generated) | `EL-HOME-01-006/007` | empty → empty state | per-field as above |

### 14.2 Backend needs (NEED-, provisional — the static site needs almost nothing)

| id | Capability sentence | Caller | Status |
|---|---|---|---|
| `NEED-001` | Retrieve the lesson bundle for topic T (served statically as `manifest.json` + rendered page) | lesson page | SATISFIED by the publish flow; no runtime API |
| `NEED-002` | Realtime tutor channel (streaming STT → reasoning → TTS over WS) | voice dock (founder-gated) | ABSENT — `ws-client-contract.md` defines the client expectation; backend open (TIMELINE ⬜) |
| `NEED-003` | Same-origin event sink accepting batched `ZivonEvents` payloads (pseudonymous, no child free-text) | `ZivonEvents` | ABSENT — blocked on founder CSP decision + Phase-3 telemetry; queue design keeps the UI honest meanwhile |

### 14.3 Event register

See §9's table — that table IS the register (provisional until SP3's contract
lands; alignment debt recorded in `open-questions.md` Q5).

### 14.4 Walk-through test (the brief's done-criterion)

Any pixel/word/sound a student can perceive on a spec'd screen traces as follows:
element row in `component-inventory.csv` (EL- id, component, file, states) →
`source_ref` names the binding artifact it comes from (doctrine §, kit file,
blocks-schema, nginx config) → data reads point at an INF- register row →
events point at §9 → every state the row lists has a cell in `state-matrix.md`.
Limitation, recorded honestly: the first hop (EL → feature F- id) cannot close
until the features doc exists — the inventory's `feature_id` column carries
`UNRESOLVED(features.md)` and `open-questions.md` Q2 defines the mechanical
remap. Every component's failure state is specified (G4) — including the ones
that are deliberately `n/a (reason)`.
