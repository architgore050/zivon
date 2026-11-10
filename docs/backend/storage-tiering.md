# Storage tiering specification — Zivon

Stage-2 systems design (2026-11-07). The home document for **where every byte lives, how it
moves, and what survives a failure**. Consumes `docs/product/backend-handoff.md` §5–6 and the
founder correction of 2026-11-07 (three distinct storage units). Machine-readable twin of §2:
[`data-classification.csv`](data-classification.csv); sync rules twin: [`sync-policy.csv`](sync-policy.csv)
(§3). Traceability rule: every class cites Stage-1 IDs or is *systems-originated* with a reason.

---

## 1. The tier model — four units, two tiers, one invariant

The founder's correction is binding: **the backend cache, the hot database, and the cold
store are three distinct storage units — never conflated.** They are formalized as four units
(glossary in `backend-spec.md` §2):

| Unit | Identity | Tier | Credentials | In the request path? |
|---|---|---|---|---|
| **U1 Backend cache** | voice-backend pod memory + PVC `zivon-cache` (narration/asset warm copies) | hot | pod service account | yes — hot reads only |
| **U2 Hot DB** | PostgreSQL 16 Deployment + Service + PVC `zivon-db`, in-cluster alongside the backend | hot | app DB role (least privilege) | yes — transactional reads/writes |
| **U3 SSD content volumes** | existing PVCs `zivon-frontend`, `zivon-sources`, `hf-cache` | hot | workload service accounts | yes — static serving + factory workspace |
| **U4 Cold store** | S3-compatible object store at a **separate provider** (own account, own credentials, own billing; region per ADR-0004) | cold | **two separate identities**: write-only/append archival writer; rarely-used privileged deleter/restore identity | **never** for hot reads — restore, archive, and origin copies only |

Vocabulary used throughout these specs:

- **System of record (SoR)** — the one authoritative place for a datum at a given time.
  Anything else is a cache or a backup. Every class in §2 names exactly one SoR.
- **Cold-verified** — object uploaded → read-back checksum matched → catalogue row stamped
  `cold_verified_at`. Only cold-verified objects may ever be evicted or aged out of hot tiers.
- **Eviction invariant (hard rule, applies to every class whose only copy is on U1/U2/U3):**
  an object may be removed from a hot unit only if (a) a cold copy exists, (b) a read-back
  checksum matched, (c) the catalogue row records `cold_verified_at`, and (d) retention/pinning
  rules permit eviction. Eviction writes `evicted_at` in the same transaction as the removal
  intent; a later read of an evicted object transparently fetches from cold and may re-warm.
  **Nothing is ever evicted while the cold provider is unreachable.**
- **Failure-domain rule:** U1–U3 share the cluster's failure domain; U4 is deliberately
  outside it. Anything whose loss would be unrecoverable must have its durable home in U4
  (or git, for C16). The cluster dying must not destroy: published content, consent ledger,
  credit ledger, DB (via WAL archives), or run evidence.

Watermarks (NFR-21): volume usage **alert > 70 %**, **evict-eligible cache > 75 %**,
**page > 90 %** `[ASSUMPTION]`.

---

## 2. Data classification — 20 classes, every dimension filled

Derivation: Stage-1 retention table (handoff §6) + ENT? entities + the 18-EVT catalogue +
founder corrections (C2 narration stored, C19 IP buckets, three-unit separation). Classes
C1–C4/C14–C16 cover the existing factory/site; C5–C13, C17–C20 cover the new voice backend.
Two tables render the same rows as `data-classification.csv` (CSV is authoritative if they drift).

### 2.1 Identity, sensitivity, retention

