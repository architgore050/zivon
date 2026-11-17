# Identity and settings surfaces (`/login`, `/signup`, verify/reset, onboarding, `/app/settings`)

Status: implementation contract for the F2 identity screens (landed 2026-11-17,
branch `feature/w3-f2-identity-settings`, based on `main` @ `d65b658`). It
describes code that exists; it is not a spec-only artifact.

Scope: the account creation and recovery screens, the first-run profile setup,
the signed-in settings and privacy pages, and sign-out. It does **not**
re-specify the F0 account service, sessions, cookies, tokens, Google, or email
delivery (`backend/auth/`, ADR-0029) — every write goes through those modules.

The shell, the guard, and the CSP contract are `docs/specs/frontend/web-shell.md`.
Visual authority stays `docs/frontend/design-doctrine.md` §1–§9; these are base
Field Notes surfaces with one paper card per auth screen and no §10 lesson
device.

## 1. Surfaces and routes

| Route | Methods | Session | Template | Owner |
|---|---|---|---|---|
| `/login` | GET, POST | guest (signed-in visitors are sent on) | `web/templates/auth/login.html` | F2 |
| `/signup` | GET, POST | guest | `auth/signup.html` | F2 |
| `/verify-email` | GET, POST | optional | `auth/verify_email.html` | F2 |
| `/forgot-password` | GET, POST | guest | `auth/forgot_password.html` | F2 |
| `/reset-password` | GET, POST | guest (emailed token) | `auth/reset_password.html` | F2 |
| `/onboarding` | GET, POST | required | `auth/onboarding.html` | F2 |
| `/onboarding/skip` | POST | required | — (303 to `/app`) | F2 |
| `/logout` | POST | optional (idempotent) | — (303 to `/login`) | F2 |
| `/app/settings` | GET, POST | required | `app/settings.html` | F2 |
| `/app/settings/password` | POST | required | — (303 to `/app/settings`) | F2 |
| `/app/settings/privacy` | GET | required | `app/settings_privacy.html` | F2 |
| `/app/settings/delete` | POST | required | — (303 to `/login?deleted=1`) | F2 |

The HTML routes call the same `AuthService` methods the JSON endpoints use
(`register`, `login`, `verify_email`, `request_password_reset`,
`reset_password`, `update_profile`, `set_or_change_password`,
`delete_account`, `revoke_session`). No password hash, session token, OAuth
state, or email token is minted or checked in `web/`.

`GET /v1/auth/google/start` and `/v1/auth/google/callback` stay F0 endpoints;
the screens only link to them (`intent=login` from sign-in/sign-up,
`intent=link` from settings) and map the callback's `?error=<code>` redirect to
honest copy without echoing the code.

## 2. Flow contracts

| Flow | Contract |
|---|---|
| Sign in | `AuthService.login`; unknown address and wrong password render the same 401 copy after the same work (no enumeration); success sets the F0 cookie and 303s to `safe_next_path(next)`. |
| Sign up | `AuthService.register` (one account per email); the consent checkbox is required to submit; success sets the cookie and 303s to `/onboarding`; the verification mail goes through the F0 email seam. A duplicate address is a 409 that points at `/login`. |
| Safe `next` | Read and re-validated with `backend.auth.service.safe_next_path`; only a single-slash same-origin path is kept, `//host`, absolute URLs, backslashes, and control characters fall back to `/app`. The value is a hidden field, and a Google sign-in carries the same value as `next=` in the F0 start URL. |
| Verify email | The emailed one-time token is shown as a state; the confirm button POSTs it, and the token is consumed by `AuthService.verify_email`. A used/expired token is a branded 400 with a way forward. There is **no resend endpoint in F0** — the screen says resending is not built yet instead of shipping a dead button. |
| Forgot password | Always renders the same "if that address has an account" state; `AuthService.request_password_reset` runs as a background task after the response (same as the JSON endpoint). Malformed addresses are a 422 (format only, never account existence). |
| Reset password | The link carries a one-time token; the form posts token + new password + confirmation. Success revokes every session and 303s to `/login?reset=1`. The token is not consumed by a validation failure, so a mismatched confirmation can be corrected. |
| Onboarding | Class (9–12), board (CBSE / ICSE / State Board), language (English / Hindi / Hinglish), optional goal. Saving calls `AuthService.update_profile`. Skip writes nothing and 303s to `/app`. |
| Sign out | CSRF-checked POST; revokes this session through `AuthService.revoke_session` and clears the F0 cookie. A stale/absent session still clears the cookie (idempotent). |
| Settings | Profile (email read-only, display name, class, board, language), password set/change, Google link state, sign-out, and a link to the privacy/data page. A board or a locale saved through `/v1/me` that is not one of the shipped choices keeps its value: the saved option is offered and accepted unchanged, so editing another field cannot silently rewrite it. |
| Data controls | Export is `GET /v1/me/export` (JSON attachment); delete requires the exact word `DELETE` plus the current password when the account has a password identity, then calls `AuthService.delete_account`, clears the cookie, and 303s to `/login?deleted=1`. |
| Google-created account | `password_set: false` renders a "Set a password" panel with no current-password field; setting one keeps the same account. Google linking from settings requires a verified email (F0 rule) and is hidden with a reason when verification is missing or Google is unconfigured. |

