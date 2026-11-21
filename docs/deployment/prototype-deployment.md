# Prototype deployment — small VPS (docker compose path)

Status: the non-cluster deployment path for the **prototype milestone** (2026-11-19,
branch `cloud/w5-deploy-readiness`). It deploys the **product runtime** — frontend
nginx + core-backend monolith (web shell, voice loop, personalized learning) +
Postgres 16 — behind an edge TLS proxy on a single host. It does **not** replace
the decided K8s stack: `k8s/` and `docs/deployment/kubernetes.md` are untouched,
and every choice here defers to the locked decisions in `docs/deployment/README.md`.

| Fact | Value |
|---|---|
| Compose file | `docker-compose.prod.yml` (project name `zivon-prod`) |
| Env template | `.env.prod.example` → copy to `.env.prod` (never committed) |
| Edge TLS | Caddy (`--profile edge`) **or** Cloudflare Tunnel / a host reverse proxy in front of `127.0.0.1:8080` |
| Scope served | Class 9/10 Physics (content complete), the full consumer frontend, auth, practice/speaking/tests, SWOT, personalized learning (`/app/personalized`) |
| Out of scope here | content-factory Jobs, llm-manager node, admin dashboard, evals CronJobs — build-time/cluster pieces (§ 9) |

Why a compose path at all: the prototype milestone needs a **working product for
product-market-fit testing** (AGENTS.md), not a cluster. The K8s path optimizes
for the factory and long-lived cluster services; a PMF test needs one cheap host
that serves real Indian students over HTTPS with a real voice loop on real
phones. This path reuses the exact images, the exact nginx config, and the exact
migration command the cluster uses, so nothing here forks the product.

## 1. Topology

```
                Internet
                   │  HTTPS :443 (TLS terminates HERE, only here)
        ┌──────────▼──────────┐
        │  edge               │  Caddy (--profile edge, docker/caddy/Caddyfile)
        │  (ACME cert)        │  — or — Cloudflare Tunnel / host Caddy / nginx
        └──────────┬──────────┘
                   │  plain HTTP → 127.0.0.1:8080 (or web:8080 in-network)
        ┌──────────▼──────────┐
        │  web (frontend)     │  zivon-frontend image, nginx-unprivileged :8080
        │  static site +      │  serves ./frontend snapshot + /audio/
        │  reverse proxy      │  proxies /app /login auth paths /v1/ /api/ /voice/
        └──────┬──────────────┘
               │  http://core-backend:8000 (same upstream name as the cluster)
        ┌──────▼──────────────┐         ┌─────────────────────────┐
        │  core-backend       │         │  postgres (16.6-alpine) │
        │  FastAPI monolith   │────────▶│  127.0.0.1:5432 (host)  │
        │  /v1 /v1/admin      │  :5432  │  zivon-db-data volume   │
        │  /app web shell     │         └─────────────────────────┘
        │  /voice/ws + PL     │
        └─────────────────────┘
        volumes: zivon-runs (logs fallback/artifacts),
                 zivon-personalized-index (RAG index)
```

- One origin end to end: the browser talks only to the edge; `docker/nginx.conf`
  (the SAME file as the cluster) owns every path→backend routing decision, CSP
  header set, cookie pass-through, and the `/voice/` WebSocket upgrade. Nothing
  here forks `docker/nginx.conf` — that is a hard rule (web-shell.md §6).
- Edge TLS is the **locked posture** (`docs/deployment/README.md`): Zivon
  services serve plain HTTP and never implement TLS themselves.
- All three service ports bind `127.0.0.1` on the host — only the edge is
  publicly reachable. `127.0.0.1:5432` exists so `psql`, `pg_dump`, and the
  assessment import script work from the host; it is not reachable off-host.

## 2. Host requirements

| Item | Minimum | Notes |
|---|---|---|
| OS | Ubuntu 22.04/24.04 LTS (Debian 12 fine) | any distro with Docker Engine + compose v2 plugin |
| CPU | 2 vCPU | the monolith is slim (no torch/pdfplumber/playwright); the brain is remote (ADR-0017) |
| RAM | 4 GB | postgres ≈ 256 Mi, backend ≈ 256–512 Mi (cluster `k8s/27` resources), nginx < 50 Mi, headroom for builds |
| Disk | 20 GB | images ≈ 1.5 GB total (backend ~350 MB, frontend ~55 MB, postgres ~250 MB, caddy ~50 MB) + DB growth + backups; the 3.8 GB factory image is NOT pulled here |
| Network | inbound 80 + 443 (ACME HTTP-01/TLS-ALPN) | only for the `edge` profile; Cloudflare Tunnel needs no inbound ports |
| Docker | Engine ≥ 24 + `docker compose` v2 | `docker compose version` must print v2.x |
| Users | non-root sudo user; `docker` group | never run the stack as root |