| Class | What it is | Stage-1 source IDs | SoR | Mutability | Sensitivity | Retention (min → max) | Phase |
|---|---|---|---|---|---|---|---|
| C1 | Published lesson bundle (HTML/JS/CSS/SVG + manifest + `courses.js` per topic·class·version) | NEED-001/002; INF-009…052; ENT?-PageMeta | cold origin + git snapshot (`frontend/`); live copy on `zivon-frontend` PVC | immutable per version (content-hash key) | public | forever → forever | P0 |
| C2 | Pre-generated narration audio (Opus per block·lang·page-version; C-051 adopted) | NEED-017; INF-018…048 spoken; ENT? narration_asset | cold origin; DB asset row; live copy on `zivon-frontend` PVC | immutable (`text_hash` key) | public (lesson text, no student data) | forever per version → forever | P0 |
| C3 | Translations & language bundles (per-block strings + glosses + mt/reviewed flags; SC-01) | NEED-016; ENT?-LanguageBundle; INF-014…017, 049, 087, 088 | hot DB while editing; joins C1 at publish | mutable until published, then immutable | public | forever per published version | P1 |
| C4 | Content-factory run evidence (`runs/`: request.json, stage artifacts, status.json, run_report.json) | INF-100/101; ENT?-RunStatus; NEED-015 read side | SSD `zivon-sources` during run; catalogue row in hot DB | append-only per run | internal (model payloads, no student data) | last 10 runs hot → forever in cold | P0 (mirror) |
| C5 | Live session state (current turn, anchor, sim values, partials, flags) | ENT?-Session runtime; INF-030, 032, 062, 064, 069 | U1 in-process memory only | mutable, 24 h idle TTL | pseudonymous | 24 h idle → 24 h idle | P0 |
| C6 | Session transcripts (final student utterance + tutor reply per turn) | ENT?-VoiceTurn; INF-060/061; NEED-004/006/007 | hot DB `voice_turn` rows — **never cold** (A-02 minimization decision) | append-only | **child-data (flagged)** | 0 → **7 d hard delete** | P0 |
| C7 | Raw child audio (mic frames) | INF-062 transient; T11; F-ADD-VOI-01 AC-6 | **NOT STORED** — transient buffer streamed to STT, discarded | n/a | **child-voice (highest)** | 0 → 0 (never persisted) | P0 rule |
| C8 | Device profile & settings (lang, pace, Guide/Tell, data-saver, onboarding flags, memory_local) | ENT?-DeviceProfile; INF-063, 065, 077…083; NEED-018 | **client localStorage** (the device is the SoR); server mirror post-challenge only | mutable (local) | device-local (not server data) | until user clears | P1 (mirror post-challenge) |
| C9 | Consent ledger (granted/declined/withdrawn per device·version·guardian_flag) | ENT?-ConsentRecord; INF-072…076; EVT-013 record side; NEED-012 | hot DB append-only; daily immutable snapshot to cold | append-only (superseded, never edited) | **child-data (legal evidence)** | until deletion request → until deletion request | P0 |
| C10 | Telemetry events (18-EVT catalogue, schema-validated, pseudonymous, no free text) | ENT?-TelemetryEvent; EVT-001…018; NEED-010 | hot DB (recent) → cold archive | append-only | pseudonymous/operational (per-EVT privacy class) | 30 d hot min → 90 d hot then archived forever | P0 (90-d delete) / P1 (archive) |
| C11 | Usage & credit ledger + guard counters (STT s / TTS chars / LLM tokens — counts only, never content) | ENT?-CreditLedger; INF-097/098; EVT-007/008; NEED-009 | hot DB (`guard_counters` hot rows + `credit_ledger` append-only) | append-only ledger + mutable counters | operational (no content, no PII) | 90 d ledger → 90 d hot then monthly cold archive | P0 |
| C12 | Logs / metrics / traces (structured JSON logs, Prometheus TSDB, per-stage histograms — zero transcripts/PII by rule) | systems-originated (observability per AGENTS.md + Day-8 decision) | cluster volumes / observability stack | append-only | operational — zero transcripts by rule | 7 d → 30 d logs / 15 d TSDB `[ASSUMPTION]` | P0 (Prometheus+logs) |
| C13 | Admin audit log (guard profile flips, trigger actions, report status changes, deletion completions) | systems-originated (NEED-015 AC-6; F-OPS-MET-01 logged toggle) | hot DB append-only; snapshot with C9 | append-only (hash-chained if feasible) | internal (staff actions) | 1 y `[ASSUMPTION]` → 1 y then cold snapshot | P0 (minimal rows) |
| C14 | DB backups (continuous WAL archives + daily base backup of U2) | systems-originated (durability backbone for C3, C6*, C9, C10, C11, C13, C17, C18, C20) | **cold is the primary home**; hot local staging only | immutable once archived | inherits table sensitivity (child-adjacent → encrypted before upload, A-13) | full window 30 d `[ASSUMPTION]` → 30 d rolling + monthly pinned snapshot 12 mo `[ASSUMPTION]` | P0 (WAL+base+one drill) |
| C15 | Model artifacts (Gemma 4 26B A4B weights + tokenizer) | systems-originated (Gate A outcome 2026-11-07) | GPU host disk; cold copy for rebuild | immutable per version | internal | per version → forever | P1 (GPU hosting open ops item) |
| C16 | Configuration & manifests (`k8s/`, `infra.env`, Dockerfiles, CI workflows — secrets excluded, runtime-only) | repo rule + AGENTS.md | git (repo); git remote counts as the separate provider for this class | versioned | internal — zero secrets (CI gitleaks) | forever → forever | P0 (exists) |
| C17 | Problem reports (category, page/block refs, optional child-safe text, status) | ENT?-ProblemReport; INF-104/105; EVT-014 record side; NEED-014 | hot DB until resolved + 90 d | append-only + status mutable | child-safe free text (no solicitation, no PII accepted) | until resolved → resolved + 90 d | P0 (intake) / P1 (inbox) |
| C18 | Deletion requests & tombstones (device-scoped erasure records + re-delete-on-restore list) | NEED-013; EVT-018 record side | hot DB; re-delete list mirrored with C9 snapshot | append-only | pseudonymous tombstone (prevents resurrection) | forever → forever (the tombstone IS the evidence) | P0 (record + pipeline) |
| C19 | Abuse rate-limit buckets (salted daily-rotating IP-hash counters per endpoint family) | systems-originated (founder correction 3; A-12) | U1 memory + rolling hot-DB counters; **never cold** | append-only rolling | pseudonymous network attribute (raw IP never stored) | 0 → 72 h rolling `[ASSUMPTION]` | P0 |
| C20 | Session metadata (session_id, device_pseudo_id, lang, flags, started/ended, turn counts — no free text) | ENT?-Session; INF-095/096; NEED-003/015 | hot DB 30 d ops view → hard delete after nightly roll-up to daily aggregates (no pseudonyms) 12 mo `[ASSUMPTION]` | append-only + flags mutable | pseudonymous | 30 d rows → 12 mo aggregates | P0 |

