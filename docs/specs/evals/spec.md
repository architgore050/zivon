# Zivon Content Factory Evaluation Framework Specification (`evals/`)

- **Status**: Specified (Wave S1 — `SP4-EVALS`)
- **Target Package**: `evals/` (repo root)
- **Applies To**: Build-time Content Factory (`pipeline.py`, `factory/`) and Gate B Kid-Comprehension Loop (`TIMELINE.md`)
- **Binding Constraints**: [`AGENTS.md`](../../../AGENTS.md), [`TIMELINE.md`](../../../TIMELINE.md), [`docs/content-factory/architecture.md`](../../content-factory/architecture.md), [`skills/prompting-and-agent-design/SKILL.md`](../../../skills/prompting-and-agent-design/SKILL.md), [`ADR-0017`](../../backend/adr/0017-eval-result-store-and-tiering.md), [`ADR-0018`](../../backend/adr/0018-eval-judge-model-and-calibration.md)

---

## 1. Separation Rule: `testing/` vs `evals/`

### 1.1 The Core Distinction

Zivon currently mixes deterministic unit/integration tests with prompt-anchor checks, teaching-quality assertions, and weak-hardware performance budget grading inside `testing/content_factory/{unit,integration,perf}` and `testing/frontend/`. This conflation creates two failure modes:
1. Prompt tuning breaks unit tests that assert on literal prompt substrings (`test_agents_generate.py`, `test_review.py`, `test_interactive.py`) even when model output quality improves.
2. Passing the mock-backed unit and integration suites (`286 unit + 8 e2e + 11 frontend`) gives zero signal on whether the real model teaches Physics accurately, catches planted factual/rendering defects, or regresses across `PIPELINE_VERSION` bumps.

The separation rule is strict and binary:

| Dimension | `testing/` (Software Correctness) | `evals/` (Teaching & Model Behavior Quality) |
|---|---|---|
| **Primary Question** | "Does our Python/JS/CSS code execute its deterministic contract without bugs?" | "Does the factory produce accurate, clear, accessible, fast study pages, and are our reviewers calibrated?" |
| **System Under Test** | Code modules (`factory/*.py`, `llm_manager/*.py`, `frontend/assets/zivon.{js,css}`) | Prompt + Model + Rubric + Golden Source Pack + Rendered Topic Artifact |
| **Model Dependency** | Never calls a real LLM; uses `testing/content_factory/mocks/openai_mock.py` or `StubLLM` | Deterministic smoke mode (`0` model calls) on golden artifacts + Full mode via `llm_manager/` (`LLMManager`) |
| **Output Type** | Binary pass/fail (`unittest` exit code `0` or `1`) | Structured scorecards (`0.0–1.0` metrics, TPR/TNR recall, latency/token distributions, diff vs baseline) + pass thresholds |
| **Failure Meaning** | A code regression was introduced; block the PR immediately | Teaching quality, prompt compliance, perf budget, or judge calibration regressed; block release or trigger prompt/kit repair |
| **Execution Cadence** | Every commit / every PR (`.github/workflows/ci.yml` `tests` job) + `k8s/50-test-cronjob.yaml` | Fast deterministic `eval-smoke` on every PR; full LLM-judged + Chromium perf suite on `k8s/52-eval-cronjob.yaml` & `scripts/trigger-evals.sh` |

### 1.2 What Belongs in `testing/` (Retained)

A test stays in `testing/` if and only if it is **100% deterministic, requires no real LLM inference, and tests code mechanics**:
1. **Configuration & CLI parsing** (`testing/content_factory/unit/test_config.py`, `test_stages_learner.py`): env-var tripwires, type validation, `Config.with_class_level()`, `run_fingerprint()` determinism.
2. **Schema & Validator mechanics** (`test_schemas.py`, `test_llm.py`, `test_llm_manager.py`, `test_llm_manager_service.py`): JSON Schema Draft-07 validation, `run_validation_rounds` transcript trimming, compact error formatting, SSE streaming transport, inactivity timeout, `call_deadline_s` abort, `/healthz` and `/v1/chat/completions` HTTP status codes against `openai_mock.py`.
3. **Deterministic rule & lint engine mechanics** (`test_checks.py`, `test_lint.py`): proving that `rule_answer_keys`, `rule_citations`, `rule_self_containment`, `rule_numbers` (boundary-aware regex), `rule_diagram_svg`, `lint_js`, `lint_css`, `lint_html`, and `lint_page_css_scope` return expected findings when fed synthetic valid/invalid dicts or strings.
4. **Ingestion, PDF table extraction & retrieval mechanics** (`test_ingest.py`, `test_textops.py`, `test_retrieval.py`, `test_catalog_sync.py`): `pdfplumber` ruled-table reconstruction, `chapter_url_offset` mapping, 404/unreachable truncation logic, `FixtureEmbedder` cosine top-k, and `sources/catalog.json` ↔ `source-catalog.md` sync.
5. **Orchestrator & artifact state machine** (`test_artifacts.py`, `test_render.py`, `test_perf_fixloop.py`, `integration/test_end_to_end.py`): `RunContext` resume, `wipe_run`, `merge_blocks`/`remove_blocks`, catcher loop routing (`03→04`, `07→08`, `09→10`) against `openai_mock.py`, and HTML/CSP/manifest generation on minimal fixtures.
6. **Frontend shell runtime mechanics** (`testing/frontend/test_shell.py`, `test_behaviour_layer.py`): static shell self-containment, `zivon.js` MCQ/numeric tolerance click handlers, `ZivonSim` error boundary, and `.zn-check` `<legend>` float geometry on synthetic HTML.

### 1.3 What Moves to `evals/` (Migrated)

Every assertion that measures **prompt design, model output quality, golden-page compliance, reviewer calibration, or weak-hardware performance budgets** migrates to `evals/` (full row-by-row mapping in [`migration-map.csv`](migration-map.csv)):
1. **Prompt-contract & prompt-anchor checks** currently embedded in `test_agents_generate.py`, `test_interactive.py`, `test_review.py`, and `test_perf_fixloop.py` (e.g., asserting that `02-generate` routes computed geometry to simulations, carries the coverage contract and grounding law, or that `03-check` and `09-review` prompts include specific rubric steps and live design doctrine). In `evals/`, prompt contracts are verified alongside behavioral evals on golden inputs rather than brittle unit-test string checks, while `testing/` keeps only function-signature and `extra_validator` wiring tests.
2. **Weak-hardware performance harness & profile grading** (`testing/content_factory/perf/harness.py`, `testing/content_factory/perf/profiles/*.json`, `unit/test_perf_profile.py`, `unit/test_perf_harness_pid.py`): the Chromium CDP + `psutil` instrument (`weak-android.json`, `mid-laptop.json`) is an evaluation grader (`EV-PERF-001`). Its canonical home moves to `evals/checkers/perf_harness.py` and `evals/goldens/profiles/`.
   - **Backward-Compatibility Shim Rule**: Because `factory/perf.py` and `factory/fixloop.py` import `testing.content_factory.perf.harness.run_profile` at runtime during stage `07-perf` and `08-fixloop`, `testing/content_factory/perf/harness.py` remains as a 5-line re-export shim (`from evals.checkers.perf_harness import *`) until `factory/` updates its import path. Its unit tests (`test_perf_profile.py`, `test_perf_harness_pid.py`) remain in `testing/content_factory/unit/` to test the grader's own code mechanics.
3. **Published golden-page quality & completeness checks** currently mixed into `testing/frontend/test_shell.py` (`test_published_catalogue_entries_resolve` and published-course network scans) and `integration/test_end_to_end.py` (page quality assertions): `test_shell.py` retains the structural check that `courses.js` links resolve, while `evals/` (`EV-E2E-001`, `EV-VIS-001`, `EV-PERF-001`) evaluates every published topic in `frontend/courses/` for factual grounding, visual doctrine adherence, accessibility, and weak-Android performance budgets.

### 1.4 Target `evals/` Package Layout

