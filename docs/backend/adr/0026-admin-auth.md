---
artifact: adr
version: "1.0"
created: 2026-11-09
status: Accepted
---

# ADR-0026: Minimal admin auth for the observability dashboard — single-admin bearer secret, HttpOnly session, fail-closed

## Status

Accepted

**Date:** 2026-11-09
**Deciders:** SP3-OBS spec agent (founder directive, Wave S1); identity model inherited from ADR-0007

## Context

The dashboard v0 (`docs/specs/observability/dashboard-spec.md`, k8s manifests 23–24) exposes operational secrets-of-a-kind: factory run statuses, error feeds, credit-tranche burn vs the 2,000-credit demo reserve, and — most sensitively — the two trigger buttons whose semantics must equal `scripts/trigger-tests.sh` and `scripts/trigger-factory-run.sh` (TIMELINE.md "Admin trigger commands"). It must be **admin-only**.

Forces:

- **The identity model (ADR-0007) is pseudonymous and learner-centric; there are no user accounts in the product** — `TIMELINE.md` explicitly puts "multi-user auth" out of scope, and admins number exactly one (the founder) plus, potentially, the teammate. Full identity machinery (users, roles, OAuth) is over-building by the repo's own "subtract first" rule.
- **The buttons are remote code execution by design** (they create cluster Jobs). Unauthenticated exposure is unacceptable even on an internal NodePort; the dashboard must also never widen the factory's manual-only rule.
- **Grafana's own auth is the gate for the infra plane** (`docs/deployment/README.md`, Decisions locked) — this ADR must give the *product* dashboard an equally explicit, equally minimal gate without depending on Grafana.
- **Secrets discipline (AGENTS.md non-negotiable):** credentials live in K8s Secrets at runtime, never in manifests/images/code.
- **Audit:** admin actions are exactly the L3 audit class in ADR-0025 — auth events must flow through `logging_manager` like everything else.

**[ASSUMPTION]** Exactly two admin principals exist this window (founder + teammate) and can share one rotation-capable secret; per-person identity for admins is post-challenge (revisit with ADR-0007's full identity work).

## Decision

**Single shared admin secret, bearer → session cookie, constant-time compare, fail-closed, fully audited.**

1. **Credential:** one random ≥ 32-byte token, stored ONLY in K8s Secret `zivon-admin-auth` (key `ZIVON_ADMIN_TOKEN`), mounted env-only into the dashboard Deployment. Rotation = replace Secret + rollout restart (gotcha 18 pattern); no other credential exists.
2. **Flow:** `GET /admin/login` (static form) → `POST /admin/login` with the token → server compares with `hmac.compare_digest` → on success sets an **HttpOnly, SameSite=Strict, Secure-at-edge** cookie (opaque random 128-bit session id, server-side session table with 12 h TTL and idle re-auth after 60 min, max 8 concurrent sessions then oldest-evicted). On failure: generic `401` (no user-enumeration surface — there is only one username anyway), a 1 s constant delay, and an L3 `dashboard.auth_failure` audit event with source IP + attempt count.
3. **Enforcement:** a FastAPI dependency guards every route except `/admin/login` and `/healthz`; unauthenticated requests get `303 → /admin/login` (browser) / `401` (API clients). Fail-closed: if the Secret is missing, the dashboard starts but returns `503` on every admin route and logs `dashboard.auth_unconfigured` (CRITICAL) — it never falls back to open access.
4. **Rate limit:** token endpoint limited to 5 failures / 15 min / source IP (in-process counter; the dashboard is single-replica), then 15 min lockout with a CRITICAL audit event.
5. **Buttons inherit script semantics, nothing more:** `POST /admin/actions/tests-now` and `POST /admin/actions/factory-run` require (a) an authenticated admin session AND (b) a second, deliberate confirmation token rendered into the form (CSRF defence: double-submit token checked server-side). They shell out to the **same scripts** (kept as the implementation behind the buttons, TIMELINE.md) — the dashboard adds no third trigger path, never schedules the factory, and every invocation is an L3 `dashboard.action_triggered` audit event (action, args, result).
6. **Transport:** TLS terminates at the edge (locked posture, `docs/deployment/README.md`); the Service is ClusterIP, the cookie is `Secure` when `ZIVON_PUBLIC_BASE_URL` starts with `https://` (set at edge), plain otherwise — the value arrives via `k8s/infra.env` line-edit.
7. **What is intentionally NOT built:** per-user accounts, password DB, OAuth/OIDC, RBAC, SSO — all post-challenge; revisit when ADR-0007's identity model grows an admin persona.

## Consequences

### Positive

- Buildable in an afternoon; the entire auth surface is ~100 lines + one Secret + tests — reviewable by the security lens with high confidence.
- Every privileged action lands in the L3 audit stream (30 d hot / 365 d cold per ADR-0025), so "who ran the factory Job" is answerable.
- Fail-closed + rate-limited + CSRF-checked covers the OWASP basics for this tiny surface without pulling an auth framework.

### Negative

- A shared secret means no per-person attribution (audit shows *that* an admin acted, not *which* human) — accepted until per-person identity exists; the secret is rotation-capable to shorten any shared-credential exposure.
- In-process rate limiting and session table are lost on pod restart (sessions drop → admins re-login; acceptable at single-replica scale).

### Neutral

- Grafana keeps its own auth for infra dashboards; two gates exist by design (infra plane vs product plane) and are cross-linked from the dashboard's "Cluster monitoring" link.
- If a teammate admin is never needed, nothing changes — the model already has zero per-principal state.

### Model Choice

| Consequence | This decision |
|-------------|---------------|
| **Build, buy, or prompt** | Build (stdlib/FastAPI-only). Buy (managed auth) ruled out: egress, cost, and a second identity system for one user; framework auth (e.g. OAuth lib) over-build for one shared secret |
| **What is now coupled to it** | Dashboard route guards, the `zivon-admin-auth` Secret name, audit event names in `logging-api.md` |
| **Operating cost accepted** | Session-table memory (≤ 8 sessions), rotation ritual on suspicion |
| **Reversal cost** | Low: swap the dependency for real identity when ADR-0007 grows an admin persona; route-guard seam stays |
| **What would reopen this** | A second service needing admin auth beyond the two buttons, a non-trivial admin team, or any requirement for per-person attribution |

## Alternatives Considered

### HTTP Basic auth

Rejected: browsers cache credentials for the session with no logout, no lockout, no CSRF-free form flow, and the token would ride every request header (larger leak surface in logs/proxies). The cookie flow is barely bigger and strictly safer.

### Grafana as the dashboard's gate (proxy in front)

Rejected: couples the product dashboard's availability and auth policy to the Grafana install and its ingress shape; the locked decision scopes Grafana to infra metrics. Cross-link instead.

### No auth on a ClusterIP-internal dashboard ("not reachable anyway")

Rejected: the buttons create cluster Jobs; defense-in-depth is cheap here and the threat model includes anyone on the LAN / a future public ingress created by accident.

## References

- `docs/specs/observability/dashboard-spec.md` (routes, buttons, session rules)
- `docs/specs/observability/logging-api.md` (`dashboard.*` audit events)
- ADR-0025 (audit retention), ADR-0007 (identity model), ADR-0011 (pseudonymous IDs)
- `TIMELINE.md` "Admin trigger commands" (button = script semantics), scope ladder (multi-user auth out of scope)
- `docs/deployment/README.md` Decisions locked (edge TLS; Grafana gate for infra plane)
- AGENTS.md (secrets runtime-only; env-var configuration)
