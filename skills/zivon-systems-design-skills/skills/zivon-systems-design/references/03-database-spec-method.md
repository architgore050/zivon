# Database spec method

## 1. Derivation order (never start from tables)
1. From the information inventory + `ENT?-…` list → **entities and attributes** (merge synonyms, split mixed concerns).
2. From capability needs → **access patterns** (query, frequency, latency, consistency need: read-your-own-writes?).
3. From data classes (`02`) → **placement** (which store is SoR; which entities have retention clocks).
4. Then: relations, keys, constraints, indexes, partitioning, migrations.
Every column cites `INF-…`/`ENT?-…`; every index cites a `NEED-…` query. Columns the systems design adds (ids, timestamps, versions, tombstones) are tagged "systems-originated".

## 2. Engine choice (ADR; this is the default argument, not a mandate)
Relational with transactions (PostgreSQL) fits: consent ledger and usage ledger need atomicity; lesson/translation/version relationships; JSONB for block specs (validated by the existing JSON-schema layer in `factory/schemas.py`, not by the DB alone); mature backup/WAL archiving for the cold-sync design. Alternatives to weigh: SQLite (single-node MVP, trivially simple, no WAL-to-cold story as strong, concurrency limits), document store (schema flexibility, weaker cross-entity integrity), key-value/Redis (session state only). Choose by access patterns, not fashion. Phase per `02` §6: the P0 demo may use in-memory state and files; the spec still defines the target schema so migration is mechanical.

## 3. Modeling patterns to evaluate

**Identifiers**: time-ordered unique ids (UUIDv7 or ULID) as primary keys; never expose sequential ids; never encode PII in ids.
**Timestamps**: `timestamptz` in UTC; `created_at`, `updated_at`; business times (e.g. `consented_at`) separate from row times.
**Content versioning**: `lesson` (stable identity: topic, class) → `lesson_version` (immutable after publish; content hash; status draft/reviewed/published/retired; created_by pipeline run) → `content_block` (id like `b-01`, type, `spec` JSONB, citations). A published version is never updated; fixes create a new version. `live_pointer(lesson_id, locale, lesson_version_id)` is the only mutable switch.
**Localization**: `block_translation(block_id, locale, spec_patch JSONB, source: 'human'|'machine', reviewed_by, reviewed_at, status)` or translate-whole-block rows; `ui_string(key, locale, text, source)`; `glossary_term(term_id, locale, rendering, gloss, do_not_translate)`. Fall-back rule is data: `locale_fallback(locale → fallback_locale)`; the API returns *which* locale was served so the UI can say so.
**Audio assets**: `narration_asset(block_id, locale, voice, speed, lesson_version_id, text_hash, object_id)` - keyed by `text_hash` so identical text never regenerates. The audio bytes live in the object catalogue (`02` §3), not in the DB.
**Sessions**: `device_profile` (pseudonymous, no name/phone), `session(id, device_profile_id, lesson_version_id, started_at, ended_at, language, mode)`, `turn(id, session_id, seq, role, text, lang, anchor_block_id, sim_state JSONB, created_at, latency_ms JSONB)`. Guard sizes; cap `sim_state`.
**Consent**: `guardian_link(id, status, verified_method, verified_at)`, `consent_record(id, subject_ref, purpose, scope, granted_at, withdrawn_at, notice_version, evidence_ref)` append-only; effective consent is derived, never overwritten.
**Preferences/memory (personalization)**: `preference(device_profile_id, key, value, set_by: 'student'|'guardian'|'system', updated_at)`; any inferred item has `explanation` and is deletable; table exists only if T5/T6 decisions permit.
**Usage ledger**: `usage_entry(id, session_id, kind: stt_seconds|tts_chars|llm_tokens, quantity, provider, cost_credits, at)`; `budget(scope, period, limit, used)` with constraints for atomic decrement. The hot path reads `budget`, never sums the ledger.
**Events**: `event(id, name, schema_version, subject_pseudo_id, session_id, ts, props JSONB, client_ts)` partitioned by time; event names and props validated against the catalogue (vendored `measure-instrumentation-spec`); no free-text child speech in props.
**Object catalogue**: see `02` §3.
**Admin/audit**: `audit_log(id, actor, action, target, before_hash, after_hash, at)`.

## 4. Constraints and integrity
Foreign keys on, `ON DELETE` chosen deliberately (children's rows must be deletable by subject); CHECK constraints for enums and ranges (e.g. sim control bounds); unique keys for idempotency (`(session_id, seq)`; `(device_profile_id, key)`); NOT NULL by default; JSONB columns have a documented schema and a version field; app-layer validation uses the same schemas as the content factory where applicable.

## 5. Indexes, partitioning, performance
Derive indexes from the access-pattern table (query, filter, sort, expected cardinality, latency target). Partition append-only tables by time; make "drop old partition" the retention mechanism. Avoid premature sharding; state the row-count at which you would revisit. Use the vendored `postgres-pro`/`database-optimizer` references for index types, `EXPLAIN` workflow, pooling, vacuum; check each with the p95 targets in the NFR table.

## 6. Retention and deletion in the schema
Every table with personal or pseudonymous data has: `retention_class`, a documented max age, a scheduled job (or partition drop) that enforces it, and a deletion path by `subject_ref`. Prefer **hard delete + minimal tombstone** for child data over soft-delete flags that retain content. Per-subject encryption keys for transcripts enable "crypto-erasure" across hot and archived copies - evaluate vs complexity.

## 7. Migrations and change management
Migration tool tied to the ORM/driver choice (the repo is Python; verify before assuming). Pattern: expand → migrate/backfill → contract; no destructive change in the same release as the code that stops using it; every migration is reversible or has a documented forward-fix; migrations run in CI against a fresh DB and against a restore of a recent backup; schema version recorded in the DB and exposed in `/health`.

## 8. Deliverable structure for the DB spec
1. Scope, engine ADR, phase plan. 2. Entity list with source traceability. 3. ER diagram (Mermaid). 4. Per-table spec: purpose, columns (name, type, null, default, source INF/ENT?, PII class, retention), keys, constraints, indexes, partitioning, volume estimate, SoR/tier, deletion path. 5. Access-pattern table. 6. Retention & deletion matrix. 7. Migration plan. 8. Seed/reference data. 9. Traceability CSV (column ↔ INF ↔ NEED). 10. Open questions and assumptions.
