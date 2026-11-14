# App shell and routing

How a Zivon URL becomes bytes, which layer owns it, and what it is allowed to
do. The target is one nginx, one Python service, one Postgres, and **no SPA**.
The current repo is already most of the way there: static file-path routing on
nginx, a same-origin voice WebSocket, and a shell that works offline. The full
product adds server-rendered app, auth, and admin pages behind the same origin.

Read `docs/specs/frontend/spec.md` §2–§3 for the binding implementation view,
`docker/nginx.conf` for the live header/cache/proxy truth, and
`tmp/full-frontend/REQUIREMENTS.md` §3 for the full route and API map.

## 1. The four delivery classes

| Class | Served by | Indexable | Cache | Auth |
|---|---|---|---|---|
| Public static | nginx from `frontend/` | yes | HTML `no-store`; JS/CSS `no-cache`; other assets 300 s | none |
| Generated lesson | nginx from the `zivon-frontend` PVC / mounted `frontend/courses/` | yes | HTML `no-store`; JS/CSS `no-cache`; other assets 300 s; audio immutable | none |
| Server-rendered app/auth | nginx → core-backend (FastAPI + Jinja) | no (`noindex`) | private/no-store | session cookie |
| Admin | nginx → core-backend (staff auth) | no (`noindex`) | private/no-store | separate staff session |

The static shell is baked into `Dockerfile.frontend` at `/opt/zivon-shell` and
seeded into the served root with a no-clobber copy. Generated pages arrive at
runtime on a volume/PVC and are never baked into an image. `publish-frontend.sh`
mirrors the PVC into the repo snapshot and refuses to touch the shell.

## 2. Route map

### 2.1 Static (nginx / CDN)

| Route | Page | Notes |
|---|---|---|
| `/` | Landing | Public, indexable; one H1; real demo clip with transcript |
| `/courses` | Catalogue | All four classes, class tabs, search/filter, status |
| `/courses/{class}/physics` | Class/course page | Chapter list, availability, continue |
| `/courses/{class}-physics/{chapter-slug}/` | Generated lesson | Canonical lesson path; keep it stable |
| `/{locale}/...` or shipped `<topic>/<locale>/` | Localized public pages | Hook only; do not build a wildcard router early |
| `/method` | Method | Socratic tutoring, retrieval, simulations, sources, limits |
| `/about` | About / build-in-public | Founder story, Gnani stack, provenance |
| `/pricing` | Pricing + Pro waitlist | Free during launch; no fake urgency |
| `/privacy` | Privacy summary + clear data | Scoped `connect-src 'self'` |
| `/terms`, `/contact`, `/status` | Trust pages | Static; contact is a form or mail link, no PII in logs |
| `/404` / `/404.html` | Branded not found | `error_page 404 /404.html`; no JS |

### 2.2 Auth (server-rendered)

| Route | Page |
|---|---|
| `/login` | Email + password, Google, “continue as guest” |
| `/signup` | Create account; optional Google; merge explanation |
| `/verify-email` | Consume verification token |
| `/forgot-password` | Request reset |
| `/reset-password` | Consume reset token |
| `/onboarding` | Three steps: class, board, language; skippable |
| `/auth/google/start`, `/auth/google/callback` | OAuth start/callback |

### 2.3 App (server-rendered, auth required unless noted)

| Route | Page |
|---|---|
| `/app` | Dashboard |
| `/app/courses` | My courses (optional redirect to `/courses`) |
| `/app/practice` | Practice hub |
| `/app/practice/{session_id}` | Practice player |
| `/app/practice/{session_id}/summary` | Practice summary |
| `/app/practice/history` | Practice history |
| `/app/speaking` | Speaking hub |
| `/app/speaking/{prompt_id}` | Speaking recorder |
| `/app/tests` | Tests hub |
| `/app/series` | Series catalogue |
| `/app/series/{slug}` | Series detail |
| `/app/tests/new` | Test builder |
| `/app/tests/{attempt_id}` | Test player |
| `/app/tests/{attempt_id}/review` | Results and review |
| `/app/progress` | Physics map |
| `/app/swot` | SWOT |
| `/app/doubts`, `/app/doubts/{doubt_id}` | Doubt history/detail |
| `/app/bookmarks` | Bookmarks |
| `/app/settings`, `/app/settings/privacy` | Settings and data controls |