*Note on C14: backups may contain rows of C6 (transcripts) inside WAL/base files. That is why
C6 itself never gets a separate cold copy — the only cold copies of transcript rows are inside
encrypted, aged-out backup files with a documented window and the re-delete-on-restore list
(§6). This is the deliberate, recorded compromise between debuggability and minimization.

### 2.2 Placement, sync, verification, eviction, deletion, restore priority

| Class | Hot placement (U1/U2/U3) | Cold placement (U4) | Sync trigger | Verification | Eviction rule | Deletion path | Restore priority |
|---|---|---|---|---|---|---|---|
| C1 | `zivon-frontend` PVC live + `zivon-cache` warm copy | **all published versions** (origin) | on publish: upload → verify → **then** flip live pointer | sha256 read-back + catalogue stamp | LRU only if `cold_verified_at` set and not pinned (live + demo lessons pinned) | version retire (state flag; git history survives) | **P0 — first** |
| C2 | `zivon-frontend` PVC + `zivon-cache` | all generated versions (origin) | on generation: upload → verify → then serve | sha256 read-back + catalogue stamp | LRU only if `cold_verified_at` set | version retire | **P0 — first** |
| C3 | hot DB (drafts) + frontend PVC (published) | published bundles (with C1) + DB backups | at publish (with C1) + DB backups | sha256 read-back; reviewer-gate flag before a language ships | none needed (small) | delete unreleased drafts on discard | P1 |
| C4 | `zivon-sources` PVC (active + last 10 runs) | completed runs archived compressed after settle delay | run completes + 24 h settle delay; nightly batch | tar + sha256 manifest; row-count check | drop archived runs older than hot window | lifecycle expiry by documented window (none planned) | P2 |
| C5 | in-memory only | **none — never synced** | none (TTL expiry) | n/a | n/a (expires) | n/a — lost-on-crash acceptable; client resumes with context | n/a |
| C6 | hot DB only | **none by design** | none — deliberately no cold copy | 7-day TTL job + NEED-013 immediate path | TTL job deletes rows | 7 d hard delete; intentionally unrecoverable after TTL (recorded) | n/a (recreate = re-ask) |
| C7 | none | none | none — never synced | storage audit: **zero audio objects in U1–U4** | n/a | n/a (nothing stored) | n/a |
| C8 | n/a (client storage) | post-challenge mirror would ride DB backups | n/a (client) | client clear action + NEED-013 server scope | n/a | client clear + NEED-013 | n/a |
| C9 | hot DB | daily snapshot + long-retention encrypted backups | on write (outbox target; P0: nightly snapshot) + daily | sha256 snapshot + row count | none (never evicted from hot) | NEED-013 pipeline + re-delete-on-restore list | **P0 — first** |
| C10 | hot DB 90 d | compressed daily partitions (JSONL) after close | nightly after day-partition closes | row count + min/max ts + checksum manifest **before** dropping hot rows | drop hot partition only after verified archive | archive lifecycle per retention; subject rows via NEED-013 re-delete list | P1 |
| C11 | hot DB (counters hot-read every turn — never sums the ledger) | monthly compressed archive | nightly (ledger); in-memory + hot row (counters) | daily reconciliation vs Gnani dashboard ≤ 2 % (AC-2) | archive then delete hot ledger rows | NEED-013 does **not** delete ledger (no subject content) — documented | P1 |
| C12 | cluster volumes / observability stack | optional compressed logs 90 d (P2) | nightly if kept (P2) | log-pipeline audit: zero transcript/PII matches | rotation by age | n/a by design (nothing personal) | P2 |
| C13 | hot DB | with C9 daily snapshot | on write (outbox target; P0: in nightly snapshot) | sha256 snapshot | none | kept as evidence even under subject deletion (staff actions are not child data) — documented | P1 |
| C14 | local staging only | **cold is the primary home** | WAL: `archive_timeout = 60 s` continuous; base: daily 02:30 IST off-peak | checksum + monthly restore drill (P0: one drill before submission) | staging purged after verified | backup ageing + **re-delete-on-restore list** for deleted subjects | **P0 — first** |
| C15 | GPU host disk | cold copy on version change | on model version change | sha256 (provider-published checksums where available) | GPU host ephemeral by design — rebuild from cold copy | delete superseded versions after new host verified | P1 (large, slow — plan RTO) |
| C16 | n/a | git remote (GitHub) | git push (developer flow) | git history + CI verification (kubeconform/kube-linter) | n/a | repo deletion rules (never commit secrets) | P0 (exists) |
| C17 | hot DB | rides DB backups only (no separate archive) | DB backups (C14) | backup checksum (C14) | removed at resolved + 90 d by retention job | NEED-013 device-scoped deletion + resolved+90 d job | P1 |
| C18 | hot DB | with C9 snapshot | on deletion completion | sha256 snapshot | none | **never deleted** (tombstone IS the deletion evidence) | P0 |
| C19 | in-memory + hot DB | none | none — rolling expiry | rolling TTL job | expires by design | expires by design | n/a |
| C20 | hot DB 30 d | rides DB backups only | roll-up nightly then delete rows | roll-up row-count reconciliation | 30-d job deletes rows after roll-up | NEED-013 device-scoped delete + 30-d job | P1 |

