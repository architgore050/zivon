# Translation Pipeline Specification (`docs/specs/translation/`)

This directory contains the build-ready architecture and implementation specification for Zivon's **build-time lesson translation pipeline** and **runtime locale contract** (Wave S1 — `SP2-TRANS`, consumed by `EX2-TRANS` and `EX5-FRONT`).

## Governing Decisions & Non-Negotiables

1. **Build-time block-by-block translation via Evon v3.3 (`ADR-0013`, `ADR-0021`)**:
   Lesson pages are translated at build time inside the content factory (`pipeline.py`) **after** the English draft and interactive simulations have passed `03-check`, `07-perf`, and `09-review` (`10-reviewfix`), and **before** `11-link` publishes to `frontend/`. Translation operates **one block at a time** (`b-00-meta`, `b-01`..`b-45`) so each model call fits comfortably inside a small, deterministic context window and resumes at per-`(locale, block_id)` granularity.
2. **All model calls route through `llm_manager/` (`AGENTS.md`)**:
   The translator and translation reviewer are consumers of `llm_manager/` (`LLMClient` adapter in `factory/llm.py` talking to the isolated `llm-manager` Service node at `k8s/16-llm-manager.yaml`). Hand-rolled HTTP calls to an inference server are strictly prohibited.
3. **Zero Gnani Prisma/Timbre credit burn (`ADR-0015`)**:
   Translation uses open-weight/self-hosted **Evon v3.3** via the `llm-manager` node and consumes **0** Gnani API programme credits (preserving the 5,000-credit pool and 40% demo-day reserve exclusively for live Prisma STT and Timbre TTS).
4. **Two-tier Translation Memory (`ADR-0022`)**:
   Verified block translations are cached by deterministic content hash `tm_key = sha256(source_content_sha256 : locale : glossary_version : prompt_version)` on the `zivon-sources` PVC (`sources/cache/tm/`, Phase A) and in PostgreSQL Class C3 tables (`block_translation`, `translation_memory_entry`, `glossary_term`, Phase B/C) backed by WAL shipping (`SYNC-02`) and Class C1 bundle outbox sync (`SYNC-01`).
5. **Bilingual First-Mention Physics Glossary & Immutable Numerals/SI Units (`ADR-0023`, `ADR-0009`, `DCR-001`)**:
   First mention of a Physics term in a block renders `<Native Term> (<English Term>)` (e.g., `वेग (velocity)`); Western Arabic numerals (`0–9`), SI units (`m/s²`, `N`, `kg`), variables, equations, citations, and SVG geometry attributes are never translated or transliterated.

## Layout of This Folder

| File | Purpose | Primary Consumers |
|---|---|---|
| [`README.md`](README.md) | Folder map, governing constraints, and quick navigation | All agents (`EX2-TRANS`, `EX5-FRONT`, `EX0-BACKEND`, merge reviewer) |
| [`spec.md`](spec.md) | End-to-end architecture specification: pipeline stages (`10a`–`10d`), per-block resumability, block-by-block strategy, Translation Memory & PostgreSQL/cold-storage tiering (`db-spec.md` & `storage-tiering.md` traceability), publishing & frontend locale switcher contract, `DCR-001` script baseline rules, runtime tutor translation stub, capacity & cost model, and failure-mode / screen-state matrices | `EX2-TRANS`, `EX5-FRONT`, `EX0-BACKEND` |
| [`block-contract.md`](block-contract.md) | Exact request and response JSON schemas (`TRANSLATE_BLOCK_REQUEST`, `TRANSLATED_BLOCK_RESPONSE`, per-block-type `spec` contracts for `b-00-meta`, `text`, `worked_example`, `check`, `reveal`, `diagram`, `simulation`), SVG `<text>` extraction/re-injection protocol, and `llm_manager` call wiring | `EX2-TRANS` |
| [`reviewer-rubric.md`](reviewer-rubric.md) | Quality gate specification (`10b-transcheck` & `10c-transrepair`): 9 deterministic code checks (`factory/transcheck.py`), calibrated Evon v3.3 LLM-judge prompt and rubric following `skills/prompting-and-agent-design/`, `REVIEW_CALL_REPORT` issue schema, and bounded progress-aware repair catcher loop | `EX2-TRANS` |
| [`open-questions.md`](open-questions.md) | Tracked assumptions (`[ASSUMPTION]`), deferred post-challenge items, and cross-wave integration notes | Founder, merge agent, `EX2-TRANS` |

## Cross-References

- **ADRs**:
  - [`docs/backend/adr/0021-translation-stage-placement-and-resumability.md`](../../backend/adr/0021-translation-stage-placement-and-resumability.md)
  - [`docs/backend/adr/0022-translation-memory-and-cache-architecture.md`](../../backend/adr/0022-translation-memory-and-cache-architecture.md)
  - [`docs/backend/adr/0023-physics-terminology-and-script-rendering-policy.md`](../../backend/adr/0023-physics-terminology-and-script-rendering-policy.md)
  - Upstream Wave S0 ADRs: `ADR-0004` (Cold storage provider), `ADR-0006` (WAL & outbox sync), `ADR-0009` (Language & locale model), `ADR-0013` (Build-time translation pipeline), `ADR-0015` (Transactional credit guards)
- **Content Factory**:
  - [`docs/content-factory/architecture.md`](../../content-factory/architecture.md)
  - [`docs/content-factory/blocks-schema.md`](../../content-factory/blocks-schema.md) (see § "Change Proposal CP-TRN-001")
  - [`docs/content-factory/config-reference.md`](../../content-factory/config-reference.md)
  - [`llm_manager/README.md`](../../../llm_manager/README.md) & [`factory/llm.py`](../../../factory/llm.py)
- **Frontend & Design Doctrine**:
  - [`docs/frontend/design-doctrine.md`](../../frontend/design-doctrine.md) (§10.2, §10.3, §10.5, §10.7)
  - [`frontend/assets/zivon.js`](../../../frontend/assets/zivon.js) & [`scripts/publish-frontend.sh`](../../../scripts/publish-frontend.sh)
