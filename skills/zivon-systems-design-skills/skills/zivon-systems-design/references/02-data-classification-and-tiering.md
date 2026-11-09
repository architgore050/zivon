# Data classification, SSD vs cold storage, and sync

Definitions used in the spec (state them at the top of the backend spec):
- **SSD / hot**: persistent block storage attached to the backend nodes (in Kubernetes a PersistentVolumeClaim on local/NVMe or a block volume). Low latency, limited size, tied to the compute failure domain.
- **Cold storage**: an S3-compatible object store at a **separate provider** (own account, credentials, billing, ideally region). Cheap, durable, higher latency, not in the request path for hot reads.
- **System of record (SoR)**: the one place that is authoritative for a datum at a given time. A copy elsewhere is a cache or a backup, never a second SoR.
- **Cold-verified**: object uploaded, read-back checksum matched, catalogue row updated.

## 1. Classification dimensions (one row per data class)

`class_id` · description · SoR (DB / SSD file / cold) · source INF/ENT?/EVT ids · size per item · items/day · **mutability** (immutable / append-only / mutable) · **access pattern** (hot-read / read-after-write / rare / audit-only) · **sensitivity** (public / internal / pseudonymous / personal / child-voice) · **retention** (min, max, legal basis) · **tier policy** · **sync trigger** · **verification** · **eviction rule** · **deletion path** · **restore priority** (P0 first) · owner.

## 2. Starter classes (edit to fit the product document; every row is a hypothesis)

| Class | Example | SoR | Mutability | Hot on SSD | Cold | Sync trigger | Notes |
|---|---|---|---|---|---|---|---|
| C1 Published lesson bundles | page HTML/JS/SVG/JSON per topic·class·version·language | Cold + git history of `frontend/` (repo rotates versions via git) | Immutable per version (content-hash key) | Working cache of current versions (nginx volume), LRU | Origin copy of every published version | **On publish**: upload → verify → then flip "live" | Edge/CDN in front is a cache; never SoR |
| C2 Pre-generated narration audio | TTS of static lesson text per block·language·voice·version | Cold (regenerable but costly in credits) | Immutable | Cache of hot lessons | Origin | On generation, same as C1 | Never regenerate per student; saves credits and latency |
| C3 Translations & glossaries | per-block localized specs, term glossary, review status | DB (while editing) → bundled into C1 at publish | Mutable until published | DB | In C1 bundles + DB backups | At publish + backup | Review state is a record |
| C4 Content-factory run evidence | `runs/` requests, responses, reports | SSD (PVC `zivon-sources`) during run | Append-only per run | Active run + last N runs | Completed runs archived compressed | **Run completes + settle delay (e.g. 24 h)**, nightly batch | Keep manifest row in DB for lookup |
| C5 Live session state | current turn, anchor, sim values, partial transcript | Memory (+ short TTL store) | Mutable | In-memory/Redis-like or DB row with TTL | none | none; TTL expiry | Lost-on-crash is acceptable; client can resume with context |
| C6 Session transcripts (text) | per-turn text, language, anchor ref | DB | Append-only | N days (e.g. 30) `[ASSUMPTION]` | compressed archive until retention end, **only if retained at all** | Nightly partition close + archive | Retention is a product+legal decision (T11/T5) |
| C7 Raw child audio | microphone capture | **Not stored by default** | - | optional debug capture ≤ 24-72 h, encrypted, opt-in | **never** unless explicit consent+counsel | none | Default = stream to STT and discard |
| C8 Device/guardian profile & preferences | language, speed, level, memory toggles | DB | Mutable | DB | in DB backups | with DB backups | Minimum fields; no behavioural profile by default |
| C9 Consent ledger | who consented to what, when, how verified, withdrawal | DB | Append-only | DB | long-retention encrypted backups + periodic immutable snapshot | On write (outbox) + daily | Legal evidence; never edited, only superseded |
| C10 Learning events | `EVT-…` per interaction | DB (recent) → archive | Append-only | 30-90 days hot `[ASSUMPTION]` | compressed partitions by day/month (JSONL/Parquet) | Nightly after partition closes; verify then drop hot rows | Pseudonymous id; no free-text child speech |
| C11 Usage & credit ledger | STT sec, TTS chars, LLM tokens per session | DB | Append-only | DB | in backups + monthly archive | nightly | Drives budget enforcement (hot path read) |
| C12 Logs / metrics / traces | structured logs, Prometheus, traces | SSD (observability stack) | Append-only | 7-30 days | optional compressed logs 90 days | nightly if kept | No PII/transcripts in logs |
| C13 Admin audit log | staff actions, config changes | DB | Append-only | recent | long-retention | on write + daily | Tamper-evident (hash chain) if feasible |
| C14 DB backups | base backups + WAL | cold primarily | Immutable | local staging only | **primary location** | WAL: continuous; base: daily/weekly | Object-lock or write-only creds |
| C15 Model artifacts | Evon weights, tokenizer | Model host disk | Immutable | model host | copy for rebuild | on version change | Not user data; large; slow restore - plan RTO |
| C16 Configuration & manifests | k8s/, infra.env | git | versioned | n/a | git remote | n/a | Secrets excluded - runtime only |

## 3. Sync policy - when does the SSD sync into cold storage?

State each rule in the backend spec as a row: **class · trigger · mechanism · verify · on-failure · SLO**.