### 2.3 Pull-the-plug answers (per class — what survives which single failure)

The test asked per class: **if the unit dies right now, what is lost and from where is it
rebuilt?**

| Failure | Consequence | Recovery |
|---|---|---|
| **U1 pod dies** (cache/session memory gone) | live sessions drop (C5), warm caches cold | client reconnects → new session bootstrap (NEED-003); caches re-warm from U2/U3; guard counters rebuilt from hot DB rows (C11) — no credit loss beyond ≤ 1 turn |
| **U3 `zivon-frontend` PVC dies** | live site + narration gone | re-seed from cold origin copies (C1/C2 verified) or git snapshot `frontend/`; `live_pointer` in U2 says which version to serve; **RTO ≤ 4 h** (NFR-19) |
| **U3 `zivon-sources` PVC dies** | active run evidence lost mid-run | run resumes from completed stages (existing resumability); archived runs re-seed from cold (C4); worst case: re-run stages — credits, not data, are the cost |
| **U2 dies entirely (PVC + pod)** | hot DB lost | rebuild Postgres from U4: base backup + WAL replay → **RPO ≤ 5 min** (NFR-17), RTO ≤ 4 h; apply re-delete-on-restore list (C18); catalogue + pointers restored. **P0 SIMULATED (2026-11-10): no WAL replay implemented — effective RPO = last base backup (≤ 24 h)** |
| **Cluster dies** | U1+U2+U3 gone | content re-seeded from cold/git; DB from U4 backups; voice backend is stateless except via U2 — full restore ≤ 4 h; Core pages could even be served from the git `frontend/` snapshot alone |
| **U4 provider dies** | no new cold copies; restores impossible while out | serving continues from U1–U3 (nothing hot-reads cold); outbox queues uploads (alert on backlog age > 15 min); **no eviction while cold unreachable**; lifecycle/deletion jobs pause with visible backlog |
| **Gnani API dies** | voice loop down | Core path untouched (layer independence); dock shows failure states; narration (C2) is static — read-aloud keeps working |
| **GPU host dies** | tutor generation down | typed path also down (same LLM) → dock system-error + retry; Core + read-aloud unaffected; rebuild host from C15 cold copy |