```text
evals/
├── __init__.py                 # Package version, public API exports
├── __main__.py                 # CLI entry point: `python -m evals <subcommand>`
├── cli.py                      # Subcommands: run, calibrate, diff, record-edit, record-kid-test, report
├── config.py                   # EvalConfig (reads ZIVON_* + ZIVON_EVAL_* env vars; zero secrets in files)
├── models.py                   # Typed dataclasses / JSON schemas for EvalRun, CardResult, DefectSample, DiffReport
├── runner.py                   # Suite orchestrator (smoke vs full vs calibration; deterministic-first funnel)
├── store.py                    # Dual-write persistence: runs/evals/ JSONL + PostgreSQL outbox (ADR-0017)
├── diff.py                     # Run-to-run regression calculator & threshold alerter
├── report.py                   # JSON + Markdown + terminal scorecard formatter & Prometheus/dashboard emitter
├── checkers/                   # Deterministic code graders (0 model calls)
│   ├── __init__.py
│   ├── curator_checks.py       # Source pack integrity, title-line provenance, citation & number traceability
│   ├── synthesizer_checks.py   # Schema, block budget (4-45), teach-order structure, computed-geometry routing
│   ├── visual_checks.py        # JS/CSS/HTML/SVG lints, kit scope, ZivonSim skeleton, Chromium DOM/a11y/bbox probe
│   ├── perf_harness.py         # Migrated from testing/content_factory/perf/harness.py (CDP throttle, RSS, FPS, overflow)
│   └── prompt_contract_checks.py # Prompt-contract invariants migrated from unit/test_agents_generate.py & test_review.py
├── judges/                     # LLM-as-judge graders via llm_manager/ (ADR-0018)
│   ├── __init__.py
│   ├── base.py                 # LLMManager wrapper, structured JSON validation, quote-grounding verifier
│   ├── curator_judge.py        # Claim-to-passage quote verification & external-concept smuggling judge
│   ├── pedagogy_judge.py       # Reuses 03-check rubric: teach-before-test, chapter coverage, worked_example recompute
│   └── code_design_judge.py    # Reuses 09-review-facts & 09-review-design bounded procedures
├── cards/                      # Declarative eval card definitions (YAML/JSON + Python bindings)
│   ├── EV-CUR-001.yaml
│   ├── EV-SYN-001.yaml
│   ├── EV-SYN-002.yaml
│   ├── EV-VIS-001.yaml
│   ├── EV-PERF-001.yaml
│   ├── EV-REV-001.yaml
│   ├── EV-REV-002.yaml
│   ├── EV-E2E-001.yaml
│   └── EV-KID-001.yaml
└── goldens/                    # Versioned golden inputs, expected properties, profiles, and seeded defects
    ├── manifest.json           # Registry of golden topics + schema version + pipeline_version compatibility
    ├── profiles/
    │   ├── weak-android.json   # Shipping perf gate profile
    │   └── mid-laptop.json     # Dev/CI fast perf profile
    ├── topics/
    │   ├── class-9-motion/
    │   ├── class-11-motion-in-a-straight-line/
    │   ├── class-9-forces-reference-kit/
    │   └── class-10-light-reflection-and-refraction/
    └── defects/
        ├── 03-check/           # Seeded bad + clean samples for Comprehension & Fact Reviewer calibration
        └── 09-review/          # Seeded bad + clean samples for Code & Design Reviewer calibration
```

---

## 2. Eval Card Design (Per Factory Stage + End-to-End)

Every eval card follows two non-negotiable rules from [`skills/prompting-and-agent-design/SKILL.md`](../../../skills/prompting-and-agent-design/SKILL.md) (`[S2]`, `[S7]`):
1. **Deterministic-First Funnel**: Code-based graders (`evals/checkers/`) always run before any LLM judge (`evals/judges/`). If a deterministic check fails a fatal invariant (e.g., broken schema, missing citation, `eval()` in JS), the card records the deterministic failure and skips the expensive LLM judge call unless `--force-judge` is passed.
2. **Single Rubric Source of Truth**: Evals **never** invent parallel rubrics that drift from the factory's own gates. `evals/judges/` imports and reuses the exact severity ladders, category enums (`REVIEW_CATEGORIES` in `factory/schemas.py`), bounded 5-step procedures (`_FACTS_TASK`, `_DESIGN_TASK` in `factory/review.py`), and coverage/recompute laws (`factory/agents.py`), plus the `unverified:` minor hedge.

### 2.1 Card Summary Matrix

| Card ID | Factory Stage(s) | Role Evaluated | Deterministic Checkers (`0` calls) | LLM Judge (`llm_manager` calls) | Smoke Suite? | Full Suite? |
|---|---|---|---|---|---|---|
| `EV-CUR-001` | `00-ingest`, `01-locate`, `02-generate.ground_truth` | Curator citation integrity & source provenance | `curator_checks.py` (`matched_via`, `rule_citations`, `rule_numbers`) | `curator_judge.py` (`1` call/topic: quote fidelity + zero smuggled priors) | Yes (det. only) | Yes |
| `EV-SYN-001` | `02-generate.blocks`, `04-repair` | Synthesizer block-schema validity, coverage & geometry routing | `synthesizer_checks.py` (`GENERATED` schema, 4–45 blocks, `run_all_rules`, 0 graph SVGs) | `pedagogy_judge.py` (`1` call/topic shared with `EV-SYN-002`: chapter inventory coverage) | Yes (det. only) | Yes |
| `EV-SYN-002` | `02-generate.lesson`, `02-generate.blocks` | Synthesizer pedagogy, teach-before-test & numerical recomputation | `synthesizer_checks.py` (`rule_self_containment`, `rule_answer_keys`, glossary/section density) | `pedagogy_judge.py` (reuses `03-check` prompt: teach-before-test + arithmetic recompute) | Yes (det. only) | Yes |
| `EV-VIS-001` | `05-interactive`, `06-render` | Visual Builder renderability, kit scope, a11y & computed sims | `visual_checks.py` (`lint_js/css/html`, `lint_page_css_scope`, Chromium 0-error load, DOM/a11y/bbox) | `code_design_judge.py` (`2` calls/topic: reuses `09-review-facts` Step 3 + `09-review-design`) | Yes (det. + DOM) | Yes |
| `EV-PERF-001` | `07-perf`, `08-fixloop` | Performance Engineer weak-Android budget & fixloop preservation | `perf_harness.py` (`weak-android.json`: RSS, FPS, load, FCP, `overflow_px <= 2`, pedagogy diff guard) | `0` calls (or `1` call if `08-fixloop` modified `page.js` to audit physics preservation) | Yes (`mid-laptop`) | Yes (`weak-android`) |
| `EV-REV-001` | `03-check` | Comprehension & Fact Reviewer calibration (seeded defects + clean goldens) | `curator_checks.py` + `synthesizer_checks.py` on seeded corpus | Runs `factory.agents.run_check` on `8` calibration samples (`8` calls) | No (mocked schema only) | Yes |
| `EV-REV-002` | `09-review` (`facts`, `design`, `static`, `lint`) | Code Reviewer security, consistency & rendering calibration | `lint.py` + `_static_review_findings` on `5` security/scope defect samples (`0` calls) | Runs `factory.review.run` on `6` truth/rendering samples (`12` calls) | Yes (det. security defects) | Yes |
| `EV-E2E-001` | `00-ingest` → `11-link` | End-to-end page quality, catcher convergence & human edit rate | Full artifact + manifest + ledger audit + `git diff` human edit counter | Aggregates stage judges (`0` extra calls when stage cards run) | Yes (golden artifacts) | Yes |
| `EV-KID-001` | Post-`11-link` (Gate B) | Kid-comprehension sessions & defect promotion loop | Schema & completeness check on recorded `eval_kid_session` rows (`0` calls) | `0` calls (human-in-the-loop Gate B observations) | Yes (schema check) | Yes |

---

### 2.2 Detailed Card Specifications

#### Card `EV-CUR-001`: Curator Citation Integrity & Source Provenance
- **Stage**: `00-ingest` + `01-locate` + `02-generate` (`ground_truth` layer).
- **Golden Inputs**:
  - `sources/catalog.json` + cached NCERT chapter PDFs (`ncert-science-9` Ch. 8 *Motion*, `ncert-physics-11-part1` Ch. 2 *Motion in a Straight Line*, `ncert-science-10` Ch. 9 *Light – Reflection and Refraction*) + contamination-pair fixtures (`testing/content_factory/mocks/fixtures/pdfs/kinem-ch02.pdf` and `kinem-ch04.pdf`).
- **Deterministic Checks (`evals/checkers/curator_checks.py`)**:
  1. `check_title_provenance`: Asserts `source_pack["chapter"]["matched_via"] == "title_line"` for every canonical chapter query; verifies the `kinem-ch02` vs `kinem-ch04` body-phrase trap resolves to `ch02.pdf` with zero false-exact promotion.
  2. `check_table_and_glyph_extraction`: Verifies extracted `ncert_text` contains zero private-use `U+F0XX` symbol-font artifacts and preserves `[table]` pipe-delimited rows where ruled tables exist.
  3. `check_ground_truth_citations`: Runs `factory/checks.py::rule_citations` and `factory/schemas.py::GROUND_TRUTH` validation — every claim (`12..40`), key term (`>= 4`), equation, and misconception has `>= 1` citation whose `source_id` is in `{"ncert"} | {s["source_id"] for s in source_pack["supplements"]}`.
  4. `check_verbatim_numbers_in_claims`: Verifies every numeral in `ground_truth.claims[*].statement` satisfies `factory/checks.py::_number_in_corpus` against `source_pack["ncert_text"]` + supplement texts (no unit conversion or invented constants in `ground_truth`).
- **LLM-Judge Rubric (`evals/judges/curator_judge.py`)**:
  - **Prompt Contract**: Given `SOURCE MATERIAL` and `GROUND TRUTH`, verify each `claim-NN` and `eq-NN` in one pass.
  - **Severity Ladder** (reused from `03-check`):
    - `fatal`: A claim or equation contradicts the cited source passage, or cites a passage that does not support the claim. Must quote the exact source text.
    - `major`: A claim smuggles in a Physics concept from outside the source pack (e.g., introducing `F = ma` or momentum inside a kinematics-only chapter pack).
    - `minor`: Wording/formatting or unverifiable suspicion prefixed `unverified:`.
  - **Anchor Examples**:
    - *Anchor 1 (Fatal)*: `{"claim_id": "claim-04", "severity": "fatal", "message": "Claim states acceleration due to gravity is 10 m/s²; source pack [ncert page 102] states 9.8 m s-2."}`
    - *Anchor 2 (Major — Smuggled Concept)*: `{"claim_id": "claim-11", "severity": "major", "message": "Claim defines kinetic energy (1/2 mv²), which appears nowhere in the Motion in a Straight Line source pack."}`
- **Pass Thresholds**:
  - Deterministic checks: `100%` pass (`0` fatal, `0` major).
  - Judge checks: `0` fatal issues, `0` major smuggled-concept issues, `claim_quote_precision >= 0.98`.
