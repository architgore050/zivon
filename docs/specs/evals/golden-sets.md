# Golden Sets, Expected Properties & Seeded-Defect Calibration Corpus (`evals/goldens/`)

This document specifies the structure, inventory, schemas, storage placement, and version-rotation protocol for `evals/goldens/`.

---

## 1. Golden Topics Inventory (`evals/goldens/topics/`)

Zivon maintains **4 versioned golden topics** (the 3 already generated/built in the repo across Class 9 and Class 11 + the 3rd curriculum tier from `TIMELINE.md` Day 0 for Class 10):

| Golden ID | Directory under `evals/goldens/topics/` | Class | Chapter & Primary Source (`sources/catalog.json`) | Committed Repo Artifact / Snapshot | Pipeline Version / Status |
|---|---|---|---|---|---|
| `GT-01` | `class-9-motion/` | 9 | *Motion* (`ncert-science-9`, `iesc107.pdf` / `iesc108.pdf`, pages 1–22) | `frontend/courses/class-9-physics/how-forces-affect-motion/` (`index.html`, `page.js`, `page.css`, `manifest.json`, run `motion-c9`) | Published (`2026-11-03T15:11:31Z`); grandfathered pre-v7 snapshot + v7 expected properties |
| `GT-02` | `class-11-motion-in-a-straight-line/` | 11 | *MOTION IN A STRAIGHT LINE* (`ncert-physics-11-part1`, `keph102.pdf`, pages 1–14 + `openstax-hs-physics` supplements) | `frontend/courses/class-11-physics/motion-in-a-straight-line/` (`index.html`, `page.js`, `manifest.json`, run `motion-in-a-straight-line-c11`, validated in run `040410` on `0.3.17`) | Published (`2026-11-08T22:38:16Z`, `PIPELINE_VERSION = 7`, kit v1.6 + computed-geometry routing) |
| `GT-03` | `class-9-forces-reference-kit/` | 9 | *How Forces Affect Motion* (`ncert-science-9` Ch. 6, 2025 ed., all 7 sections, Ex 6.1–6.8, 16 exercises) | `docs/frontend/design-doctrine-lesson-example.html` (linked to `frontend/assets/zivon.css` + `zivon.js`) | Canonical kit-era reference golden (`doctrine v1.6`): 7 sections, 11 checks, 11 worked examples, 3 sims, 4 diagrams, 1 reveal |
| `GT-04` | `class-10-light-reflection-and-refraction/` | 10 | *Light – Reflection and Refraction* (`ncert-science-10`, `jesc109.pdf` + `siyavula-physical-sciences-10` supplements) | Source pack + `expected.json` committed in `evals/goldens/topics/class-10-light-reflection-and-refraction/` (`TIMELINE.md` Day 0/Day 3 target topic) | Golden input & expected-property contract frozen for unattended generation evals |

### 1.1 Per-Topic Directory Layout

Each folder under `evals/goldens/topics/<topic_id>/` contains:
```text
evals/goldens/topics/<topic_id>/
├── expected.json          # Structural, factual, numerical, and perf invariants (schema below)
├── source_pack_meta.json  # Book ID, chapter title, page range, sha256 of extracted ncert_text, supplement chunk IDs
└── artifact_ref.json      # Pointer to committed repo snapshot (e.g., frontend/courses/...) or PVC run_id
```

> **Why we store `expected.json` + `artifact_ref.json` instead of duplicating HTML/JS in git**:
> `frontend/courses/` and `docs/frontend/design-doctrine-lesson-example.html` are already committed in git (`AGENTS.md` / `scripts/publish-frontend.sh`). Referencing them via `artifact_ref.json` prevents duplicate multi-hundred-KB HTML/JS blobs in git while keeping `eval-smoke` 100% self-contained in CI.

---

## 2. Expected-Property File Schema (`expected.json`)

