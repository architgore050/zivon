# Customer-readiness todo — ready-to-prototype lock-in list (2026-11-23)

**Read this before declaring the Zivon prototype customer-ready.**

The prototype is customer-ready only when:

- the four Class 10 lessons work in the free prototype path (Light, Human Eye, Electricity, Magnetic Effects),
- the free voice loop + free lesson shell works end to end,
- the basic prototype deployment is not crashed or redirecting, and
- every item left below is either done or has an honest blocker + ready-when.

This is the lock-in list for ready-to-prototype with customers + basic deployment.

## Ready criteria

- Published Class 10 lessons: Light, Human Eye, Electricity, Magnetic Effects in EN/HI/Hinglish.
- Free lesson shell: `/app/class-10-physics/*`; free voice loop: speak a doubt → hear a spoken tutor response.
- Basic deploy smoke: `curl -I https://<public-base>/app`, no 500s, frontend serves, backend up, deploy not in dev/mock.

## What is left (lock-in list)

| # | Left work | Owner | Blocker / verification | Ready when |
|---|---|---|---|---|
| M1 | Magnetic Effects lesson regen + assessment bank | founder-local | OpenCode Go route 429 (`GoUsageLimitError`); run `bash scripts/magnetic_founder_local.sh` | regen + bank merged, `python scripts/verify_magnetic_manifest.py` passes, importer dry-run has Magnetic |
| M2 | Class 10 exam/series pack | founder-local/QA | Magnetic bank above; pack is not customer-facing unless publishable | `python -m factory.exam --class 10 --require-publishable` green or explicitly blocked |
| P1 | PL5 live judge + real teach-check-adapt session | founder-local | OpenCode Go route 429 and/or `ZIVON_PERSONALIZED_*` missing | one real session recorded with timings/defects |
| D1 | Domain/DNS/host + SSH | founder | access/values missing | `curl -I https://<public>/app` + `ssh <host> true` |
| D2 | Postgres prod credentials + migration | founder/deploy | values missing/unsafe | `docker compose --env-file .env.prod config` green + `alembic upgrade-from-empty` green |
| D3 | Session/admin secrets (`ZIVON_SESSION_TOKEN_KEY`, `ZIVON_IP_HASH_SALT`, `ZIVON_ADMIN_TOKEN`) | founder | values missing | `python scripts/validate_prod_compose.py --env .env.prod` green |
| D4 | TLS/ACME email | founder | values missing | Caddy cert request works; not staging |
| O1 | Google OAuth creds + redirect URI | founder | values missing | `/sign-in/google` redirects correctly |
| E1 | Email transport (SMTP/Resend) | founder | values missing | signup/reset returns 201; no SMTP errors |
| V1 | Free voice loop customer smoke | QA/customer | Gnani keys present | real-device audio round-trip works |

## Lock-down process

- Move an item to “ready” only after the **ready-when** check passes.
- If blocked, record the exact blocker and the exact command/check that proves it later.
- Do not claim customer-ready while anything above still has unrecorded work.
