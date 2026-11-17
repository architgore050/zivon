# 2026-11-17 — W3 F2 identity and settings surfaces

Branch `feature/w3-f2-identity-settings`, based on `main` @ `d65b658`
(F0C server-rendered shell). Worktree `tmp/worktrees/w3-f2`.

## Done

- **Auth screens on the F0C shell** (`web/routes/auth.py`, `web/templates/auth/`):
  `/login`, `/signup`, `/verify-email`, `/forgot-password`, `/reset-password`,
  `/logout`. All writes call the existing `backend/auth` service; no password,
  token, session, or Google logic lives in `web/`.
- **Signup and onboarding:** `/onboarding` (class 9–12, board, EN/HI/Hinglish,
  optional device-local goal) plus a skip that writes nothing.
- **Settings and privacy** (`web/routes/settings.py`,
  `web/templates/app/settings*.html`): owner email (read-only, allow-listed),
  display name, class/board/language, password set/change with session
  rotation, Google link state (linked / unverified / unconfigured), sign-out,
  export link, and delete with the exact-word + password confirmation.
- **CSRF:** guest forms use a signed double-submit token
  (`web/forms.py`); verify/reset rely on the emailed one-time token;
  onboarding/settings/logout verify the F0C session token. Every rejection is
  a branded 403 and changes nothing.
- **No enumeration:** wrong password and unknown email render the same 401
  copy; forgot-password always renders the same state; rate limits render 429
  with `Retry-After`.
- **Assets:** `frontend/assets/auth.css` (new, no edits to `product.css`) and
  `frontend/assets/auth.js` (password reveal, onboarding goal persistence).
- **nginx/e2e wiring:** one anchored regex proxy location for the remaining
  auth paths with the same CSP/headers/cookie pass-through as `/app`.
- **Docs:** new `docs/specs/frontend/identity-settings.md`; `web-shell.md`
  handoff/known-debt updated; `state-matrix.md` gained APP-02/APP-03;
  `public-site.md` sign-in handoff row updated.
- **Tests:** `testing/backend/test_web_auth.py` (login/signup/verify/reset) and
  `test_web_settings.py` (settings/onboarding/logout/export/delete), shared
  hermetic setup in `web_auth_support.py`; 68 tests green with the existing
  24 shell tests.

## Not done / recorded debt

- Resend-verification endpoint does not exist in F0; the screen states that
  honestly (no dead button).
- The terms checkbox is required but not stored (no F0 column).
- The optional goal is device-local only (no `users.goal`).
- Guest progress merge prompt is shipped; the sync is F3 (`NEED-019`).
- Auth HTML routes emit no structured events yet (no map rows).
- Google-created accounts are prompted to set a password on Settings; a
  `/app` banner waits for F3's dashboard template.

## Next

- Review agent: merge gate + the security/tests/docs lenses.
- F3: dashboard + progress sync, including the merge summary and the
  set-password banner on `/app`.