Generative outputs legitimately vary in prose wording across model runs. `expected.json` defines the **invariant properties** that any valid generation of that chapter must satisfy:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "GoldenTopicExpectedProperties",
  "type": "object",
  "required": [
    "golden_id",
    "topic_slug",
    "course_id",
    "class_level",
    "pipeline_version_min",
    "source_provenance",
    "structure_bounds",
    "required_concepts_and_equations",
    "canonical_numerical_anchors",
    "visual_and_kit_invariants",
    "perf_budgets"
  ],
  "additionalProperties": false,
  "properties": {
    "golden_id": { "type": "string", "pattern": "^GT-[0-9]{2}$" },
    "topic_slug": { "type": "string" },
    "course_id": { "type": "string" },
    "class_level": { "type": "integer", "minimum": 6, "maximum": 12 },
    "pipeline_version_min": { "type": "integer", "minimum": 1 },
    "source_provenance": {
      "type": "object",
      "required": ["primary_book_id", "chapter_title_normalized", "matched_via"],
      "properties": {
        "primary_book_id": { "type": "string" },
        "chapter_title_normalized": { "type": "string" },
        "matched_via": { "const": "title_line" },
        "forbidden_smuggled_terms": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Terms from later chapters that must not be taught/tested as primary facts"
        }
      }
    },
    "structure_bounds": {
      "type": "object",
      "required": [
        "sections_min",
        "claims_min",
        "claims_max",
        "blocks_min",
        "blocks_max",
        "checks_min",
        "worked_examples_min",
        "simulations_min",
        "diagrams_max"
      ],
      "properties": {
        "sections_min": { "type": "integer" },
        "claims_min": { "type": "integer" },
        "claims_max": { "type": "integer" },
        "blocks_min": { "type": "integer", "minimum": 4 },
        "blocks_max": { "type": "integer", "maximum": 45 },
        "checks_min": { "type": "integer" },
        "worked_examples_min": { "type": "integer" },
        "simulations_min": { "type": "integer" },
        "diagrams_max": { "type": "integer" }
      }
    },
    "required_concepts_and_equations": {
      "type": "object",
      "required": ["key_terms_must_include", "equation_patterns_must_include"],
      "properties": {
        "key_terms_must_include": { "type": "array", "items": { "type": "string" } },
        "equation_patterns_must_include": { "type": "array", "items": { "type": "string" } }
      }
    },
    "canonical_numerical_anchors": {
      "type": "array",
      "description": "Textbook numericals whose problem numbers and computed answers are pinned",
      "items": {
        "type": "object",
        "required": ["source_label", "problem_numbers", "expected_answer_values", "tolerance_rel"],
        "properties": {
          "source_label": { "type": "string" },
          "problem_numbers": { "type": "array", "items": { "type": "string" } },
          "expected_answer_values": { "type": "array", "items": { "type": "number" } },
          "tolerance_rel": { "type": "number", "default": 0.02 }
        }
      }
    },
    "visual_and_kit_invariants": {
      "type": "object",
      "required": [
        "requires_lang_bar",
        "requires_sim_readout_populated",
        "computed_graphs_as_simulations",
        "max_overflow_px"
      ],
      "properties": {
        "requires_lang_bar": { "type": "boolean" },
        "requires_sim_readout_populated": { "type": "boolean" },
        "computed_graphs_as_simulations": { "type": "boolean" },
        "max_overflow_px": { "type": "integer", "const": 2 }
      }
    },
    "perf_budgets": {
      "type": "object",
      "required": ["profile", "ram_budget_mb", "fps_min", "load_budget_s", "fcp_budget_s"],
      "properties": {
        "profile": { "type": "string" },
        "ram_budget_mb": { "type": "number" },
        "fps_min": { "type": "number" },
        "load_budget_s": { "type": "number" },
        "fcp_budget_s": { "type": "number" }
      }
    }
  }
}
```

### 2.1 Concrete Example: `GT-02` (`class-11-motion-in-a-straight-line/expected.json`)

```json
{
  "golden_id": "GT-02",
  "topic_slug": "motion-in-a-straight-line",
  "course_id": "class-11-physics",
  "class_level": 11,
  "pipeline_version_min": 7,
  "source_provenance": {
    "primary_book_id": "ncert-physics-11-part1",
    "chapter_title_normalized": "motioninastraightline",
    "matched_via": "title_line",
    "forbidden_smuggled_terms": [
      "simple harmonic motion",
      "moment of inertia",
      "torque",
      "angular momentum"
    ]
  },
  "structure_bounds": {
    "sections_min": 5,
    "claims_min": 12,
    "claims_max": 40,
    "blocks_min": 20,
    "blocks_max": 45,
    "checks_min": 10,
    "worked_examples_min": 4,
    "simulations_min": 2,
    "diagrams_max": 0
  },
  "required_concepts_and_equations": {
    "key_terms_must_include": [
      "instantaneous velocity",
      "instantaneous speed",
      "acceleration",
      "free fall",
      "stopping distance"
    ],
    "equation_patterns_must_include": [
      "v = v0 + at",
      "x = v0t + (1/2)at^2",
      "v^2 = v0^2 + 2ax"
    ]
  },
  "canonical_numerical_anchors": [
    {
      "source_label": "NCERT Ch. 2 stopping distance / retardation (126 km/h = 35 m/s over 200 m)",
      "problem_numbers": ["126", "200"],
      "expected_answer_values": [3.06, 11.4],
      "tolerance_rel": 0.02
    }
  ],
  "visual_and_kit_invariants": {
    "requires_lang_bar": true,
    "requires_sim_readout_populated": true,
    "computed_graphs_as_simulations": true,
    "max_overflow_px": 2
  },
  "perf_budgets": {
    "profile": "evals/goldens/profiles/weak-android.json",
    "ram_budget_mb": 750,
    "fps_min": 24,
    "load_budget_s": 6.0,
    "fcp_budget_s": 3.5
  }
}
```

---

## 3. Seeded-Defect Calibration Sets (`evals/goldens/defects/`)

Every seeded defect sample is a self-contained JSON bundle derived from a **real failure class observed during Zivon's build** (`TIMELINE.md` / `docs/logs/`). Each file contains:
- `sample_id`: Stable identifier (`SD-CHK-001`..`008`, `SD-SEC-001`..`005`, `SD-REV-001`..`006`),
- `origin_incident`: The production run ID and date that motivated the sample,
- `inputs`: The minimal stage inputs (`source_pack`, `ground_truth`, `lesson`, `blocks`, or rendered `files`), and
- `expected`: Exact grading criteria (`expected_verdict`, `expected_severity`, `expected_category`, `expected_block_id`, `must_quote_source`, `outcome_type`: `"positive_defect"` vs `"negative_clean"`).

### 3.1 `03-check` Calibration Corpus (`evals/goldens/defects/03-check/`)

| Sample ID | Origin Incident | Defect Class | Planted Mutation | Expected `03-check` Output |
|---|---|---|---|---|
| `SD-CHK-001` | Graph v2 calibration (`2026-11-03`) | Direct source contradiction | Mutates `b-03` in `GT-01` to state *"The SI unit of speed is km/h and velocity is a scalar."* | `verdict: "fail"`, `severity: "fatal"`, `block_id: "b-03"`, quotes `[ncert]` |
| `SD-CHK-002` | Run `000509` `b-21` (`2026-11-08`) | Wrong computed answer in `worked_example` | Sets `b-21` answer for `126 km/h` (`35 m/s`) stopping over `200 m` to `a = -3.94 m/s², t = 8.9 s` instead of `-3.06 m/s², 11.4 s`. | `verdict: "fail"`, `severity: "fatal"`, `block_id: "b-21"` (recompute check) |
| `SD-CHK-003` | Run `005728` (`2026-11-03`) & Run `040410` `b-28` (`2026-11-09`) | Smuggled out-of-chapter concept | Injects check block `b-28` testing SHM pendulum period $T = 2\pi\sqrt{L/g}$ and Newton's $F = ma$ into Class 11 Ch. 2 Kinematics draft. | `severity: "major"`, `block_id: "b-28"` (routes to `04-repair` for omission/rewrite) |
| `SD-CHK-004` | Run `040410` `b-19`/`b-20` (`2026-11-09`) | Teach-before-test violation | Places a check block `b-19` with `expected_understanding: "Derive reaction-time stopping distance"` when `lesson` text never mentions reaction time. | `severity: "major"`, `block_id: "b-19"` |
| `SD-CHK-005` | Motion thin-page run (`2026-11-04`, image `0.3.4`) | Chapter coverage omission | Removes all `worked_example` blocks and the final two titled chapter sections from `GT-01` while keeping remaining blocks accurate. | `verdict: "fail"`, `severity: "fatal"`, quotes omitted chapter sections/exercises |
| `SD-CHK-006` | Graph v2 trivia-overflag fix (`2026-11-03`) | Unverifiable common-knowledge expansion | Adds parenthetical `"(SI stands for Système International d'Unités)"` in `b-01` when source text only writes `"SI unit"`. | `verdict: "pass"`, `0` fatals, `0` majors; any note must be `severity: "minor"` (with `unverified:` if hedged) |
| `SD-CHK-007` | `GT-01` clean draft | True Negative (Clean Class 9 Golden) | Unmutated repaired `GT-01` draft + full coverage. | `verdict: "pass"`, `0` fatals, `0` majors |
| `SD-CHK-008` | `GT-02` run `040410` repaired draft | True Negative (Clean Class 11 Golden) | Unmutated `GT-02` draft with `b-28`/`b-19` repaired. | `verdict: "pass"`, `0` fatals, `0` majors |

### 3.2 `09-review` Calibration Corpus (`evals/goldens/defects/09-review/`)

#### Deterministic Security & Kit-Scope Samples (`SD-SEC-001..005` — `0` Model Calls)

| Sample ID | Origin Incident | Defect Class | Planted Mutation | Expected Deterministic Grader Output |
|---|---|---|---|---|
| `SD-SEC-001` | `AGENTS.md` non-negotiable | Arbitrary code execution | Injects `eval("ctx.t")` and `new Function("return 1")` into `page.js`. | `lint_js` flags both; `review.run` raises `LintError` |
| `SD-SEC-002` | `AGENTS.md` self-containment & CSP | External network exfiltration | Injects `fetch("https://api.example.com")` in `page.js`, `@import url("https://fonts.googleapis.com/...")` in `page.css`, and `<a href="https://evil.example">` in SVG. | `lint_js`, `lint_css`, and `rule_diagram_svg` flag all 3 |
| `SD-SEC-003` | CodeQL round 2 (`2026-11-05`, image `0.3.7`) | Unclosed/inline `<script>` & SVG handler | Injects `<script>window.x=1` in `index.html` and `<svg onload="alert(1)">`. | `lint_html` (`html.parser`) and `rule_diagram_svg` flag both |
| `SD-SEC-004` | `factory/review.py::_static_review_findings` | Broken page metadata / CSP | Strips `Content-Security-Policy` meta tag from `index.html` and empties `sources: []` in `manifest.json`. | `_static_review_findings` emits 2 `fatal` issues (`verdict: "fail"`) |
| `SD-SEC-005` | Doctrine v1.6 kit drift (`2026-11-09`, image `0.3.14`) | Unscoped CSS & canvas sizing | Adds `.zn-lang-bar { position: sticky }` and `.zn-sim-b-04 canvas { width: 100%; height: auto }` to `b-04/page.css`. | `lint_page_css_scope` returns 2 violations |

#### Model Reviewer Samples (`SD-REV-001..006` — `2` Calls per Sample: `09-review-facts` + `09-review-design`)

| Sample ID | Origin Incident | Target Call | Defect Class & Planted Mutation | Expected Reviewer Output |
|---|---|---|---|---|
| `SD-REV-001` | Run `180935` `b-31` plateau (`2026-11-08`) | `09-review-facts` | `index.html` displays quiz explanation `"t = 49 s"` while `page.js` mutates `#b-31` DOM text to `"t = 37 s"` at runtime. | `severity: "fatal"`, `category: "inconsistency"`, `block_id: "b-31"`, harness `verdict: "fail"` |
| `SD-REV-002` | `test_review.py` & `05-interactive` physics contract | `09-review-facts` | Simulation `b-06` cites `eq-02` ($x = v_0 t + \frac{1}{2}at^2$ with $a > 0$) but `draw(ctx)` plots $x = v_0 t - \frac{1}{2}at^2$ (decelerating curve while label says accelerating). | `severity: "fatal"`, `category: "drawn_behaviour"`, `block_id: "b-06"`, harness `verdict: "fail"` |
| `SD-REV-003` | Run `032406` `b-09` (`2026-11-09`) | `09-review-design` | Static SVG `b-09` draws `<rect x="60" y="60" width="300" height="100"/>` for the area under a diagonal $v\text{–}t$ line with $u > 0$ (should be a trapezoid to the $t$-axis). | `severity: "fatal"`, `category: "rendering"`, `block_id: "b-09"`, harness `verdict: "fail"` |
| `SD-REV-004` | `0.3.13` live probe `b-05` (`2026-11-08`) | `09-review-design` | Diagram `b-05` places Point P `<circle cx="180" cy="110"/>` 24 px off the plotted curve and draws its "tangent" line cutting across the curve as a secant. | `severity: "major"` or `"fatal"`, `category: "rendering"`, `block_id: "b-05"` |
| `SD-REV-005` | Run `040410` (`2026-11-09`) & `0.3.12` probe | `09-review-design` | Simulation `b-08` never writes to `.zn-sim-read` (`aria-live` readout stays empty on slider change) and diagram `b-05` `<svg>` has no `aria-label` or `<title>`. | `severity: "major"`, `category: "accessibility"`, `block_id: "b-08"` / `"b-05"` |
| `SD-REV-006` | Run `040410` clean render (`2026-11-09`) | Both calls | Clean `GT-02` rendered files (`0` diagram blocks, JS-computed `v-t`/`x-t` sims `b-04`/`b-08`, `.zn-sim-read` populated, kit chrome present). | `0` fatals across both calls; harness `verdict: "pass"` |