Region/data-residency note: the prototype host placement follows the same
question as the cold storage decision (ADR-0004 / Q-L1): child-adjacent data is
minimized and the DB holds accounts/progress (data-classification.csv C-classes).
Keep the host and backups in a jurisdiction you can defend with counsel before
scaling past the PMF test; the DB is the only state that matters (§ 7).

## 3. DNS & TLS (two supported shapes)

**Option A — VPS + Caddy edge (recommended for PMF testing; chosen path).**

1. Buy/create the domain (e.g. `zivon.example.com`) and add an **A/AAAA record**
   pointing at the VPS IP. One record, no proxy in front of it (a Cloudflare
   proxied record changes ACME behavior — use Option B instead).
2. Set `ZIVON_DOMAIN=zivon.example.com` and `ZIVON_ACME_EMAIL=...` in `.env.prod`.
3. Open inbound 80 + 443. Caddy issues and renews the Let's Encrypt certificate
   automatically (HTTP-01 + TLS-ALPN) into the `caddy-data` volume.
4. `docker compose --env-file .env.prod -f docker-compose.prod.yml --profile edge up -d`

**Option B — Cloudflare Tunnel (no open ports; the challenge-demo shape,
`docs/specs/voice-agent/latency-budget.md` measured through it).**

1. Cloudflare proxied DNS record for the subdomain.
2. Install `cloudflared` on the host, `cloudflared tunnel login`, create a tunnel,
   and route the hostname to `http://127.0.0.1:8080` (the `web` service's
   localhost binding). TLS terminates at Cloudflare's edge — consistent with the
   locked posture; the origin hop stays inside the tunnel.
3. Run the stack WITHOUT `--profile edge`. Do not run both Caddy and cloudflared
   on the same host ports.

**Non-negotiable either way:** the public origin MUST be HTTPS. Browsers grant
microphone access only in a **secure context** — without HTTPS the voice dock
cannot work on any real device (`docs/deployment/README.md`, HTTPS posture).
Set `ZIVON_APP_BASE_URL=https://<domain>` to the SAME origin; email links and
the Google OAuth redirect are built from it, and `ZIVON_AUTH_COOKIE_SECURE`
defaults to `Secure` in prod (cookies would be dropped on an http origin anyway).

If you front the edge with a host-level reverse proxy other than Caddy, keep it
a dumb TCP/HTTP pass-through to `127.0.0.1:8080`: the CSP/security-header sets
and the WebSocket upgrade are owned by `docker/nginx.conf`, and tests assert
them (web-shell.md §9) — adding a second header layer invites drift.

## 4. Env setup

```bash
# on the VPS, as a non-root sudo user
git clone https://github.com/architgore050/zivon.git && cd zivon
git checkout 06b00d41d064b73f47324be83712b2866e03e7ca   # pin the reviewed SHA (the head this runbook shipped with — it is where docker-compose.prod.yml landed; 07d98a4 and earlier predate the compose path)
cp .env.prod.example .env.prod && chmod 600 .env.prod
$EDITOR .env.prod     # fill every REQUIRED value; placeholders only in git
```

Fill, in order (the full contract is annotated in `.env.prod.example`):

