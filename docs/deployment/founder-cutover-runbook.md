# Founder cutover runbook — from nothing to a live site (2026-11-21)

Status: the plain-language, start-to-finish checklist for putting the Zivon
prototype on a rented server and making it reachable at your own HTTPS domain.
It is the "what do I actually do" companion to
[`prototype-deployment.md`](prototype-deployment.md) (the technical runbook —
that one explains WHY every choice is the way it is; this one just walks you
through it). Nothing here requires an engineer, and nothing here was executed
against real infrastructure from the build sandbox — no DNS, TLS, or SSH
cutover was attempted; every command below is yours to run at cutover time.

**How this works, in one paragraph:** you rent a small Linux server (a "VPS"
— Virtual Private Server, a rented machine in a data center), point your
domain at it (a "DNS record" — the internet's phone book), put the
configuration values the app needs into one file, install Docker (software
that runs the app as self-contained units called "containers"), and start the
app. From then on the machine serves the site over HTTPS automatically,
including the security certificate (browsers refuse microphone access to
sites without HTTPS, so this is not optional — the voice tutor needs it).

The ten steps, in order:

| # | Step | Section | Time |
|---|---|---|---|
| 1 | Rent a server + have a domain | §a | ~30 min (incl. signup) |
| 2 | Point the domain at the server (DNS) | §b | ~10 min + waiting |
| 3 | Fill `.env.prod` (the one config file) | §c | ~30–60 min (credentials) |
| 4 | One-time server prep (Docker + firewall) | §d | ~15 min |
| 5 | Get the code onto the server | §e | ~5 min |
| 6 | Start the app (validate, then `up -d`) | §f | ~10 min |
| 7 | Verify: migrations, smoke script, one real phone | §g | ~20 min |
| 8 | Set up + verify nightly backups | §h | ~30 min |
| 9 | If something breaks: troubleshooting / rollback | §i | as needed |
| 10 | Confirm which values are still missing | §j | checklist |

Sections §a–§j are ordered; do them in order and do not skip §b (starting the
server before DNS is ready can burn the certificate issuer's retry limits).

---

## §a. What to rent and choose

**One server ("VPS").** A small one is enough — the prototype serves a Class
10 Physics site, a login system, and the voice loop, not a video pipeline.

| Item | What to pick | Why |
|---|---|---|
| Provider | any reputable VPS seller (DigitalOcean, Hetzner, AWS Lightsail, or an Indian provider such as E2E Networks) | any Linux VM works; pick one with a region you can justify for learner data (prototype-deployment.md §2) |
| Size | 2 vCPU, 4 GB RAM, 20 GB disk | matches prototype-deployment.md §2; ~US$6–12/month class |
| OS | **Ubuntu 24.04 LTS** (22.04 also fine) | the commands below are written for Ubuntu |
| SSH key | create one and use it to log in (the provider's setup wizard does this) | safer than a password |
| What NOT to rent | a Kubernetes cluster, a managed database, object storage | the compose path runs its own database; you can add those later if ever needed |

**One domain.** Any registrar (the shop where you buy domain names —
Namecheap, GoDaddy, Cloudflare, BigRock, etc.). The exact name is your
decision; this document writes `zivon.example.com` as the placeholder —
replace it with your real domain everywhere.

- **If you will use the recommended setup (Caddy on the server — Option A of
  prototype-deployment.md §3):** when you add the DNS record in §b, create it
  **DNS-only** (some dashboards call this "grey cloud"). Do NOT enable the
  proxy/"orange cloud" option on that record — a proxied record changes how
  the certificate is issued and breaks the default path.
- **If you prefer no open ports at all (Cloudflare Tunnel — Option B):** you
  instead proxy the record through Cloudflare and install `cloudflared` — see
  prototype-deployment.md §3 Option B. This runbook's steps assume Option A;
  Option B changes §b and §f's last command only.

---

## §b. Point the domain at the server (DNS)

DNS is the internet's address book. You need ONE entry saying "the name
`zivon.example.com` lives at the IP address of my server".

1. Find the server's IP address — it is on your provider's dashboard
   (something like `203.0.113.42`; IPv6 looks like `2001:db8::8a2e:370:7334`).
2. In your registrar's DNS panel, create the record(s):

| Type | Name | Value | TTL | Notes |
|---|---|---|---|---|
| A | `zivon` (or `@` for the bare domain) | the server's IPv4 address | 300 | required |
| AAAA | `zivon` | the server's IPv6 address, if it has one | 300 | optional |

3. Wait for it to spread ("propagate"). Check from your laptop:

```bash
dig +short zivon.example.com        # should print the server IP
# or, without dig:  nslookup zivon.example.com
```

**Do not go to §f until `dig` answers with your server's IP.** The
certificate issuer (Let's Encrypt — the free authority that issues HTTPS
certificates) refuses to issue more than a handful of failed certificates per
hour per domain; starting the server before DNS is ready wastes those
attempts and can lock you out of certificates for an hour. Low TTL (300
seconds) means future changes spread in ~5 minutes.

---

## §c. Fill `.env.prod` — the one configuration file

The app reads all its settings and secrets from environment variables (named
values, e.g. `ZIVON_DOMAIN=zivon.example.com`). On the server they live in a
single file, `.env.prod`, which you will create in §e. This section is the
fill-in sheet: what each value is and where it comes from. **That file is
secret — never paste its contents into a chat, an issue, or a commit.**

Create three groups of values on your laptop first (a plain text note is
fine); you will paste them into `.env.prod` in §e.

### c.1 Values you generate yourself (no third party needed)

Run this on any machine that has Python 3 — it prints a long random string.
Run it once per value (every run gives a different string):

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

| Variable | What it is | How to make it |
|---|---|---|
| `POSTGRES_PASSWORD` | the database's password | `python3 -c "import secrets; print(secrets.token_hex(16))"` — keep it letters/digits only (characters like `@ : /` would break the connection string built from it) |
| `ZIVON_SESSION_TOKEN_KEY` | signs login session cookies | `token_hex(32)` command above |
| `ZIVON_IP_HASH_SALT` | salt for anonymous abuse counters | `token_hex(32)` command above |
| `ZIVON_ADMIN_TOKEN` | the admin-API password (single admin) | `token_hex(32)` command above |

### c.2 Values only you (the founder) can provide

| Variable | What it is | Where it comes from |
|---|---|---|
| `ZIVON_DOMAIN` | your site's name | your decision (§a); e.g. `zivon.example.com` |
| `ZIVON_APP_BASE_URL` | the full public address of the site | `https://` + the same domain, e.g. `https://zivon.example.com` — must start with `https://` and match `ZIVON_DOMAIN` exactly |
| `ZIVON_ACME_EMAIL` | the address certificate-expiry notices go to | your email |
| `ZIVON_EMAIL_BACKEND` | how the app sends mail: `smtp` or `resend` | your choice (see below) |
| `ZIVON_EMAIL_FROM` | the sender address on outgoing mail | e.g. `Zivon <no-reply@your-domain>` (your domain) |
| `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | the "Sign in with Google" credentials | Google Cloud Console: create/select a project → "OAuth consent screen" → "Credentials" → "Create credentials" → "OAuth client ID" → type **Web application**. Optional until you enable Google sign-in; the site works with email+password without it |
| `GOOGLE_REDIRECT_URI` | where Google sends users back | exactly `https://your-domain/auth/google/callback` (fill once §b's domain is final) |
| `ZIVON_SMTP_HOST`, `ZIVON_SMTP_PORT`, `ZIVON_SMTP_USER`, `ZIVON_SMTP_PASSWORD` | mail-server settings — **only if `ZIVON_EMAIL_BACKEND=smtp`** | your email provider's "SMTP settings" page (host like `smtp.gmail.com`, port `587`, plus an app-password the provider issues) |
| `ZIVON_RESEND_API_KEY` | mail-API key — **only if `ZIVON_EMAIL_BACKEND=resend`** | a resend.com account → API keys (Resend is an email-delivery service; it also needs your domain added as a sender) |

Mail is **required in production**: the app refuses to start in the deployed
mode without a real mail transport, because verification and password-reset
emails must actually send. Choose `smtp` (use an inbox you already have) or
`resend` (a purpose-built sending service) — either works; set the matching
variables and leave the other group's values as the template has them.

### c.3 Values the two voice/AI vendors give you (for a live voice tutor)

| Variable | What it is | Where it comes from |
|---|---|---|
| `ZIVON_VOICE_GEMINI_API_KEY` | the tutor's "brain" (Google Gemini API) | Google AI Studio → "Get API key" |
| `GNANI_PRISMA_API_KEY` | speech-to-text (Gnani) | your Gnani dashboard |
| `GNANI_TIMBRE_API_KEY` | text-to-speech (Gnani) | your Gnani dashboard |

The site and lessons work without these; without them the voice dock
degrades honestly to a text path (documented behavior, not a failure).

### c.4 Do NOT set these (derived / forbidden)

- `ZIVON_DB_URL`, `ZIVON_LOG_DSN` — the deployment file builds them from
  `POSTGRES_*` automatically. Setting them again creates two sources of truth.
- `ZIVON_ENV=dev`, `ZIVON_EMAIL_BACKEND=dev`, `ZIVON_SPEAKING_MOCK=1`,
  `POSTGRES_HOST_AUTH_METHOD=trust` — all refused in the deployed mode
  (prototype-deployment.md §4).

Everything else in the template keeps its default — you only fill REQUIRED
and founder-owned values. The machine-checkable version of this section is
`scripts/validate_prod_compose.py` (run in §f).

---

## §d. One-time server prep (Docker + firewall)

Log in to the server (`ssh your-user@<server-ip>` — the user your provider's
wizard created) and run the following. Docker is the software that runs the
app as containers; `docker compose` (the plugin) reads the repo's
`docker-compose.prod.yml` and starts everything.

**1. Install Docker Engine + the compose plugin** (from Docker's official
Ubuntu repository):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"    # lets you run docker without sudo; log out and back in once
```

Then log out and back in, and confirm: `docker compose version` must print a
`v2.x.x` line.

**2. Open exactly three doors in the firewall** (22 = your SSH login,
80 + 443 = HTTP and HTTPS — 80 exists only so the certificate can be issued
and renewed):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

**3. Turn on automatic security patches:**

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # answer Yes
```

Everything the app runs stays bound to the server's private address
(`127.0.0.1`) except the HTTPS edge — the deployment file already enforces
that (prototype-deployment.md §1); the firewall is the second lock.

---

## §e. Get the code onto the server

```bash
# on the server
git clone https://github.com/architgore050/zivon.git
cd zivon
```

`git` is preinstalled on Ubuntu 24.04; if not: `sudo apt-get install -y git`.

**Pin the release.** Check out the exact commit ("SHA" — the 40-character
commit id, e.g. `06b00d4…`) that was reviewed for release — the founder
runbook shipped with `06b00d41d064b73f47324be83712b2866e03e7ca`; use the SHA
recorded in the release/promotion PR if one is newer:

```bash
git checkout <release-sha>
```

**Create the config file** (from the committed template — placeholders only,
you fill your real values from §c):

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod      # only your user may read it (it holds secrets)
nano .env.prod           # fill every REQUIRED + founder-owned value from §c
```

---

## §f. Start the app

**1. Validate before starting** (two checks; both are read-only):

```bash
# a. the deployment file's own check — fails loudly naming any missing value:
docker compose --env-file .env.prod -f docker-compose.prod.yml config > /dev/null && echo "compose config OK"

# b. the repo's pre-boot validator (needs python3, no Docker):
python3 scripts/validate_prod_compose.py --env .env.prod
```

The second one prints a PASS/FAIL report (required values present, the domain
matching the public URL, the mail settings coherent, the HTTPS posture
intact). **Do not continue while anything prints FAIL** — the report names
the exact variable.

**2. Build and start:**

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build        # a few minutes the first time
docker compose --env-file .env.prod -f docker-compose.prod.yml --profile edge up -d
```

(`--profile edge` adds Caddy, the TLS edge that terminates HTTPS for the whole
site. Leave it off only if you chose the Cloudflare Tunnel path — §a.)

**3. What success looks like:**

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

| Container | State |
|---|---|
| `zivon-prod-postgres-1` | Up (healthy) |
| `zivon-prod-migrate-1` | **Exited (0)** — migrations ran and finished; this is correct |
| `zivon-prod-core-backend-1` | Up (healthy) |
| `zivon-prod-web-1` | Up (healthy) |
| `zivon-prod-edge-1` | Up |

**Migrations** (database-structure upgrades) run automatically before the
backend starts — the compose file's `migrate` service executes
`python -m db.migrate upgrade head` (the same command the Kubernetes cluster
uses, ADR-0016), and the backend is not allowed to start until it finished
cleanly. You never run migrations by hand. To confirm:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs migrate   # no error lines
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec postgres psql -U zivon -d zivon -c "SELECT version_num FROM alembic_version;"
# expected: 0005_personalized_learning
```

The HTTPS certificate is issued automatically the first time the edge
container starts (it needs DNS ready, §b, and ports 80+443 open, §d). The
first start is the slow one; watch it with
`docker compose ... logs -f edge` until it prints a certificate success, then
Ctrl-C.

A failed migration, or any refused boot, leaves the previous containers
untouched — nothing half-applies (prototype-deployment.md §5/§8).

---

## §g. Verify the site actually works

**1. Machine checks** (one command — all seven must PASS):

```bash
scripts/deploy_smoke.sh https://zivon.example.com
```

It checks backend health including the database (`/v1/health` with
`"db": "ok"`), the page chain, a static asset, and the voice route. Every
line prints PASS or FAIL with the reason.

**2. Log in as a human.** In a normal browser: open
`https://your-domain/login`, create an account with an email you control (the
verification mail must arrive — this is the first live proof of your §c mail
settings), verify, and land in the app.

**3. The real acceptance check — one phone, one voice turn.** This is the
honest end-to-end acceptance for the prototype (AGENTS.md): on a real phone
(use mobile data, not your office Wi-Fi), open a Class 10 lesson
(`https://your-domain/class-10-physics/`), tap the voice dock, **grant
microphone permission** (this proves HTTPS is genuinely in place — phones
only offer the mic prompt on secure sites), and speak one doubt, e.g. "why
does a pencil look bent in water?" — and hear a clear spoken answer.
Without the §c.3 voice keys the dock answers in text only (honest
degradation); with them, this is the full loop.

---

## §h. Backups — set up, schedule, and PROVE

The database is the only irreplaceable state (accounts, progress, consent
records). Everything else is rebuildable from git. The repo ships
`scripts/backup_db.sh`: it dumps the database via the running postgres
container, compresses it, and lands it **outside the repo** (default
`~/zivon-backups/`), deleting dumps older than the retention window. Any
failure exits non-zero, so a scheduler can alert on it.

**1. One manual run to prove it works:**

```bash
scripts/backup_db.sh                       # uses .env.prod, writes ~/zivon-backups/
# expect the last line:  PASS backup: /home/you/zivon-backups/zivon-db-<date>.sql.gz (…, gzip-verified)
ls -lh ~/zivon-backups/
```

**2. Schedule it nightly.** Either a cron line (simplest):

```bash
crontab -e     # add this one line:
15 21 * * *  cd /home/you/zivon && scripts/backup_db.sh >> /home/you/zivon-backups/backup.log 2>&1
```

or a systemd timer (the modern equivalent — survives and logs better):

```ini
# /etc/systemd/system/zivon-backup.service   (sudo nano)
[Unit]
Description=Zivon nightly database backup
[Service]
Type=oneshot
User=you
WorkingDirectory=/home/you/zivon
ExecStart=/home/you/zivon/scripts/backup_db.sh

# /etc/systemd/system/zivon-backup.timer
[Unit]
Description=Run the Zivon DB backup nightly at 21:15 UTC
[Timer]
OnCalendar=*-*-* 21:15:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zivon-backup.timer
systemctl list-timers            # zivon-backup.timer should appear
```

**3. Keep one copy OFF the server.** Copy the newest dump somewhere else
regularly (a second disk, your laptop, or an object store) — a backup on the
same machine dies with the machine:

```bash
scp you@server:~/zivon-backups/zivon-db-<newest>.sql.gz .    # from your laptop
```

**4. The restore drill — do it once now, then monthly.** An untested backup
is not a backup. This restores the newest dump into a THROWAWAY database
name (`zivon_restore_check`) inside the same postgres container — it never
touches live data:

```bash
gunzip -c ~/zivon-backups/zivon-db-<newest>.sql.gz | \
  docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE zivon_restore_check" \
         && psql -U "$POSTGRES_USER" -d zivon_restore_check -v ON_ERROR_STOP=1' | tail -5

# verify it is real:
docker compose --env-file .env.prod -f docker-compose.prod.yml exec postgres \
  psql -U zivon -d zivon_restore_check -c "SELECT version_num FROM alembic_version;"

# clean up:
docker compose --env-file .env.prod -f docker-compose.prod.yml exec postgres \
  psql -U zivon -d postgres -c "DROP DATABASE zivon_restore_check"
```

Time the drill. Honest numbers for this path: nightly dumps mean at most ~24
hours of data loss after a disaster (RPO), and ~30 minutes to restore and
re-verify (RTO). There is **no** minute-level recovery (no WAL/PITR) on this
path — the same recorded gap as the cluster (prototype-deployment.md §7). For
total host loss, the rebuild order is §d → §e → start postgres → restore the
newest dump into the fresh volume (the full-volume procedure is
prototype-deployment.md §7) → re-copy the personalized index (§5 there) →
repoint DNS.

---

## §i. When something breaks — troubleshooting and rollback

| Symptom | Likely cause | Fix |
|---|---|---|
| `up` fails: "port is already allocated" (80/443) | another program owns the port (a preinstalled web server) | `sudo lsof -i :80` to find it; if it is `apache2`/`nginx` from the OS: `sudo systemctl stop apache2 && sudo systemctl disable apache2`, then `up -d` again |
| `config` or the validator FAILs naming a variable | a REQUIRED value from §c is missing/empty in `.env.prod` | fill it (§c), re-run the check. The backend also refuses to boot naming the exact missing variable — `docker compose ... logs core-backend` |
| Caddy log shows ACME/Let's Encrypt errors, no certificate | DNS not propagated yet, port 80 blocked, or the record is proxied ("orange cloud") | `dig +short your-domain` must answer with the server IP; `sudo ufw allow 80/tcp`; make the record DNS-only. If you burned attempts: **wait 1 hour** (issuer rate limit) before retrying |
| Site loads but `scripts/deploy_smoke.sh` fails `/v1/health` with 503 `db: boot_failed` | the backend started before Postgres accepted connections (classic after a host reboot) | confirm postgres is Up (healthy), then `docker compose ... restart core-backend`, re-run the smoke script |
| postgres restarting / unhealthy | usually a changed `POSTGRES_PASSWORD` against an existing data volume — the password only applies on FIRST creation | check `docker compose ... logs postgres`; restore the original password in `.env.prod`, or (only if the data is disposable/restorable from a backup) wipe the volume and recreate — the destructive route is prototype-deployment.md §7's restore procedure |
| Certificate expired / renew fails | the edge could not reach port 80 for renewal | keep 80 open permanently; `docker compose ... restart edge` triggers a retry |
| Everything 502/504 through the domain | the `web` container is down | `docker compose ... ps` + `logs web`; `up -d` recreates it |

**Rollback — going back to the previous working version:**

- **Bad code update** (after a future `git pull`): check out the previous
  release SHA (`git checkout <prev-sha>`), `docker compose ... build`, then
  `docker compose ... up -d core-backend web`. Containers restart on the old
  image; **the database is untouched** by a rollback. A completed migration
  is never auto-reversed (migrations are forward-only): if the old code
  needs the old schema, that is the restore case below.
- **Bad migration already applied:** there is no downgrade — restore last
  night's dump (§h / prototype-deployment.md §7), then fix the code forward.
- **Bad `.env.prod` edit:** the file is untracked, so git cannot restore it.
  Keep a host-side copy outside the repo
  (`cp .env.prod ~/zivon-backups/.env.prod.bak-$(date +%F)`), restore it,
  then `docker compose ... up -d` (env is re-read only when containers are
  recreated).
- **When to roll back at all:** errors after a deploy that a single
  `restart` does not fix. Otherwise prefer reading logs first
  (`docker compose ... logs core-backend`) — most boot failures are one
  missing variable.

---

## §j. Founder-input checklist — what is still missing before cutover

Names only (values are runtime secrets; generate/obtain them at §c on your
machine and never paste them anywhere shared):

| # | Variable | Needed for | Status |
|---|---|---|---|
| 1 | `ZIVON_DOMAIN` | the site address + the TLS certificate | **MISSING — founder decision** |
| 2 | `ZIVON_APP_BASE_URL` | email links, OAuth redirect, cookies (`https://<domain>`) | **MISSING — follows from #1** |
| 3 | `ZIVON_ACME_EMAIL` | certificate-issuer notices | **MISSING — founder email** |
| 4 | `ZIVON_EMAIL_BACKEND` (`smtp` or `resend`) | production mail (REQUIRED in the deployed mode) | **MISSING — founder choice** |
| 5 | `ZIVON_SMTP_HOST` / `ZIVON_SMTP_PORT` / `ZIVON_SMTP_USER` / `ZIVON_SMTP_PASSWORD` | mail, if `smtp` | **MISSING — if #4 = smtp** |
| 6 | `ZIVON_RESEND_API_KEY` | mail, if `resend` | **MISSING — if #4 = resend** |
| 7 | `ZIVON_EMAIL_FROM` | the sender address on outgoing mail | **MISSING — founder confirms** |
| 8 | `GOOGLE_CLIENT_ID` | "Sign in with Google" | **MISSING — optional until enabled** |
| 9 | `GOOGLE_CLIENT_SECRET` | "Sign in with Google" | **MISSING — optional until enabled** |
| 10 | `GOOGLE_REDIRECT_URI` | Google callback (`https://<domain>/auth/google/callback`) | **MISSING — follows from #1** |
| 11 | `ZIVON_VOICE_GEMINI_API_KEY`, `GNANI_PRISMA_API_KEY`, `GNANI_TIMBRE_API_KEY` | a live voice turn | optional until voice goes live |

Self-generated on the host at cutover (not founder-provided):
`POSTGRES_PASSWORD`, `ZIVON_SESSION_TOKEN_KEY`, `ZIVON_IP_HASH_SALT`,
`ZIVON_ADMIN_TOKEN` (§c.1 commands). Optional-until-enabled: the
personalized-learning route (`ZIVON_PERSONALIZED_BASE_URL`,
`ZIVON_PERSONALIZED_API_KEY`, then flip
`ZIVON_PERSONALIZED_TURN_ENGINE_ENABLED=true`) — the teach route answers an
honest 503 until then.

---

## Honest blocked status — what this runbook cannot verify yet

Three flows are implemented and unit-tested with mocked seams, but are
**BLOCKED on founder inputs or a founder-local run** — no live verification
has been run or claimed from the build sandbox:

| Flow | Blocked on | Honest state until then |
|---|---|---|
| Live Google OAuth E2E | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (§j #8–10) | routes degrade honestly (`/v1/auth/google/start` → 503, the login page hides the Google button); email+password sign-in works |
| Production email delivery | `ZIVON_EMAIL_BACKEND` (`smtp`\|`resend`) + the matching `ZIVON_SMTP_*` values or `ZIVON_RESEND_API_KEY`, `ZIVON_EMAIL_FROM` (§j #4–7) | the deployed mode refuses to boot without a real transport (the `dev` sink is refused in prod); adapters and mocked-transport tests are green |
| The live voice turn (Gemini region-blocked from the build sandbox) | a founder-local run: the §g step-3 real-phone check on cutover day, with `ZIVON_VOICE_GEMINI_API_KEY`, `GNANI_PRISMA_API_KEY`, `GNANI_TIMBRE_API_KEY` configured | the voice path degrades to the text-only mode; no live STT→tutor→TTS turn has been verified from here |