- **Cost in Model Calls**: `0` calls (smoke) / `1` call per topic (full).

#### Card `EV-SYN-001`: Synthesizer Block-Schema Validity, Coverage & Computed-Geometry Routing
- **Stage**: `02-generate` (`blocks` layer) + `04-repair`.
- **Golden Inputs**: Golden source packs + `02-generate/output.json` (and `04-repair/output.json` when repair ran).
- **Deterministic Checks (`evals/checkers/synthesizer_checks.py`)**:
  1. `check_generated_schema`: Validates against `factory/schemas.py::GENERATED` and `BLOCKS` (`{"blocks": {"blocks": [...]}}` wrapper, `4 <= len(blocks) <= 45`, `id` matches `^b-[0-9]{2}$`).
  2. `check_block_ordering_and_citations`: First block is `text`, last block is `check`, every lesson section has `>= 1` check, and `factory/checks.py::run_all_rules` returns `verdict == "pass"` (`0` fatal, `0` major on `rule_citations`, `rule_numbers`, `rule_answer_keys`, `rule_diagram_svg`).
  3. `check_computed_geometry_routing` (per 2026-11-09 founder rule, 0.3.17): Scans all `diagram` blocks; flags `fatal` if a static SVG `diagram` block plots a mathematical function, coordinate graph (`x-t`, `v-t`, `a-t`), area-under-curve polygon/rect, or trajectory instead of routing it to a `simulation` block.
  4. `check_prompt_contracts`: Verifies `factory/agents.py` prompt invariants (wrapper shape example, `4-45 blocks` budget matching `BLOCKS["properties"]["blocks"]["maxItems"]`, grounding law, coverage contract, computed-geometry routing instruction).
- **LLM-Judge Rubric (`evals/judges/pedagogy_judge.py` — Coverage Pass)**:
  - Reuses `03-check` Item 7 (`COVERAGE` in `factory/agents.py`): inventories the source chapter's titled sections, in-text questions (*Pause and Ponder*, *Think as a Scientist*), worked examples, and distinct end-of-chapter exercise types, then checks that every section and distinct exercise type is mapped to a block (allowing same-type repetitive drills to fold into one representative block).
  - **Anchor Example (Fatal Coverage Omission)**:
    - `{"block_id": null, "severity": "fatal", "category": "content", "message": "Page omits Section 2.6 'Relative Velocity' and Exercise 2.14 (relative motion numerical type) from NCERT Ch. 2 [ncert pages 23-25]."}`
- **Pass Thresholds**:
  - Schema & deterministic rules: `100%` pass (`0` violations).
  - Computed-geometry routing: `0` static graph diagrams (`100%` routed to `simulation`).
  - Chapter section & exercise-type coverage: `1.00` (`0` omitted chapter sections or exercise types).
- **Cost in Model Calls**: `0` calls (smoke) / `1` call per topic shared with `EV-SYN-002` (full).

#### Card `EV-SYN-002`: Synthesizer Pedagogy, Teach-Before-Test & Mathematical Recomputation
- **Stage**: `02-generate` (`lesson` + `blocks` layers).
- **Golden Inputs**: Golden source packs + `ground_truth`, `lesson`, `blocks`.
- **Deterministic Checks (`evals/checkers/synthesizer_checks.py`)**:
  1. `check_self_containment`: Runs `factory/checks.py::rule_self_containment` (`0` hits on `"previous chapter"`, `"the textbook"`, `"Figure X.Y"`, `"Exercise N"`, external URLs).
  2. `check_answer_key_consistency`: Runs `factory/checks.py::rule_answer_keys` (MCQ `0 <= answer_index < len(options)`, `answer == options[answer_index]`, numeric `float(answer)` parses).
  3. `check_readability_and_structure`: Verifies `len(lesson["objectives"]) in range(2, 5)`, `len(lesson["glossary"]) >= 3`, paragraph sentence count `<= 6`, and every `worked_example` has `>= 1` step with non-empty `title` and `detail`.
- **LLM-Judge Rubric (`evals/judges/pedagogy_judge.py` — Pedagogy & Recompute Pass)**:
  - Reuses `03-check` Items 1–6 (`factory/agents.py`):
    1. **Recompute (`fatal`)**: Independently recomputes every `worked_example` and numeric `check` from its verbatim problem numbers using only equations in `ground_truth.equations`. Any arithmetic or unit error is `fatal`.
    2. **Teach-Before-Test (`major`)**: Compares each `check` block's `expected_understanding` against the preceding `lesson` sections and `text` blocks. Testing a concept before teaching it is `major`.
    3. **Teaching Order & Age Fit (`major`/`minor`)**: Checks that each section progresses from everyday observation → plain definition → symbol/equation, pitched at `class_level`.
  - **Anchor Examples**:
    - *Anchor 1 (Fatal Wrong Recomputation — from run `000509` b-21)*: `{"block_id": "b-21", "severity": "fatal", "category": "answer_key", "message": "Problem states u = 126 km/h (35 m/s), v = 0, s = 200 m; v² - u² = 2as gives a = -3.06 m/s² and t = 11.4 s, but block states 3.94 m/s² and 8.9 s."}`
    - *Anchor 2 (Major Teach-Before-Test Gap — from run `040410` b-19)*: `{"block_id": "b-19", "severity": "major", "category": "content", "message": "Check b-19 requires kinematic stopping-distance scaling (s ∝ u²), which is not derived in the lesson text preceding b-19."}`
- **Pass Thresholds**:
  - Numerical recomputation accuracy: `1.00` (`0` wrong answers or steps).
  - Teach-before-test compliance: `1.00` (`0` untaught checks).
  - Self-containment: `0` external references.
- **Cost in Model Calls**: `0` calls (smoke) / `1` call per topic shared with `EV-SYN-001` (full).

#### Card `EV-VIS-001`: Visual Builder Renderability, Kit Scope, Accessibility & Computed Sims
- **Stage**: `05-interactive` + `06-render`.
- **Golden Inputs**: Rendered topic directory (`index.html`, `page.js`, `page.css`, `manifest.json`), `blocks.json`, `gt.json`, `docs/frontend/design-doctrine.md`, `docs/frontend/design-doctrine-lesson-example.html`, `frontend/assets/zivon.css`, `frontend/assets/zivon.js`.
- **Deterministic Checks (`evals/checkers/visual_checks.py`)**:
  1. `check_hard_lints_and_kit_scope`: Runs `lint_html`, `lint_js`, `lint_css`, and `lint_page_css_scope` (`0` hits; every selector in `page.css` scoped under `.zn-sim-<id>`; zero canvas width/height/aspect-ratio overrides; palette hex/var compliance).
  2. `check_computed_sim_loop`: Static AST/regex scan of each `ZivonSim.register("<id>", ...)` in `page.js` confirming `draw(ctx)` computes curves via loop/equation evaluation (`for`/`while` over domain) with `0` sequences of `>= 4` hard-coded `moveTo`/`lineTo` literal coordinate pairs.
  3. `check_chromium_render_and_a11y`: Launches headless Chromium against `file://.../index.html`:
     - `0` `console.error` and `0` `pageerror` events on load and after interacting with every range slider and `.zn-check-btn`.
     - Kit chrome present: `.zn-lang-bar` with `aria-checked="true"`, every `.zn-sim` has `<p class="zn-sim-read" aria-live="polite">` and `page.js` populates non-empty text into `.zn-sim-read` after `init`/`draw` (catching the run `040410` unpopulated `.zn-sim-read` defect deterministically!).
     - Every `<svg>` has `viewBox`, no fixed `width`/`height` attributes, and accessible label/caption.
     - Card geometry check (from `test_behaviour_layer.py::test_long_question_stays_inside_the_card`): for every `.zn-check` fieldset, `legend.top >= card.top - 1` and `firstOption.top >= legend.bottom - 1`.
- **LLM-Judge Rubric (`evals/judges/code_design_judge.py`)**:
  - Reuses the two bounded `09-review` procedures (`_FACTS_TASK` Step 3 `drawn_behaviour` + `_DESIGN_TASK` Steps 1–4 `visual_language`, `frame`, `accessibility`, `rendering` in `factory/review.py`).
  - **Anchor Examples**:
    - *Anchor 1 (Fatal Drawn Behaviour)*: `{"block_id": "b-08", "severity": "fatal", "category": "drawn_behaviour", "message": "In b-08 draw(), position x is updated as u*t + a*t² instead of u*t + 0.5*a*t², contradicting eq-02."}`
    - *Anchor 2 (Major Rendering Sweep — from 0.3.13 live probe)*: `{"block_id": "b-05", "severity": "major", "category": "rendering", "message": "b-05 Point P circle is drawn at (180, 110) off the parabola y(x), so the tangent line reads visually as a secant."}`
- **Pass Thresholds**:
  - Deterministic lint, kit scope, `.zn-sim-read` population, & Chromium geometry: `100%` pass.
  - Judge verdict: `0` fatals (`verdict == "pass"`), `<= 1` major rendering/accessibility finding per page.
- **Cost in Model Calls**: `0` calls (smoke, incl. headless Chromium checks) / `2` calls per topic (full: `facts` + `design`).