| Group | Variables | Required? |
|---|---|---|
| Posture | `ZIVON_APP_BASE_URL` (`https://…`), edge: `ZIVON_DOMAIN` + `ZIVON_ACME_EMAIL` | REQUIRED |
| Database | `POSTGRES_PASSWORD` (DB name/user default to `zivon`) | REQUIRED secret |
| Session | `ZIVON_SESSION_TOKEN_KEY`, `ZIVON_IP_HASH_SALT` (`python3 -c "import secrets; print(secrets.token_hex(32))"`) | REQUIRED secrets — boot refuses without them in prod |
| Admin | `ZIVON_ADMIN_TOKEN` (single-admin bearer, ADR-0026) | required for admin routes; empty = honest 503 |
| Google OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI=<origin>/auth/google/callback` | optional until Google sign-in is enabled |
| Email | `ZIVON_EMAIL_BACKEND=smtp|resend` + the matching `ZIVON_SMTP_*` or `ZIVON_RESEND_API_KEY`, `ZIVON_EMAIL_FROM` | REQUIRED — the dev mail sink is refused in prod |
| Gemini tutor | `ZIVON_VOICE_GEMINI_API_KEY` | required for a live voice loop; empty = honest text-path degradation |
| Gnani voice | `GNANI_PRISMA_API_KEY`, `GNANI_TIMBRE_API_KEY` | required for a live voice loop; empty = honest degradation |
| Personalized route | `ZIVON_PERSONALIZED_BASE_URL` (OpenCode OpenAI-format URL), `ZIVON_PERSONALIZED_API_KEY`, then flip `ZIVON_PERSONALIZED_TURN_ENGINE_ENABLED=true` | optional until PL teaching is enabled; enabling with an incomplete route makes boot REFUSE (§7.3) |

Secret-name mapping: this file IS the compose-path equivalent of the K8s Secret
registry (`docs/deployment/secrets.md`) — `zivon-voice-env` → the session/voice/
Gnani variables, `zivon-db-env` → `POSTGRES_PASSWORD`, `zivon-admin-auth` →
`ZIVON_ADMIN_TOKEN`, the personalized route → `ZIVON_PERSONALIZED_*`. Same key
names, so the rotation runbook there applies unchanged (rotate the value in
`.env.prod`, then `docker compose ... up -d core-backend` to restart the
consuming container; jobs pick values up on next run).

`ZIVON_DB_URL` and `ZIVON_LOG_DSN` are **derived** by the compose file from the
`POSTGRES_*` values — never set them here (one source of truth for the DB
password). Validate the interpolated stack before any boot:

### 4.1 Founder-credential-blocked live paths (status 2026-11-21)

Two flows are implemented and tested with mocked seams but cannot be verified
live until the founder fills the matching values in `.env.prod` (names only
here — the values are runtime secrets):

- **Live Google OAuth E2E — BLOCKED** on `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
  and `GOOGLE_REDIRECT_URI=<origin>/auth/google/callback`. Until then the routes
  degrade honestly (`/v1/auth/google/start` → `503 E-SERVICE-UNAVAILABLE`, the web
  login page hides the Google button) and email+password is the only working
  sign-in. Mocked-provider tests are green; no live Google sign-in is claimed.
- **Production email delivery — BLOCKED** on `ZIVON_EMAIL_BACKEND=smtp|resend`
  plus the matching `ZIVON_SMTP_*` values or `ZIVON_RESEND_API_KEY` (and
  `ZIVON_EMAIL_FROM`). Until then verification/reset mail would refuse to boot
  in prod (`dev` sink is refused in `cluster`/`prod`), so these must be set
  before any real deployment. Adapter + mocked-transport tests are green; no
  production delivery is verified yet.

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config
```

Forbidden in `.env.prod` (refused or posture-breaking): `ZIVON_ENV=dev` (the
compose file hard-sets `prod`; dev would silently fall back to an in-memory
sqlite DB), `ZIVON_EMAIL_BACKEND=dev`, `ZIVON_SPEAKING_MOCK=1`,
`POSTGRES_HOST_AUTH_METHOD=trust` (dev-only; password auth only here).

## 5. Boot, migrations, and content import

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d postgres
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d core-backend   # runs `migrate` first, gates on it
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d web
# edge: add --profile edge (Option A) or configure cloudflared (Option B)
```

- **Migrations** run as a one-shot service — the exact cluster command
  (`python -m db.migrate upgrade head`, `k8s/26-backend-migrate-job.yaml`,
  ADR-0016): `0001 → … → 0005_personalized_learning`, single head, expand/
  contract only. `core-backend` starts only on
  `service_completed_successfully`; a failed migration is loud and leaves the
  previous containers untouched. Migrations are forward-only in operation:
  there is no sanctioned downgrade on prod data (reversal = restore a backup,
  § 7). To re-run after a code pull: `up -d core-backend` again (the migrate
  service re-runs; a completed chain is a no-op).
