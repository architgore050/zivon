# Gap register — Wave S2 (SP6-GAPS, 2026-11-09)

Audit base: `main` at WS1 merge `add64e7` (five S1 specs + ADR-0017–0028 on main). Every row below has severity + owner; buildable gaps carry a contract-level mini-spec. Doc-level inconsistencies fixed in-patch are marked **FIXED** (see the commit `docs(backend): SP6 delta audit fixes…`).

| ID | Severity | Owner | Status | One-line |
|---|---|---|---|---|
| GAP-001 | blocker | EX6-CICD (manifests EX0) | OPEN | Secrets: K8s Secret names + creator + rotation; nothing in manifests/images |
| GAP-002 | major | EX6-CICD | OPEN | Promotion `main → prod` with security checks has no workflow (AGENTS.md requires it; CI only covers `main` PRs) |
| GAP-003 | blocker | EX1-VOICE | OPEN | Voice WS auth/abuse: protected side of the login-free product (rate limits, token, consent) — build contract frozen |
| GAP-004 | major | EX0-BACKEND | OPEN | Backup/restore drill is a design claim (RB-12/DRILL-01), not an operable runbook |
| GAP-005 | blocker | EX0-BACKEND (log TTL EX3) | OPEN | Retention/TTL as real CronJobs (voice_turn 7 d, log TTLs) — reconcile to 53 |
| GAP-006 | major | EX3-OBS + founder-manual | OPEN | Error alerting thresholds + founder on-call path (dashboard banner + `log_events` only today) |
| GAP-007 | major | EX0-BACKEND | OPEN | DPDP guardian-deletion runbook: 8-step pipeline exists; intake/SLA/verification procedure missing |
| GAP-008 | blocker | EX2-TRANS (fallback EX0) | OPEN | Single upstream: factory + translation both depend on OpenRouter via the llm-manager node — fallback plan missing |
| GAP-009 | major | EX6-CICD + founder-manual | OPEN | Demo-day ops: load rehearsal, demo-profile tranche switch, rollback, content-version check |
| GAP-010 | major | EX5-FRONT + EX6-CICD | OPEN | Domain/DNS/HTTPS + static hosting for localized variants (`/hi/`, `/hi-Latn/`, P1 locales) — hosting open by design |
| GAP-011 | minor | EX5-FRONT | OPEN | SEO discoverability: hreflang, sitemap/robots, JSON-LD, OG — verify SP5 seo-plan coverage; child-privacy guardrail |
| GAP-012 | major | EX0-BACKEND | OPEN | Content rollback: `publish-frontend.sh` git-history rotation has no tested rollback procedure |
| GAP-013 | minor | EX3-OBS | OPEN | EVT-ID reconciliation: SP3 `EVT-F01…F12` vs SP5 `EVT-<verb>` — SP3 names canonical |
| GAP-014 | blocker | EX0-BACKEND | OPEN | Core-backend buildability: verify backend-spec §6.1/§6.3 + db-spec cover every endpoint/table (incl. C3, eval, log tables) |
| GAP-015 | blocker | EX8-NARRATION | OPEN | Narration stage has no spec folder — speakable-block rules, availability flag, audio manifest mini-spec in §GAP-015 |
| GAP-016 | major | EX5-FRONT (doctrine founder-manual) | OPEN | Frontend §R reconciliation: provisional EL remap, CSP `connect-src 'self'` scoping, §10.12 drift guard |
| GAP-017 | blocker | EX6-CICD (EX0/EX3/EX4/EX5 implement) | OPEN | k8s numbering: plan reservations 17–18/21–22/23–24/25–28/29–30/51–53 vs backend-spec legacy — single map before any EX applies manifests |
| GAP-018 | major | founder-manual | OPEN | Credit calibration: exact Gnani + Gemini prices (A-01/A-05) and demo-profile numbers are still [ASSUMPTION] |
| GAP-019 | major | founder-manual | OPEN | Voice-dock doctrine §10.12: founder authors; if absent the agent guard halts dock UI work (AGENTS.md + TIMELINE Day 9) |
| GAP-020 | minor | EX7-GAPS / post-challenge | OPEN | Post-challenge backlog: LiveKit (`livekit-plugins-gnani`), OTel full stack, Loki, per-user admin identity, in-cluster Gemma GPU serving |

