# Accessibility, performance, and SEO

The quality floor for every screen. These are not separate audits: they are
part of the component and the screen spec. A change that breaks one of these is
not done.

External anchors (checked 2026-11-14): WCAG 2.2 Recommendation (12 Dec 2024),
MDN cookies/CSP, web.dev Core Web Vitals (updated 31 Oct 2024), schema.org
LearningResource. Repo anchors: `docs/frontend/design-doctrine.md` §10.8,
`docs/specs/frontend/perf-budget-tests.md`, `seo-plan.md`, `ws-client-contract.md`,
`docs/backend/backend-spec.md` NFR-06/07/08, `testing/frontend/test_perf_budget.py`.

## 1. Accessibility target: WCAG 2.2 AA

Target AA for every student-facing surface. The product rules below are
stricter than the minimum where children, mobile, or low-end hardware demand
it.

| Area | Rule | WCAG anchor |
|---|---|---|
| Contrast | Body text ≥ 4.5:1; large text ≥ 3:1; UI/graphical boundaries ≥ 3:1. The doctrine's palette is already validated; new colours are a doctrine change. | 1.4.3, 1.4.11 |
| Resize/reflow | Readable at 200% text zoom and 320 CSS px without two-dimensional scrolling (except a diagram/test paper that genuinely needs it). | 1.4.4, 1.4.10 |
| Text spacing | No loss when line height 1.5×, paragraph 2×, letter 0.12×, word 0.16×. | 1.4.12 |
| Keyboard | Every action works with a keyboard; no trap; focus order follows reading order. | 2.1.1, 2.1.2, 2.4.3 |
| Focus visible | 3 px pen-blue ring, 3 px offset; never `outline: none` without a replacement. | 2.4.7 |
| Focus not obscured | A sticky bar, drawer, or sheet must not cover the focused control. | 2.4.11 |
| Target size | Product rule: 44 × 44 px minimum for touch. WCAG 2.2 minimum is 24 × 24; the product is stricter. | 2.5.8 (and product rule) |
| Dragging | Any drag interaction has a non-drag path (arrow keys or ± buttons). | 2.5.7 |
| Timing | A timed test warns before expiry and auto-submits with a message; no silent loss. | 2.2.1 |
| Animation | `prefers-reduced-motion` removes non-essential motion; no autoplay. | 2.3.3, 1.4.2, 2.2.2 |
| Forms | Labels, instructions, errors tied to fields, suggestions for fixes, no redundant entry. | 3.3.1–3.3.3, 3.3.7 |
| Auth | No cognitive-function test; paste and password managers work; no hidden OTP. | 3.3.8 |
| Name/role/value | Native elements first; custom widgets expose role, name, state. | 4.1.2 |
| Status messages | `aria-live` for feedback; not for every streaming token. | 4.1.3 |
| Language | `lang` on the page and on mixed-script spans. | 3.1.1, 3.1.2 |
| Hover/focus content | Tooltips dismissible, hoverable, persistent. | 1.4.13 |

### Keyboard and focus

- Skip link first; landmarks (`header`, `nav`, `main`, `footer`) and one `<h1>`.
- Tab order follows DOM order; do not use positive `tabindex`.
- Radio groups: arrow keys move selection, one tab stop. Tabs: arrow keys move,
  Home/End jump. Menus: Esc closes, arrow keys move.
- Modal dialog: focus moves in, is contained, returns to the trigger; Esc
  closes unless a destructive action is mid-flight.
- The lesson's sticky language bar must not cover the focused control at
  360 px; test it.
- Space is a page shortcut only when the focus is not in a control. The dock's
  hold-to-talk must not hijack Space while a button, input, or link is focused.
- Focus is always visible, including on the paper background and on a selected
  chip (fill + ring must both remain legible).

### Screen-reader rules

- Canvas simulations have a text mirror (`.zn-sim-read`, `aria-live="polite"`)
  carrying the readable state; the kit updates it on control change or error,
  never on every animation frame, so it cannot flood the live region. A broken
  sim announces its error.
- Diagrams carry an `aria-label` listing their labels; complex diagrams may add
  a long description.
- Decorative SVG is `aria-hidden="true"`; meaningful SVG has a title/label.
- The dock is a labelled `region`; the mic has `aria-pressed`; the transcript
  is `aria-live="polite"` but throttled; every state has words, not just a
  shape.
- Audio has a transcript or a text alternative; a play control has a name.
- Tables have captions and scoped headers; the palette has an accessible name
  per cell.

### Colour and meaning

- Never colour-only: pair with a word, check/cross, shape, or pattern.
- Red = honesty/correction; green = done; blue = the one annotation/live value.
  Do not reuse them decoratively.
- In sunlight and on a low-quality screen, shape and words survive; hue may not.

## 2. Performance

### The two budget eras

The enforced gate today is the founder-loosened weak-Android profile; the
Phase-4 target is the brief's. Both are binding at different times. Thresholds
live in `testing/content_factory/perf/profiles/*.json`, never in test code.

| Metric | Enforced now | Era-2 target |
|---|---|---|
| Page load (weak-Android) | ≤ 6.0 s | < 2.0 s |
| FCP | ≤ 3.5 s | ≤ 1.2 s |
| fps under 4× CPU throttle | ≥ 24 (≈ 60 fps on device) | ≥ 24 |
| Browser-process RAM | ≤ 750 MB | ≤ 750 MB |
| Viewport / throttle | 360×640 @ dsf 2, 4× CPU, 2 pinned cores | same |
| LCP (p75 mobile) | ride the budget | ≤ 2.5 s |
| INP (p75) | long-task proxy ≤ 200 ms | ≤ 200 ms |
| CLS | ≤ 0.1 | ≤ 0.1 |