### 2.4 Admin (server-rendered, staff auth)

`/admin/login`, `/admin`, `/admin/content`, `/admin/questions`, `/admin/series`,
`/admin/blueprints`, `/admin/users`, `/admin/credits`, `/admin/reports`,
`/admin/flags`, `/admin/evals`, `/admin/debt`.

Admin v0 is a separate dashboard container on `:8082` today. The full product
moves the staff cockpit behind `/admin/*` on the same origin, with a separate
staff session. Do not expose it on the student origin without that auth split.

### 2.5 API and WebSocket namespace

Keep `/v1/*` and add, in the same origin:

- `/v1/auth/*`, `/v1/me/*`
- `/v1/catalog/*`, `/v1/progress/*`, `/v1/swot`
- `/v1/practice/*`, `/v1/speaking/*`, `/v1/tests/*`, `/v1/series/*`
- `/v1/doubts/*`, `/v1/bookmarks/*`, `/v1/waitlist`
- `/v1/admin/*` (staff only)
- `/voice/ws` (WebSocket, same origin)
- Existing: `/v1/session`, `/v1/consent`, `/v1/events`, `/v1/reports`,
  `/v1/data`, `/v1/health`

Do not create a second API origin, a CDN API, or a client-side router. Every
call is same-origin.

## 3. nginx contract

The site config in `docker/nginx.conf` is the only site config; compose and
cluster use the same file. Keep these properties:

- `error_page 404 /404.html;`, `autoindex off`, `try_files $uri $uri/ =404`.
- Site-wide security headers: CSP, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `Cache-Control` from the map.
- Cache map: HTML and `courses.js` `no-store`; JS/CSS `no-cache`; everything
  else 300 s; `/audio/` immutable, one year; audio rate limit per IP.
- `/voice/` proxies to `core-backend:8000` with WebSocket upgrade and a long
  read timeout; `Host $http_host` preserves the port for the origin check.
- `/v1/` and `/api/` proxy to `core-backend:8000` with the same forwarded
  headers.
- `/courses/` and `/privacy/` are the only static locations with a scoped
  `connect-src 'self'`; every other non-lesson location keeps
  `connect-src 'none'`.
- Every location that declares its own `add_header` repeats the full header
  set: nginx drops inherited `add_header` in that case. This is a known trap.

When the app/auth/admin pages land, add dedicated locations that proxy to the
backend. Do not weaken the static CSP globally to make one page work; scope the
relaxation to the location that needs it, and repeat the full header set.

## 4. Cookies, sessions, same-origin

- Session cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, scoped to the site;
  rotate the session identifier on login and privilege change.
- CSRF token for state-changing requests; validate on the server.
- No session token in `localStorage`, `sessionStorage`, a URL, or a readable
  cookie.
- Staff sessions are separate from student sessions. A student cookie never
  grants admin access; staff auth is password + optional TOTP.
- Guest-first: a student can read, simulate, check, and practise locally
  without an account. Signing in links the device and merges local progress;
  never silently discard it.
- Device pseudonym (`zivon.device_pseudo_id`) is local-only and used as a
  session label. It is not a login and not a name. Do not join it to email,
  phone, or a public profile.
- Google OAuth resolves by `google_sub`, then verified email; one account, no
  Google-only duplicate. No phone OTP; no magic-link login.
- Password reset and email verification are recovery flows, not login methods.
- Logout revokes the session server-side, not just the cookie.
- The admin break-glass token remains server-side only; never ship it to a
  browser.

## 5. CSP and third parties

The default page policy is `default-src 'self'`, `connect-src 'none'`, no
inline script, no `eval`. Lesson pages and `/privacy/` opt into
`connect-src 'self'` for the same-origin WS/API. Any new page that calls an API
gets its own scoped policy in nginx and a matching meta tag.

Rules:

- No third-party hosts: no Google Fonts, no CDN, no analytics, no tag manager,
  no chat widget, no social embed.
- No inline `<script>` or inline event handlers. Use external files with
  `defer` or a hash/nonce where the server renders the page.
- No `eval`, `new Function`, or string-bodied timers.
- No `unsafe-inline` or `unsafe-eval` in a product page.
- Do not add `frame-ancestors` permissively; default to `'none'` if framing is
  not required.
