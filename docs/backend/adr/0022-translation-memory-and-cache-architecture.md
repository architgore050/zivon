# ADR-0022: Two-Tier Translation Memory and Cache Architecture

- **Status**: accepted
- **Date / deciders**: 2026-11-09 / SP2-TRANS (Wave S1 architecture spec), building on ADR-0004 (cold storage provider separation), ADR-0006 (WAL & outbox sync), ADR-0009 (language/locale model), and ADR-0013 (build-time translation pipeline)
- **Driving NFRs / requirements**:
  - `NFR-TRN-04`: Re-running or updating a lesson where `M` of `N` blocks are unchanged must reuse verified translations for all `M` unchanged blocks with **0 model calls** (`100%` cache hit rate on unchanged `(block_sha256, locale, glossary_version)`). `[STRONG]`
  - `NFR-TRN-05`: Build-time factory runs in Phase A (P0 challenge demo, no Postgres required in-cluster yet per `02-data-classification-and-tiering.md` §6) must still benefit from persistent cross-run Translation Memory on the `zivon-sources` PVC, while seamlessly hydrating/syncing with the Phase B PostgreSQL System of Record (`block_translation`, `translation_memory_entry`) and Class C1/C3 cold storage. `[C: ADR-0004, ADR-0006]`
  - `NEED-TRN-02` / `ENT?-BlockTranslation` / `ENT?-GlossaryTerm`: Every column, key, and retention rule must trace to `docs/backend/db-spec.md` and `docs/backend/storage-tiering.md` (Data Classes `C1` and `C3`).

## Context

When a Physics chapter is regenerated (`--fresh`) after a prompt tweak, a simulation fix in `05-interactive`, or a single-block repair in `04-repair`, 70–95% of the chapter's text, worked-example, check, reveal, and diagram blocks often remain textually identical, or share identical boilerplate strings and glossary terms across chapters.

Without a content-addressed **Translation Memory (TM)** keyed by the normalized source block payload, every `--fresh` run or minor repair would re-translate all 15–45 blocks across all target languages (`hi`, `hi-Latn`, `ta`, `te`, etc.), burning Evon v3.3 compute time and risking non-deterministic translation drift on already-reviewed blocks.

At the same time, Zivon's architecture (`skills/zivon-systems-design-skills/skills/zivon-systems-design/references/02-data-classification-and-tiering.md` §6 and `03-database-spec-method.md` §3) defines a phased storage model:
- **Phase A (P0 Demo)**: The content factory runs as a standalone Kubernetes Job mounting `zivon-sources` PVC and `zivon-frontend` PVC without requiring a live PostgreSQL instance in the loop.
- **Phase B/C (Pilot & Production)**: PostgreSQL is the System of Record (SoR) for **Class C3 (Translations & glossaries)**, backed up via continuous WAL shipping (`SYNC-02` per ADR-0006) to the separate cold-storage provider (ADR-0004), and compiled at publish time into **Class C1 (Published lesson bundles)** synced via the transactional outbox (`SYNC-01`).

We need a Translation Memory design that works identically in Phase A (file-backed on `zivon-sources` PVC) and Phase B/C (PostgreSQL SoR + PVC read-through cache + cold backup) using the exact same canonical hash key.

## Options considered

| Option | Pros | Cons | Cost / ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Option 1: Do nothing (rely only on `runs/<run_id>/` stage resume)** | Zero new storage structures. | `--fresh` wipes `runs/<run_id>/`, destroying all translations even for unchanged blocks; editing 1 block in `04-repair` invalidates stage-level cache. | High Evon compute waste on `--fresh` and repairs | Fails `NFR-TRN-04` |
| **Option 2: PostgreSQL-only Translation Memory (`block_translation` table only)** | Single relational SoR from day one; supports SQL queries for human review queues. | Makes the build-time content factory Job depend on a live Postgres cluster during Phase A (violating `AGENTS.md` "avoid over-engineering databases early" and `02-data-classification-and-tiering.md` §6 Phase A). | Blocks Phase A factory runs if DB is absent/down | Fails `NFR-TRN-05` & layer independence |
| **Option 3 (Selected): Deterministic Content-Addressed TM Key (`tm_key`) with Two-Tier Storage (Tier 1: `zivon-sources` PVC content-addressed store for Phase A/build-time; Tier 2: PostgreSQL Class C3 tables `block_translation` + `translation_memory_entry` + `glossary_term` for Phase B/C, synced via ADR-0006)** | Works offline/DB-free in Phase A via `sources/cache/tm/`; maps 1:1 to PostgreSQL `translation_memory_entry` and `block_translation` in Phase B via deterministic UUIDv7 / SHA-256 key; preserves human-reviewed overrides (`source='human'`) across regenerations. | Requires a deterministic canonicalization function (`canonical_block_hash`) and a lightweight import/export sync between PVC cache and Postgres in Phase B. | Minimal (~2–8 KB JSON per block; ~15 MB/year across all classes & locales) | Meets all NFRs |

## Decision

We adopt **Option 3**:

### 1. Canonical Content-Addressed Key (`tm_key` / `block_sha256`)

Every translatable unit (a content block `b-01`..`b-45` or the `b-00-meta` lesson envelope) has its translatable source fields extracted and normalized (UTF-8 NFC, stripped trailing whitespace, sorted JSON keys, excluding non-translatable fields such as `citations` or numeric `min`/`max`/`step`/`initial` bounds) to compute:
- `source_content_sha256 = sha256(canonical_json(translatable_payload))`
- `tm_key = sha256(f"{source_content_sha256}:{target_locale}:{glossary_version}:{translator_prompt_version}")`

