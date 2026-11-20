# Web shell (`web/`) — server-rendered app foundation

Status: implementation contract for the F0C shell (landed 2026-11-17, branch
`feature/w3-f0c-web-shell`, based on `main` @ `e0f2e7a`). It describes code
that exists; it is not a spec-only artifact.

Scope: the **shared shell** the authenticated app pages use — `/app` today,
plus the auth/app pages F2/F3/F5/F6/F7 add. This document does not specify
those feature pages. It fixes the route/mount seam, the account guard, the
template context, the CSP/header contract, and what a feature workstream may
change without reopening the foundation.

Visual authority stays `docs/frontend/design-doctrine.md` §1–§9 and F1's
`frontend/assets/product.css`. The shell renders no §10 lesson device: no
ruled grid, no Caveat/Kalam body, no taped cards, no language bar, no voice
dock. `/app` is a shell page, not a lesson page.

## 1. Surface classification

| Route | Surface | Render | Indexable |
|---|---|---|---|
| `/app` | authenticated app | SSR (FastAPI + Jinja2) | no (`noindex`, `X-Robots-Tag`) |
| `/app/*` (future) | authenticated app | SSR, same guard | no |
| `/login` (F2) | auth | SSR, single paper card | no |
| `/`, `/courses`, lessons | public | static (F1 / factory) | yes, unchanged |

The shell adds **no** static route. Public discovery and lesson reading remain
static files served by nginx; only pages whose primary content needs the
session cookie are server-rendered.

## 2. Mount and route contract

`backend.app.create_app` calls `web.mount_web(app)` **after** the JSON API
routers and after the voice mount.

- It registers HTML routes only. It never adds `/v1/*`, `/voice/*`, or
  `/admin/*`; no JSON contract or WebSocket frame changes.
- It registers no catch-all. A future `/app/practice` route from F5 is matched
  by F5's router, not shadowed by the shell.
- `web/routes/__init__.py` is the router aggregator. A feature workstream adds
  a module there (`practice.py`, `tests.py`, …) and includes it in the same PR.
- The one exception handler pair is part of the mount: a guest gets a 303 to
  `/login`, an unavailable auth service gets a 503 HTML page. HTML routes must
  never return the JSON error envelope for these two cases.
- `/app` is registered with `include_in_schema=False`; the OpenAPI document
  stays the JSON API contract.

## 3. Shell template contract

`web/templates/base.html` is the only page frame. It renders:

- the Field Notes base identity through `frontend/assets/product.css`
  (`.site-head`, `.wrap`, `.site-nav`, `.site-actions`, `.chip`, `.page-head`,
  `.band`, `.section-head`, `.notice`, `.site-foot`, `.legal`);
- the local font files already shipped for the public site (preload only,
  same origin, no external host);
- `/assets/product.js` with `defer` (menu behaviour; it no-ops when the
  catalogue elements are absent).

It never links `frontend/assets/zivon.css` or uses a `zn-` class.

Slots every route fills through `ShellContext`:

| Context key | Meaning |
|---|---|
| `page_title` | page title; `base.html` appends `· Zivon` |
| `shell_kind` | `app` (signed-in nav + account chip) or `public` (guest/error/auth shell) |
| `user` | `ShellUser` or `None`; only display name, class level, board, language labels |
| `csrf_token` | derived CSRF token for future forms; `None` for a guest |
| `nav_items` | tuple of `NavItem`; the header and mobile menu render the same list |
| `active_nav` | key of the most specific matching item; drives `aria-current="page"` |
| `flash` | tuple of `FlashMessage` (`empty` / `partial` / `error`) rendered as `.notice` |
| `error` | one-line error rendered in the `role="alert"` notice slot |
| `auth_available` | false hides the Sign-in control when auth is down |
| `csp_meta` | meta CSP mirror (server constant) |
| `release_tag` | build label in the footer; not a secret |

Blocks: `head` (extra head tags a feature page needs) and `main` (the page
body). Partials: `partials/site_header.html`, `partials/site_footer.html`,
`partials/messages.html`, `partials/language.html`.

Template rules:

