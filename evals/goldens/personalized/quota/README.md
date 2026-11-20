# Free-tier quota/abuse goldens (EV-PL-005, PL5 2026-11-19)

`scenarios.json` is the machine-readable golden for the `DET-PL05-*`
deterministic checkers (`evals/checkers/personalized_checks.py`): the six
quota/abuse scenarios of docs/specs/personalized-learning/evals.md §6 plus the
tenant-isolation, CSRF, and `next`-redirect fixtures. The probe caps inside
the scenarios are the small overrides the checkers inject through
`QuotaCaps` — the product itself reads caps from `ZIVON_PERSONALIZED_*` env
config; there is no plan/subscription/entitlement table anywhere (the
no-paywall rule, DET-PL05-NO-PAYWALL).

| Scenario | Kind | Expected |
|---|---|---|
| normal | quota_reserve | allowed, state `ok` |
| warn_at_15_percent | quota_reserve | allowed, state `warn` (≤ 15 % remaining) |
| user_exhausted | quota_reserve | denied `user_turn_cap`, state `exhausted`, API `403 E-QUOTA-EXHAUSTED` |
| global_exhausted | quota_reserve | denied `global_turn_cap`, global row `exhausted`, API `503 E-QUOTA-EXHAUSTED` |
| rate_limited | rate_limit | `429 E-RATE-LIMIT` with a `Retry-After` header on the family limit |
| cache_hit | artifact_cache | second identical build costs 0 model calls and 0 quota — graded by `DET-PL03-CACHE` and the artifacts suite; the shared no-double-charge invariant is graded here (`DET-PL05-QUOTA`) |

Tenant-isolation fixture: two synthetic users (`tenant-a-canary`,
`tenant-b-canary`); every session endpoint returns `404 E-NOT-FOUND` for the
other user's ids — detail, messages, export, delete, end, turns (no existence
oracle). CSRF fixture: missing and invalid `X-CSRF-Token` are both `403
E-AUTH-CSRF` with zero rows written. `next`-redirect fixture: `//evil.example`
and `http://evil.example/x` fall back to `/app`; only same-origin paths
survive `backend.auth.service.safe_next_path`.

Synthetic ids only; no keys, no real addresses. Recorded 2026-11-19;
regenerable with `python scripts/gen_pl5_goldens.py`.