## 3. CSRF matrix

| Form | Credential | Verified by |
|---|---|---|
| `/login`, `/signup`, `/forgot-password` | signed double-submit guest token: random nonce in an HttpOnly `zivon_form_token` cookie + `keyed_hash(secret, "form-csrf:", nonce)` hidden field | `web/forms.py::guest_token_valid` |
| `/verify-email`, `/reset-password` | the one-time emailed token itself | `AuthService.verify_email` / `reset_password` (single-use, hashed, expiring) |
| `/onboarding`, `/onboarding/skip`, `/app/settings*`, `/logout` | F0C session-derived token rendered by `csrf_field()`, hidden `name="csrf_token"` | `AuthService.verify_csrf` |

Every rejection renders the branded 403 page and changes nothing. A guest form
without the nonce cookie cannot be replayed from another origin; a session form
without the session token cannot be forged from a stolen cookie alone.

Form bodies are parsed with `parse_qs` (stdlib). Starlette's `request.form()`
needs `python-multipart`, which the backend image does not ship; a browser form
always uses `application/x-www-form-urlencoded`. Bodies over 16 KB and more
than 32 fields are rejected. The body is read in chunks and dropped at the cap,
so an unauthenticated oversized post is never buffered whole; nginx's default
1 MB `client_max_body_size` is the outer bound.

## 4. Rendered data and privacy

| Data | Where it may appear |
|---|---|
| Email address | `/app/settings`, `/app/settings/privacy` only — the owner asking "which account is this?". It is an explicit allow-listed value, never `ShellUser` and never a `users` row. |
| Display name, class, board, language | shell (`ShellUser`) and settings forms; escaped by Jinja autoescape |
| CSRF token | hidden form field / `csrf-token` meta on an authenticated page |
| Session token, session id, user id, token hashes, expiry | never in HTML; a test asserts the raw cookie and user id are absent |

The web-shell document says the shell must never contain an email address; that
rule still holds for `ShellUser` and every other page. Settings is the one
deliberate exception because REQUIREMENTS §10.21 requires the student to see
the account email. `/app`, the auth screens, and error pages still carry no
account identifier.

## 5. Error and rate-limit copy

| Condition | Status | Student sees |
|---|---|---|
| Wrong password / unknown email | 401 | "Email or password is wrong. Check both and try again." (identical for both) |
| Missing/invalid field | 422 | a `role="alert"` summary plus a field error tied by `aria-describedby` |
| Guest CSRF failure / expired session form | 403 | "This form expired" + reload instruction |
| Rate limited (login/register/reset/verify) | 429 + `Retry-After` | "Too many attempts from this connection. Try again in about N s." |
| Duplicate signup | 409 | "That email already has a Zivon account. Sign in instead…" |
| Invalid/used verify or reset token | 400 | "This link is no longer valid" / "no longer valid" + a fresh path |
| Auth service not wired | 503 | the F0C 503 shell, no Sign-in control |
| Google callback failure | 303 to `/login?error=<code>` | mapped copy; the raw code is never printed |
| Network/offline | browser offline page | n/a server-side; lessons stay static |

## 6. States

| Screen | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | quota-exhausted | consent-missing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `/login` | email+password card, Google (when configured), guest link | n/a (SSR bytes complete first) | n/a (form never empty) | Google unconfigured → honest status, no dead button | 401/422/429/503 as above | browser offline page | signed-in visitor → 303 `next` | no animation | English copy; saved language shown in the shell only | n/a (no voice) | n/a (voice consent is per device, not an account state) |
| `/signup` | email+password+confirm+consent | n/a | n/a | Google unconfigured status | 422/409/429 | browser offline page | signed-in visitor → `/app` | no animation | as above | n/a | n/a |
| `/verify-email` | inbox state, or token state with a confirm button | n/a | no token → inbox state | resend not built → honest status + contact link | used/expired token → 400 | browser offline page | token still works for a guest or a signed-in student | no animation | as above | n/a | n/a |
| `/forgot-password` | email card | n/a | n/a | sent state says the response is identical either way | 422/429 | browser offline page | n/a (guest only) | no animation | as above | n/a | n/a |
| `/reset-password` | token + new password card | n/a | no token → incomplete-link state | n/a | 422 mismatch, 400 expired | browser offline page | n/a (the token is the credential) | no animation | as above | n/a | n/a |
| `/onboarding` | three questions, skip | n/a | class unset → placeholder / radios unselected | goal is device-local and labelled so | 422 field errors | browser offline page | guest → 303 `/login?next=/onboarding` | no animation | English copy + saved-language note | n/a | n/a |
| `/app/settings` | profile facts + three forms | n/a | n/a | unverified email, password unset, Google unlinked/unconfigured each have a row state | 422/401/403 | browser offline page | guest → 303 `/login?next=/app/settings` | no animated toggles | labels English; saved language as data | n/a | n/a |
| `/app/settings/privacy` | stored-data list, export, delete disclosure | n/a | export may be empty but still valid JSON | delete form collapsed in `<details>` | 401/422 on delete | browser offline page | guest → 303 | no animation | as above | n/a | per-device voice consent is linked, not managed here |
| `/logout` | n/a | n/a | n/a | n/a | CSRF → 403 | browser offline page | stale tab still clears the cookie | n/a | n/a | n/a | n/a |