- no inline `<script>`, `<style>`, `style=""`, or `on*=""` handler; islands are
  same-origin files under `frontend/assets/` (or a future asset folder) loaded
  with a normal `<script src>` tag;
- no third-party host, font, analytics script, or CDN;
- every page template extends `base.html`;
- user-controlled strings are escaped by Jinja autoescape; never use `|safe`
  on a profile field.

## 4. Account guard and context

The guard reuses the F0 account path; it is not a second auth implementation.

1. Read the cookie named by `BackendConfig.auth_cookie_name`
   (`zivon_session` by default).
2. Validate it with `AuthService.resolve` (server-side session row, expiry,
   revocation).
3. A missing, malformed, expired, or revoked cookie is a **guest**: respond
   `303` to `/login?next=<request path and query, percent-encoded>`. The
   `next` value is always a same-origin path, never a host, so it cannot become
   an open redirect.
4. A valid cookie yields `AccountContext` with the user row and a CSRF token
   derived by `AuthService.csrf_for`. One resolver, `resolve_auth_session` in
   `web/context.py`, reads the cookie for every shell page: the guard uses its
   `shell_account` slice, while the F2 form routes also receive the
   `AuthContext` (the stored CSRF hash and the session id that
   `verify_csrf`/`revoke_session` need) and the raw value long enough to derive
   the token. The raw cookie is never rendered, logged, or passed to a
   template.
5. `app.state.auth is None`, a config error, or a session-store exception
   yields the 503 shell: an HTML page with a retry/completion path, no JSON
   stack trace, and no Sign-in control that would point back into the failed
   service.

What HTML may contain: display name, class label, board, language name and
native label, CSRF token. What it must never contain: email address, user id,
session id, token hash, expiry, raw cookie value, or any session row field.

One page is a deliberate, documented exception: `/app/settings` renders the
signed-in student's own email address as an allow-listed profile field, because
REQUIREMENTS §10.21 asks the screen to show which account is signed in
(`docs/specs/frontend/identity-settings.md` §4). It does not come through
`ShellUser`; `web/routes/settings.py` builds an explicit view dict. Every other
shell page, including `/app`, still carries no email address.

`ShellUser.from_user` is the only conversion from the `users` row to shell
template data. A template never receives the row itself.

Future server-rendered forms post the hidden input from `csrf_field()`
(`name="csrf_token"`) and the route validates it with
`AuthService.verify_csrf(ctx, form_token)` before any write. The JSON API keeps
its `X-CSRF-Token` header contract unchanged.

## 5. Headers and CSP

The app pages are the only non-lesson surface besides `/privacy/` that may call
the same-origin API, because F3/F5/F6/F7 render small islands over `/v1/*`.

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'` |
| `Cache-Control` | `no-store` |
| `X-Robots-Tag` | `noindex, nofollow` |
| `Referrer-Policy` | `no-referrer` |
| `X-Content-Type-Options` | `nosniff` |

- The same CSP string lives in `web/render.py` (`CSP_POLICY`) and in the
  `docker/nginx.conf` app/login locations; a test asserts they are identical.
- The page meta tag carries the same policy minus `frame-ancestors` (browsers
  ignore that directive in a meta tag). The meta is defense in depth; the
  header is the enforced policy.
- `connect-src 'self'` is scoped to `/app` and `/login` only. Every other
  static location keeps the server-level `connect-src 'none'`.
- No inline script or style is allowed, so the policy has no
  `unsafe-inline`/`unsafe-eval`.
- The backend sets these headers too, so a direct development request to the
  core backend is not unprotected; nginx repeats the full set because
  `add_header` is not inherited once a location declares its own.

## 6. Assets and proxying