- A CSP change is a security decision. Record why and scope it to the smallest
  location.
- Serve over HTTPS with HSTS at the edge; `Secure` cookies require it. Do not
  add a mixed-content exception for a convenience script.

## 6. i18n: English, Hindi, Hinglish

Supported UI/content locales: `en`, `hi`, `hi-Latn` (Hinglish in Latin script).
The voice tutor may accept more Gnani-supported speech languages, but the UI
ships these three.

Per-surface language rule (frozen):

| Surface | EN | HI | Hinglish |
|---|---|---|---|
| Lessons, UI, AI Lesson tests, Challenge/Loop drills, non-CBSE practice | yes | yes | yes |
| Board Practice, PYQ Pattern, Exact PYQ (CBSE-style) | yes | yes | no |
| Voice tutor | yes | yes | yes |

Rules:

- Never silently mix languages. If a variant is missing, show English plus a
  visible “not available in this language yet” marker.
- Distinguish machine-translated from reviewed content where the bundle says so.
- Never translate SI units, symbols, equations, autonyms, source names, or
  model names.
- One language belongs to the page, not to a single widget. The language bar
  switches every string on a lesson page.
- The persistent key is `localStorage["zivon_locale"]`. `zivon.lang` is a
  read-only legacy fallback; never write it again.
- Set `<html lang="...">` and per-block `lang` when scripts mix. Devanagari
  needs the doctrine's Hindi fallback stack.
- A localized route is the same page with content swapped at publish time, not
  a runtime translation. Do not build a client-side translator.
- Hreflang and per-locale sitemaps are gated on the locale model decision. Do
  not emit a half-built hreflang cluster.

## 7. SEO and noindex

Indexable: landing, catalogue, class pages, public lesson pages, method,
about, pricing, trust pages. Not indexable: `/app/*`, `/auth/*`, `/login`,
`/signup`, `/onboarding`, `/admin/*`, search results, and anything personalized.

Every indexable page:

- one canonical URL, self-referencing;
- one `<h1>`, a unique `<title>`, a useful meta description;
- Open Graph/Twitter tags only where the page is meant to be shared;
- JSON-LD where the type is honest: `Organization` for the site,
  `LearningResource` for a lesson, `Course`/`FAQPage` only when the content
  actually matches;
- canonical host from `ZIVON_PUBLIC_BASE_URL`; never hard-code a domain;
- sitemap and `robots.txt` generated at publish time, not hand-edited;
- source-pack licences surfaced in the lesson's structured data.

Every private page:

- `<meta name="robots" content="noindex, nofollow">` and an
  `X-Robots-Tag: noindex` header where the server controls it;
- excluded from `sitemap.xml`;
- no canonical pointing at a public URL.

Board-style series copy: “close to the paper pattern”, “built for practice”,
“not an official CBSE paper”. Never “official”, “exact CBSE”, or an
affiliation claim for generated items. Exact PYQs carry source attribution.

## 8. New route checklist

- [ ] The route is in the frozen map/requirements, not invented.
- [ ] The delivery class is explicit: static, generated lesson, SSR app, auth,
      or admin.
- [ ] The owner workstream and files are named; no cross-owner edits.
- [ ] nginx location exists (or the static file path resolves) and repeats the
      full header set if it declares one.
- [ ] The page has a canonical/noindex decision.
- [ ] Auth/consent gate is explicit; guest behaviour is defined.
- [ ] Cookie/session use is `HttpOnly`/`Secure`/`SameSite=Lax`; CSRF on writes.
- [ ] The page has a 360 px layout and a keyboard path.
- [ ] The 404 and expired-token paths have an exit.
- [ ] The route is added to the sitemap only if indexable.
- [ ] Tests cover status, headers, no external refs, and the auth redirect.

## 9. Failure and rollback

- Unmatched URL → branded 404, one sentence, link home.
- Expired session → redirect to login with a safe return path; never loop.
- Backend down → static pages keep serving; app pages show a server error page
  with a retry, not a blank screen.
- Voice backend down → lesson reading, sims, checks, read-aloud, and typed input
  still work; the dock shows its offline state.
- Deploy rollback is an image-tag rotation; do not run schema-destructive
  migrations in the same step as a UI rollback.