- **Assessment packs** (practice/speaking/tests content, W4): import from a repo
  checkout on the host — the script is the only write path into the DB
  (`docs/backend/runbooks/assessment-import.md`):
  ```bash
  ZIVON_DB_URL="postgresql://zivon:<POSTGRES_PASSWORD>@127.0.0.1:5432/zivon" \
    python3 scripts/import_assessment_packs.py --dry-run   # verify first
  ZIVON_DB_URL="postgresql://zivon:<POSTGRES_PASSWORD>@127.0.0.1:5432/zivon" \
    python3 scripts/import_assessment_packs.py
  ```
  (Host Python needs the backend requirements: `pip install -r
  backend/requirements.txt`. Re-runs are idempotent upserts keyed by stable ids.)
- **Generated lesson content** ships with the repo: the committed `frontend/`
  snapshot (hand-maintained shell + published Class 9/10 pages in EN/HI/
  Hinglish) is bind-mounted at the nginx html root. Refresh = `git pull` +
  `docker compose -f docker-compose.prod.yml restart web`. Generated pages are
  never baked into images (repo rule); a new publish goes through
  `scripts/publish-frontend.sh` on the build machine, lands in git, and the VPS
  pulls it.
- **Personalized-learning RAG index** (PL2): build on the host from the repo,
  then copy into the backend volume:
  ```bash
  python3 scripts/build_personalized_index.py            # → runs/personalized-index
  docker compose --env-file .env.prod -f docker-compose.prod.yml \
    exec core-backend mkdir -p /app/personalized-index
  docker compose --env-file .env.prod -f docker-compose.prod.yml \
    cp runs/personalized-index/. core-backend:/app/personalized-index/
  ```
  A missing index degrades retrieval to the marked lexical fallback — it never
  breaks the teach loop into a silent failure.

## 6. Smoke tests (run after every deploy)

```bash
# 1. containers green (migrate must be Exited(0); others Up/healthy)
docker compose --env-file .env.prod -f docker-compose.prod.yml ps

# 2. static edge + frontend
curl -sS https://<domain>/healthz                 # "ok" (nginx probe, via edge → web)
curl -sSI https://<domain>/                       # 200 + no-store HTML
curl -sSI https://<domain>/courses/10/physics     # 301 → /class-10-physics/
curl -sSI https://<domain>/class-10-physics/      # 200 (Class 10 lesson shell live)

# 3. backend readiness through the origin (NOT the raw port)
curl -sS https://<domain>/v1/health               # ok + db ok (/readyz semantics)
curl -sS -o /dev/null -w '%{http_code}\n' https://<domain>/app      # 303 → /login?next=/app (guest guard)
curl -sS -o /dev/null -w '%{http_code}\n' https://<domain>/login   # 200 (F2 screen)

# 4. direct liveness on the host (debug; never public)
curl -sS http://127.0.0.1:18085/healthz           # {"ok": true, ...}
curl -sS http://127.0.0.1:18085/readyz            # {"ok": true, "db": "ok"} — 503 = fix before traffic

# 5. voice WS reaches the monolith (headers only; a real turn needs Gnani+Gemini keys)
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: c2bva2V5' https://<domain>/voice/ws

# 6. headers on an app page (no-store, noindex, CSP)
curl -sSI https://<domain>/app | grep -iE 'cache-control|content-security|x-robots'
```