### Byte budgets

- Lesson page JS: ≤ 60 KB gzip (kit + page).
- App page JS islands: ≤ 120 KB gzip per page; no framework runtime.
- Shell fonts: ≤ 300 KB total after the woff2 migration; preload only the two
  above-the-fold faces; keep TTF fallbacks and the font licence file truthful.
- CSS: keep the shared kit small; page CSS is lens-scoped.
- No external CDN, no third-party font, no analytics bundle.

### Rules that keep the budget

- Server-render the HTML; do not ship a client-side data fetch for first paint.
- One `defer` script per island; mount only if its root exists.
- Use `transform`/`opacity` for animation; never animate layout properties.
- The simulation draws one static frame under reduced motion; no rAF loop.
- Lazy-load audio (`preload="none"`), images below the fold, and non-critical
  islands. Never lazy-load the LCP element.
- Avoid layout thrash in the test palette and timer; batch reads/writes.
- Test with the harness, not a fast laptop: `python -m testing.content_factory.perf.harness`
  with the `weak-android` profile, and the `testing/frontend/test_perf_budget.py`
  suite.
- Do not raise a threshold to make a red build green. Fix the cause; a budget
  change is a founder decision with evidence.

## 3. SEO and discoverability

### Indexable surfaces

Landing, catalogue, class pages, public lesson pages, method, about, pricing,
trust pages. Generated lesson pages are the SEO product: one canonical URL per
topic, stable path, real HTML.

### Per-page metadata

- Unique `<title>` and meta description; one `<h1>`; canonical self-reference.
- Open Graph/Twitter only on pages meant to be shared; one local OG image,
  Field Notes artwork, never a child's image.
- `ZIVON_PUBLIC_BASE_URL` is the only source of absolute URLs; no hard-coded
  domain.
- `sitemap.xml` + `robots.txt` are generated at publish time from the published
  catalogue; `robots.txt` disallows `/healthz` and points at the sitemap.
- `noindex` (meta + `X-Robots-Tag` where server-controlled) on `/app/*`,
  `/auth/*`, `/login`, `/signup`, `/onboarding`, `/admin/*`, search results, and
  any personalized page.
- No JavaScript redirect for language or canonicalization. A localized page is
  a real file at a real URL.

### Structured data

- Site: `Organization`.
- Lesson: `LearningResource` with `name`, `inLanguage`, `educationalLevel`,
  `about`, `learningResourceType`, `isBasedOn` (source titles + licences),
  `dateModified` from the manifest, `provider`, `url`.
- Course/FAQ only when the content actually matches the type; do not mark up a
  marketing claim as a FAQ.
- Validate with the Rich Results Test; structured data must match visible
  content.
- No tracking pixel, no third-party SEO script, no Search Console JS. Use a DNS
  TXT record or a static verification file.

### hreflang and locale

- Hreflang is gated on the locale model decision. Do not emit a half-built
  cluster. When it lands: one `hreflang` per locale plus `x-default` → English
  canonical, and self-canonical on each variant.
- Locale codes must match the decided model (`en`, `hi`, `hi-Latn` in the
  current product subset). A wrong code is worse than no hreflang.
- Do not duplicate content across locales; translate or mark the fallback
  visibly.

### Claims and honesty

- CBSE-style copy: “close to the paper pattern”, “built for practice”, “not an
  official CBSE paper”. Never “official”, “exact CBSE”, or an affiliation
  claim for generated items.
- Exact PYQs carry source attribution.
- Titles/descriptions describe reviewed content; `dateModified` comes from the
  pipeline, not a hand edit.
- No clickbait on a children's product.

## 4. Privacy and security in the frontend

- No trackers, third-party analytics, ad pixels, session replay, or social
  embeds. The CSP and the child-privacy rule forbid them.
- Telemetry is pseudonymous and contains no free text, transcript, email, or
  name. Batch ≤ 20 events / ≤ 5 s, queue ≤ 200, drop-oldest.
- Consent gates the mic and voice telemetry. Pre-consent only the allowed
  Core-safe events go out.
- No raw audio retained. Speaking transcripts are text, saved only with the
  attempt, and deletable.
- Session cookies are `HttpOnly`, `Secure`, `SameSite=Lax`; CSRF on state
  changes; no token in local storage.
- Delete and export are real: a failed wipe says it failed and deletes nothing
  local; a successful wipe removes local keys after the server ack.
- Every page: CSP, `nosniff`, `no-referrer`. No inline script/eval, no external
  host.

## 5. Acceptance evidence for the PR

- [ ] axe (or the repo's equivalent) reports zero serious/critical on each
      changed public/app screen.
- [ ] Keyboard-only walkthrough of the changed flow, including the modal and
      the focus return.
- [ ] 360 px, 768 px, 1280 px screenshots; no horizontal overflow.
- [ ] Reduced-motion pass: no autoplay, sim draws once, caption instant.
- [ ] Offline pass: static content readable; network actions disabled with a
      reason.
- [ ] Perf harness result on `weak-android` within the profile; JS/font bytes
      within budget.
- [ ] Metadata check: title, description, canonical, OG, JSON-LD, robots.
- [ ] No external URL, no inline script, no secret in the diff.
- [ ] i18n check: no silent English on a localized page; missing variant is
      marked.
