# ADR-0029: One student account per email — email+password and Google, cookie sessions, device pseudonymity for guests
- Status: accepted
- Date / deciders: 2026-11-16, F0 backend foundation (Wave 1), implementing the founder decisions of 2026-11-15 (post-challenge startup track; full consumer product with accounts)
- Driving requirements: REQUIREMENTS §3.5 (accounts are additive), §6 (identity/auth/privacy), §8.1/§8.4 (tables), §9.1/§9.2 (API); `docs/backend/backend-spec.md` §6.4/§8.1a; `docs/backend/db-spec.md` §4.18
- Supersedes: the "no student accounts anywhere" premise of **ADR-0007** for the product runtime. Device-scoped pseudonymity is retained for guests and for the voice stack's session token.

## Context

ADR-0007 chose anonymous device pseudonymity because accounts were out of scope for the
challenge demo, and named its revisit trigger as "any scale-up beyond the demo". The
founder decisions of 2026-11-15 fire that trigger: the product is now a startup track with
a full consumer frontend (dashboard, progress, practice, tests, SWOT, settings) in which a
student must return on another device and keep their evidence. A device-only identity
cannot serve that, and the frontend requirements already specify one account with email+
password **and** Google, no phone OTP, no magic link.

The existing stack must keep working: `/v1/session`, `/v1/consent`, `/v1/events`,
`/v1/reports`, `/v1/data`, `/voice/ws`, and the HMAC device session token are unchanged.
An account is an additional identity a device can be linked to.

## Options considered

| Option | Pros | Cons | Fails which requirement? |
|---|---|---|---|
| **One `users` row per email; `auth_identity` rows for `password` + `google`; opaque cookie sessions; device link stays optional** | one identity as required; Google and password coexist; guest path untouched; no password for Google-only students until they choose one | needs auth UI, email delivery, reset flow, and a new threat surface | — |
| Keep device-only identity | zero auth work | no cross-device progress, no recovery, no account settings; contradicts the full-frontend scope | §6.1/§6.2 |
| Separate Google-only and password-only accounts | simpler identity table | two identities for one student; progress split; violates "one account" | §6.1 |
| Phone OTP or magic-link login | no password to remember | explicitly excluded by the frozen product map; adds SMS cost/vendor | §6.1 |
| Password hash duplicated on `users` and `auth_identity` | matches a literal reading of the table sketch | two sources of truth for one credential | correctness (rejected) |

## Decision

1. **One account per email.** `users.email` is stored case-folded and unique. Passwords live
   only on the `password` identity row (a Google-created account has no password identity
   until the student sets one); a nullable `password_hash` on `users` is deliberately not
   created.
2. **Google is a second identity, never a second account.** The callback resolves by
   `provider_subject` (Google `sub`) first, then by Google-asserted **verified** email. It
   attaches to the existing account and records the verification the local account lacked.
   It never merges two accounts; a conflicting link is `E-CONFLICT`. A Google-created
   account answers `password_set: false` so the UI can prompt for a password. When the
   matched local account was **unverified**, Google's proof wins: the unproven `password`
   identity and every live session are discarded before the new session is issued, so an
   attacker who pre-registered a victim's address with their own password cannot keep
   reading the account after the victim signs in with Google (account pre-hijacking). The
   student keeps the same `users` row and is prompted to set a new password.
3. **Sessions are opaque and revocable.** The cookie carries a 256-bit token; the table
   stores only a keyed BLAKE2b MAC of the token, its expiry, and
   revocation. TTL 30 days, rotated on password change/reset and after a Google link.
   Cookie: `HttpOnly; Secure; SameSite=Lax; Path=/` (Secure is configurable only for local
   development).
4. **CSRF is derived, not stored in the clear.** The server derives the CSRF token from the
   session token and keeps its keyed hash; the client echoes it in `X-CSRF-Token` on
   authenticated state-changing calls. A stolen cookie alone cannot mutate state from a
   cross-site form.
5. **No account enumeration.** Unknown email and wrong password return the same
   `E-AUTH-INVALID` after the same Argon2 work; password-reset requests always return 202,
   and the lookup/insert/mail work runs after the response so latency does not reveal
   whether the address exists.