---

## GAP-001 — Secrets management (blocker) · owner EX6-CICD (manifests EX0, values founder)

**What is missing.** AGENTS.md + `docs/deployment/` require secrets runtime-only (env / K8s Secrets), never in images/manifests/workflows — but no consolidated registry exists. Today `k8s/infra.env` documents `zivon-factory-env` (OpenRouter key, shared by factory + llm-manager node). Gemini API key, Gnani keys, DB creds, B2/R2 creds, session-token key, IP-hash salt, admin secret have no named home.

**Mini-spec (contract, for EX6 to implement + document):**
- Secret objects to exist (names fixed, values never committed):
  | Secret | Keys (names only) | Created by | Consumed by |
  |---|---|---|---|
  | `zivon-factory-env` (exists) | OpenRouter key | founder | factory Job, llm-manager node |
  | `zivon-voice-env` | `GNANI_PRISMA_API_KEY`, `GNANI_TIMBRE_API_KEY`, `ZIVON_VOICE_GEMINI_API_KEY`, `ZIVON_DB_URL`, `ZIVON_SESSION_TOKEN_KEY`, `ZIVON_IP_HASH_SALT` | EX0 manifests, founder values | core-backend monolith (incl. `voice/`) |
  | `zivon-db-env` | `POSTGRES_PASSWORD` | EX0 | Postgres + monolith |
  | `zivon-cold-writer` / `-deleter` / `-restore` | B2/R2 keys (3 identities, storage-tiering §5) | EX0 | sync worker / deletion / restore (least-privilege split preserved) |
  | `zivon-admin-secret` | single-admin bearer (ADR-0026) | EX3 | dashboard v0 |
- Manifests mount via `envFrom` / `envFrom.secretRef`; no `env.value` secrets, no `docker-compose` defaults.
- Rotation = redeploy of the consuming Deployment (keys read at pod start, gotcha 18); expiry/rotation date recorded in the deployment runbook (EX6).
- EX6 documents the exact `kubectl create secret generic` commands (names/keys only) in `docs/deployment/`; CI stays key-free (`secrets` job green).

## GAP-002 — Promotion pipeline `main → prod` (major) · owner EX6-CICD

**What is missing.** AGENTS.md: “`main` → `prod` only via the promotion pipeline, which includes security checks.” The only workflows today are `ci.yml` (PR/push to `main`) + `codeql.yml`. No promotion workflow exists; `prod` is a stale branch at the old pre-Stage-2 base.

**Mini-spec:**
- New `.github/workflows/promotion.yml` (`workflow_dispatch` + tag `v*`): build images from `main`, run security checks (gitleaks `secrets`, trivy `CRITICAL,HIGH`, pip-audit `deps`, CodeQL triage), then open/merge the promotion PR `main → prod` (founder approves; never direct push).
- `prod` deploys only from the promotion tag (same `--network=host` image ritual + `apply-k8s.sh` context); rollback = redeploy previous tag.
- EX6 owns the workflow; no other EX edits `ci.yml`/`promotion.yml` (CI requests via manifest `integration_notes`).

## GAP-003 — Voice WS auth/abuse (blocker) · owner EX1-VOICE

**What is missing.** Backend-spec §8.3 freezes the numbers; EX1 has no code. The product is otherwise login-free — the WS side must not silently become the open relay.

