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

| Screen id (canonical / alias) | Route | Files |
|---|---|---|
| `SCR-HUB-01` (alias `SCR-HOME-01`) — course catalogue / hub | `/` (`frontend/index.html`) | shell only |
| `SCR-LES-01` — lesson page | `/courses/<course_id>/<topic_slug>/` (`index.html`) | generated page + kit + shell injection (`shell-injection.md`) |
| `SCR-PRIV-01` — privacy summary & data wipe | `/privacy/` (`frontend/privacy/` or shell-injected view) | shell + `GET /v1/data/challenge` -> `DELETE /v1/data` |
| `SCR-ADM-01` — admin dashboard v0 | `:8082` (`dashboard/`) | staff-only container (EX3-OBS, out of student shell scope) |
| `SCR-404-01` — branded not found | `/404.html` (any unmatched URL) | shell (`frontend/404.html`) |

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
2. **Document hook already present**: every page carries `<html lang="…">`.
   The v1 chips switch the SELECTED state only (`zivon.js::wireLangChips` sets
   `aria-checked`; verified against the shell — it does not yet switch
   `documentElement.lang`; the doctrine example demonstrates the fuller stub).
   Switching the document lang arrives with i18n-aware generation (C3 spec
   only adds persistence + preselect). A localized
   route is the same page with `lang` and content swapped at publish time — no
   runtime router, ever (G1).
3. **Generation hook**: localized trees can only be produced by i18n-aware
   content generation (factory side) and mirrored by the publish flow; the
   frontend never translates at runtime. This is a factory-side publish work item,
   not a frontend one — tracked in `open-questions.md` Q7.
4. **SEO hook**: hreflang pairs + per-locale sitemap entries are specified in
   `seo-plan.md` §3 but marked do-not-build until ADR-0009 lands.

---

## 4. Screen & region list (canonical — reconciled per `open-questions.md` §R)

Regions follow `docs/product/features.md` §4 and `ui-element-inventory.csv` (97 canonical `EL-` rows, plus retained provisional shell aliases for backward compatibility).