The signed-in shell's own state table stays `web-shell.md` §8.

## 7. Accessibility and mobile

- One `<h1>` per page, a `legend` per question group, labels above fields,
  visible `:focus-visible`, 48 px inputs, 48 px choice rows, 44 px links.
- Every input/select in settings has a matching `label for`; tests assert it.
- Field errors are `<p class="field-error" id="…">`, referenced by
  `aria-describedby`, and the form-level error is `role="alert"`.
- Passwords are masked; the reveal control is added by `auth.js` only when JS
  runs (no dead button without JS). `autocomplete` is `current-password` or
  `new-password`, never `off` for a password.
- The layout is one column at 360 px; `auth.css` drops card padding below
  26 rem and never sets a fixed width. No motion is required; the
  `prefers-reduced-motion` rule is a no-op guard.
- No inline script/style/handlers; `frontend/assets/auth.css` and `auth.js`
  are same-origin, and `auth.js` makes no network call.

## 8. Guest merge handoff (F2 prompt, F3 sync)

`/login` and `/signup` carry a standing prompt: progress saved on this device
stays on this device, creating an account does not delete it, and moving it
into the account arrives with progress sync. F2 implements the **prompt** only.
The sync and merge summary belong to F3 (`NEED-019`); local keys
(`zivon.progress`, `zivon.bookmarks`) are not read, rewritten, or cleared by
any F2 route.

The optional onboarding goal is the one local value F2 writes:
`localStorage["zivon.goal"]` via `auth.js`, prefilled on a return visit, with
the "not sent to the server" hint visible. No F0 column exists for it.

## 9. Tests

`python -m unittest discover -s testing/backend -t .` runs:

- `testing/backend/test_web_auth.py` — renders, guest cookie flags, player
  states; login success/failure parity, missing-field ARIA links, password
  never echoed, guest CSRF rejection, retry after a validation error, safe and
  unsafe `next` values, rate-limit 429 + `Retry-After`, 503 shell; signup
  success/validation/duplicate/rate-limit/CSRF; verification inbox/token/used
  states and both redirect targets; reset no-enumeration, token consumption,
  mismatch retry, session revocation; non-form, >16 KB, and >32-field bodies
  rejected with the branded 400; static template rules and the nginx auth proxy
  block.
- `testing/backend/test_web_settings.py` — guest guard on GET/POST, owner
  profile render with no user id or raw cookie, unverified/verified Google
  states, escaping, CSRF field reuse, label/for pairing; profile save and
  validation rollback; an out-of-set locale preserved through a save; password
  rotation with other-device revocation and recorded session metadata, wrong
  current password, mismatch, CSRF, service-rejection status/copy; Google-created
  account password prompt; onboarding save/validation/skip/CSRF; logout and
  stale-tab logout; privacy page, export attachment, delete confirmation/password/
  CSRF, a Google-created account deleting without a password, and the tombstone;
  static template rules.

Shared hermetic setup: `testing/backend/web_auth_support.py` (SQLite in
memory, dev email sink, fake Google transport). No network, no keys.

## 10. Known debt and handoffs

| Item | Owner | Note |
|---|---|---|
| Verification resend | F0/F2 backend follow-up | No endpoint exists; the screen states it honestly instead of a dead button. |
| Terms-acceptance record | F0 backend follow-up | Signup requires the checkbox, but no column stores the acceptance; the terms page is the reference copy. |
| Goal persistence on the account | F0/F3 | No `users.goal`; F2 keeps it device-local and labels it. |
| "Set a password" banner on `/app` | F3 | Settings surfaces the Google-created state today; the dashboard can repeat the prompt when F3 owns that template. |
| Guest progress merge | F3 (`NEED-019`) | F2 shows the prompt; no local data is read or moved. |
| Structured auth events | F11/observability | HTML auth routes emit no `log_event` rows yet; the F0 JSON routes do not either. Add map rows before instrumenting. |
| Settings password-change limit | F0 | `/app/settings/password` and `/v1/me/password` share the same properties: session + CSRF + current password, but no dedicated rate-limit family. Add one if F0 adds it rather than inventing a family here. |
| Two open auth tabs | F2 | Every GET of `/login`/`/signup`/`/forgot-password` issues a fresh nonce, so the older tab's hidden token fails closed with the 403 page and a reload instruction. Reusing an existing nonce would remove the stutter; not worth new state today. |
| Google start with an expired session | F0 | `/v1/auth/google/start` answers the JSON `E-AUTH-REQUIRED` envelope when the session died between render and click; a `303` to `/login?next=` would be friendlier when F0 revisits that route. |
| Public nav sign-in link | F1 | The static public pages do not yet link to `/login`; the server-rendered shell does. |