Pass bar: (1) green, (2) static 200s, (3) `/v1/health` reports `db ok`, (4)
`readyz` 200 — a 503 `db: boot_failed` means the backend booted without its DB
(it stays alive and refuses traffic by design), (5) a WS-shaped response (101,
or the app's close/403 semantics — NOT a plain 404/timeout), (6) headers present.
Then one manual check on a real phone: open a Class 10 lesson over HTTPS, grant
mic permission (secure-context proof), and speak one doubt — the honest end-to-end
acceptance for this deployment (AGENTS.md prototype definition). The
personalized teach route answers `503 E-PL-MODEL-DOWN` until the PL route is
configured — that is the documented honest state, not a failure.

Where signals land: stdout JSON events from every service (`docker compose logs
core-backend | python -m json.tool --json-lines` style inspection), and the
`log_events` Postgres store (the `ZIVON_LOG_DSN` sink) — the same contract as
the cluster (`docs/deployment/observability.md`). The admin dashboard and
Prometheus/Grafana stay out of this path (§ 9).

## 7. Backups

The DB is the only irreplaceable state (learner accounts, progress, the
`log_events` store, quota counters). Named volumes (`zivon-runs`,
`zivon-personalized-index`, Caddy state) are rebuildable artifacts — document
how they were built instead of snapshotting them.

- **Nightly logical backup** (cron on the host) — matches the cluster's
  base-backup intent (`k8s/infra.env` `BASE_BACKUP_CRON_SCHEDULE`, 21:00 UTC):
  ```bash
  # one-time: create the target dir INSIDE the volume (pg_dump makes the file,
  # not parent dirs — without this the first cron run fails)
  docker exec zivon-prod-postgres-1 mkdir -p /var/lib/postgresql/data/backups
  0 21 * * * docker exec zivon-prod-postgres-1 \
      pg_dump -U zivon -d zivon -Fc -f /var/lib/postgresql/data/backups/zivon-$(date -u +\%Y\%m\%d).dump
  30 21 * * * find /var/lib/docker/volumes/zivon-prod_zivon-db-data/_data/backups -name '*.dump' -mtime +13 -delete
  ```
  (Check the actual container name with `docker compose ps`; the backup lands
  INSIDE the db-data volume — also copy the newest dump off-host after the run,
  e.g. `docker compose cp` to a second disk or an object store.)
- **Honest RPO/RTO:** nightly dumps ⇒ effective RPO ≤ 24 h, RTO ≈ 30 min
  (restore + boot + smoke). There is **no WAL shipping/PITR on this path** —
  exactly like the cluster today (`k8s/25-postgres.yaml` explicitly runs
  `archive_mode=off`; backend-spec ADR-0006's PITR guarantee is a recorded gap,
  not a hidden one). If a PMF test ever needs sub-hour RPO, wire WAL archiving
  to object storage first (backend-engineering skill §2), on both paths.
- **Restore drill:** rehearse before real students arrive — the timed procedure
  is `docs/deployment/restore-drill.md` (`RB-12`); on this path it reduces to
  ```bash
  docker compose ... down
  docker volume rm zivon-prod_zivon-db-data && docker volume create zivon-prod_zivon-db-data
  docker compose ... up -d postgres
  cat zivon-YYYYMMDD.dump | docker exec -i zivon-prod-postgres-1 pg_restore -U zivon -d zivon --clean --if-exists
  docker compose ... up -d && re-run the § 6 smoke tests
  ```
  (A fresh volume has no `backups/` dir — re-create it per § 7 before the next
  nightly cron.)
  An untested backup is not a backup. Time it, record RPO/RTO, fix what hurt.
- **Rotation:** rotate secrets on the cadence in `docs/deployment/secrets.md`
  (Gemini 90 d, DB password quarterly, session key/IP salt on compromise only —
  rotating them invalidates sessions / abuse-counter continuity).

## 8. Rollback

| Failure | Action |
|---|---|
| Bad image (backend/frontend) after a pull | Images are pinned (`zivon-backend:0.1.0`, `zivon-frontend:0.1.6` — same tags as the cluster manifests). Roll back by checking out the previous SHA (`git checkout <prev-sha>`), `docker compose build && up -d core-backend web`. Containers restart on the old image; the data volume is untouched. |
| Bad migration already applied | **No downgrade path.** Forward-only (Alembic discipline, backend-engineering skill §1): restore last night's dump if the schema/data is unusable, then fix forward. This is why migrations gate the backend on `service_completed_successfully` — a failed migrate never replaces the running containers. |
| Bad env change | `git checkout .env.prod` is impossible (untracked) — keep a host-side copy (`cp .env.prod /root/backups/.env.prod.bak-<date>` outside the repo) and restore it; `docker compose up -d` re-reads env only on container recreation. |
| Config broken at boot | The backend refuses to boot on silent defaults (missing `ZIVON_ENV`/strict secrets → exit before listening). `docker compose ps` shows the restart loop; `docker compose logs core-backend` names the exact missing variable. Fix `.env.prod`, recreate. |
| Host reboot leaves the backend degraded | The docker daemon restarts `restart: unless-stopped` containers individually on boot and does NOT re-evaluate `depends_on` ordering — core-backend can come up before Postgres accepts connections, latch its recorded `db boot_failed` state (no in-process retry, same posture as the cluster), and keep serving `/readyz` 503 even after Postgres is healthy. After any host reboot: `curl http://127.0.0.1:18085/readyz`; if it says `db: boot_failed`, `docker compose --env-file .env.prod -f docker-compose.prod.yml restart core-backend` once `postgres` is healthy, then re-run § 6. |
| Whole-host loss | New host: § 2→5 in order, restore the newest dump (§ 7), re-copy the PL index, repoint DNS. Everything else is in git or rebuildable. |

The rollback story in one sentence: images are pinned and rebuilt from git SHAs,
migrations never half-apply to a running stack, and the DB dump is the reversal
for anything data-shaped.

## 9. What this path deliberately does NOT cover

| Cluster piece | Why it stays cluster-only |
|---|---|
| Content factory Jobs (`k8s/10/20`), `runs/`+PVC resume, HuggingFace cache | build-time batch workload with a 3.8 GB image; generation runs on the build machine and publishes into `frontend/` (§ 5) |
| llm-manager node (`k8s/16`) + inference-router | the factory's OpenAI-format model path; product runtime calls Gemini/Gnani/OpenCode directly per the routing table (AGENTS.md "Current stack") |
| Admin dashboard (`k8s/23/24`), test/eval/log/sync CronJobs (`k8s/50–53`) | operator plane; run it on the cluster or a dev machine, pointing at this DB via `ZIVON_LOG_DSN`/`ZIVON_ADMIN_TOKEN` if needed |
| Cold storage sync (B2/R2, `zivon-cold-*`) | storage-tiering §5 identities and jobs; the prototype DB backup above is the interim durability story |
| Prometheus/Grafana, log-retention CronJob | monitoring is the cluster decision (`docs/deployment/README.md`); compose-path ops = § 6 checks + `log_events` queries |

Free-tier vs small-VPS tradeoff (why the VPS path is the recommendation for PMF):

| Dimension | Free tier (platform hosting / cluster free credits) | Small VPS + Caddy (~$6–12/mo class) |
|---|---|---|
| HTTPS origin | platform TLS, often a shared/foreign domain — breaks the same-origin cookie + voice WS assumptions | your domain, one origin, secure context guaranteed |
| Voice loop (wss + long turns) | platform proxies frequently cap WS idle/timeout | nginx's 600 s `/voice/` timeout passes through unchanged; Caddy adds none |
| Persistence | ephemeral or gated volumes — the DB (C-classes, accounts) is the risk | named volume + your own backup cron |
| Data residency story | provider-controlled region | you pick the region; one jurisdiction to defend |
| Cost control | $0 but quota/opaque limits | fixed bill; Gnani credits + Gemini tokens remain the real spend (capacity-and-cost.md) |
| Ops burden | near-zero until it isn't | one host to patch, one compose file, § 6–8 |

The honest recommendation: **small VPS for the PMF test**, free-tier only for
screenshots/throwaway demos — the prototype's acceptance (real students, real
voice, saved progress) needs the origin, persistence, and timeout control only
the VPS path gives.