**Mini-spec (from backend-spec §8 + SP1 ws-contract §1–§6 — do not re-decide):**
- Auth: `session_token` = HMAC-signed `{session_id, device_pseudo_id, iat, exp(12 h)}`; carried as `?session_token=` on WSS connect (backend-spec §8.1) **and** as `session.start.session_token` (SP1 ws-contract — EX1 supports both ingress shapes, same validator). Invalid → close 4401. No cookie, never in logs/URLs beyond the query param.
- Consent gate (server-side, §8.2): WSS connect + `audio.chunk`/`typed.doubt` blocked with `E-CONSENT-REQUIRED` unless latest `consent_record.action = granted`; re-consent on version bump (`E-CONSENT-STALE`).
- Rate limits (§8.3, `[ASSUMPTION]` until submission-week tuning): api 30/min; ws 10 connects/min + 1 concurrent/session + 10 cluster-wide; events 12 batches/min; reports 5/min; DELETE /data 3/min — all keyed on salted daily-rotating IP hash (HMAC, ≤72 h, never raw IP). Breach → `429 E-RATE-LIMIT` / WS close 1013 + backoff hint. nginx `limit_req` covers static + ST-04 audio (100/min static, 60/min audio).
- Credit guard (NEED-009, hooks H1–H4) is enforced *before* the brain call (§8.4); an in-progress turn is never cut.

## GAP-004 — Backup/restore drills (major) · owner EX0-BACKEND

**What is missing.** Design gives RPO ≤ 5 min / RTO and runbooks RB-01…RB-12, plus DRILL-01 (one timed cold-restore drill before Gate D). No operable drill procedure (who/when/how-verified) exists.

**Mini-spec:** `docs/deployment/restore-drill.md` (EX0): monthly RB-12 + one P0 DRILL-01 before Gate D; steps = quiesce writers → restore latest `zivon-db` backup to scratch namespace → smoke (boot, `voice_turn` read, guard counter) → re-delete verification (tombstoned rows stay tombstoned) → tabletop breach walk-through; sign-off recorded in `docs/logs/`. Failure of the drill blocks Phase 3 done, not the demo.

## GAP-005 — Retention/TTL CronJobs (blocker) · owner EX0-BACKEND (log class EX3)

**Mini-spec:** one CronJob bundle `k8s/53-sync-cronjobs.yaml` (plan reservation 51–53; backend-spec `55-` renumbered at SP6) with P0 rows: `ttl-voice-turn` (7-day hard delete, `voice_turn`), `ttl-coverage`, `ttl-abuse-bucket`, `rollup-daily-stats`, `ttl-telemetry`, `sync-nightly`, `base-backup` (storage-tiering §6.3). History limits (not `ttlSecondsAfterFinished` inside `jobTemplate`, gotcha 12). `log_events` TTLs (30 d hot / 365 d cold per ADR-0025) are EX3-owned rows in the same bundle. Backoff: Jobs stay `backoffLimit: 0` semantics where resumption matters; factory Job (`k8s/20`) stays manual-only and is not named here.

## GAP-006 — Error alerting + on-call (major) · owner EX3-OBS, on-call founder-manual

**What exists.** SP3 defines `instrumentation-map.csv` (62 rows), alerting-minimum = dashboard banner + alert events; no paging integration.

**Mini-spec (EX3):** thresholds are rows in the map (`severity`/`error_class` closed vocab): CRITICAL (e.g. `dashboard.auth_unconfigured`, `privacy.subject_deleted` breach) → dashboard banner + `log_events` CRITICAL event; WARNING (e.g. `log.store_fallback`, rate-limit spikes) → dashboard error feed. No PagerDuty/email/Telegram in P0 (P1). **Founder-manual:** who watches the dashboard during demo day, and the escalation path (founder phone → SSH/`kubectl` → rollback per GAP-009). Recorded as a founder runbook line, not a code feature.

## GAP-007 — DPDP guardian-deletion runbook (major) · owner EX0-BACKEND

**What exists.** Design: 8-step deletion pipeline (storage-tiering §6) + `delete_subject(session_id)` (SP3 logging-api) + tombstone verification. No intake procedure.

**Mini-spec (EX0, `docs/deployment/deletion-runbook.md` + API-A9 parity):** intake (guardian request via admin surface) → identity check via `guardian_ref` seam (no account created) → pipeline run (per-class purge C1–C20, B2/R2 delete, `runs/logs` scrub, vector/embedding purge) → tombstone ledger write (`deletion_receipt`) → response within DPDP clocks (Q-L2 counsel item; clocks live as `[ASSUMPTION]` until counsel rules). The runbook is also the breach-notification path anchor (RB-11).