#### Card `EV-PERF-001`: Performance Engineer Weak-Android Budget & Fixloop Audit
- **Stage**: `07-perf` + `08-fixloop`.
- **Golden Inputs**: Staged/published site root (`frontend/index.html` + `frontend/courses/<course>/<slug>/index.html`) + `evals/goldens/profiles/weak-android.json` and `mid-laptop.json`.
- **Deterministic Checks (`evals/checkers/perf_harness.py`)**:
  1. Runs `run_profile(url, profile_path)` with CDP 4x CPU throttle and 2-core affinity (`weak-android.json`):
     - `peak_browser_rss_mb <= 750.0`
     - `fps_median >= 24.0` during scroll + check click + `sim_seconds` canvas run
     - `overflow_px <= 2` at `360px` (`weak-android`) and `1280px` (`mid-laptop`)
     - `load_s <= 6.0` (Phase 1–3 current gate) and tracked against `2.0s` Phase 4 target (`AGENTS.md` / `TIMELINE.md`)
     - `fcp_s <= 3.5` (Phase 1–3 current gate) and tracked against `1.2s` Phase 4 target
     - `console_errors == []` and `page_errors == []`
  2. `check_fixloop_pedagogy_preservation`: When `08-fixloop` ran (`rounds > 0`), verifies that `index.html` and `manifest.json` are byte-identical to `06-render` output (renderer-owned file guard) and that every simulation `block_id` registered in `05-interactive` is still registered and drawing in `page.js`.
- **LLM-Judge Rubric**: None (`0` calls) when `rounds == 0`. If `08-fixloop` modified `page.js` (`rounds > 0`), `09-review-facts` Step 3 (`drawn_behaviour`) verifies the optimization did not strip physics equations.
- **Pass Thresholds**: `pass == True` on `weak-android.json` (`0` budget failures) and `100%` pedagogy preservation.
- **Cost in Model Calls**: `0` calls.

#### Card `EV-REV-001`: Comprehension & Fact Reviewer (`03-check`) Calibration
- **Stage**: `03-check` (`factory/agents.py::run_check` + `factory/checks.py::run_all_rules`).
- **Purpose**: A reviewer gate that passes everything or fails everything is broken scaffolding (`skills/prompting-and-agent-design/SKILL.md` `[S2][S7]`). This card tests the **reviewer itself** against a balanced corpus of seeded defects and clean goldens.
- **Golden Inputs**: `evals/goldens/defects/03-check/SD-CHK-001..008.json` (detailed in [`golden-sets.md`](golden-sets.md)).
- **Deterministic Checks**:
  - Verifies `factory/checks.py::run_all_rules` deterministically catches all code-checkable defects (invented problem numerals, missing citations, answer-key index mismatch, external references) before model call.
  - Verifies `03-check` prompt contract (`Severity ladder (apply it exactly)`, `THE LESSON THE PAGE TEACHES`, `RECOMPUTE every worked_example`, `COVERAGE`, `unverified:`, no adversarial `"Assume the draft contains at least one error"`).
- **LLM-Judge Execution (Reviewer Under Test)**:
  - Invokes `factory.agents.run_check` via `llm_manager` against each of the `8` calibration samples (`6` seeded-bad, `2` clean goldens) and grades the reviewer's returned `CHECK_REPORT` against the sample's ground-truth `expected_verdict`, `expected_severity`, `expected_block_id`, and `must_quote_source`:

| Sample ID | Planted Defect / Condition | Expected Reviewer Output |
|---|---|---|
| `SD-CHK-001` | Contradicts source fact (`b-03` claims velocity is a scalar with SI unit `km/h`) | `verdict: "fail"`, `severity: "fatal"` on `b-03`, quotes source passage |
| `SD-CHK-002` | Wrong computed numerical answer (`b-21` stopping acceleration `3.94 m/s²` instead of `3.06 m/s²`, from run `000509`) | `verdict: "fail"`, `severity: "fatal"` on `b-21` |
| `SD-CHK-003` | Smuggled out-of-chapter concept (`b-28` tests SHM `T = 2π√(l/g)` in Class 11 Ch. 2 Kinematics, from run `040410`) | `severity: "major"` on `b-28` (triggers `04-repair`) |
| `SD-CHK-004` | Teach-before-test violation (`b-19` tests relative velocity before any lesson section introduces it, from run `040410`) | `severity: "major"` on `b-19` |
| `SD-CHK-005` | Chapter coverage omission (drops Kinematic Equations for Uniformly Accelerated Motion section & exercises) | `verdict: "fail"`, `severity: "fatal"`, quotes omitted section/exercise |
| `SD-CHK-006` | Unverifiable minor nuance (mentions standard abbreviation `"SI stands for Système International"` not spelled out in chapter) | `verdict: "pass"`, `0` fatals/majors; if noted, `severity: "minor"` (`unverified:` allowed) |
| `SD-CHK-007` | Clean Golden Page 1 (Class 9 *Motion* repaired draft) | `verdict: "pass"`, `0` fatal, `0` major (True Negative check) |
| `SD-CHK-008` | Clean Golden Page 2 (Class 11 *Motion in a Straight Line* run `040410` repaired draft) | `verdict: "pass"`, `0` fatal, `0` major (True Negative check) |

- **Pass Thresholds**:
  - **Fatal Defect Recall (Sensitivity)**: `1.00` (`3/3` of `SD-CHK-001`, `002`, `005` flagged `fatal` with `verdict="fail"` and source quote).
  - **Blocking Defect Recall (`fatal` + `major`)**: `>= 0.80` (`>= 4/5` of `SD-CHK-001..005` flagged `fatal` or `major` on the exact target `block_id`).
  - **Clean Golden Specificity (1 − False Positive Rate)**: `1.00` (`3/3` of `SD-CHK-006..008` return `verdict="pass"` with `0` fatals and `0` false majors).
- **Cost in Model Calls**: `0` calls (smoke) / `8` calls (full calibration).

#### Card `EV-REV-002`: Code Reviewer (`09-review`) Security, Consistency & Rendering Calibration
- **Stage**: `09-review` (`factory/lint.py` + `factory/review.py::_static_review_findings` + `09-review-facts` + `09-review-design`).
- **Golden Inputs**:
  - `5` deterministic security/scope defect bundles (`SD-SEC-001..005`).
  - `6` model-reviewer calibration bundles (`SD-REV-001..006`) in `evals/goldens/defects/09-review/`.
- **Part A — Deterministic Security & Scope Calibration (`0` model calls, runs in Smoke & Full)**:
  - `SD-SEC-001`: `eval("1+1")` and `new Function(...)` in `page.js` → caught by `lint_js` (`LintError`).
  - `SD-SEC-002`: `fetch("https://...")` in `page.js`, `@import url("https://...")` in `page.css`, `<img src="https://...">` in `index.html`, `<a href="https://...">` in SVG → caught by `lint_js`, `lint_css`, `lint_html`, `rule_diagram_svg`.
  - `SD-SEC-003`: Inline `<script>` in `index.html` and `onload=` in `<svg>` → caught by `lint_html` (`html.parser` scan) and `rule_diagram_svg`.
  - `SD-SEC-004`: Missing `Content-Security-Policy` meta tag, missing `lang="en"`, or empty `manifest.json` `sources` → caught by `_static_review_findings` as `fatal`.
  - `SD-SEC-005`: Unscoped `.zn-lang-bar` selector or `.zn-sim-b-04 canvas { width: 100% }` in `page.css` → caught by `lint_page_css_scope`.
- **Part B — Model Reviewer Calibration (`09-review-facts` + `09-review-design`, `2` calls per sample = `12` calls in Full)**:

| Sample ID | Planted Defect / Condition | Target Reviewer Call | Expected Reviewer Output |
|---|---|---|---|
| `SD-REV-001` | HTML-vs-JS inconsistency (`index.html` shows `49 s` while `page.js` rewrites DOM to `37 s`, from run `180935` b-31) | `09-review-facts` | `severity: "fatal"`, `category: "inconsistency"`, `block_id: "b-31"`, harness `verdict: "fail"` |
| `SD-REV-002` | Simulation draw loop contradicts cited equation (`page.js` draws downward parabola for positive acceleration) | `09-review-facts` | `severity: "fatal"`, `category: "drawn_behaviour"`, `block_id: "b-06"`, harness `verdict: "fail"` |
| `SD-REV-003` | Hand-drawn rectangle for trapezoid area under diagonal `v–t` line (`u > 0`, from run `032406` b-09) | `09-review-design` | `severity: "fatal"`, `category: "rendering"`, `block_id: "b-09"`, harness `verdict: "fail"` |
| `SD-REV-004` | Point P circle drawn off the curve so tangent line reads as a secant (from 0.3.13 live probe b-05) | `09-review-design` | `severity: "major"` or `"fatal"`, `category: "rendering"`, `block_id: "b-05"` |
| `SD-REV-005` | Interactive canvas lacks `aria-live` readout updates in `.zn-sim-read` and SVG lacks accessible name | `09-review-design` | `severity: "major"`, `category: "accessibility"` |
| `SD-REV-006` | Clean Golden Render (Class 11 *Motion in a Straight Line* run `040410` final files) | Both calls | `0` fatals in both calls, harness `verdict: "pass"` |

- **Pass Thresholds**:
  - Part A (Security & Scope): `100%` catch rate (`5/5`).
  - Part B (Fatal Recall): `1.00` (`3/3` of `SD-REV-001..003` flagged `fatal` with `verdict="fail"`).
  - Part B (Major Recall): `>= 1.00` (`2/2` of `SD-REV-004..005` flagged `major` or `fatal` with matching `category`).
  - Part B (Clean Golden Specificity): `1.00` (`SD-REV-006` returns `verdict="pass"` with `0` fatals).
  - Thinking-Loop Guard: `max_completion_tokens <= 35000` and `length_cuts == 0` across all `12` calls.