---

---

## 3. Sync policy — when hot moves to cold (twin: [`sync-policy.csv`](sync-policy.csv))

Six rules. Each row: **class · trigger · mechanism · verify · on-failure · SLO · runbook · phase.**

| ID | Class | Trigger | Mechanism | Verification | On failure | SLO `[ASSUMPTION]` | Phase |
|---|---|---|---|---|---|---|---|
| **SYNC-01** | C1, C2, C3-published | artifact finalized (publish / narration generation done) | **publish gate:** outbox row in the same DB transaction as the catalogue row → uploader (multipart > 16 MB, idempotent key = content hash, bounded concurrency, retry+backoff). P0 form: synchronous upload+verify step inside the publish flow (script step, no worker) | sha256 read-back (or provider checksum — semantics confirmed for multipart at build) → stamp `cold_verified_at` → **only then** flip `live_pointer` | publish stays `reviewed` (not live); backlog alert | ≥ 99 % verified ≤ 5 min; alert if outbox backlog age > 15 min | P0 (gate) / P1 (worker) |
| **SYNC-02** | C14 | WAL segment closes or `archive_timeout = 60 s` elapses | Postgres `archive_command` → ship segment to U4 (`wal/{timeline}/{segment}`); base backup daily 02:30 IST off-peak CronJob (`pg_basebackup` → zstd → multipart). **P0 SIMULATED (2026-11-10): no real object storage wired — `backend.sync base-backup` stages the encrypted envelope locally (`base/{date}.enc`); no WAL archiving at all; restore path = `python -m backend.sync decrypt` + manual upload** | segment checksum on write; base backup checksum; **monthly restore drill** (P0: one drill before submission) | archive_command retries; if persistent: alert WAL archive lag; DB keeps running (hot unaffected) | archive lag ≤ 5 min (NFR-17 = RPO). **Not met in P0 — effective RPO = last base backup** | P0 |
| **SYNC-03** | C9, C13, C18 | on write (target: outbox) — P0: nightly 21:00 IST CronJob | export append-only tables since last snapshot → JSONL.zst + manifest (row count, min/max ts, sha256) → upload **encrypted client-side** (A-13) → immutable versioned copy. **P0 SIMULATED (2026-11-10): `backend.sync sync-nightly` stages the encrypted JSONL envelope locally (`consent-snap/{date}.jsonl.enc`); no real object storage wired; recovery = `python -m backend.sync decrypt` + manual upload/re-import** | manifest row-count + checksum read-back | retry next night; alert if 2 consecutive misses (legal evidence — escalation) | snapshot lag ≤ 24 h | P0 |
| **SYNC-04** | C10, C11 | day partition closed and older than hot window (90 d events; monthly ledger) | export → compress (JSONL) → upload date-partitioned key (`c10/dt=YYYY-MM-DD/part-NNNN.jsonl.zst`) → verify → **then** drop hot rows/partition | row count + min/max ts + checksum manifest **before** any hot delete — never drop before verified | keep hot rows, retry; if SSD pressure: alert (rows stay — SSD watermark rule yields to verification rule) | archive lag ≤ 48 h | P1 (P0 = plain 90-d delete, no archive) |
| **SYNC-05** | C4 | run completes + 24 h settle delay | nightly batch: tar+zstd completed runs → upload + manifest; catalogue row per archive | tar checksum + file-count check | retry nightly; runs stay hot (last-10 window) | archive lag ≤ 72 h | P0 (mirror) / P1 (full) |
| **SYNC-06** | C12 | optional, P2 only | compressed logs 90 d | checksum | skip (logs are not personal data) | n/a | P2 |

Cross-cutting:

- **SCRUB-01 — scrub & drift (weekly, P1; P0 = manual spot-check):** compare `object_catalog` vs cold
  listing (missing/orphan objects), re-checksum a 1–5 %/day sample (NFR-20), alert on drift count > 0.
- **DRILL-01 — restore drill (monthly, P1):** full restore into an empty namespace, timed against RTO ≤ 4 h
  (NFR-19). **P0 minimum: one drill before submission** (founder-run, logged in `docs/logs/`).
- **Idempotency everywhere:** content-addressed keys mean a double upload is a no-op verify, not a duplicate.

---

## 4. Eviction & cache policy (U1/U3) — rule EVICT-01