---

## 4. Storage Placement & Version Rotation Rules

### 4.1 Where Golden Sets Live

| Asset Type | Storage Location | Size Budget | Sync / Backup Rule |
|---|---|---|---|
| `expected.json`, `source_pack_meta.json`, `artifact_ref.json`, and `defects/**/*.json` | Committed in Git under `evals/goldens/` | `< 500 KB` total across all files | Versioned in Git (`C16` / `C1`); available in every CI runner and container build without network or PVC mounts. |
| Committed Golden Topic Renders (`GT-01`, `GT-02`, `GT-03`) | Committed in Git at `frontend/courses/` and `docs/frontend/design-doctrine-lesson-example.html` | `~150–300 KB` per topic | Mirrored via `scripts/publish-frontend.sh` (`C1`); git history is the version rotation. |
| Full Historical Run Directories & Raw PDF Caches | `zivon-sources` PVC (`subPath: runs` and `subPath: evals`) → Cold Object Storage (`C4`) | `5–50 MB` per run | Synced to cold storage via transactional outbox (`ADR-0017`); never committed to Git. |

### 4.2 How Goldens Rotate When Content or Pipeline Versions Change

1. **Authoring-Prompt-Only Change (`PIPELINE_VERSION` unchanged)**:
   - `expected.json` and `defects/` do **not** rotate. Run `python -m evals run --suite full` to verify the prompt change improves or preserves scores against the existing golden baseline.