- **Cost in Model Calls**: `0` calls (smoke) / `12` calls (full calibration).

#### Card `EV-E2E-001`: End-to-End Topic Page Quality, Catcher Convergence & Human Edit Rate
- **Stage**: Full pipeline (`00-ingest` → `11-link`) + post-publish diff (`frontend/courses/`).
- **Golden Inputs**: Run directory `runs/<run_id>/` (`status.json`, `run_report.json`, `calls_ledger.jsonl`, `issues_ledger.jsonl`) and published snapshot `frontend/courses/<course_id>/<topic_slug>/`.
- **Deterministic Checks & Metrics Computed**:
  1. `pipeline_completed_ok`: `run_report["ok"] is True` and `status["stages"]["11-link"]["state"] == "ok"`.
  2. `catcher_convergence_rate`: For every catcher stage that ran (`04-repair`, `08-fixloop`, `10-reviewfix`), verifies `blocking_score` (`2 * fatals + 1 * majors`) strictly decreased from round `0` to final round with `0` stall-out failures.
  3. `recurring_plateau_count`: Runs `scripts/issue_report.py::aggregate` logic on `issues_ledger.jsonl`; checks count of recurring `(stage, call, block_id, category)` tuples across `>= 3` rounds.
  4. `thinking_efficiency`: From `calls_ledger.jsonl`, computes `total_thinking_s = sum(first_token_s)`, `max_completion_tokens`, `validation_rejection_rate`, and `length_cuts` (`must == 0`).
  5. `human_edit_rate` (**Key Pipeline Metric from `TIMELINE.md` Day 2 & Day 3**):
     - Measured by comparing the factory's stage `11-link` output snapshot against the final committed files in `frontend/courses/<course_id>/<topic_slug>/{index.html,page.js,page.css}`:
       $$\text{human\_edit\_rate} = \frac{\text{manual\_changed\_lines}}{\text{total\_generated\_lines}}, \quad \text{human\_edits\_count} = \text{number of manual commits/hunks post-publish}$$
     - Target: `human_edits_count == 0` (`human_edit_rate == 0.00`) for unattended topic generation.
- **Pass Thresholds**:
  - `pipeline_completed_ok == True`
  - `length_cuts == 0`
  - `human_edits_count == 0` (alert if `> 0`)
- **Cost in Model Calls**: `0` additional calls (aggregates stage card outputs + run ledgers).

#### Card `EV-KID-001`: Gate B Kid-Comprehension & Defect Promotion Loop
- **Stage**: Post-publish human validation (Gate B, `TIMELINE.md` Day 4 & Day 7; post-challenge P1 continuous loop).
- **Golden Inputs**: Recorded kid-tester session records (`eval_kid_session` rows — see §6.3).
- **Deterministic Checks**:
  - Validates each session record against `KID_SESSION_SCHEMA` (pseudonymous `tester_code` e.g. `kid-01`, `tester_class` `6..12`, `topic_slug`, `lesson_version_id`, `is_above_class_level: bool`, `restated_in_own_words: bool`, `followup_1_correct: bool`, `followup_2_correct: bool`, `confusion_blocks: list[str]`, `promoted_defect_id: str | None`).
  - Computes Gate B pass criteria across the cohort (`N >= 3` testers per round):
    - Criterion 1: `sum(restated_in_own_words and followup_1_correct and followup_2_correct) / N >= 2/3` (`>= 0.67`).
    - Criterion 2: `any(is_above_class_level and restated_in_own_words and followup_1_correct and followup_2_correct) is True`.
    - Criterion 3: Every `confusion_blocks` entry on a failed session must reference a valid `block_id` and link to either a prompt/kit fix commit or a newly seeded defect sample (`promoted_defect_id`).
- **Pass Thresholds**: Cohort comprehension pass rate `>= 0.67` (`>= 2/3` kids) + `>= 1` above-level pass.
- **Cost in Model Calls**: `0` calls.

---

## 3. Golden Sets Summary (Full Detail in [`golden-sets.md`](golden-sets.md))

The golden dataset is organized into three versioned layers under `evals/goldens/`:
1. **Golden Topics (`evals/goldens/topics/<topic_id>/`)**:
   - `GT-01` (`class-9-motion`): NCERT Class 9 Science (2025 ed.) Ch. *Motion* → published at `frontend/courses/class-9-physics/how-forces-affect-motion/`.
   - `GT-02` (`class-11-motion-in-a-straight-line`): NCERT Class 11 Physics Part I Ch. 2 *Motion in a Straight Line* + OpenStax HS Physics → published at `frontend/courses/class-11-physics/motion-in-a-straight-line/` (validated in run `040410` on `0.3.17`).
   - `GT-03` (`class-9-forces-reference-kit`): NCERT Class 9 Ch. 6 *How Forces Affect Motion* complete reference page → committed at `docs/frontend/design-doctrine-lesson-example.html` (all 7 titled sections, 11 checks, 11 worked examples, 3 sims, 4 diagrams, 1 reveal).
   - `GT-04` (`class-10-light-reflection-and-refraction`): NCERT Class 10 Science (`ncert-science-10`, `jesc109.pdf`) + Siyavula Grade 10 (`siyavula-physical-sciences-10`) — the 3rd curriculum tier from `TIMELINE.md` Day 0 (`Class 9 Motion, Class 10 Light: Reflection, Class 11 Kinematics`), with frozen `expected.json` property contract ready for unattended generation verification.
2. **Seeded-Defect Calibration Sets (`evals/goldens/defects/`)**:
   - `03-check/SD-CHK-001..008.json` (`8` samples: `5` planted defects derived from real production failures in `TIMELINE.md` + `1` unverifiable minor hedge + `2` clean goldens).
   - `09-review/SD-SEC-001..005.json` (`5` deterministic security/scope defects) and `09-review/SD-REV-001..006.json` (`5` planted truth/rendering/a11y defects from real runs `180935`, `032406`, `040410` + `1` clean golden).
3. **Expected-Property Contracts (`expected.json`)**:
   - Instead of brittle byte-for-byte HTML snapshots that break whenever a model rephrases a sentence, each golden topic defines structural and semantic invariants in `expected.json` (required section titles, minimum claim/equation/check/worked_example counts, required simulation physics variables, exact numerical answers for canonical textbook exercises, and performance budgets).

---

## 4. Regression Tracking, Persistence & Human-Edit-Rate Capture

### 4.1 Persistence Architecture (Traceable to `db-spec.md` & `storage-tiering.md`, [`ADR-0017`](../../backend/adr/0017-eval-result-store-and-tiering.md))

Following [`skills/zivon-systems-design-skills/`](../../../skills/zivon-systems-design-skills/skills/zivon-systems-design/SKILL.md) (`references/02-data-classification-and-tiering.md` and `references/03-database-spec-method.md`), eval artifacts and relational records are phased so P0 works with zero database dependencies while Phase B/production persists into PostgreSQL and cold object storage:

- **Phase A (P0 / Build-Time / Offline Cluster)**:
  - `evals/store.py` writes append-only JSONL ledgers (`runs/evals/eval_runs_ledger.jsonl`, `runs/evals/eval_cards_ledger.jsonl`, `runs/evals/human_edits_ledger.jsonl`, `runs/evals/kid_sessions_ledger.jsonl`) and per-run directories (`runs/evals/<eval_run_id>/eval_report.json`, `diff_report.json`, `eval_summary.md`) onto the `zivon-sources` PVC (`subPath: evals`, alongside `subPath: runs`).
  - `scripts/publish-artifacts.sh` mirrors `evals/` alongside `runs/` to the host for offline inspection.
- **Phase B (PostgreSQL + Cold Storage Tiering — `db-spec.md` & `storage-tiering.md` Alignment)**:
  - When `ZIVON_DB_URL` is configured, `evals/store.py` dual-writes into five PostgreSQL tables using **UUIDv7** primary keys, `timestamptz` UTC timestamps, and JSONB payload columns validated by `evals/models.py`:

| Table Name | Primary Key | Purpose & Foreign Keys | Data Class & Tier (`storage-tiering.md`) | Traceability (`db-spec.md`) |
|---|---|---|---|---|
| `eval_run` | `id UUID` (UUIDv7) | One row per eval suite execution: `suite` (`smoke`\|`full`\|`calibration`), `pipeline_version` (`INT`), `factory_image_tag`, `generator_model`, `judge_model`, `git_sha`, `prompt_bundle_sha256`, `started_at`, `completed_at`, `duration_s`, `overall_pass`, `regression_detected`, `baseline_eval_run_id UUID NULL`, `model_calls_count`, `total_thinking_s`, `report_object_id UUID NULL`. | `C4` (Content-factory & eval evidence): Hot on Postgres + SSD PVC (`zivon-sources`) for 90 days; full bundle archived to Cold S3-compatible object store on completion via transactional outbox (`object` catalogue table). | `SYSTEMS-ORIGINATED` / `NEED-EVAL-TRACKING` |
| `eval_card_result` | `id UUID` (UUIDv7) | One row per `(eval_run_id, card_id, topic_slug)`: `eval_run_id UUID NOT NULL REFERENCES eval_run(id)`, `card_id VARCHAR(32)` (`EV-CUR-001`..`EV-KID-001`), `topic_slug VARCHAR(128) NULL`, `lesson_version_id UUID NULL`, `verdict` (`pass`\|`fail`\|`skip`), `deterministic_score NUMERIC(5,4)`, `judge_score NUMERIC(5,4) NULL`, `fatal_count INT`, `major_count INT`, `minor_count INT`, `unverified_count INT`, `metrics JSONB` (FPS, RSS, load_s, recall, specificity), `issues JSONB`, `created_at TIMESTAMPTZ`. | `C4`: Hot in Postgres (indexed on `(card_id, topic_slug, created_at DESC)`); archived in `eval_run` cold bundle. | `SYSTEMS-ORIGINATED` / `NEED-EVAL-TRACKING` |
| `eval_defect_sample_result` | `id UUID` (UUIDv7) | Per-sample calibration outcome for `EV-REV-001` and `EV-REV-002`: `eval_card_result_id UUID REFERENCES eval_card_result(id)`, `sample_id VARCHAR(32)` (`SD-CHK-001`..), `expected_verdict`, `actual_verdict`, `expected_severity`, `actual_severity`, `target_block_matched BOOL`, `source_quoted BOOL`, `outcome_class` (`TP`\|`TN`\|`FP`\|`FN`), `latency_s NUMERIC(8,2)`, `thinking_s NUMERIC(8,2)`, `completion_tokens INT`. | `C4`: Hot in Postgres; archived with `eval_run`. | `SYSTEMS-ORIGINATED` / `NEED-JUDGE-CALIBRATION` |
| `eval_human_edit` | `id UUID` (UUIDv7) | Tracks the founder's key pipeline metric (**human edit rate per generated topic**, `TIMELINE.md`): `topic_slug VARCHAR(128)`, `course_id VARCHAR(64)`, `class_level SMALLINT`, `factory_run_id VARCHAR(128)`, `pipeline_version INT`, `lesson_version_id UUID NULL`, `generated_git_sha CHAR(40)`, `published_git_sha CHAR(40)`, `total_generated_lines INT`, `manual_added_lines INT`, `manual_deleted_lines INT`, `human_edit_rate NUMERIC(6,4)`, `edit_categories JSONB` (`["content", "rendering", "css", "js"]`), `notes TEXT`, `recorded_at TIMESTAMPTZ`. | `C4`: Permanent in Postgres (`retention: forever`, zero PII, < 1 KB/row) + included in daily DB backups (`C14`). | `INF-HUMAN-EDIT-RATE` / `NEED-PIPELINE-RELIABILITY` |
| `eval_kid_session` | `id UUID` (UUIDv7) | Gate B kid-comprehension observation row: `session_code VARCHAR(32)` (pseudonymous `kid-r1-01`), `consent_record_id UUID NULL REFERENCES consent_record(id)`, `topic_slug VARCHAR(128)`, `lesson_version_id UUID NULL`, `tester_class SMALLINT`, `topic_class SMALLINT`, `is_above_class_level BOOL`, `restated_in_own_words BOOL`, `followup_1_correct BOOL`, `followup_2_correct BOOL`, `gate_b_pass BOOL`, `confusion_blocks JSONB`, `notes TEXT` (redacted, no child PII), `promoted_defect_id VARCHAR(32) NULL`, `recorded_at TIMESTAMPTZ`. | `C10` / `C4` hybrid: Pseudonymous, linked to `C9` `consent_record`; hard-deletable (`ON DELETE CASCADE` or tombstoned) if guardian withdraws consent (`05-privacy-security-ops.md`). | `INF-GATE-B-RESULT` / `NEED-KID-VALIDATION` |

- **Storage Tiering & "Pull the Plug" Invariant (`storage-tiering.md`)**:
  - Raw eval run directories (`runs/evals/<eval_run_id>/`) are compressed to `.tar.zst`, hashed (`sha256`), uploaded to the cold S3-compatible provider under key `c4/evals/dt=YYYY-MM-DD/<eval_run_id>/<sha256>.tar.zst`, read-back verified (`cold_verified_at` set in `object` catalogue table), and only evicted from the SSD PVC when `cold_verified_at IS NOT NULL` and age `> 14 days` (keeping the latest baseline run for each `PIPELINE_VERSION` pinned on SSD).

### 4.2 Run-to-Run Diff Reports & Regression Alerting (`evals/diff.py`)

Every `evals run` automatically compares its results against the **pinned baseline run** (by default, the most recent passing `full` eval run on `main` or the previous `PIPELINE_VERSION` baseline):

1. **Diff Dimensions Computed**:
   - **Stage Score Delta ($\Delta S_{\text{card}}$)**: Change in deterministic and judge pass rates per card (`EV-CUR-001`..`EV-E2E-001`).
   - **Reviewer Calibration Delta ($\Delta \text{Recall}, \Delta \text{Specificity}$)**: Change in `EV-REV-001` (`03-check`) and `EV-REV-002` (`09-review`) true-positive defect catch rate and clean-golden false-positive rate.
   - **Performance Budget Delta ($\Delta \text{load\_s}, \Delta \text{fps\_median}, \Delta \text{peak\_rss\_mb}$)**: Per-topic hardware metrics on `weak-android.json`.
   - **Cost & Thinking-Bloat Delta ($\Delta \text{thinking\_s}, \Delta \text{completion\_tokens}, \Delta \text{calls}$)**: Detects runaway thinking regressions (e.g., the 2026-11-08 `09-review` 130k-token loop).
   - **Human Edit Rate Trend ($\Delta \text{human\_edit\_rate}$)**: Rolling average across the last $K$ generated topics (must trend toward `0.00`).

2. **Alert Conditions (Hard Regression Exit Code `2`)**:
   - Any card that passed in the baseline run flips to `verdict == "fail"`.
   - Reviewer `fatal` defect recall in `EV-REV-001` or `EV-REV-002` drops below `1.00` (a reviewer missed a planted fatal defect).
   - Clean-golden specificity in `EV-REV-001` or `EV-REV-002` drops below `1.00` (a reviewer hallucinated a fatal on a verified golden page).
   - Any topic's `fps_median` on `weak-android` drops by `> 20%` or below `24.0 fps`, or `peak_browser_rss_mb` exceeds `750 MB`, or `overflow_px > 2`.
   - Per-call `thinking_s` or `completion_tokens` increases by `> 2.0x` on the same golden input, or `length_cuts > 0`.
   - `human_edit_rate > 0.05` (more than 5% of lines edited by hand) on a newly published topic.

### 4.3 Human-Edit-Rate Capture Workflow

To make `TIMELINE.md`'s primary metric (**human edit rate per generated topic**) automatic rather than manual bookkeeping:
1. When stage `11-link` finishes in `factory/link.py`, it writes the SHA-256 and line count of each generated file (`index.html`, `page.js`, `page.css`) into `manifest.json` under `"generation_fingerprints": {"index.html": {"sha256": "...", "lines": 412}, ...}`.
2. When `scripts/publish-frontend.sh` mirrors the topic to `frontend/courses/<course>/<slug>/` or after any human hotfix commit to `frontend/courses/`, running:
   ```bash
   python -m evals record-edit --topic class-11-physics/motion-in-a-straight-line [--notes "0 lines edited; published raw from run 040410"]
   ```
   diffs the committed files in `frontend/courses/` against the run's stage `11-link` (or `06-render`/`10-reviewfix`) snapshot in `runs/<run_id>/`, computes `manual_added_lines`, `manual_deleted_lines`, and `human_edit_rate`, and appends the record to `runs/evals/human_edits_ledger.jsonl` (and `eval_human_edit` in Postgres).

---

## 5. CI Wiring, Kubernetes CronJob (`k8s/52`) & Trigger Script

### 5.1 Fast Eval Smoke in GitHub Actions (`.github/workflows/ci.yml`)

Per protocol §7, this spec does **not** edit `.github/workflows/ci.yml` directly; the CI/CD agent or merge agent adds the `eval-smoke` job below.

**Design of the `eval-smoke` PR Gate**:
- **Scope**: Runs `python -m evals run --suite smoke` — executes all deterministic checkers (`curator_checks`, `synthesizer_checks`, `visual_checks`, `prompt_contract_checks`, `EV-REV-002` Part A security defects `SD-SEC-001..005`, and `EV-PERF-001` on `mid-laptop.json` against committed golden pages in `frontend/courses/`).
- **Cost & Speed**: `0` LLM calls, `0` API keys required (honors `AGENTS.md`: *"CI must pass key-free"*), runtime `< 45 seconds`.
- **Job specification for `.github/workflows/ci.yml`**:

```yaml
  # ---- 7. fast eval smoke (deterministic checkers + golden page audit) -------
  eval-smoke:
    name: Eval smoke (golden contracts + deterministic checkers)
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0  # v7.1.0
        with:
          python-version: "3.12"
          cache: pip
      - name: Install dependencies
        run: |
          pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu
          pip install -r requirements.txt
          python -m playwright install --with-deps chromium
      - name: Run deterministic eval smoke suite on golden sets
        run: python -m evals run --suite smoke --fail-on-regression
```

Also update the `quality` job's `mypy` command in `.github/workflows/ci.yml` to include `evals/`:
```yaml
      - name: Mypy type check
        run: mypy --ignore-missing-imports factory/ docker/ pipeline.py testing/ evals/
```

### 5.2 Scheduled Full Eval Suite (`k8s/52-eval-cronjob.yaml`)

