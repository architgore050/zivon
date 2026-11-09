# Open Questions, Tracked Assumptions & Cross-Wave Integration Notes (`SP2-TRANS`)

- **Spec ID**: `SP2-TRANS` · `open-questions.md`
- **Date**: 2026-11-09

---

## 1. Tracked Assumptions (`[ASSUMPTION]` Register)

Every quantitative estimate or unverified external dependency in the `SP2-TRANS` specification is tagged below with its validation trigger:

| ID | Assumption | Value / Rule Used in Spec | How & When to Validate | Owner |
|---|---|---|---|---|
| `ASM-TRN-01` | Evon v3.3 per-block completion latency via `llm-manager` | `~4–10 s` per block on cloud GPU / OpenRouter (`~35 calls × 8 s ≈ 4.6 min` per chapter-locale cold build; `< 30 s` on warm TM hit) `[ASSUMPTION]` | Measure `latency_s` and `first_token_s` in `calls_ledger.jsonl` on the first `Motion` Class 9 `hi` + `hi-Latn` run in `EX2-TRANS`. | `EX2-TRANS` |
| `ASM-TRN-02` | `10c-transrepair` first-pass rejection rate | `~15%` of blocks (`~4` blocks per 28-block chapter) require 1 repair round on cold generation `[ASSUMPTION]` | Inspect `issues_ledger.jsonl` (`stage="10b-transcheck"`) via `scripts/issue_report.py` after 3 chapters. | `EX2-TRANS` |
| `ASM-TRN-03` | Indic text expansion ratios (`ADR-0023`) | Prose `<= 1.50x`, titles `<= 1.35x`, SVG `<text>` `<= 1.25x` (`+6 chars`), simulation slider labels `<= 32 chars` `[ASSUMPTION]` | Run `07-perf` horizontal-overflow check (`weak-android.json` at `360px` viewport) on rendered `hi` and `ta` pages. | `EX2-TRANS` + `EX5-FRONT` |
| `ASM-TRN-04` | `DCR-001` per-script baseline nudge values (`--script-baseline-nudge`) | `-1.5px` (`Deva`: `hi`, `mr`), `-2.0px` (`Telu`, `Knda`, `Mlym`), `-1.0px` (`Taml`, `Beng`, `Gujr`, `Guru`), `0px` (`Latn`: `en`, `hi-Latn`) `[ASSUMPTION]` | Visually inspect `LessonKit` SVG ruled lines on real Android Chrome/WebView at `360px` and `768px` widths during Phase 4 pass (`docs/frontend/design-doctrine.md` §10.11). | `EX5-FRONT` + Founder |
| `ASM-TRN-05` | Cold-storage outbox verification SLO for localized bundles (`SYNC-01`) | `>= 99%` of published localized bundles (`C1`) cold-verified within `5 min` of `11-link` completion `[ASSUMPTION]` | Measure `cold_verified_at - created_at` in `object` catalogue table once Phase B outbox worker (`EX0-BACKEND`) is active. | `EX0-BACKEND` |

---

## 2. Open Questions for Founder Decision