| Screen | Region | Canonical `EL-` ids (provisional aliases in parentheses) |
|---|---|---|
| `SCR-HUB-01` (`SCR-HOME-01`) | `.R1` header | `EL-HUB-001`, `EL-HUB-002`, `EL-HUB-003` (`EL-HOME-01-001`, `EL-HOME-01-002`, `EL-HOME-01-003`, `EL-HOME-01-004`) |
| `SCR-HUB-01` (`SCR-HOME-01`) | `.R2` class-grouped catalogue | `EL-HUB-004`, `EL-HUB-005`, `EL-HUB-006` (`EL-HOME-01-005`, `EL-HOME-01-006`, `EL-HOME-01-007`) |
| `SCR-HUB-01` (`SCR-HOME-01`) | `.R3` footer | `EL-HUB-007` (`EL-HOME-01-008`) |
| `SCR-HUB-01` (`SCR-HOME-01`) | `global` status | `EL-HUB-008` |
| `SCR-LES-01` | `.R1` lesson header | `EL-LES-01-001`, `EL-LES-01-002`, `EL-LES-01-003`, `EL-LES-01-004`, `EL-LES-01-005` (`EL-LES-01-081` pen underline) |
| `SCR-LES-01` | `.R2` language bar | `EL-LES-01-006`, `EL-LES-01-007`, `EL-LES-01-008`, `EL-LES-01-009` (`EL-LES-01-001..004` provisional bar/chips) |
| `SCR-LES-01` | `.R3` text blocks + read-aloud + anchor | `EL-LES-01-010`, `EL-LES-01-011`, `EL-LES-01-012`, `EL-LES-01-013` (`EL-LES-01-080` ruled lines) |
| `SCR-LES-01` | `.R4` diagrams | `EL-LES-01-014`, `EL-LES-01-015`, `EL-LES-01-016`, `EL-LES-01-017` (`EL-LES-01-050`) |
| `SCR-LES-01` | `.R5` interactive simulations | `EL-LES-01-018`, `EL-LES-01-019`, `EL-LES-01-020`, `EL-LES-01-021`, `EL-LES-01-022`, `EL-LES-01-023`, `EL-LES-01-024` (`EL-LES-01-060`, `EL-LES-01-061`) |
| `SCR-LES-01` | `.R6` comprehension checks | `EL-LES-01-025`, `EL-LES-01-026`, `EL-LES-01-027`, `EL-LES-01-028`, `EL-LES-01-029`, `EL-LES-01-030`, `EL-LES-01-031` (`EL-LES-01-030..033`) |
| `SCR-LES-01` | `.R7` worked examples, reveals, glossary | `EL-LES-01-032`, `EL-LES-01-033`, `EL-LES-01-034`, `EL-LES-01-035`, `EL-LES-01-036` (`EL-LES-01-020`, `EL-LES-01-040`) |
| `SCR-LES-01` | `.R8` sources footer & problem report | `EL-LES-01-037`, `EL-LES-01-038`, `EL-LES-01-039`, `EL-LES-01-040`, `EL-LES-01-041` (`EL-LES-01-070` provisional sources) |
| `SCR-LES-01` | `.R9` voice dock (bottom sheet, §10.12) | `EL-LES-01-042` (`EL-LES-01-090` region), `EL-LES-01-043`, `EL-LES-01-044`, `EL-LES-01-045`, `EL-LES-01-046`, `EL-LES-01-047`, `EL-LES-01-048`, `EL-LES-01-049`, `EL-LES-01-050`, `EL-LES-01-051`, `EL-LES-01-052`, `EL-LES-01-053`, `EL-LES-01-054`, `EL-LES-01-055`, `EL-LES-01-056` |
| `SCR-LES-01` | `.R10` consent gate overlay (§10.14) | `EL-LES-01-057`, `EL-LES-01-058`, `EL-LES-01-059`, `EL-LES-01-060`, `EL-LES-01-061` |
| `SCR-LES-01` | `.R11` student settings sheet (P1 deferred) | `EL-LES-01-062`, `EL-LES-01-063`, `EL-LES-01-064`, `EL-LES-01-065`, `EL-LES-01-066`, `EL-LES-01-067` |
| `SCR-LES-01` | `.R12` first-use onboarding hints (P1 deferred) | `EL-LES-01-068`, `EL-LES-01-069` |
| `SCR-LES-01` | `global` degraded & credit notices | `EL-LES-01-070`, `EL-LES-01-071`, `EL-LES-01-072` |
| `SCR-PRIV-01` | `.R1..R3` privacy summary & clear data | `EL-PRV-001`, `EL-PRV-002`, `EL-PRV-003`, `EL-PRV-004`, `EL-PRV-005` |
| `SCR-ADM-01` | `.R0..R5` admin dashboard v0 (`dashboard/`) | `EL-ADM-001..012` (`EL-ADM-001`, `EL-ADM-002`, `EL-ADM-003`, `EL-ADM-004`, `EL-ADM-005`, `EL-ADM-006`, `EL-ADM-007`, `EL-ADM-008`, `EL-ADM-009`, `EL-ADM-010`, `EL-ADM-011`, `EL-ADM-012`) |
| `SCR-404-01` | `.R1..R2` branded 404 | `EL-404-01-001`, `EL-404-01-002`, `EL-404-01-003` |

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

## 7. Voice dock integration (seam + §10.12 design)

**Status 2026-11-10: DCR-002 closed.** `design-doctrine.md` now contains §10.12
(voice dock, bottom-sheet), §10.13 (read-aloud) and §10.14 (consent gate); the
dock's visual design is no longer founder-gated. This section specifies the
implementation seam; §10.12 is the visual authority. For history, the original
guard read: `design-doctrine.md` v1.6 contained no §10.12. The seam:

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
- **Behavior (v1, honest stub)**: chips switch the selected state only
  (`wireLangChips` sets `aria-checked`; the shell does not switch
  `documentElement.lang` today — that lands with i18n-aware content
  generation, doctrine v1.6 §10.5 ruling; factory work item, Q7). C3 adds
  persistence + preselect, nothing more. The UI must not pretend: no chip
  implies translated content that does not exist.