## GAP-008 — Single OpenRouter upstream + Evon hosting (blocker) · owner EX2-TRANS (fallback EX0)

**What is missing.** Factory + translation both call the isolated llm-manager node (`k8s/16`) whose upstream is `https://openrouter.ai/api/v1` (`stealth/crouton-alpha`). If OpenRouter is down/slow, both builders stall. Translation additionally needs Evon v3.3 capacity (cold build ≈ 1.17M tokens/topic/locale, SP2 §6) — host undecided (open-weight self-host vs managed).

**Mini-spec (EX2 + EX0):**
- Upstream order (config, not code): 1) OpenRouter (current); 2) local Strata inference server (existing `docker/inference-router.Dockerfile` bridge, `ZIVON_BASE_URL` swap + rollout-restart per gotcha 18); 3) for translation only: deferred queue (checkpointing makes stranded runs zero-loss — TMs + per-block checkpoints resume on recovery).
- `ZIVON_BASE_URL` swap is a founder-run rollout-restart (not a Job); probes: node `/healthz` + one 1-token generation before a factory/translation trigger.
- Evon v3.3 host is EX2’s Phase-0 decision (RunPod/Modal/HF/local quantized quantified); GPUBudget line in capacity-and-cost is updated at that point (translation tokens are the only Evon spend; zero Gnani credits).

## GAP-009 — Demo-day ops (major) · owner EX6-CICD + founder-manual

**Mini-spec (EX6 documents; founder executes):** (a) load rehearsal plan — judge-traffic shape from A-07 (≤500 sessions/day) run against `demo` guard profile the day before; (b) demo-profile switch — API-A4 toggles `guard_profile` (`normal` ↔ `demo`, logged to `audit_log`; demo = bounded relaxed caps, GAP-018 numbers); (c) rollback plan — bad publish → `publish-frontend.sh` re-run against previous git tag, plus image redeploy to previous tag (promotion rollback, GAP-002); (d) content-version rotation check — `git log frontend/` shows the live tag, catalogue `generated_at` matches the landed publish commit.

## GAP-010 — Domain/DNS/HTTPS + localized hosting (major) · owner EX5-FRONT + EX6-CICD

**Current posture (locked).** Edge TLS only; pages host-agnostic; mic-demo needs secure context. Domain/hosting decision deliberately open (TIMELINE ⬜). No localized (`/hi/`) hosting path exists.

**Mini-spec:** hosting lands as (domain DNS → edge TLS → nginx `frontend/` PVC mirror) via EX6 `docs/deployment/kubernetes.md`; localized variants are static subtrees under the same Deployment (`frontend/courses/<id>/<slug>/<locale>/` + `/hi/` catalogue entries) served by the existing `zivon-frontend` PVC — no new Service. Until the domain lands, the NodePort dev parity (30080) is the demo link.

## GAP-011 — SEO/discoverability (minor) · owner EX5-FRONT

SP5 `seo-plan.md` covers per-locale hreflang pairs, sitemap + robots generation, JSON-LD, OG cards. **SP6 check:** child-privacy guardrail holds — no third-party trackers/analytics, no external fonts/CDNs at runtime (G2/CSP), OG/sitemap generators are offline + idempotent from `ZIVON_PUBLIC_BASE_URL`. EX5 implements + CI-tests (`test_sitemap`, `test_robots`, `test_hreflang_pairs` per perf-budget-tests.md pattern); field CWV data stays lab-only unless the founder signs the Search Console privacy call (Q8).

## GAP-012 — Content rollback (major) · owner EX0-BACKEND

`scripts/publish-frontend.sh` mirrors the `zivon-frontend` PVC into repo `frontend/`; a re-publish wholesale-replaces a topic’s previous version (git history is the rotation). No tested rollback exists.

**Mini-spec (EX0):** rollback = `git checkout <prior-tag> -- frontend/` + re-publish mirror; runbook line in `docs/deployment/` + `factory/runbook.md`: verify live page hash vs `manifest.json`, confirm catalogue `generated_at`, re-run frontend smoke. RB-07 (bad publish → flip `live_pointer`) is the content-side twin.