1. **Watermarks (NFR-21):** alert > 70 % · evict-eligible > 75 % · page > 90 % (page = human
   intervention, runbook RB-01).
2. **What may be evicted:** only objects with `cold_verified_at IS NOT NULL` and `pinned = false`.
   **Pinned by default:** the current live version of every published topic + the demo-flow lessons
   (the Gate-C demo topics). Pinning is a catalogue column, flipped by the publish flow.
3. **Eviction order:** LRU within class C2 narration first (largest, re-warmable), then C1 warm
   copies on `zivon-cache`. U3 `zivon-frontend` live site is **never evicted** — it is the serving
   copy; its durability comes from SYNC-01 origin copies, not from eviction.
4. **Eviction transaction:** set `evicted_at` + `state='evicted'` in the same transaction as the
   file-removal intent; a later read fetches from cold (transparent re-warm, latency visible only
   to that first request).
5. **Never evict while U4 is unreachable** (invariant §1). Outbox backlog grows instead; alert
   at 15 min backlog age; SSD headroom is the bound — at 90 % the runbook is add-volume, not evict.
6. **Cache warming:** publish flow warms `zivon-cache` with the newly live version + demo lessons.

---

## 5. Cold provider selection (ADR-0004 — criteria matrix from official pages, fetched 2026-11-07)

Verified this session from official pricing/docs pages (B2 pricing page; R2 pricing + data-location
docs). Cells marked **[verify]** were not confirmable from an official page in this session —
no blog numbers used.

| Criterion | **Backblaze B2** | **Cloudflare R2** | Wasabi | AWS S3 (Mumbai ap-south-1) | GCS (Mumbai ap-south1) |
|---|---|---|---|---|---|
| S3 API compat / SDK | S3-compatible API + native SDKs | S3 API first-class | S3-compatible | native | interop XML API (partial S3 compat) |
| Storage price | **$6.95 / TB-mo** ($0.00695/GB) | $0.015/GB-mo Std; $0.01 IA | [verify — page unreachable this session] | [verify — region table not parseable this session; Std is the highest of the five] | [verify] |
| Egress | **free up to 3× monthly storage**, then $0.01/GB; free via CDN partners | **free, all classes** | [verify] | free first 100 GB/mo (all AWS), then paid | paid, high |
| Request/API cost | **Class A/B/C calls free** (PAYG); Class D $0.004/10 k, 2 500/day free | Class A $4.50/M, B $0.36/M; **free tier 1 M A + 10 M B/mo** | [verify] | per-request pricing | per-request |
| Free tier | **first 10 GB free** | **10 GB-mo + ops free tier** | 10 GB trial [verify] | none (100 GB egress only) | none |
| Min duration / size fees | **none** | none (Std); IA 30 d min | 30-day minimum storage duration policy [verify] | IA 30 d, Glacier 90 d, Deep Archive 180 d min | none (Standard) |
| Immutability | **Object Lock + native file versioning** [verify feature pages] | no Object Lock/versioning today [verify] | [verify] | Object Lock (governance/compliance) | Object Lock (V1/V2) |
| Lifecycle rules | yes | yes | yes | yes | yes |
| Durability / availability claim | eleven-nines durability (vendor) | eleven-nines durability (vendor) | eleven-nines [verify] | 11 nines / 99.99 % SLA | 11 nines |
| **India region / residency** | **none** (us-west, us-east, eu-central [verify]) | **no India jurisdiction**; Automatic placement + `apac` hint (best effort); Mumbai PoP for access | none [verify] | **yes — ap-south-1 Mumbai** | **yes — ap-south1 Mumbai** |
| Write-only credentials | application keys per-bucket with fine-grained perms (no-delete achievable) | API tokens with bucket-scoped read/write-only | [verify] | IAM (clean) | IAM |
| Provider independence from compute host | full (separate company/account/billing) | full | full | **no** if compute later lands on AWS; yes vs current minikube host | yes |
| Exit path | S3 API → swappable | S3 API → swappable | S3 API | vendor lock-in risk | interop layer |

**Decision (ADR-0004):** **Backblaze B2 primary** (lowest archive price at growth scale, free
Class A/B/C transactions — WAL streaming costs nothing, no minimum-duration traps, native
versioning + Object Lock for the backup immutability requirement, 10 GB free tier covers the
whole challenge window) **+ Cloudflare R2 as the second copy for C9/C14 monthly pinned
snapshots** (free tier, free egress, `apac` hint closest to India) — two independent providers
at zero marginal cost at our volumes. **India-residency candidates (S3 ap-south-1, GCS
ap-south1) stay open pending counsel** (A-13): until the counsel answer, child-adjacent archives
are envelope-encrypted client-side before upload to either provider, keys held in-cluster only.

