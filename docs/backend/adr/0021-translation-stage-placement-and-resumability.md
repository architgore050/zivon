# ADR-0021: Translation Stage Placement and Per-Block Resumability in the Content Factory

- **Status**: accepted
- **Date / deciders**: 2026-11-09 / SP2-TRANS (Wave S1 architecture spec), building on ADR-0013 (build-time translation pipeline) and ADR-0009 (language/locale model)
- **Driving NFRs / requirements**:
  - `NFR-TRN-01`: Build-time translation must consume **zero** Gnani Prisma/Timbre API credits (all calls route to self-hosted/open-weight **Evon v3.3** through `llm_manager/service/` per `AGENTS.md`). `[C: ADR-0013, ADR-0015]`
  - `NFR-TRN-02`: A translation or review failure on one block or one language must **never** re-run upstream English generation (`00-ingest`..`10-reviewfix`) or already-verified blocks in the same run (founder rule: a gate failure never re-runs the whole pipeline). `[STRONG]`
  - `NFR-TRN-03`: Resuming a killed factory Job (`backoffLimit: 0`) must skip completed `(locale, block_id)` units from `runs/<run_id>/` on the `zivon-sources` PVC in `< 1 s` per cached block. `[ASSUMPTION]`
  - `NEED-TRN-01` / `F-WRP-TRN-01`: Static localized lesson bundles (`/hi/`, `/hi-Latn/`, and P1 Indic locales per ADR-0009) must pass both deterministic structural checks and an independent Translation Reviewer gate before `11-link` / `publish-frontend.sh` exposes them.

## Context

`ADR-0013` established that lesson localization runs at **build time** inside the content factory rather than at student request time, using **Evon v3.3** translating **one block at a time** via the isolated **llm-manager node** (`k8s/16-llm-manager.yaml`, `llm_manager/`).

However, `ADR-0013` left open the exact stage placement within the Graph v2 pipeline (`docs/content-factory/architecture.md`, currently stages `00-ingest` through `11-link`, `PIPELINE_VERSION = "7"`):

1. **Where in the stage graph does translation execute?**
   - If translation runs immediately after `03-check` / `04-repair` (before `05-interactive`, `07-perf`, and `09-review`), any English block or simulation label modified during `08-fixloop` or `10-reviewfix` invalidates the translation or causes HTML-vs-JS label drift (`09-review-facts` category `inconsistency`). Worse, if `09-review` rejects an English page at the code gate, all translation tokens spent on `K` languages after `04-repair` are wasted.
   - Furthermore, `diagram` blocks carry inline `<svg>` with `<text>` annotation labels, and `simulation` blocks carry `spec.title`, `spec.description`, `spec.controls[].label`, and canvas/readout strings in `page.js` that only stabilize **after** `05-interactive`, `08-fixloop`, and `10-reviewfix` pass.
2. **What is the unit of resumability?**
   - In Graph v2 (`factory/stages.py`), stages `00`–`11` checkpoint at the *stage* boundary (`runs/<run_id>/<stage>/output.json` + `status.json`). A single chapter has 15–45 blocks (`BLOCKS.maxItems = 45`) plus lesson-level metadata (`title`, `objectives`, `sections`, `glossary`). Across 2–5 target languages, translating a chapter requires 35–230 sequential model calls through `llm-manager`. Stage-only checkpointing would lose up to 200 completed block translations if a pod is preempted or hits a node reboot mid-stage (as observed in run `110435` in `TIMELINE.md`).

## Options considered

| Option | Pros | Cons | Cost / ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Option 1: Do nothing / translate inside `02-generate` giant call** | Zero new stages; single prompt emits all locales at once. | Multiplies `02-generate` output tokens by `(1 + K)` languages, exceeding context/completion limits and causing `finish_reason=length` truncation; any `03-check` repair requires regenerating all locales; violates ADR-0013's per-block Evon v3.3 mandate. | High truncation & retry waste | Fails `ADR-0013`, `NFR-TRN-02`, and `skills/prompting-and-agent-design` task-size law |
| **Option 2: Translate right after `04-repair` (before `05-interactive` and `09-review`)** | Translated text is available before `06-render` runs the first time. | Runs before `05-interactive` and `09-review`/`10-reviewfix`; if `10-reviewfix` alters simulation labels/readouts or `09-review` fails the run, translation tokens are wasted; requires running `06-render` and `07-perf` across all locales before English is even verified. | High wasted Evon compute on failed/repaired English runs | Fails `NFR-TRN-02` (wastes work before code gate) |
| **Option 3 (Selected): Post-review pre-link stages (`10a-translate` → `10b-transcheck` → `10c-transrepair` → `10d-transrender`) between `10-reviewfix` and `11-link`, with per-`(locale, block_id)` disk + TM checkpointing** | English content, SVG diagrams, and JS simulations are 100% verified (`03-check`, `07-perf`, `09-review` all green) before a single translation token is spent; per-block checkpointing on `zivon-sources` PVC + TM lookup makes pod restarts zero-loss; `11-link` publishes English + all passing locales atomically. | Adds 4 bounded sub-stages to `STAGE_ORDER` (bumps `PIPELINE_VERSION` `"7"` → `"8"` when wired); requires a localized render pass (`10d-transrender`) before `11-link`. | Low: reuses `LLMClient`, `RunContext`, and `render.py` templates | Meets all NFRs |
| **Option 4: Standalone post-publish K8s Job (`zivon-translator-job`) decoupled from `pipeline.py`** | Keeps `pipeline.py` English-only; translation can run asynchronously after English is live. | Breaks single-command reproducibility (`python pipeline.py "Motion" --class 9`); requires coordinating two Jobs over the same `zivon-sources` and `zivon-frontend` PVCs (`ReadWriteOnce` contention); English page ships with dead language switcher chips until the second Job finishes. | Extra K8s Job template, PVC locking risk, split `run_report.json` | Degrades operational simplicity (`AGENTS.md`) |