## GAP-013 — EVT-ID reconciliation (minor) · owner EX3-OBS — RESOLVED AT WS1, recorded

SP3 `EVT-F01…F12` (frontend-originated sub-range, `frontend.*` names) vs SP5 `EVT-<verb_noun>` (§9). **Decision (WS1):** SP3 names + `EVT-Fxx` ids are canonical for the `logging_manager` contract; SP5’s catalogue rows are client-side trigger notes that map 1:1 to `EVT-Fxx` event names when EX5 instruments `zivon.js` (no dual taxonomy in code). SP3 OQ-9 closes on this mapping; EX3 owns the map file.

## GAP-014 — Core-backend buildability (blocker) · owner EX0-BACKEND

**Question asked.** Is `backend-spec.md` §6.1/§6.3 + `db-spec.md` implementable as written by EX0 with zero existing monolith code?

**Finding.** Yes, with three table addenda EX0 must carry as Alembic migrations (no spec rewrite needed — these are the execution backlog):
1. Translation C3 tables (`glossary_term`, `translation_memory_entry`, `block_translation`, `ui_string`, `locale_fallback`) per SP2 §5.1.
2. Eval tables (`eval_run`, `eval_card_result`, `eval_defect_sample_result`, `eval_human_edit`, `eval_kid_session`, class C4) per ADR-0027.
3. `log_events` (day-partitioned Postgres, ADR-0025) owned by EX3, created by EX0’s migration chain.
Every endpoint card (API-001…009 + admin A1…A10) already traces to a table/column in db-spec/db-traceability; no endpoint is orphaned. EX0 adds the three addenda tables + the `voice_turn` TTL hook (GAP-005) and records them in the traceability CSV in the same PR (repo rule: docs in the same PR as the code).

## GAP-015 — Narration buildability (blocker) · owner EX8-NARRATION

**What exists.** C-051 (pre-generated narration, never metered), ST-04 (`GET /audio/{course}/{block}.{lang}.{hash}.opus`, immutable, `max-age=31536000`), A-15 budget (≤1,500 build narration cap) — scattered across features/backend-spec. No narration spec folder.

**Mini-spec (EX8 implements; this row is the contract):**
- **Speakable-block rules (per block type):** `text` → full prose; `animation`/`simulation` → `spec.title` + `spec.description` + readout strings from `page.js` (never JS code); `diagram` → `svg_texts` only; `check` → question + options (no answers read aloud until revealed); metadata (`b-00-meta`) → title + objectives. All other `spec` fields are excluded.
- **Availability flag:** `manifest.json` field `narration: {available: bool, lang, hash}`; frontend probes `HEAD /audio/...` or reads the flag; `available=false` → INF-089 disabled copy (button hidden, never a broken player).
- **Audio manifest:** `i18n/<locale>/narration/<block_id>.<hash>.opus` + per-locale `narration-manifest.json` `{block_id, lang, hash, chars, duration_ms}`; content-hash path = immutable cache key; republish bumps the hash (old audio stays addressable until eviction).
- **Budget:** build-time Timbre v3.0 calls only, ≤ A-15; runtime never synthesizes narration (zero student-time credits).

## GAP-016 — Frontend §R reconciliation (major) · owner EX5-FRONT

§R (provisional EL → canonical EL) + `check_specs.py` 6× EXPECTED_ABSENT stale flags + CSP `connect-src 'self'` scoping + doctrine §10.12 guard. **SP6 position:** WS1 started §R (see `docs/specs/frontend/open-questions.md` WS1 note); the full remap of `component-inventory.csv` (33 provisional rows) is EX5 work against the canonical `ui-element-inventory.csv` (98 rows) — go/no-go is `check_specs.py` green. CSPscoped change = one line in factory CSP emission + lint sweep intact (same-origin beacon only; strict-CSP intent unchanged; founder signs). **Doctrine guard (founder note, AGENTS.md):** if `design-doctrine.md` still lacks §10.12 when EX5 reaches the dock, the agent informs the founder and halts dock UI work — never improvises the design.