6. **Argon2id** (m=64 MiB, t=3, p=4), 128-bit salt per password, minimum 10 characters, a
   small static common-password block list, and a rejection when the password equals the
   email local part. No composition rules.
7. **Tokens for email verification and reset** are single-use, hashed at rest, expiring
   (48 h verify, 1 h reset); reset requires a verified email and revokes every session.
8. **Email** goes through an `EmailSender` seam: dev in-memory sink, SMTP (STARTTLS), or
   Resend. Tests use the sink and never touch the network. SMTP STARTTLS uses a
   certificate-verifying context (`ssl.create_default_context()`), not smtplib's
   verification-disabled default. The dev sink is refused in `cluster`/`prod` (the boot
   disables auth loudly) so a misconfiguration cannot silently swallow verification and
   reset mail. A delivery failure is logged and does not roll back a completed signup (the
   resend action is an F2 follow-up).
9. **Rate limits** per endpoint family on the salted, daily-rotating IP hash of the
   **proxy-observed** client address (`X-Real-IP`, else the last `X-Forwarded-For` hop, else
   the socket peer). The first XFF element is client-controlled through the edge nginx
   (`$proxy_add_x_forwarded_for` appends), so it is never used for limiting. The limiter is
   in-memory, matching the existing abuse limiter and the single-replica P0 deployment.
10. **Deletion** hard-deletes every user-scoped row (sessions, identities, tokens, progress,
    events, bookmarks), unlinks devices (`device.user_id = NULL`), and leaves only an
    anonymised `users` tombstone (`deleted+<id>@invalid`, no name/class) plus an `audit_log`
    entry. Export returns the student's own data and no hashes/tokens; when the 2,000-event
    window truncates, the payload says so (`progress_events_total`,
    `progress_events_truncated`) instead of dropping rows silently.
11. **Device pseudonymity stays.** `device_pseudo_id` remains the guest anchor, consent stays
    per device, and the voice session token is unchanged. Register/login may attach a device
    to the account; guests never need an account to read, practise, or talk to the tutor.
12. **Admin remains separate** (ADR-0026): the single-admin bearer Secret is not replaced by
    student sessions, and no `staff` account is created by these endpoints.

## Consequences

Easier: cross-device progress, recovery, settings, and the account surfaces the product now
requires; a single credential source; no change to the voice/consent path.

Harder / accepted trade-offs:

- A second auth surface to operate (email deliverability, reset abuse, session table growth).
- The in-memory limiter is per process; a multi-replica deployment must move it to Postgres
  or Redis **before** scaling out.
- Google userinfo over TLS is trusted instead of verifying the `id_token` signature against
  JWKS; both are fetched directly from Google with a token issued to this client.
- A Google-created account can set a password from a live session without re-entering a
  password (there is none yet). A stolen session already grants account access; a future
  "sensitive action re-auth" step can tighten this.
- A student who registered with a password but never verified the address, then signs in with
  Google, loses that password credential and is prompted to set a new one (the pre-hijack
  trade-off: proof of address ownership beats an unproven password).
- Verification/reset mail failures do not fail the API call; the resend endpoint is not in
  F0 and is tracked for F2.

Monitor: reset/verify send failures, rate-limit hits on auth families, tombstone count,
session-table size, and Google callback error codes.

## Revisit trigger (measurable)

- **Any multi-replica backend** → replace the in-memory auth limiter with a shared store.
- **DPDP guardian-consent decision** → add verified-guardian flow on the ADR-0007 seam before
  scaling minors beyond the current posture.
- **Passkeys/WebAuthn** become a product requirement → add a `passkey` provider row rather
  than a fourth identity concept.
- **Email deliverability or abuse** metrics breach the agreed SLO → move to a dedicated
  transactional-email provider decision (Resend adapter already exists).

## References

- `docs/backend/adr/0007-identity-device-pseudonymity.md` (device pseudonymity retained)
- `docs/backend/adr/0026-admin-auth.md` (admin stays separate)
- `tmp/full-frontend/REQUIREMENTS.md` §3.5, §6, §8.1, §8.4, §9.1, §9.2
- `docs/backend/db-spec.md` §4.18; `docs/backend/backend-spec.md` §6.4/§8.1a
- `backend/auth/*`, `backend/routes/auth.py`, `backend/routes/me.py`, migration `0003_full_frontend`