Full eval runs (which invoke LLM judges and reviewer calibration via the in-cluster `llm-manager` Service and run the `weak-android.json` perf profile) execute on a Kubernetes `CronJob` at manifest number **`52`** (`k8s/52-eval-cronjob.yaml`), reusing the exact hardening and kube-linter patterns from `k8s/50-test-cronjob.yaml`:
- **Cadence Config**: `EVAL_CRON_SCHEDULE="0 */6 * * *"` (every 6 hours by default; configurable in `k8s/infra.env` and rendered via `envsubst` in `scripts/apply-k8s.sh` — never hardcoded in the YAML).
- **Kube-Linter Compliance (Gotcha 12)**: No `ttlSecondsAfterFinished` on the CronJob's `jobTemplate.spec`; cleanup uses `successfulJobsHistoryLimit: 3` and `failedJobsHistoryLimit: 3`.
- **Security Context (Gotchas 1 & 17)**: `automountServiceAccountToken: false`, `runAsNonRoot: true`, `runAsUser: 1000`, `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`, `readOnlyRootFilesystem: true`.
- **Model Routing**: Uses `envFrom: configMapRef: zivon-factory-config` (so `ZIVON_BASE_URL` points at `http://llm-manager.zivon.svc.cluster.local:80/v1`, never hand-rolling HTTP to the inference server) and optional `ZIVON_API_KEY` from `secretKeyRef: zivon-factory-env`.
- **Volumes**: Mounts `zivon-sources` PVC (`subPath: evals` at `/app/runs/evals` and `subPath: runs` read-only at `/app/runs/factory` so evals persist across pod deaths), `zivon-hf-cache` at `/app/.cache/huggingface` with `HF_HUB_OFFLINE=1` (Gotcha 15b), and `/tmp` as `emptyDir`.

#### `k8s/52-eval-cronjob.yaml` Specification

```yaml
# Scheduled full evaluation suite (deterministic checkers + reviewer calibration
# + LLM judges + weak-android perf gate + regression diff).
# Reuses the k8s/50-test-cronjob.yaml pattern; rendered from k8s/infra.env
# (${EVAL_CRON_SCHEDULE}) by scripts/apply-k8s.sh.
apiVersion: batch/v1
kind: CronJob
metadata:
  name: eval-suite
  namespace: zivon
  labels:
    app: zivon-factory
    component: evals
spec:
  schedule: "${EVAL_CRON_SCHEDULE}"   # rendered from k8s/infra.env
  concurrencyPolicy: Forbid           # never overlap eval runs on the single-slot/shared node
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0                 # a failing or regressing eval is a signal, never retried blindly
      activeDeadlineSeconds: 3600     # 1h safety cap for full calibration + judge suite
      # No ttlSecondsAfterFinished on CronJob jobTemplate (kube-linter gotcha 12).
      template:
        metadata:
          labels:
            app: zivon-factory
            task: eval-suite
        spec:
          restartPolicy: Never
          automountServiceAccountToken: false
          enableServiceLinks: false   # prevent legacy K8s SERVICE_PORT env collisions (gotcha 16)
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            fsGroup: 1000
          containers:
            - name: evals
              image: zivon-factory:0.3.17
              imagePullPolicy: IfNotPresent
              command:
                - python
                - -m
                - evals
                - run
                - --suite
                - full
                - --fail-on-regression
              securityContext:
                runAsNonRoot: true
                runAsUser: 1000
                allowPrivilegeEscalation: false
                capabilities:
                  drop: ["ALL"]
                readOnlyRootFilesystem: true
              envFrom:
                - configMapRef:
                    name: zivon-factory-config
              env:
                - name: HF_HUB_OFFLINE
                  value: "1"
                - name: ZIVON_API_KEY
                  valueFrom:
                    secretKeyRef:
                      name: zivon-factory-env
                      key: ZIVON_API_KEY
                      optional: true
              volumeMounts:
                - name: evals-store
                  mountPath: /app/runs/evals
                  subPath: evals
                - name: factory-runs
                  mountPath: /app/runs/factory
                  subPath: runs
                  readOnly: true
                - name: hf-cache
                  mountPath: /app/.cache/huggingface
                - name: tmp
                  mountPath: /tmp
              resources:
                requests:
                  cpu: 500m
                  memory: 1Gi
                limits:
                  cpu: "2"
                  memory: 2Gi
          volumes:
            - name: evals-store
              persistentVolumeClaim:
                claimName: zivon-sources
            - name: factory-runs
              persistentVolumeClaim:
                claimName: zivon-sources
            - name: hf-cache
              persistentVolumeClaim:
                claimName: zivon-hf-cache
            - name: tmp
              emptyDir: {}
```

### 5.3 On-Demand Trigger Script Sketch (`scripts/trigger-evals.sh`)

Mirrors `scripts/trigger-tests.sh` as the third admin "button" for the Day-8 dashboard:

```bash
#!/usr/bin/env bash
# The on-demand "button" for the in-cluster evaluation suite (stand-in for the
# Day-8 admin dashboard "Run evals now" button).
#
# Usage:
#   scripts/trigger-evals.sh                        -> clones cronjob/eval-suite (full suite)
#   scripts/trigger-evals.sh smoke                  -> one-off smoke job (0 model calls)
#   scripts/trigger-evals.sh calibrate              -> reviewer calibration only (EV-REV-001/002)
set -euo pipefail
suite="${1:-full}"
suffix="${2:-manual}"
job="eval-${suite}-${suffix}-$(date +%H%M%S)"

if [[ "$suite" == "full" ]]; then
  kubectl create job "$job" --from=cronjob/eval-suite -n zivon
else
  kubectl create job "$job" --from=cronjob/eval-suite -n zivon --dry-run=client -o json \
    | python3 -c '
import json, sys
obj = json.load(sys.stdin)
obj["spec"]["template"]["spec"]["containers"][0]["command"] = [
    "python", "-m", "evals", "run", "--suite", sys.argv[1], "--fail-on-regression"
]
print(json.dumps(obj))
' "$suite" | kubectl apply -f -
fi

echo "eval run started: job/$job (suite=$suite)"
echo "watch it: kubectl logs -f job/$job -n zivon"
```

Line-edits required in `k8s/infra.env` and `scripts/apply-k8s.sh` when the execution agent builds `evals/`:
- `k8s/infra.env`: Add `EVAL_CRON_SCHEDULE="0 */6 * * *"` and optional `ZIVON_EVAL_JUDGE_MODEL` (defaults to `ZIVON_MODEL` if unset; see [`ADR-0018`](../../backend/adr/0018-eval-judge-model-and-calibration.md)).
- `scripts/apply-k8s.sh`: Export `EVAL_CRON_SCHEDULE` and apply `envsubst '${EVAL_CRON_SCHEDULE}' < k8s/52-eval-cronjob.yaml | kubectl apply -f -`.

---

## 6. Reporting, Dashboard Hooks & Kid-Test Feedback Loop

### 6.1 Run Report Format (JSON + Human-Readable Markdown/CLI)

Every execution of `python -m evals run` writes two artifacts into `runs/evals/<eval_run_id>/`:

1. **Machine-Readable Report (`eval_report.json`)**:
```json
{
  "eval_run_id": "eval-full-20261109-143000",
  "suite": "full",
  "pipeline_version": 7,
  "factory_image_tag": "0.3.17",
  "git_sha": "0a43d9535749a22714804f2387efc8f2fe4e9252",
  "prompt_bundle_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "generator_model": "stealth/crouton-alpha",
  "judge_model": "stealth/crouton-alpha",
  "started_at": "2026-11-09T14:30:00Z",
  "completed_at": "2026-11-09T14:36:12Z",
  "duration_s": 372.0,
  "overall_pass": true,
  "regression_detected": false,
  "baseline_eval_run_id": "eval-full-20261108-220000",
  "summary": {
    "cards_total": 9,
    "cards_passed": 9,
    "cards_failed": 0,
    "model_calls_total": 26,
    "total_thinking_s": 148.4,
    "human_edit_rate_rolling": 0.0,
    "gate_b_comprehension_rate": 1.0
  },
  "cards": [
    {
      "card_id": "EV-REV-001",
      "stage": "03-check",
      "topic_slug": null,
      "verdict": "pass",
      "deterministic_score": 1.0,
      "judge_score": 1.0,
      "metrics": {
        "fatal_recall": 1.0,
        "blocking_recall": 1.0,
        "clean_specificity": 1.0,
        "samples_tested": 8
      },
      "delta_vs_baseline": {
        "fatal_recall": 0.0,
        "blocking_recall": 0.0,
        "clean_specificity": 0.0
      },
      "issues": []
    }
  ]
}
```

2. **Human-Readable Summary (`eval_summary.md` & stdout)**:
   Printed to stdout at the end of every run and saved as Markdown:
   ```text
   === ZIVON EVAL SUITE: full (run eval-full-20261109-143000 | pipeline v7 | model stealth/crouton-alpha) ===
   Card         Stage                  Target / Scope                     Det.   Judge  Verdict  Delta vs Baseline
   EV-CUR-001   00-ingest..02-gt       3 golden topics + kinem trap       1.00   1.00   PASS     0.00
   EV-SYN-001   02-generate.blocks     3 golden topics (schema+coverage)  1.00   1.00   PASS     0.00
   EV-SYN-002   02-generate.lesson     3 golden topics (recompute+teach)  1.00   1.00   PASS     0.00
   EV-VIS-001   05-interactive..06     3 golden topics (lint+DOM+design)  1.00   1.00   PASS     0.00
   EV-PERF-001  07-perf (weak-android) 3 golden topics (<=750MB,>=24fps)  1.00   n/a    PASS     load -0.12s
   EV-REV-001   03-check calibration   8 samples (6 bad, 2 clean)         1.00   1.00   PASS     recall 1.00 (0.00)
   EV-REV-002   09-review calibration  11 samples (5 sec, 5 rev, 1 clean) 1.00   1.00   PASS     recall 1.00 (0.00)
   EV-E2E-001   00..11 + edit rate     2 published runs (edit_rate=0.00)  1.00   n/a    PASS     edit_rate 0.00
   EV-KID-001   Gate B kid sessions    Round 1 cohort (3/3 passed)        1.00   n/a    PASS     0.00
   --------------------------------------------------------------------------------------------------------------
   OVERALL: PASS | Regressions: 0 | Model calls: 26 | Thinking time: 148.4s | Duration: 372.0s
   ```