- **Persistence (device pseudonym per the brief's ADR-0007 — ABSENT, flag Q3)**:
  until that ADR exists, the only sanctioned persistence is local-only:
  `localStorage["zivon_locale"] = <locale>` written on explicit chip activation
  (single owner key, reconciled with the translation spec in open-questions
  Q11; `zivon.lang` is read-only legacy), read on load to preselect a chip; no
  server write, no identifier, cleared by
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
| C3 | Locale persistence `localStorage["zivon_locale"]` (`zivon.lang` read-only legacy) + chip preselect | `frontend/assets/zivon.js` (`wireLangChips`) | §8 |
| C4 | Font payload reduction: subset + convert the four TTFs to woff2 (keep TTF fallbacks), `preload` the two above-the-fold faces (Bricolage variable, Courier Prime regular) | `frontend/assets/fonts/`, `zivon.css` | §11; ~940 KB → est. <300 KB, the only realistic path inside the <2 s re-tighten on 3G-class networks. Keep `FONTS-LICENSE.md` accurate; re-run the perf gate before/after |
| C5 | Reserved voice-dock mount region + lazy loader stub (loads NOTHING until the founder's dock lands) | `zivon.js` boot + `spec.md` §7 | §7 seam |

Not in this list (explicitly): any CI workflow edit (integration_notes for the
merge agent: `perf-budget-tests.md` §6 describes the `tests`-job extension and
the Lighthouse-CI job the CI/CD agent must add); any factory renderer change
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

## 14. Traceability: canonical registers (reconciled per `open-questions.md` §R)

### 14.1 Information items (INF-, canonical — reconciled against `docs/product/information-inventory.csv`)

| id | Name | Source (canonical / real field) | Shown in | Nullability & fallback | Localization |
|---|---|---|---|---|---|
| `INF-001` | `hub_kicker` | shell static | EL-HUB-001 | required | translate chrome |
| `INF-002` | `hub_title` | shell static | EL-HUB-002 EL-HUB-005 | required | translate chrome |
| `INF-003` | `hub_sub` | shell static | EL-HUB-003 | required | translate chrome |
| `INF-004` | `class_group_heading` | derived from courses.js class field | EL-HUB-004 | absent when <2 classes -> no headings | heading word translate |
| `INF-005` | `card_title` | ENT?-PageMeta.title | EL-HUB-005 | required | translate when bundle exists; else English |
| `INF-006` | `card_meta` | ENT?-PageMeta | EL-HUB-005 | required | labels translate; numerals per locale |
| `INF-007` | `hub_empty_copy` | shell static | EL-HUB-006 | shown only when catalogue empty | translate chrome |
| `INF-008` | `hub_attribution` | shell static | EL-HUB-007 | required | translate chrome; model names untranslated |
| `INF-009` | `lesson_kicker` | ENT?-PageMeta.course_id | EL-LES-01-001 | required | id string never translated |
| `INF-010` | `lesson_title` | ENT?-PageMeta.title | EL-LES-01-002 | required | translate; else English |
| `INF-011` | `lesson_meta` | ENT?-PageMeta | EL-LES-01-003 | required | labels translate; numerals per locale |
| `INF-012` | `objectives_label` | shell static | EL-LES-01-004 | shown only when objectives exist | translate chrome |
| `INF-013` | `objective_items` | factory block spec (objectives) | EL-LES-01-005 | optional block -> section absent | translate; exam-standard terms kept + gloss |
| `INF-014` | `lang_bar_label` | shell static | EL-LES-01-006 | required on lesson pages | translate chrome |
| `INF-015` | `chip_en` | shell static | EL-LES-01-007 | required | autonym fixed - never translated |
| `INF-016` | `chip_hi` | shell static | EL-LES-01-008 | required; disabled until bundle exists | autonym fixed |
| `INF-017` | `chip_hinglish` | shell static | EL-LES-01-009 | required | autonym fixed (house style) |
| `INF-018` | `paragraph_text` | factory block spec (text) | EL-LES-01-010 | required per block | translate per block; untranslated -> English + INF-087 marker |
| `INF-019` | `highlighted_statement` | factory block spec (highlighted_statement) | EL-LES-01-011 | required one per page (doctrine) | translate; pen underline unchanged |
| `INF-020` | `read_aloud_label` | shell static | EL-LES-01-012 | required | translate chrome |
| `INF-021` | `ask_about_this_label` | shell static | EL-LES-01-013 | hidden when voice unavailable | translate chrome |
| `INF-022` | `diagram_svg` | factory block spec (diagram SVG) | EL-LES-01-014 | required | labels via INF-024; geometry unchanged |
| `INF-023` | `diagram_caption` | factory block spec | EL-LES-01-015 | required | translate |
| `INF-024` | `diagram_labels` | factory block spec | EL-LES-01-016 | required | translate (SC-01); symbols fixed |
| `INF-025` | `diagram_aria_label` | derived from INF-022 | EL-LES-01-014 | required (a11y gate) | build from translated labels |
| `INF-026` | `diagram_longdesc` | factory block spec (P1) | EL-LES-01-017 | optional -> details absent | translate |
| `INF-027` | `sim_title` | factory block spec (simulation) | EL-LES-01-019 | required | translate |
| `INF-028` | `sim_description` | factory block spec | EL-LES-01-019 | required | translate |
| `INF-029` | `control_label` | factory block spec (controls) | EL-LES-01-020 | required per control | translate (SC-02); keep exam term in glossary |
| `INF-030` | `control_value` | computed from simulation state | EL-LES-01-020 | required; numerals per locale | show raw value while loading |
| `INF-031` | `unit_symbols` | factory block spec (unit field SC-02) | EL-LES-01-020 | required per control | NEVER translated (INF rule) |
| `INF-032` | `sim_state_mirror` | factory template (SC-02 state_text_template) + live values | EL-LES-01-022 | required (a11y + tutor reading) | translate template |
| `INF-033` | `default_behaviour` | factory block spec | EL-LES-01-021 | required | translate (for mirror) |
| `INF-034` | `reset_label` | shell static | EL-LES-01-023 | required when reset exists | translate chrome |
| `INF-035` | `sim_error_text` | shell static | EL-LES-01-024 | shown only on sim failure | translate chrome |
| `INF-036` | `check_question` | factory block spec (check) | EL-LES-01-025 | required | translate (answer key language-independent) |
| `INF-037` | `check_option_text` | factory block spec | EL-LES-01-026 | required per option | translate |
| `INF-038` | `check_button_label` | shell static | EL-LES-01-028 | required | translate chrome |
| `INF-039` | `check_feedback` | factory block spec (feedback) | EL-LES-01-029 | required; generic sentence if missing | translate |
| `INF-040` | `option_feedback` | factory block spec (SC-03 P1) | EL-LES-01-030 | optional -> INF-039 used | translate |
| `INF-041` | `check_explanation` | factory block spec (explanation) | EL-LES-01-031 | required | translate |
| `INF-042` | `numeric_hint` | shell static | EL-LES-01-027 | required for numeric checks | translate chrome; number format per locale |
| `INF-043` | `we_problem` | factory block spec (worked_example) | EL-LES-01-032 | required | translate prose; numbers verbatim |
| `INF-044` | `we_step` | factory block spec | EL-LES-01-033 | required per step | translate |
| `INF-045` | `we_answer` | factory block spec | EL-LES-01-034 | required | translate prose; value+unit fixed |
| `INF-046` | `reveal_content` | factory block spec (reveal) | EL-LES-01-035 | required | translate |
| `INF-047` | `glossary_term` | factory block spec (glossary) | EL-LES-01-036 | required per pair | term NOT translated (exam standard) |
| `INF-048` | `glossary_definition` | factory block spec | EL-LES-01-036 | required per pair | translate |
| `INF-049` | `term_gloss` | factory translation pass (SC-01) | EL-LES-01-036 | optional -> term shown bare + flagged for review | exists only for translated pages |
| `INF-050` | `sources_lead` | shell static | EL-LES-01-037 | required | translate chrome |
| `INF-051` | `source_entries` | ENT?-PageMeta.sources (manifest) | EL-LES-01-038 | required >=1 (fact gate) | name+license NOT translated |
| `INF-052` | `generated_at` | ENT?-PageMeta.generated_at | EL-LES-01-039 | required | numerals per locale |
| `INF-053` | `report_label` | shell static | EL-LES-01-040 | required | translate chrome |
| `INF-054` | `report_categories` | shell static | EL-LES-01-041 | required fixed set | translate labels; codes fixed |
| `INF-055` | `report_confirmation` | shell static | EL-LES-01-041 | required | translate chrome |
| `INF-056` | `mic_label` | shell static | EL-LES-01-043 | required | translate chrome |
| `INF-057` | `dock_state_labels` | shell static | EL-LES-01-044 | required per state (no state without copy) | translate chrome; every language gets every state's copy |
| `INF-058` | `earcon_sounds` | shell static audio assets | EL-LES-01-045 | required (paired to states) | n/a - non-linguistic |
| `INF-059` | `stop_label` | shell static | EL-LES-01-046 | required while speaking | translate chrome |
| `INF-060` | `final_transcript` | Prisma STT via NEED-006 | EL-LES-01-047 | low-confidence -> no-match state instead of showing garbled text | shown as heard (no cleanup) |
| `INF-061` | `tutor_reply` | Evon via NEED-007 | EL-LES-01-047 | required per turn | in student's language mix (mirroring) |
| `INF-062` | `partial_transcript` | Prisma partials via NEED-006 | EL-LES-01-048 | off by default (opt-in) | shown as heard |
| `INF-063` | `caption_toggle_label` | shell static | EL-LES-01-049 | required | translate chrome |
| `INF-064` | `anchor_chip_text` | derived from page context (NEED-005) | EL-LES-01-050 EL-LES-01-056 | whole-page fallback when nothing focused | template translate; block title per page language |
| `INF-065` | `identity_line` | shell static | EL-LES-01-051 | shown once per device | translate chrome |
| `INF-066` | `typed_fallback_copy` | shell static | EL-LES-01-052 | required | translate chrome |
| `INF-067` | `help_phrases` | shell static (curated per topic family) | EL-LES-01-053 | required per failure type | phrases in the student's language; physics terms kept |
| `INF-068` | `failure_copy` | shell static | EL-LES-01-044 EL-LES-01-052 | required - every state has exits + copy | translate chrome; same tone all languages |
| `INF-069` | `memory_list` | ENT?-Session.coverage (NEED-011) | EL-LES-01-054 | empty -> ""Nothing yet - this is a fresh session\" | Titles per page language |
| `INF-070` | `memory_clear_copy` | shell static | EL-LES-01-054 | required | translate chrome |
| `INF-071` | `settings_label` | shell static | EL-LES-01-055 EL-LES-01-062 | required | translate chrome |
| `INF-072` | `consent_notice` | shell static (legal-reviewed copy) | EL-LES-01-058 | required before first voice | P0 English; P1 all 3 languages |
| `INF-073` | `guardian_checkbox_label` | shell static | EL-LES-01-059 | required | translate chrome |
| `INF-074` | `consent_continue_label` | shell static | EL-LES-01-060 | required | translate chrome |
| `INF-075` | `consent_decline_label` | shell static | EL-LES-01-061 | required | translate chrome |
| `INF-076` | `consent_version_stamp` | ENT?-ConsentRecord | EL-PRV-002 | absent -> show ""no consent record on this device\" | numerals per locale |
| `INF-077` | `lang_setting_label` | shell static | EL-LES-01-063 | required | translate chrome |
| `INF-078` | `pace_options` | shell static | EL-LES-01-064 | required | label translate; numerals fixed |
| `INF-079` | `guide_tell_labels` | shell static | EL-LES-01-065 | required | translate chrome |
| `INF-080` | `data_saver_label` | shell static | EL-LES-01-066 | required | translate chrome |
| `INF-081` | `memory_row_label` | shell static | EL-LES-01-067 | required | translate chrome |
| `INF-082` | `mic_hint` | shell static | EL-LES-01-068 | shown once per device | translate chrome |
| `INF-083` | `wiggle_hint` | shell static | EL-LES-01-069 | shown once per device | translate chrome |
| `INF-084` | `offline_copy` | shell static | EL-LES-01-070 EL-HUB-008 | required | translate chrome |
| `INF-085` | `voice_warn_copy` | shell static | EL-LES-01-071 | shown on guard warn state | translate chrome |
| `INF-086` | `typed_only_copy` | shell static | EL-LES-01-072 | shown on guard exhausted state | translate chrome |
| `INF-087` | `untranslated_marker` | shell static | EL-LES-01-010 (state) | shown per untranslated block | translate chrome |
| `INF-088` | `mt_flag_copy` | ENT?-LanguageBundle.mt_flag | EL-LES-01-007..009 (state) | shown once per page+language when mt_flag true | translate chrome |
| `INF-089` | `read_aloud_unavailable` | shell static | EL-LES-01-012 (state) | required | translate chrome |
| `INF-090` | `privacy_title` | shell static | EL-PRV-001 | required | translate chrome |
| `INF-091` | `data_class_rows` | shell static (mirrors handoff §4 privacy classes) | EL-PRV-002 | required | translate; retention values per locale |
| `INF-092` | `retention_values` | derived from retention policy | EL-PRV-002 | required per row; numerals per locale | numerals per locale |
| `INF-093` | `clear_label` | shell static | EL-PRV-003 | required | translate chrome |
| `INF-094` | `clear_confirmation` | shell static | EL-PRV-004 | required | translate chrome |
| `INF-095` | `admin_sessions_count` | NEED-015 aggregate | EL-ADM-001 | zero -> empty state copy | staff UI English only |
| `INF-096` | `admin_session_rows` | NEED-015 from ENT?-Session | EL-ADM-002 | empty state | n/a |
| `INF-097` | `credit_burn_figures` | NEED-009 ledger | EL-ADM-003 | zero -> 0 shown | n/a |
| `INF-098` | `guard_state_value` | NEED-009 | EL-ADM-004 | required | n/a |
| `INF-099` | `engagement_metrics` | NEED-015 from ENT?-TelemetryEvent | EL-ADM-005 | empty state | n/a |
| `INF-100` | `run_status_rows` | ENT?-RunStatus (runs/ evidence) | EL-ADM-006 | empty -> ""no runs yet\" | n/a |
| `INF-101` | `stage_durations` | run_report.json evidence | EL-ADM-006 | absent for in-progress run -> live marker | n/a |
| `INF-102` | `trigger_labels` | shell static (staff) | EL-ADM-007..009 | required | n/a |
| `INF-103` | `run_log_stream` | kubectl logs by label (NEED-015) | EL-ADM-009 | empty -> waiting copy | n/a |
| `INF-104` | `report_rows` | ENT?-ProblemReport | EL-ADM-010 | empty state | n/a |
| `INF-105` | `report_status_options` | shell static (staff) | EL-ADM-011 | required | n/a |

### 14.2 Backend needs (NEED-001…018, canonical — reconciled against `docs/product/backend-handoff.md`)

| id | Capability sentence | Caller | Status |
|---|---|---|---|
| `NEED-001` | Static delivery of shell + generated pages (nginx image + `zivon-frontend` PVC) | browser | SATISFIED by publish flow |
| `NEED-002` | Course catalogue (`frontend/courses.js`, generated) | browser (hub) | SATISFIED by stage 11-link |
| `NEED-003` | Session bootstrap + feature flags (`POST /v1/session`) | browser (lesson page) | SATISFIED (`backend/routes/student.py`) |
| `NEED-004` | Voice conversation channel (`WSS /voice/ws`) | browser voice dock | SATISFIED (`voice/` + `ZivonVoiceClient`) |
| `NEED-005` | Page-context payload composition (`context.snapshot` <= 4 KB) | browser -> voice backend | SATISFIED (`buildContextSnapshot`) |
| `NEED-006` | Prisma v3.0 streaming STT | voice backend | SATISFIED (`voice/stt_client.py`) |
| `NEED-007` | Tutor turn generation (Gemma 4 26B A4B via Gemini API) | voice backend | SATISFIED (`voice/brain_client.py`) |
| `NEED-008` | Timbre v3.0 streaming TTS (PCM16 48 kHz downlink) | voice backend | SATISFIED (`voice/tts_client.py`) |
| `NEED-009` | Credit metering + budget guard (`ok` / `warn` / `exhausted` / `reserved_mode`) | voice backend + dock notices | SATISFIED (`guard/` + `EL-LES-01-071/072`) |
| `NEED-010` | Telemetry ingestion (`POST /api/v1/events` & `POST /v1/events`) | `ZivonEvents` batched flush | SATISFIED (`backend/routes/student.py` + `ZivonEvents.flush`) |
| `NEED-011` | Session coverage store (`PUT /v1/session/{id}/coverage`) | browser at turn boundaries | SATISFIED (`backend/routes/student.py` + dock memory view) |
| `NEED-012` | Consent record store (`PUT /v1/consent`) | consent gate overlay | SATISFIED (`backend/routes/student.py` + `ZivonConsent`) |
| `NEED-013` | Data deletion endpoint (`GET /v1/data/challenge` -> `DELETE /v1/data`) | privacy page (`/privacy/`) | SATISFIED (`backend/routes/student.py` + `ZivonPrivacy`) |
| `NEED-014` | Problem-report submission (`POST /v1/reports`) | lesson report form (`EL-LES-01-040/041`) | SATISFIED (`backend/routes/student.py` + `ZivonReport`) |
| `NEED-015` | Admin data + trigger API | admin dashboard (`dashboard/`) | SATISFIED (EX3-OBS) |
| `NEED-016` | Language bundle delivery (`i18n.js` / `window.ZIVON_I18N`) | lesson language bar (`EL-LES-01-006..009`) | SATISFIED (stage 10d-transrender + `ZivonLocale`) |
| `NEED-017` | Block read-aloud narration (`/audio/{course_id}/{block_id}.{lang}.{hash}.opus`) | read-aloud control (`EL-LES-01-012`) | SATISFIED (stage 12-narration + `ZivonReadAloud`) |
| `NEED-018` | Student settings persistence (`localStorage` device-local) | dock/page controls | SATISFIED (client-local primary) |

### 14.3 Event register (canonical EVT-001…018 + SP3 EVT-F01…F12 + SP5 triggers)

Canonical product events (`EVT-001`..`EVT-018` in `docs/product/backend-handoff.md` §4) and SP3 observability events (`EVT-F01`..`EVT-F12` in `docs/specs/observability/instrumentation-map.csv`) map to the client triggers in §9 (`EVT-lesson_viewed`, `EVT-lesson_opened`, `EVT-section_viewed`, `EVT-reveal_opened`, `EVT-sim_opened`, `EVT-sim_control_changed`, `EVT-check_answered`, `EVT-check_retried`, `EVT-mic_pressed`, `EVT-tutor_turn_completed`, `EVT-sim_error`, `EVT-client_error`, `EVT-lang_switched`, `EVT-session_ended`, `EVT-publish_viewed`, `EVT-heartbeat`, `EVT-read_aloud_played`, `EVT-consent_recorded`, `EVT-report_submitted`, `EVT-data_cleared`).

### 14.4 Walk-through test (reconciled)

Every perceivable element on `SCR-HUB-01`, `SCR-LES-01`, `SCR-PRIV-01`, `SCR-ADM-01`, and `SCR-404-01` traces from its canonical `EL-` id in `component-inventory.csv` to its feature card (`F-COR-*`, `F-WRP-*`, `F-ADD-*`, `F-XCT-*`, `F-OPS-*`) in `docs/product/features.md`, its `INF-` row in §14.1, its `NEED-` row in §14.2, and its state row in `state-matrix.md`.