## Decision

We adopt **Option 3**:

1. **Stage placement (after `10-reviewfix`, before `11-link`)**:
   Translation runs inside `pipeline.py` as four bounded stages immediately after the English page passes `09-review` / `10-reviewfix` and immediately before `11-link`:
   - `10a-translate` (`factory/translate.py`): Iterates over target locales configured in `config.json` (`translation.target_locales`, default `["hi", "hi-Latn"]` in P0/Wave 1, extensible to ADR-0009 P1 locales `["ta", "te", "mr", "bn", "gu", "kn", "ml", "pa"]`). For each locale, translates the lesson header/glossary envelope (`b-00-meta`) followed by blocks `b-01`..`b-NN` **one block per `llm_manager` call** using **Evon v3.3**.
   - `10b-transcheck` (`factory/transcheck.py`): Runs deterministic structural/lexical checks (`rule_trans_schema`, `rule_trans_citations`, `rule_trans_numbers`, `rule_trans_units_and_symbols`, `rule_trans_mcq_integrity`, `rule_trans_svg_safety`, `rule_trans_placeholders`, `rule_trans_length_budget`) plus a bounded **Translation Reviewer** model call per locale (outputs `issues` only; harness computes `verdict = "fail"` iff any `fatal` or `major`).
   - `10c-transrepair` (`factory/transrepair.py`): Progress-aware catcher paired with `10b-transcheck`. Re-translates **only** the flagged `(locale, block_id)` items with the reviewer/rule violation fed back as errors-as-context, up to `repair.translation_rounds` (default `6`) or `repair.stall_rounds` (default `3`) consecutive non-improving rechecks.
   - `10d-transrender` (`factory/render.py::render_localized`): Renders verified localized pages into the staging site (`site/courses/<course_id>/<slug>/<locale>/index.html` and localized string bundle `i18n/<locale>.json`) and runs `lint_generated` on every localized HTML output before `11-link` copies the staging tree to `frontend/`.

2. **Two-level resumability (stage + per-block checkpointing)**:
   - **Per-block artifact checkpoint**: Inside `10a-translate` and `10c-transrepair`, each completed `(locale, block_id)` translation is immediately persisted atomically (write-temp-then-rename) to `runs/<run_id>/10a-translate/blocks/<locale>/<block_id>.json` alongside its `block_sha256` input hash.
   - **Resume behavior**: If a pod is killed mid-translation and re-triggered, `10a-translate` inspects `runs/<run_id>/10a-translate/blocks/<locale>/<block_id>.json`. Any block whose file exists, validates against `TRANSLATED_BLOCK_SCHEMA`, and matches the current `block_sha256` is loaded from disk in `< 1 ms` without calling `llm-manager`.
   - **Cross-run Translation Memory (TM) lookup**: Before calling `llm-manager` on a cache miss in `runs/<run_id>/`, `10a-translate` checks the persistent Translation Memory (ADR-0022). If an identical `(block_sha256, locale, glossary_version, prompt_version)` entry exists with status `verified`, it is reused directly.

3. **Partial-locale isolation**:
   - If a target locale still has unresolved `fatal`/`major` issues after `10c-transrepair` exhausts its repair budget, the failure policy is controlled by `translation.on_locale_failure`:
     - For **required P0 locales** (`hi`, `hi-Latn` when `translation.enabled = true`): raises `StageError("10b-transcheck", ...)` keeping all completed block artifacts on disk so a re-trigger resumes solely the failed block(s).
     - For **optional/pilot locales** (`translation.optional_locales`): logs a loud warning, records `"status": "partial_fallback"` in `manifest.json` and `issues_ledger.jsonl`, and allows English + passing locales to proceed to `11-link` while the failed block falls back to English with an explicit `.zn-untranslated-notice` banner (per `features.md` state `untranslated`).

## Consequences

- **What gets easier**:
  - Zero wasted translation calls on drafts that fail `03-check`, `07-perf`, or `09-review`.
  - Granular per-block context keeps each Evon v3.3 prompt small (~1.5k–3.5k prompt tokens, ~200–800 completion tokens), eliminating `finish_reason=length` truncation and long thinking stalls.
  - Pod deaths mid-translation lose at most the single in-flight block call.
- **What gets harder**:
  - `PIPELINE_VERSION` must bump from `"7"` to `"8"` when `10a`–`10d` are enabled in `STAGE_ORDER`, or `translation.enabled` must default to `false` in `config.json` until the Evon v3.3 translation endpoint is live so existing v7 English-only run dirs remain resumable. (We specify `translation.enabled` in `config.json` and include `translation` config in `run_fingerprint` only when `translation.enabled` is `true`.)
- **What we must monitor**:
  - Per-block latency, validation rounds, and token usage in `calls_ledger.jsonl` (`stage="10a-translate"`, `round_tag="<locale>/<block_id>"`).
  - Catcher convergence rate in `issues_ledger.jsonl` (`stage="10b-transcheck"`).

## Revisit trigger

- Revisit if per-topic translation wall-clock time across `hi` + `hi-Latn` exceeds `180 s` p95 on the cluster (`llm-manager` bounded concurrency across blocks of the same topic can be raised from `1` to `2`–`4` if the upstream inference server supports multi-slot batching).

## References

- `AGENTS.md` (Content factory & `llm_manager/` non-negotiables)
- `docs/content-factory/architecture.md` (Graph v2 stage table, catcher loops, fingerprint guard)
- `llm_manager/README.md` (`LLMManager`, `run_validation_rounds`)
- `ADR-0009` (Language & locale model)
- `ADR-0013` (Build-time translation pipeline)
