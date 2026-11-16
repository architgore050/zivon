# Public site (F1) — landing, catalogue, class and trust pages

Status: **implemented** (W2, 2026-11-16). Owner: F1 public-site/catalogue.
Visual authority: `docs/frontend/design-doctrine.md` §0–§9 (base Field Notes).
Approved direction: **Concept A, “The 8pm Doubt”**, from the F0B review bundle.
The lesson extension (§10: ruled grid, Caveat body, taped cards, language bar,
voice dock) is deliberately absent from every page in this folder.

## What ships

| Route | File | Surface | Notes |
|---|---|---|---|
| `/` | `frontend/index.html` | Landing | Concept A: sample Hinglish turn, mechanism, sources, check, coverage, privacy, founder note, FAQ. Static argument; JS only enhances. |
| `/courses` | `frontend/catalogue/index.html` | Catalogue | Class tabs (9–12), search over title/chapter/concept, chapter cards from the generated `courses.js`. Empty, partial and error states. |
| `/class-9-physics/` … `/class-12-physics/` | `frontend/class-<N>-physics/index.html` | Class/course page | Chapter list, status, languages, lesson links, practice/test availability. A class with no published chapter names that state. |
| `/method/` | `frontend/method/index.html` | Method | Source-first pipeline, step-by-step tutoring, simulations, retrieval checks, voice, and explicit limitations. |
| `/about/` | `frontend/about/index.html` | About | Why Physics, what is built, stack, challenge provenance, what is still missing. |
| `/pricing/` | `frontend/pricing/index.html` | Pricing | Free during launch. No paid plan, no payment integration, no waitlist form until accounts exist. |
| `/terms/` | `frontend/terms/index.html` | Terms | Plain-language prototype terms; formal policy before accounts/payments. |
| `/contact/` | `frontend/contact/index.html` | Contact | Public issue tracker is the monitored channel; no form endpoint is invented. |
| `/status/` | `frontend/status/index.html` | Status | Static “what works today” table; no uptime percentage or fake incident history. |
| `/privacy/` | `frontend/privacy/index.html` | Privacy | Reuses the existing `zivon.js` clear-data wiring; the table and copy carry the current no-accounts state. |
| `/404.html` | `frontend/404.html` | Not found | Keeps `EL-404-01-001…003` and the nginx `error_page` contract. |

Shared components live in `frontend/assets/product.css` and
`frontend/assets/product.js`. They are **public-site only**: the lesson shell
keeps `zivon.css` / `zivon.js`. The two files share the doctrine tokens and the
bundled fonts, not the lesson-component classes.

## Why the catalogue is not `frontend/courses/index.html`

`frontend/courses/` is factory-owned. `scripts/publish-frontend.sh` replaces it
wholesale on every publish, so a hand-maintained index inside that tree would be
deleted. The catalogue therefore lives at `frontend/catalogue/index.html` and
`docker/nginx.conf` serves it at the public URL:

```nginx
location = /courses { try_files /catalogue/index.html =404; }
```

The new page folders are baked into `Dockerfile.frontend` and seeded into the
served root. The cluster seed is deliberately no-clobber (`cp -rn`, gotcha 14 in
`docs/deployment/kubernetes.md`), so an existing `zivon-frontend` PVC needs the
recorded re-seed procedure to pick up a new landing/404/privacy (new folders
copy in on their own; changed files do not).

The requirements route `/courses/{class}/physics` redirects to the canonical
class page `/class-{class}-physics/`, which lives outside the factory tree for
the same reason. The class pages are the static equivalent of the documented
route; one canonical URL per class.

## Data contract

- `frontend/courses.js` is the generated site manifest (`window.ZIVON_COURSES`,
  do not hand-edit). The catalogue and class pages read it with a plain
  `<script src>`; no `fetch`, no XHR, no network call (CSP `connect-src 'none'`
  on every non-lesson page).
- Each entry is validated for `href`, `title` and a class in 9–12. A malformed
  entry is dropped and the page shows a partial warning naming the count; it is
  never rendered as a broken link.
- Counts, languages, chapter numbers, concepts and `generated_at` come from the
  entry. Nothing is invented; practice and chapter-test availability is shown as
  “not yet” because no such content exists today.
- The catalogue search can be deep-linked with `?q=` and `?class=`; filtering
  updates the URL with `history.replaceState` (no navigation, no storage).

## States (public site)