| ID | Question | Options | Spec Default (Until Overridden) | Decider |
|---|---|---|---|---|
| `OQ-TRN-01` | **Should `translation.enabled` default to `true` or `false` in `config.json` on merge?** | **(a)** Default `false` until `EX2-TRANS` lands the seeded `sources/glossary/physics_glossary.json` and verifies Evon v3.3 on the node, keeping existing English CI/smoke tests fast.<br>**(b)** Default `true` for `["hi", "hi-Latn"]` immediately. | **Option (a)**: Default `translation.enabled: false` in `config.json` (with `--locales hi,hi-Latn` CLI flag to enable per run) so `PIPELINE_VERSION = "7"` run dirs and existing unit/integration tests stay 100% green without requiring extra mock LLM responses on English-only tests. | Founder / `EX2-TRANS` |
| `OQ-TRN-02` | **Should `07-perf` (Chromium weak-android gate) run on every localized `<locale>/index.html` or only on `en` + the tallest-script locale (`hi`)?** | **(a)** Run `lint_generated` on all locales in `10d-transrender` and run a lightweight Chromium horizontal-overflow + console-error check on each `<locale>/index.html`.<br>**(b)** Run the full 60-frame rAF FPS + RSS perf harness on every locale (adds `~15 s` × `K` locales). | **Option (a)** for P0: simulation JS (`page.js`) is identical across locales, so rAF FPS and RSS are invariant; `10d-transrender` runs `lint_generated` on all locales plus a fast layout/overflow check (`scrollWidth <= clientWidth` at `360px`) to catch any Indic text expansion overflow. | Founder |
| `OQ-TRN-03` | **Human translation review workflow in Admin Dashboard v0 (Day 8 / Phase B)** | **(a)** CLI-only override (`scripts/approve-translation.py` updating `sources/cache/tm/` and `block_translation.status = 'human_approved'`).<br>**(b)** Admin web view in Phase B showing flagged `block_translation` rows side-by-side. | **Option (a)** in Phase A/P0; **Option (b)** in Phase B (table schema `block_translation` already includes `translation_source`, `reviewed_by`, `reviewed_at`, `status='human_approved'`). | Founder |
| `OQ-TRN-04` | **Static Narration TTS (`EX8-NARRATION`) interaction with Bilingual Gloss (`ADR-0023`)** | When `EX8-NARRATION` synthesizes static Hindi lesson audio with Timbre v3.0 from a translated paragraph containing `वेग (velocity)`, should Timbre speak both words (`"वेग, यानी velocity"`) or only the primary term? | `EX8-NARRATION` strips parenthetical English glosses (or expands them using `glossary_term.pronunciation_hint`) when generating the spoken narration script so TTS prosody stays natural while the visual page shows `वेग (velocity)`. | `EX8-NARRATION` + Founder |

---

## 3. Handoff Checklist for Downstream Execution Agents

1. **`EX2-TRANS` (Content Factory Translation Stages)**:
   - Implement `factory/translate.py` (`10a-translate`), `factory/transcheck.py` (`10b-transcheck`), `factory/transrepair.py` (`10c-transrepair`), and `factory/render.py::render_localized` (`10d-transrender`) per [`spec.md`](spec.md), [`block-contract.md`](block-contract.md), and [`reviewer-rubric.md`](reviewer-rubric.md).
   - Add schemas `TRANSLATED_META_PAYLOAD`, `TRANSLATED_TEXT_PAYLOAD`, `TRANSLATED_WORKED_EXAMPLE_PAYLOAD`, `TRANSLATED_CHECK_MCQ_PAYLOAD`, `TRANSLATED_CHECK_NUMERIC_PAYLOAD`, `TRANSLATED_REVEAL_PAYLOAD`, `TRANSLATED_DIAGRAM_PAYLOAD`, `TRANSLATED_SIMULATION_PAYLOAD`, and `TRANSLATION_REVIEW_CALL_REPORT` to `factory/schemas.py`.
   - Seed `sources/glossary/physics_glossary.json` (Class 9–12 NCERT terms for `hi` and `hi-Latn`) and `sources/glossary/ui_strings.json`.
   - Add unit tests under `testing/content_factory/unit/test_translate.py` and `test_transcheck.py` covering all 9 deterministic rules (`R1`–`R9`), SVG `<text>` extraction/re-injection, TM cache hits (`tm_key`), and catcher repair loops.
2. **`EX5-FRONT` (Frontend Locale Switcher & `DCR-001`)**:
   - Upgrade `wireLangChips()` in `frontend/assets/zivon.js` from visual-only stub to full `[data-i18n]` DOM swap + `localStorage.getItem("zivon_locale")` persistence + `LessonKit` refresh per [`spec.md` §5.2](spec.md).
   - Add `DCR-001` `--script-baseline-nudge` and `[lang="hi"]` font fallback rules to `frontend/assets/zivon.css` per [`ADR-0023` §4](../../backend/adr/0023-physics-terminology-and-script-rendering-policy.md).
3. **`EX0-BACKEND` (Database & Storage Tiering)**:
   - Include Alembic migrations for Class C3 tables (`glossary_term`, `translation_memory_entry`, `block_translation`, `ui_string`, `locale_fallback`) per [`spec.md` §3.2](spec.md).