### 6.2 Dashboard Hooks & Observability Events (Alignment with SP3)

Because `SP3` (observability / admin dashboard spec) runs in parallel in Wave S1, `evals/` defines a clean event, metric, and REST contract and flags it in [`open-questions.md`](open-questions.md) for SP3 alignment:

1. **Structured Telemetry Events (`EVT-EVAL-*`)**:
   - `EVT-EVAL-RUN-STARTED`: `{eval_run_id, suite, pipeline_version, generator_model, judge_model, git_sha, triggered_by}`
   - `EVT-EVAL-RUN-COMPLETED`: `{eval_run_id, suite, overall_pass, regression_detected, duration_s, model_calls_total, total_thinking_s, card_verdicts}`
   - `EVT-EVAL-REGRESSION-ALERT`: `{eval_run_id, baseline_eval_run_id, regressed_cards, metric_deltas, blocking_reason}`
   - `EVT-EVAL-HUMAN-EDIT-RECORDED`: `{topic_slug, class_level, factory_run_id, human_edit_rate, manual_added_lines, manual_deleted_lines}`
   - `EVT-EVAL-KID-SESSION-LOGGED`: `{session_code, topic_slug, tester_class, topic_class, is_above_class_level, gate_b_pass, promoted_defect_id}`

2. **Prometheus Metrics (Scraped by `kube-prometheus-stack` per `TIMELINE.md` Day 8)**:
   - `zivon_eval_card_score{card_id, stage, mode}` (gauge, `0.0–1.0`)
   - `zivon_eval_reviewer_recall{card_id, severity}` (gauge, `0.0–1.0`)
   - `zivon_eval_reviewer_specificity{card_id}` (gauge, `0.0–1.0`)
   - `zivon_eval_human_edit_rate{topic_slug, class_level}` (gauge, `0.0–1.0`)
   - `zivon_eval_gate_b_pass_rate{round}` (gauge, `0.0–1.0`)
   - `zivon_eval_run_duration_seconds{suite}` (histogram)

3. **Admin Dashboard v0 Endpoints (`TIMELINE.md` Day 8 "Admin trigger commands")**:
   - `POST /api/v1/admin/evals/trigger` → executes `scripts/trigger-evals.sh` (`suite: "smoke" | "full" | "calibrate"`), returns `{job_name, started_at}`.
   - `GET /api/v1/admin/evals/runs?limit=20` → returns recent `eval_run` summaries + human-edit-rate trend.
   - `GET /api/v1/admin/evals/runs/{eval_run_id}/diff` → returns the structured diff report against baseline.

### 6.3 Kid-Test Feedback Loop (Gate B → Seeded Defect Promotion)

`TIMELINE.md` Day 4 and Day 7 define the core self-improvement loop of the content factory:
> *"generate → observe kid → refine prompts/skills → regenerate."*

`EV-KID-001` turns this qualitative loop into an auditable engineering workflow:
1. **Session Capture (`python -m evals record-kid-test`)**:
   After a consented 20-minute kid session (`TIMELINE.md` Day 4 / Day 7), the operator records the observation without storing any child PII or audio:
   ```bash
   python -m evals record-kid-test \
     --session-code kid-r1-02 \
     --topic class-9-physics/how-forces-affect-motion \
     --tester-class 9 \
     --topic-class 9 \
     --restated true \
     --followup-1 true \
     --followup-2 false \
     --confusion-block b-06 \
     --notes "Student moved acceleration slider in b-06 but could not tell current velocity value because .zn-sim-read was blank."
   ```
2. **Mandatory Defect Promotion on Failure**:
   Whenever a kid session fails (`gate_b_pass == false`) or logs a `confusion_block`, the operator promotes the failure into a permanent regression check before closing the issue:
   - If the failure was mechanical/visual (e.g., blank `.zn-sim-read`), add a deterministic check in `evals/checkers/visual_checks.py` and a seeded defect in `evals/goldens/defects/09-review/` (`SD-REV-005`), then record `--promoted-defect-id SD-REV-005`.
   - If the failure was pedagogical (e.g., a quiz question tested a concept not explained in the lesson), add a seeded defect in `evals/goldens/defects/03-check/` (`SD-CHK-004`).
3. **Privacy Guardrail (`AGENTS.md` & DPDP Act 2023)**:
   `eval_kid_session` stores only a pseudonymous `session_code` (`kid-r1-01`), integer class levels, boolean pass flags, block IDs, and operator notes about the *page's* failure. `evals/cli.py` rejects any input containing email addresses, phone numbers, or file paths to audio/video recordings.

---

## 7. Upgrade Path: What "Industry Standard" Means Here (and What We Reject)

### 7.1 What We Adopt ("Industry Standard" for Agentic Pipelines)

Following the 2026 evaluation literature in [`skills/prompting-and-agent-design/references/sources-and-evidence.md`](../../../skills/prompting-and-agent-design/references/sources-and-evidence.md) (`[S2]` Anthropic *Demystifying Evals for AI Agents*, Jan 2026; `[S3]` Destefanis *Authoring Agent Skills*, Jul 2026; `[S7]` *RUVERBENCH*, EMNLP 2026):
1. **Card-Based Evaluation Suites**: Every stage of the agent graph has an explicit, versioned Eval Card (`EV-*`) stating its input dataset, deterministic checks, calibrated judge rubric, pass threshold, and call cost.
2. **Deterministic-First Grader Hierarchy**: Code graders run first (`0` tokens, `100%` reproducible); LLM judges run only on semantic/pedagogical dimensions that code cannot parse; human graders (human edit rate + Gate B kid comprehension) anchor the top of the pyramid.
3. **Meta-Evaluation (Judge Calibration via Seeded Defects)**: Because Zivon's pipeline relies on internal LLM reviewers (`03-check` and `09-review`), evaluating only the final page is insufficient. `EV-REV-001` and `EV-REV-002` continuously measure the **True Positive Rate (Recall)** and **True Negative Rate (Specificity)** of our reviewers on planted production defects.
4. **Property-Based Golden Datasets over Brittle String Snapshots**: Generative lessons vary legitimately in phrasing across runs. Golden topics (`evals/goldens/topics/`) lock source packs and assert on structural, factual, mathematical, and performance properties (`expected.json`), while seeded defect sets lock exact input drafts where the expected reviewer verdict is deterministic.
5. **Run-to-Run Regression Ledger**: Every eval run records `(pipeline_version, model, git_sha, prompt_bundle_sha256)` so prompt edits, model swaps (e.g., local Qwen → OpenRouter `stealth/crouton-alpha` → Evon v3.3), and kit upgrades produce side-by-side delta reports.

### 7.2 What Is Deliberately NOT Adopted (and Why)

| Rejected Tool / Pattern | Why It Is Rejected in Zivon |
|---|---|
| **Heavy External Eval Frameworks (`ragas`, `deepeval`, `promptfoo`, `langsmith`, `braintrust`, `arize-phoenix`)** | 1. **Dependency & Image Bloat**: `Dockerfile` is strictly size- and CVE-gated by Trivy and `pip-audit` in CI (`.github/workflows/ci.yml`). Heavy eval frameworks pull in dozens of transitive dependencies (`litellm`, `pydantic` v1/v2 shims, telemetry SDKs) that break CVE gates.<br>2. **Bypass of `llm_manager/` Law**: External frameworks make their own HTTP calls via `openai`/`litellm` clients, violating `AGENTS.md`'s hard rule: *"All model calls go through `llm_manager/` — NO other module may hand-roll HTTP calls to an inference server."*<br>3. **Offline Cluster Constraint (Gotcha 15)**: Cluster pods in minikube only reach `llm-manager` (`192.168.49.1:18080` router) and have `HF_HUB_OFFLINE=1`. Cloud SaaS eval trackers fail in-cluster. |
| **Generic RAG Metrics ("Faithfulness / Answer Relevancy / Context Precision" on `1–5` Likert Scales)** | Likert scales (`1–5` vibes) suffer from high variance and central-tendency bias on quantized and open-weight models (`[S2]`, `[S7]`). Zivon uses quote-grounded `fatal` / `major` / `minor` / `unverified:` rubrics where `fatal` requires quoting the contradicted source passage and arithmetic is verified by full recomputation. |
| **Pixel-Diff Screenshot Comparison (Visual Regression Snapshots)** | Explicitly rejected in `testing/README.md`: font hinting and canvas anti-aliasing vary across Linux containers and devices. Zivon enforces layout correctness via deterministic DOM bounding-box geometry assertions in headless Chromium (`overflow_px <= 2`, `<legend>` containment, `.zn-sim-read` population) plus `09-review-design`'s semantic rendering sweep. |
| **Mock-Server Evals** | Running `evals/` against `openai_mock.py` proves nothing about teaching quality. `openai_mock.py` belongs exclusively to `testing/` (wiring & transport tests). In `evals/`, `--suite smoke` runs real deterministic checkers on real golden artifacts (`0` model calls), and `--suite full` calls the real model through `llm_manager/`. |