**Credential model (non-negotiable):**
- **Archival writer:** B2 application key, bucket-scoped **upload+read only — no delete, no
  overwrite of existing versions** (append via unique content-addressed keys). Held by the
  sync-worker service account only.
- **Deleter/lifecycle:** separate privileged identity, used only by the deletion pipeline and
  retention jobs, offline-stored except during those runs.
- **Restore identity:** third key, read-only, held offline; loaded only by runbook RB-02/RB-06.
- Object Lock (compliance mode where supported) on the backup bucket for the retention window.
- **Encrypt-then-upload** for anything child-adjacent (C9 snapshots, C14 backups, C10 archives):
  client-side envelope encryption (AGE or AES-256-GCM + per-period data keys), key material in a
  K8s Secret outside U4. Public artifacts (C1/C2/C3) get integrity (sha256), not secrecy.
- **Key scheme:** content-addressed for immutable artifacts (`c1/{course}/{class}/{lang}/{version}/{sha}.json`,
  `c2/{course}/{class}/{block}/{lang}/{text_hash}.{voice}.opus`); date-partitioned for archives
  (`c10/dt=YYYY-MM-DD/part-NNNN.jsonl.zst`, `wal/{timeline}/{segment}`, `base/{YYYY-MM-DD}.zst`,
  `consent-snap/{YYYY-MM-DD}.jsonl.zst.enc`). **Never PII in keys.**
  **P0 SIMULATED (2026-11-10):** real prefixes/naming are the target state — what
  `backend.sync` actually writes today is `base/{date}.enc` and
  `consent-snap/{date}.jsonl.enc` under the local cold-staging dir only.
- **Provider outage:** serving continues from U1–U3; outbox queues (bounded by SSD headroom);
  no eviction; lifecycle/deletion jobs pause with visible backlog; second provider unaffected.

---

## 6. Restore & deletion

### 6.1 Restore paths (RPO/RTO per class)

| What died | Restore procedure | RPO | RTO target |
|---|---|---|---|
| U2 DB pod/PVC | provision fresh Postgres → fetch latest `base/{date}.zst` from U4 → replay WAL segments to target timestamp (PITR) → apply **re-delete-on-restore list** (C18 completed requests; rule **REDEL-01** — before the DB accepts traffic) → run Alembic migrations → flip service over | ≤ 5 min (NFR-17). **P0 SIMULATED (2026-11-10): no WAL/PITR implemented — restore = `backend.sync decrypt` of the latest base backup + manual load; effective RPO = last backup (≤ 24 h); see `docs/deployment/restore-drill.md`** | ≤ 4 h (NFR-19) |
| U3 frontend PVC | re-seed from U4 origin copies (catalogue `state='cold_verified'` filter, current live pointers from U2 or, if U2 also dead, from `courses.js` in the git snapshot) → nginx serves | 0 for published versions (publish gate) | ≤ 2 h |
| U3 sources PVC | re-seed archived runs from U4; active run resumes from completed stages (existing factory resumability) | ≤ 24 h settle window | ≤ 4 h |
| Whole cluster | new namespace → apply `k8s/` manifests (git) → restore U2 per row 1 → re-seed U3 per rows 2–3 → voice backend stateless | as above | ≤ 4 h |
| Single corrupted cold object | scrub detects → re-upload from hot copy if it still exists; else from DB/manifest reconstruction; else quarantine + alert (manual) | 0 (hot copy) | ≤ 1 day |

Drill cadence: monthly full drill (P1); **one timed drill before submission (P0)** — result
recorded in `docs/logs/`.

### 6.2 Deletion pipeline (NEED-013 — the answer to "guardian clicks clear")

Ordered fan-out, orchestrated by `voice/privacy`, each step recorded in `audit_log`:

1. Insert `deletion_request` (status `requested`) — the tombstone exists before any wipe starts.
2. **U2 rows:** hard-delete `voice_turn` (7-d rows), `session`, `telemetry_event`,
   `consent_record`, `credit_ledger` device rows? **No** — ledger has no subject content
   (db-spec §6); device row deleted last (FK cascades do most of the work); `problem_report`
   device rows deleted.
3. **U1/U3 files:** none keyed by child (no per-child files exist by design — C7 never stored,
   transcripts never file-backed). Assert via catalogue: zero objects with `subject_ref = device`.