| State | Behaviour |
|---|---|
| default | Static argument renders; JS fills the catalogue/class lists and the landing coverage table. |
| loading | No spinner. The catalogue/class count and empty/error notices are hidden until the local manifest is read; the static copy is already readable. |
| empty | “No published chapter for Class N yet” on a class page; “no chapter matches” on a filtered catalogue; an empty `window.ZIVON_COURSES` array shows the same empty state. |
| partial | Some classes have chapters, others do not: a coverage line names the empty classes. A malformed manifest entry produces a partial warning. |
| error | `courses.js` missing or does not define the `window.ZIVON_COURSES` array: the catalogue and class page show an error notice and a link to the sitemap. The lesson pages remain readable. |
| offline | Static pages and already-cached lessons keep working. The catalogue reads its local manifest; there is no runtime fetch to fail. |
| permission-denied | n/a — public pages require no permission. |
| reduced-motion | No page animation; the only JS motion is the one-time pen underline. `prefers-reduced-motion` is still honoured by the shared layer. |
| untranslated | Public chrome is English today. Live lessons are fully translated; the public catalogue is not localized. A localized public route is gated on the locale model (ADR-0009). |
| quota-exhausted | n/a — the public site spends no voice credits. |
| consent-missing | n/a — public pages do not use the microphone. The privacy page explains the future consent gate. |

## SEO

- Every public page carries a title, description, canonical, viewport, one
  `<h1>`, a skip link and `id="main"`. Public pages are `index,follow`; the 404
  is `noindex,nofollow` and carries no canonical.
- The landing page carries OG/Twitter tags and `WebSite` JSON-LD. Class pages
  carry `Course` JSON-LD; the catalogue carries `CollectionPage`.
- `og:image`, `twitter:image` and `og:url` on the landing page use the existing
  `https://zivon.local` placeholder contract and are rewritten at publish time
  by `scripts/gen-seo-files.py` from `ZIVON_PUBLIC_BASE_URL`. No new page
  hard-codes a domain; canonical URLs are root-relative.
- hreflang is **not** emitted on public pages: the localized route tree is still
  the lesson/subtree form, and a half-built cluster is worse than none. The
  sitemap generator owns locale alternates for lesson pages.
- The catalogue and class lists are client-rendered from `courses.js`. Crawlers
  that execute JS see them; the sitemap remains the static discovery path for
  lessons. A static catalogue generator is a follow-up if the catalogue itself
  needs to rank.

## Honesty and compliance

- No testimonial, no fake logo, no “official CBSE/NCERT” claim. The sample voice
  turn is labelled as a sample, not a recording. The founder note is labelled as
  the founder's words.
- The voice tutor is **in development** (status/privacy): the landing says so in
  the founder note and the FAQ, and pricing lists it as “when it ships”, never as
  a free feature today.
- Provenance copy is precise: the source pack (book + pages) is recorded with
  every lesson; it is not claimed to be printed on the lesson page.
- The pricing page is explicitly free-during-launch with no paid plan or
  payment integration; it does not collect an email because no waitlist backend
  exists.
- The contact page uses the public issue tracker as the monitored channel. It
  says the privacy mailbox and the compliance takedown mailbox are not published
  yet; the N-05 notice will ship before any exam-pattern content does
  (`docs/compliance/`).
- The landing transcript is model-drafted Hinglish. A native reader must review
  it before launch; that is recorded as a known gap, not hidden.

## Tests

`testing/frontend/test_shell.py` is the public-site contract:

- static: page inventory, no external resources, internal links, metadata,
  §10 scope guard, claim language, honest no-form pricing, nginx `/courses`
  route, catalogue integrity, font licence;
- browser: Concept A with JS off, catalogue filter/search/empty/error, class
  pages, 360 px overflow, resolved lesson links, a11y basics, zero console
  errors.

`testing/frontend/test_frontend_features.py` keeps the branded-404 contract and
the SEO generator tests. `test_perf_budget.py` still gates the landing page on
the weak-Android profile.

## Known gaps / handoffs

| Gap | Owner | Notes |
|---|---|---|
| Sign-in / accounts nav | F2 | No `/login` link is shipped; a dead CTA is worse than its absence. |
| Voice tutor runtime | S1 / F4 | Not on the public lesson page yet; status and privacy say so. Pricing and the landing FAQ say “when it ships”. |
| Pro waitlist form | F2/F11 | Pricing says it is not open. Needs an endpoint, retention rule and consent copy first. |
| Static catalogue/class HTML for crawlers | F1/P5 follow-up | Client-rendered from `courses.js` today; the sitemap is the static discovery path. |
| Locale hubs (`/hi/`, `/hi-Latn/`) still use the old card renderer | F4/P5 | P5 handoff recorded in `TIMELINE.md`; `zivon.js::renderCard` is the seam. |
| Native Hinglish review of the landing sample | Founder/content | The transcript is labelled as a sample; review before launch. |
| Contact/privacy mailboxes | Founder | The issue tracker is the channel until a monitored mailbox is published. |
| Public-page OG generation | P5 | Only the landing OG URLs are rewritten by the existing generator; new pages use relative canonicals and no fake OG image. |