## 10. Security notes

- **Secrets never enter git, images, or this doc** — values live only in
  `.env.prod` (chmod 600, untracked) on the host; the committed template holds
  placeholders only. A committed secret is a leak: rotate first (secrets.md),
  then fix the leak.
- **Least exposure:** only the edge binds public ports; postgres/backend bind
  `127.0.0.1`. Images run non-root (backend UID 1000, nginx UID 101) matching
  the K8s posture; the backend image carries no test suites (deployment doc's
  test-containerization policy).
- **Rate limiting:** `docker/nginx.conf` keeps the audio `limit_req` (ST-04)
  and the app keeps its IP-keyed buckets (backend-spec §8.3, salted
  daily-rotating IP hash). The limiter is in-memory — valid for the single
  replica this path runs; multi-replica would need a shared store (ADR-0029
  revisit trigger). For public-traffic abuse on the edge itself, Cloudflare's
  edge WAF/rate limiting is the cheapest layer in front (founder decision if
  used — record it).
- **Children's data posture is unchanged:** deletion cascade, consent gating,
  DPDP runbooks (`docs/deployment/deletion-runbook.md`) all live in the
  monolith and apply here verbatim; this path adds no new processor.
- **Patch the host:** `unattended-upgrades` on; `docker compose pull` +
  rebuild on security bumps; the images' freshening layers (apt/apk) only fire
  at build time — a rebuild is what picks up CVE fixes, so rebuild + redeploy
  monthly or on a trivy/gitleaks alert, not just on code changes.
- **Known gaps on this path (honest list):** no WAL/PITR (§ 7), no
  Prometheus/Grafana or alerting (§ 9 — watch § 6 checks manually), no
  multi-host redundancy (single host is the accepted PMF risk), TLS at Caddy
  needs inbound 80/443 (Option B removes the inbound surface).