4. **U4 objects:** privileged deleter identity removes any `subject_ref`-set objects + archives
   containing the device (C10 archives: rewrite-partition path = re-export partition minus subject,
   replace object, update manifest — P1; P0 window is 90 d hot rows only, archives absent).
5. **Caches/CDN:** nothing per-child cached (static content only) — assert, don't purge.
6. **Logs:** grep pipeline (should be empty by rule — C12 zero-PII rule); any hit = incident.
7. **Backups:** cannot edit immutable archives → the completed `deletion_request` enters the
   **re-delete-on-restore list**; archives age out within the documented window (≤ 30 d rolling +
   monthly pinned 12 mo `[ASSUMPTION]`) — worst-case full erasure completes inside the window,
   target ≤ 7 d for everything live (NFR-24), DPDP 90-day posture post-challenge.
8. Mark request `completed` with counts (response shape NEED-013) + audit row. Online wipe
   best-effort < 60 s p95; the pipeline never blocks the response.

### 6.3 Retention jobs (CronJobs — the enforcement, all idempotent)

| Job | Cadence | Enforces | Phase |
|---|---|---|---|
| `ttl-voice-turn` | nightly | 7-d transcript hard delete (C6) | P0 |
| `ttl-coverage` | hourly | 24 h idle coverage clear (C5/session.coverage) | P0 |
| `ttl-abuse-bucket` | hourly | 72 h rolling expiry (C19) | P0 |
| `rollup-daily-stats` | nightly 01:30 IST | session roll-up → `daily_stats`, then 30-d session delete (C20) | P0 |
| `ttl-telemetry` | nightly | 90-d event delete (C10, P0 form) | P0 |
| `sync-nightly` | nightly 21:00 IST | SYNC-03 + SYNC-05 (+ SYNC-04 when archives exist) | P0 |
| `base-backup` | daily 02:30 IST | C14 base backup → U4 | P0 |
| `scrub-drift` | weekly | catalogue-vs-cold diff + sample checksums | P1 |
| `archive-ledger` | monthly | C11 monthly cold archive then hot prune | P1 |
| `backup-age` | weekly | expire backups outside the documented window (privileged identity) | P1 |
| `restore-drill` | monthly (P0: one before submission) | timed full restore (NFR-19) | P0/P1 |

---

## 7. What this survives — the design claims, restated as tests

1. **Pull the plug on U3 mid-demo:** live site rebuilds from U4/git ≤ 2 h; the demo itself never
   depends on a cold read (everything demo-facing is hot + pinned).
2. **Pull the plug on U2 mid-demo:** voice turns in flight die (C5 is memory); sessions resume
   against the restored DB; **no published content, consent, or ledger row is lost** (WAL ≤ 5 min).
3. **Pull the plug on U4 for a week:** nothing in the student path changes; outbox backlog grows;
   eviction stops; alerts fire; when U4 returns, backlog drains idempotently.
4. **Delete a device today:** every live copy gone ≤ 7 d; archived copies die with their backup
   window; a restore tomorrow re-deletes it (tombstone list).
5. **Writer credentials leaked:** attacker can upload junk, cannot delete or overwrite versions
   (writer has no delete; versioning + Object Lock on backups); scrub + catalogue-vs-listing diff
   catches junk objects; quarantine state available.

---

## 8. Phase map (what gets built when)

| Capability | P0 (now) | P1 (Day-8/9 + post-challenge pilot) | Target (growth) |
|---|---|---|---|
| Publish gate SYNC-01 | synchronous upload+verify in publish flow | outbox + sync-worker Deployment | + second provider fan-out |
| WAL archiving SYNC-02 | **NOT WIRED in P0 (2026-11-10): no WAL shipping; base backup = `backend.sync` → local staged envelope** | lag metric + alert | second-region WAL copy |
| Nightly snapshots SYNC-03 | `backend.sync` → local staged encrypted envelope (`*.jsonl.enc`) | outbox-driven near-real-time | hash-chained snapshots |
| Partition archival SYNC-04 | — (90-d delete only) | day partitions + verified drop | Parquet + query-on-archive |
| Eviction §4 | watermark alerts + manual LRU (cold-verified only) | automated LRU + pinning | cache warming policy |
| Scrub / drills | one timed drill before submission | weekly scrub, monthly drill | automated + second copy verify |
| Deletion §6.2 | steps 1–2, 5–8 live (no archives yet) | archive rewrite path (step 4) | crypto-erasure evaluation |
| Retention jobs §6.3 | all P0 rows | all P1 rows | — |