Why `glossary_version` and `translator_prompt_version` are in `tm_key` (while `source_content_sha256` is stored as a separate indexed column):
- If a block's English text is unchanged and the glossary/prompt contract is unchanged, `tm_key` is an exact hit.
- If the glossary is updated, `source_content_sha256` still matches in PostgreSQL (`block_translation`), allowing human-reviewed translations (`review_status = 'human_approved'`) to be retained without forced regeneration, while machine-reviewed entries (`review_status = 'machine_verified'`) can be selectively refreshed.

### 2. Tier 1 — Build-Time PVC Cache (`sources/cache/tm/`, Phase A + B)

- **Location**: `sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json` on the `zivon-sources` PVC (mounted into the factory Job alongside `sources/cache/pdfs/` and `sources/cache/text/`).
- **Write rule**: Written atomically (`os.replace`) **only after** a translated block passes both deterministic checks and the `10b-transcheck` LLM reviewer gate (`verdict == "pass"`). Unverified or rejected translations never enter `sources/cache/tm/`.
- **Lookup rule**: `10a-translate` checks `runs/<run_id>/10a-translate/blocks/<locale>/<block_id>.json` first (in-run resume), then `sources/cache/tm/<locale>/<tm_key[:2]>/<tm_key>.json` (cross-run TM). On a TM hit, the cached block is copied into the run directory and marked `cache_hit: true` in `10a-translate/output.json` (skipping both `10a` and `10b` model calls for that block, while still running deterministic code checks in `< 1 ms`).

### 3. Tier 2 — PostgreSQL System of Record & Cold Tiering (Class C3 & Class C1, Phase B + C)

In accordance with `docs/backend/db-spec.md` (`03-database-spec-method.md` §3) and `docs/backend/storage-tiering.md` (`02-data-classification-and-tiering.md` §2–§3):
- **`glossary_term`** (Class C3): Canonical physics terminology per locale (`term_id`, `locale`, `english_term`, `native_rendering`, `first_mention_format`, `hinglish_rendering`, `do_not_translate`, `pronunciation_hint`, `glossary_version`).
- **`block_translation`** (Class C3): Per-lesson-version localized block record (`id` UUIDv7, `content_block_id`, `lesson_version_id`, `locale`, `source_content_sha256`, `tm_key`, `translated_spec` JSONB, `translation_source` `'machine'|'human'`, `model_id`, `reviewer_verdict`, `reviewed_by`, `reviewed_at`, `status` `'draft'|'verified'|'human_approved'|'rejected'`).
- **`translation_memory_entry`** (Class C3): Cross-lesson deduplicated cache table keyed by `(tm_key)` with unique index on `(source_content_sha256, locale, glossary_version, prompt_version)` so identical paragraphs, worked examples, or check questions reused across versions resolve in `O(1)`.
- **`ui_string`** & **`locale_fallback`** (Class C3): Static chrome translations (`lesson.lang.label`, `lesson.check.submit`, `lesson.untranslated.banner`, etc.) and deterministic fallback chain (`hi-Latn → hi → en`, `hi → en`, `<indic> → en`).
- **Cold sync (`SYNC-01` & `SYNC-02`)**:
  - Class C3 tables in PostgreSQL are continuously archived via WAL shipping (`SYNC-02`, RPO ≤ 5 min) to the separate cold provider (ADR-0004).
  - On `11-link` / publish, verified localized blocks are baked into immutable **Class C1 Published lesson bundles** (`c1/{topic}/{class}/{locale}/{version}/{sha256}`) and uploaded via the transactional outbox (`SYNC-01`) before `live_pointer(lesson_id, locale, lesson_version_id)` flips to live.
  - Completed `10a`–`10d` run evidence under `runs/<run_id>/` follows **Class C4** (`SYNC-03`: archived compressed to cold storage 24h after run completion).

## Consequences

- **What gets easier**:
  - Zero-DB Phase A execution and full Postgres SoR Phase B execution share the exact same JSON payload and `tm_key` hash definition.
  - Modifying one block in a 35-block chapter re-translates **1 block** per locale instead of 35, cutting incremental translation time and token usage by ~97%.
  - Human corrections (`translation_source = 'human'`, `status = 'human_approved'`) take precedence over machine translations and are never overwritten by Evon regeneration when `source_content_sha256` matches.
- **What gets harder**:
  - Any change to the canonicalization logic (`canonical_block_hash`) invalidates existing `tm_key` hashes; the canonicalization rules must therefore be frozen in `docs/specs/translation/spec.md` and covered by unit tests.
- **What we must monitor**:
  - TM hit ratio (`tm_hits / total_blocks`) per factory run in `run_report.json`.
  - `sources/cache/tm/` disk usage on `zivon-sources` PVC (alert at > 70% PVC capacity per `NFR` table).

## Revisit trigger

- Revisit if semantic near-duplicates (e.g., a minor punctuation edit in an English paragraph) cause frequent cache misses: add an optional exact-sentence-level TM split or fuzzy match passed as a few-shot reference in the `10a-translate` prompt (never auto-accepted without `10b-transcheck`).

## References

- `skills/zivon-systems-design-skills/skills/zivon-systems-design/references/02-data-classification-and-tiering.md` (Classes C1, C3, C4, C14; `SYNC-01`..`SYNC-06`)
- `skills/zivon-systems-design-skills/skills/zivon-systems-design/references/03-database-spec-method.md` (§3 Localization & Content versioning)
- `ADR-0004` (Cold storage provider separation)
- `ADR-0006` (Postgres WAL archiving & transactional outbox sync)
- `ADR-0009` (Language & locale model)
- `ADR-0013` (Build-time translation pipeline)