2. **Contract / Schema / Kit Change (`PIPELINE_VERSION` bumped, e.g., `6 → 7`)**:
   - **Grandfathered Published Topics**: Existing published topics (`GT-01`) keep their `pipeline_version_min` in `expected.json` until regenerated with `--fresh`, or are regenerated and re-published via `scripts/publish-frontend.sh`.
   - **Updating `expected.json` (`python -m evals rotate-golden`)**:
     1. Trigger a `--fresh` factory run for the golden topic (`scripts/trigger-factory-run.sh "<chapter>" <class> --fresh`).
     2. Mirror the published page (`scripts/publish-frontend.sh`) and verify `EV-CUR-001` through `EV-PERF-001` pass `100%` with `human_edit_rate == 0.00`.
     3. Update `pipeline_version_min` and `artifact_ref.json` in `evals/goldens/topics/<topic_id>/` in the **same PR** as the `PIPELINE_VERSION` bump.
   - **Never Weaken a Seeded Defect (`defects/`) to Pass a Regression**:
     Per protocol §4 and `user:engineering-operating-rules`, seeded defect samples (`SD-CHK-*`, `SD-REV-*`, `SD-SEC-*`) may only be *added* or updated if the stage input schema (`GENERATED`, `BLOCKS`) itself changed shape — never weakened or deleted to hide a drop in reviewer recall.