1. **Event-driven write-behind (immutable artifacts: C1, C2, C4-complete).**
   Trigger: the artifact is finalized (publish / generation done / run complete + settle delay).
   Mechanism: transactional **outbox** - the same DB transaction that records the object in the catalogue inserts an `upload` job; a worker uploads with an idempotent key (content hash), multipart for large objects, bounded concurrency and retry with backoff.
   Verify: read back the checksum (or provider ETag/checksum feature - confirm semantics for multipart) → set `cold_verified_at`.
   Publish gate: for C1/C2, "live" is not set until cold-verified (otherwise the only copy sits on an SSD that can die).
   SLO: ≥ 99 % verified within 5 min `[ASSUMPTION]`; alert if backlog age > 15 min.
2. **Continuous log shipping (relational DB: C3, C6, C8, C9, C11, C13).**
   Trigger: WAL segment closes or `archive_timeout` (e.g. 60 s) elapses.
   Mechanism: archiver ships WAL to cold; periodic base backup (daily, off-peak ≈ 02:00-04:00 IST) plus retention window; verify by checksum and by **restore test** in CI/cron.
   RPO ≈ minutes; document exactly how far behind the archive may be.
3. **Time/partition-driven batch archival (append-only high-volume: C10, C6, C12).**
   Trigger: a partition (day/month) is closed and older than the hot window.
   Mechanism: export → compress → upload with manifest (row count, min/max ts, checksum) → verify row count and checksum → **then** drop the hot partition. Never drop before verification.
4. **Threshold-driven eviction of caches (C1, C2).**
   Trigger: SSD usage above the eviction watermark. Evict LRU objects only if `cold_verified_at IS NOT NULL` and the object is not pinned (current live version, demo lessons pinned). Never evict anything whose only copy is the SSD.
5. **Lifecycle expiry.** Cold-store lifecycle rules delete after retention; deletion requests trigger the deletion pipeline (`05` §4). Backups age out by documented window; a "re-delete on restore" list prevents resurrecting deleted subjects.
6. **Scrub & drift detection.** Weekly: compare catalogue vs cold listing (missing/orphan objects), checksum a sample, alert on drift. Monthly: full **restore drill** into an empty environment and time it against RTO.

### Eviction safety invariant (put in the spec verbatim in spirit)
An object may be removed from SSD only if: (a) a cold copy exists, (b) a read-back checksum matched, (c) the catalogue row records `cold_verified_at`, (d) retention/pinning rules permit eviction. Eviction itself writes `evicted_at` in the same transaction as the file removal intent, and reads of an evicted object transparently fetch from cold (and may re-warm).

### Catalogue table (core of the mechanism; adapt names)
`object(id, class_id, key, sha256, size_bytes, content_type, version_ref, created_at, ssd_path, cold_provider, cold_key, cold_verified_at, evicted_at, retention_until, pinned, subject_ref NULL, encryption_key_ref, state)` - `state` ∈ `ssd_only | uploading | cold_verified | evicted | deleting | deleted | quarantined`.

## 4. Separating the cold provider (requirement: separate service provider)

Criteria matrix for the ADR (fill from official pricing/docs at decision time):
S3 API compatibility and SDK maturity · storage price · egress and request pricing · minimum storage durations · **immutability/object lock** · lifecycle rules · stated durability/availability · **region/data residency** (India availability; cross-border transfer rules for children's data - verify with counsel) · provider independence from the compute host (account, network, billing, legal entity) · throughput from our region · ability to issue **write-only** credentials · encryption options (SSE vs client-side) · restore speed (some archive tiers take hours) · exit path (S3-compatible = swappable).
Candidates to evaluate (not pre-selected): Cloudflare R2, Backblaze B2, Wasabi, AWS S3 (Mumbai) / S3-Glacier tiers, Google Cloud Storage (Mumbai), Azure Blob (Central India), and Indian S3-compatible providers. Note: several providers have a single storage class (no automatic cold tiering); "cold" here means *a different, cheaper, durable place*, not necessarily an archive-retrieval tier. Treat blog price tables as orientation only.

Design patterns that hold regardless of provider:
- Credentials: the backup/archival agent gets **write-only** (or append + object-lock) credentials; deletion/lifecycle is performed by a separate privileged identity used rarely.
- **Encrypt before upload** for personal/child data (client-side envelope encryption, keys held outside the cold provider); public lesson bundles need integrity, not secrecy.
- Keys: content-addressed for immutable artifacts (`c1/{topic}/{class}/{lang}/{version}/{sha256}`); date-partitioned for archives (`c10/dt=2026-11-07/part-0001.jsonl.zst`). Never put PII in object keys.
- Provider outage: serving continues from SSD cache/CDN; uploads queue in the outbox (bounded by SSD headroom - alert on backlog); no data is evicted while cold is unreachable.
- Second cold copy for the highest-value classes (C9, C14) if cost permits - provider A + provider B - or at least a second region.

## 5. Failure behaviours to specify per class
SSD full · SSD lost · node lost · cold provider unreachable · cold provider returns corrupt data · credentials leaked · partial multipart upload · clock skew · double upload (idempotency) · restore into wrong environment. For each: detection, user-visible effect, automatic response, manual runbook step.

## 6. Phasing (honour the repo's "avoid over-engineering early")
- **Phase A (P0 demo):** static bundles from the existing frontend volume/git; in-memory session state; usage log to a file or small DB; no cold sync except git + a nightly copy of the content volume to a second provider (cheap insurance). Document that this is the *minimum*.
- **Phase B (pilot):** Postgres + outbox worker + cold sync for C1/C2/C4/C14; consent ledger; events table.
- **Phase C (growth):** partition archival, scrub/drills automated, second cold copy, per-subject encryption keys, read replicas if measured need.
Specify the target; mark each row with its phase.