| Request | Served by | Notes |
|---|---|---|
| `/app`, `/app/*` | core backend (`web/`) through nginx | HTML, cookies pass through |
| `/login` | core backend (F2's route) | the guard's redirect target; exact location with the full private header set |
| `/signup`, `/verify-email`, `/forgot-password`, `/reset-password`, `/onboarding`, `/logout` | core backend (F2's routes) | one anchored regex location repeating the `/login` proxy and header contract (`identity-settings.md` §1) |
| `/assets/product.css`, `/assets/product.js`, fonts | frontend nginx static root | same origin; unchanged F1 assets |
| `/v1/*`, `/voice/ws` | core backend | unchanged |

`docker/nginx.conf` adds exact/prefix locations for `= /app`, `^~ /app/`, and
`= /login`, an exact `= /v1/speaking/attempts` location with
`client_max_body_size 4m` and `client_body_buffer_size 8m` (F6's one transient
WAV; the route still caps at 3 MB, and the buffer keeps the upload in memory
rather than nginx's temp path), plus one anchored regex location for the rest
of the F2 auth paths
(`/signup`, `/verify-email`, `/forgot-password`, `/reset-password`,
`/onboarding`, `/logout`). Each proxies to `http://core-backend:8000` (the
compose alias and the cluster Service name), forwarding `Host $http_host`,
`X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto`. No `proxy_set_header Cookie` and no
`proxy_hide_header Set-Cookie`: the HttpOnly session cookie and the backend's
`Set-Cookie` pass through unchanged.

`Dockerfile.backend` copies `web/` into the monolith image and
`backend/requirements.txt` pins `jinja2`, so the image has templates and the
engine without adding a service or a frontend build step. The root
`requirements.txt` carries the same pin for the CI test environment.

A bare backend port (`18085`) serves the HTML without `/assets/*`, because the
static shell belongs to the frontend image; the supported path is always the
same-origin nginx route on `8081` (compose) or the Service (cluster).

## 7. Handoff to feature workstreams

- **F2 identity** owns `/login`, `/signup`, the verify/reset screens, the
  Google start/callback links, onboarding, settings/settings-privacy, and
  sign-out. It landed 2026-11-17 (`web/routes/auth.py`, `onboarding.py`,
  `settings.py`, `web/templates/auth/*`, `app/settings*.html`,
  `frontend/assets/auth.css|js`); routes, flows, the CSRF matrix, and states
  are specified in `docs/specs/frontend/identity-settings.md`. It consumes
  `ShellContext.for_public` for the single-paper-card shell and `csrf_field()`
  for every signed-in form; guest forms use the signed double-submit helper in
  `web/forms.py`. The guard's `/login?next=` target is the fixed contract.
- **F3 dashboard/progress** owns the real dashboard body and
  `web/routes/progress.py`. It replaced the `/app` body with
  `web/templates/app/dashboard.html` (route + guard unchanged), added
  `/app/progress` + `/app/bookmarks`, and added the `Progress` nav entry in
  the same PR. Contract: `dashboard-progress.md`.
- **F5/F6/F7** own practice, speaking, and tests/series routes/templates; each
  adds its router module under `web/routes/`, a template under
  `web/templates/app/`, a `nav.py` entry, and a state table for its screens.
- **F5 practice** landed 2026-11-17 (`web/routes/practice.py`,
  `web/practice_views.py`, `web/templates/app/practice/*`,
  `frontend/assets/practice.css` + `frontend/assets/practice.js`,
  `backend/practice/`), adding the `Practice` nav entry. Contract:
  `docs/specs/frontend/practice.md`.
- **F6 speaking** landed 2026-11-17 (`web/routes/speaking.py`,
  `web/templates/app/speaking/*`, `web/speaking_views.py`, the `Speak` nav
  entry, `frontend/assets/app-speaking.css` + `frontend/assets/app-speaking.js`); its contract is
  `speaking.md`.
- **F7 tests/series** landed 2026-11-17 (`web/routes/tests.py`,
  `web/test_views.py`, `web/templates/app/tests/*`, `frontend/assets/tests.css` + `frontend/assets/tests.js`,
  `backend/test_engine/`), adding the `Tests` nav entry and `/app/series`. It
  consumes the F0 guard/CSRF contract unchanged. Contract:
  `docs/specs/frontend/tests.md`.
- **PL4 personalized learning** landed 2026-11-19: `/app/personalized` (hub +
  session) as SSR pages with two same-origin islands, the settings partial
  include, and the `Learn` nav entry; contract and state matrix:
  `docs/specs/frontend/personalized.md`. The teaching turn stays the PL2
  JSON/SSE API; the shell, guard, and CSP are unchanged.
- **F8** uses the shell once F3's data exists, which it does: SWOT landed
  `/app/swot` + `/app/swot/how` as plain SSR pages with no island and no
  shell change (`docs/specs/frontend/swot.md`). **F10** does not use the
  student shell: admin keeps its separate staff session and
  container/surface.
- A feature PR never edits `base.html` chrome, the guard, or the CSP to make
  one page work. A new shell-level need is an F0 change with its own test.

## 8. States

| State | `/app` shell |
|---|---|
| default | signed-in page; account chip, class/board/language, page body |
| loading | n/a: SSR completes before bytes; a slow DB is the 503 path |
| empty | the page body is an honest empty state (no invented activity) |
| partial | language note when the saved language has no UI copy yet |
| error | 503 shell for unavailable auth; future feature pages own panel-level errors |
| offline | n/a server-side; a failed navigation is the browser's offline page (the static lesson pages stay readable) |
| permission-denied | guest is a 303 to `/login?next=`; a valid session never sees a permission form on `/app` |
| reduced-motion | no shell animation; the policy and the `prefers-reduced-motion` rule in `product.css` cover future islands |
| untranslated | shell copy is English and tells the student the language choice is saved, not rendered |
| quota-exhausted | not a shell state; voice credits are surfaced by the dock, never the page frame |
| consent-missing | not a shell state; voice consent is per device in the lesson shell |

## 9. Tests

`python -m unittest discover -s testing/backend -t .` runs
`testing/backend/test_web_shell.py`, which asserts:

- guest `/app` → `303 /login?next=/app`, and `?tab=today` is preserved and
  percent-encoded; every emitted `next` value survives `safe_next_path`, and a
  `//host` path falls back to `/app` (no protocol-relative redirect);
- a garbage cookie is a guest, not a 500;
- unavailable auth → `503` HTML shell with no Sign-in control;
- authenticated `/app` renders the user context, base doctrine classes,
  `aria-current`, the CSRF meta, `noindex`, `no-store`, and no §10 `zn-`
  class / `zivon.css`;
- the email, user id, and raw cookie never appear in HTML; a script-shaped
  display name is escaped;
- `/healthz`, `/v1/health`, `/v1/catalog`, `/v1/auth/session`, and `/voice/ws`
  still mount;
- `docker/nginx.conf` has the app/login proxy locations with the exact CSP,
  forwarded headers, cookie pass-through, `no-store`, and `noindex` (asserted
  for all three locations, so a header dropped from `^~ /app/` fails); the F2
  suite also asserts the anchored regex location for the remaining auth paths
  carries the same header set and proxy contract;
- `Dockerfile.backend` copies `web/` and the requirements pin `jinja2`.

A static template scan rejects inline script/style/handlers, and every page
template must extend `base.html`.

## 10. Known debt

- The header account chip is a label, not a menu; sign-out and account
  settings live on `/app/settings` (F2). A header menu would be an F0 change
  with its own test.
- Shell copy is English-only; the language choice is displayed and noted, not
  translated. UI translation is its own workstream.
- A URL under `/app` that matches no route answers FastAPI's JSON 404 (the
  shell registers no catch-all by design); a branded HTML 404 for the app
  surface lands with a feature PR that can own the route.
- The app nav lists Dashboard, Practice, Tests, Progress, SWOT, Learn,
  Speak, Courses, and Settings. Practice, Tests, Speak, and SWOT landed
  2026-11-17 (`docs/specs/frontend/practice.md`, `docs/specs/frontend/tests.md`,
  `docs/specs/frontend/speaking.md`, `docs/specs/frontend/swot.md`); the
  personalized `Learn` entry landed with PL4 (2026-11-19,
  `docs/specs/frontend/personalized.md`). Saved sections are a quick link on
  the dashboard/progress pages rather than their own nav entry.
- `/app` is not rate-limited by the API bucket (the abuse classifier returns
  no family for HTML paths); the JSON API it calls keeps its existing limits.