## GAP-017 — k8s numbering (blocker) · owner EX6-CICD (implementers EX0/EX3/EX4/EX5/EX8)

**Conflict found.** Backend-spec legacy numbers (`35-voice`, `36-voice-service`, `45-sync`, `55-retention`, `60-admin`) vs the founder plan reservations (below). **Fixed at SP6** for the load-bearing rows (backend-spec §12 now uses the plan): voice folds into `25–28` monolith (no separate voice image, ADR-0020); sync/retention → `51`/`53`; admin router inside the monolith. Remaining EX numbering duties:

| Manifest | Owner | Reservation |
|---|---|---|
| `17–18` voice split-out ONLY if ADR-0020 criteria fire (default: unused) | EX1 | 17 `voice-deployment`, 18 `voice-service` (conditional) |
| `21–22` translator (if service) | EX2 | 21 `translator-deployment`, 22 `translator-service` (conditional; default: in-factory stages 10a–10d, no service) |
| `23–24` dashboard | EX3 | per SP3 dashboard-spec §1 |
| `25–28` core monolith + Postgres + migration Job | EX0 | 25 `postgres`+`core-backend` (lexical order), 26 `migrate` Job, 27 `core-backend` Service exposure, 28 `config` |
| `29–30` narration audio (if needed) | EX8 | 29 `narration-pvc`/`seed`, 30 `narration-service` (conditional) |
| `51` log retention / sync worker | EX3 (log) / EX0 (sync worker P1) | per GAP-005 |
| `52` evals | EX4 | `k8s/52-eval-cronjob.yaml` (SP4 §5.2) |
| `53` sync/TTL cronjobs | EX0 | per GAP-005 |

EX6 documents this map in `docs/deployment/kubernetes.md`; EX agents apply in numeric order; `20` is the factory run Job (never rename).

## GAP-018 — Credit calibration (major) · owner founder-manual

A-01 (exact Gnani credit prices from the dashboard) and A-05 (demo-profile numbers) are still `[ASSUMPTION]`. **Mini-spec:** after the first real voice sessions, founder records dashboard prices → fixes A-05 demo caps + A-15 narration budget in `capacity-and-cost.md` in the same PR as the calibration note. Until then the guard ships with the founder-config defaults (1,000/day tranche, 30/user/day, demo reserve ~40%).

## GAP-019 — Voice-dock doctrine §10.12 (major) · owner founder-manual

DCR-002: the founder authors design-doctrine §10.12 manually. The standing guard (AGENTS.md + TIMELINE Day 9) requires agents to check the doctrine before any dock UI work and to inform the founder + halt if it is still absent. **SP6 records:** SP1/SP5 designed *states and messages only* for the dock; pixels/copy are untouched. EX5 verifies §10.12 presence at dock start.

## GAP-020 — Post-challenge backlog (minor) · owner EX7-GAPS / post-challenge

LiveKit (`livekit-plugins-gnani`), full OTel stack / Loki, per-user admin identity, in-cluster Gemma GPU serving, per-locale narration expansion — none block the challenge demo. They are the Wave-E2 / post-challenge queue, assigned only if the founder pastes a GAP list to EX7 after Wave E.

---

## FIXED rows (recorded, not reopened)

| Was | Fixed where |
|---|---|
| `Prisma/Timbre v2.5` strings in README + translation specs | WS1 consistency commit + `docs(backend): SP6 delta audit…` |
| Gemma `self-hosted`/OpenAI-router wording (backend-spec, features, handoff, capacity) | SP6 delta audit commit (this wave) |
| Backend-spec §12 k8s legacy numbers (`35/36/45/55/60`) | SP6 delta audit commit (reconciled to plan reservations) |
| ADR README stuck at 16 records | SP6 delta audit commit (0017–0028 indexed) |
| SP1 missing self-review fixes (013) | WS1 (authentic patch applied after founder re-download) |
| SP5 `EXPECTED_ABSENT` now-present reconciliation start | WS1 §R note (full remap = EX5, GAP-016) |
