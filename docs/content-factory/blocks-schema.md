# Block schema (v1, frozen 2026-11-01)

Blocks are the handoff format between the draft stage (04), the interactive
builder (06) and the renderer (07). The canonical shape is the one in
AGENTS.md: **every payload lives under `spec`**. This resolves the old
AGENTS.md-vs-TIMELINE.md contradiction (`content` / bare `question` fields are
NOT valid). The enforcing schema is `factory/schemas.py` (`BLOCKS`); a summary
lives here.

Common block fields:

| Field | Rules |
|---|---|
| `id` | `b-01`, `b-02`, ... (`^b-[0-9]{2}$`) |
| `type` | `text` \| `worked_example` \| `check` \| `reveal` \| `diagram` \| `simulation` |
| `spec` | object, shape per type below |
| `citations` | `[{"claim_id": "claim-01"}]` - must reference ground-truth claim ids; required on all factual blocks (a text/worked_example/check/reveal block without citations is a fatal rule failure) |

Optional metadata fields (additive, 2026-11-15) are listed in
[Content identity and block metadata](#content-identity-and-block-metadata-2026-11-15).

## text

    {"paragraphs": ["...", ...]}

## worked_example

    {"problem": "...", "steps": [{"title": "...", "detail": "..."}], "answer": "..."}
Every number in `problem` must appear **verbatim** in the ground truth or the primary
source text (checked by `factory/checks.py::rule_numbers` with a whole-numeral match:
`5` matches `5` and `5.0`, never `15`). The `answer` is then **computed** from those
numbers using only equations and methods the source states - answer numerals are not
source-matched; they are `03-check`'s recompute territory (coverage contract, 0.3.4).

## check

    {"question": "...", "format": "mcq", "options": ["A", "B", "C", "D"],
     "answer_index": 1, "answer": "B's text", "explanation": "...",
     "expected_understanding": "..."}
or `"format": "numeric"` with `"answer": "5"` (a number) and no options.
`answer` must equal `options[answer_index]` for mcq (hard rule). Numbers in
the correct option and in a numeric `answer` are held to the same verbatim
rule as worked examples. One option should address a listed misconception
where possible.

## reveal

    {"title": "...", "steps": [{"title": "...", "detail": "..."}]}
Rendered as native `<details>` elements - keyboard accessible with zero JS.

## diagram

    {"svg": "<svg viewBox='...'>...</svg>", "caption": "..."}
SVG rules (hard): starts with `<svg`, presentation attributes only, no
`<script>`, no `<style>`, no external URLs (xmlns is allowed), no embedded
images, no event handlers. The renderer inlines it; nothing is fetched.

## simulation

    {"title": "...", "description": "...", "learning_goal": "...",
     "controls": [{"id": "a", "label": "acceleration m/s2", "min": -5,
                   "max": 5, "step": 0.5, "initial": 2}],
     "default_behaviour": "what it shows before any input"}
A simulation with zero controls is an animation (there is no separate
`animation` type in v1 - AGENTS.md's animation folds in here). Stage 06 writes
the JS for each simulation into `page.js` under this skeleton:

    ZivonSim.register("<BLOCK_ID>", {
      init: function (ctx) { ... },   // ctx: {canvas, g, width, height, values, t}
      draw: function (ctx) { ... }    // called every frame; read ctx.values
    });

`frontend/assets/zivon.js` provides the runtime: control wiring, rAF loop,
reduced-motion support, and an on-canvas error painter (a broken simulation is
loud, never blank).

## Ordering rules (draft prompt)

First block is `text`; last block is `check`; at least 3 checks spread through
the page; diagrams/simulations interleaved where a teacher would put them.

## Content identity and block metadata (2026-11-15)

The generated page must be **self-describing**: chapter/concept identity, section
structure, stable machine hooks, and a catalogue the product layers can consume
without re-parsing HTML. Everything in this section is additive - a
`PIPELINE_VERSION`-9 draft still loads and renders (the renderer derives what an
older draft does not carry), so this is not a schema-version break.

### Identity fields

| Field | Where | Rule |
|---|---|---|
| `chapter_id` | `manifest.json` | `class-<n>-<topic-slug>` (`class-9-motion`). Deterministic from the located chapter; the page directory slug and the manifest agree. |
| `lesson_id` | `manifest.json` | Same value as `chapter_id`: a chapter owns exactly one lesson page. |
| `concept_id` | section wrapper + every block + `manifest.json` | `<chapter_id>-<section_id>` (`class-9-motion-sec-03`). A **stable grouping key**, not a curated syllabus concept: P2's `concept-tag` stage may re-map it. Until then no block is an orphan. |
| `section_id` | block (optional input), section wrapper, manifest | `sec-01`… owned by `lesson.sections`. |
| `chapter.title` | `manifest.json` | Must name a chapter. Page furniture ("Grade", "Grade 7", "Chapter-04.indd 48", a running header) is rejected and repaired from the locator's matched line or the operator's query; if nothing usable is left the render **fails loudly** instead of publishing a placeholder (`factory/identity.py`). |

Block metadata (all optional, validated by `factory/schemas.py`):

| Field | Applies to | Rule |
|---|---|---|
| `section_id` | any block | `^sec-[0-9]{2}$`. The generation prompt asks the draft to name the lesson section each block teaches. When absent (older drafts, or a block the author left unattributed) `factory/sections.py` derives it from prose overlap and makes the assignment monotone, so a section owns a contiguous run of blocks. |
| `concept_id` | any block | Stamped by the renderer from the owning section; never invented per block. |
| `difficulty` | checks | `easy` \| `medium` \| `hard` (REQUIREMENTS §7.3). Optional. |
| `expected_time_ms` | checks | Integer milliseconds, 1 000–1 800 000. Optional; the real time priors are P2's `time-priors` stage. |

### Renderer hooks

`factory/render.py` emits, on every generated page:

- `data-block-type="<type>"` and `data-concept-id="<concept_id>"` on **every**
  block element (a block is never identified by a CSS class alone);
- `data-element-id="EL-LES-01-NNN"` on the content elements
  `docs/product/ui-element-inventory.csv` defines and the page actually has
  (text paragraph, diagram figure/caption, simulation card/title/control/canvas/
  mirror, check fieldset/option/input/button/feedback/why, worked-example
  problem/step/answer, reveal details, glossary, sources footer, page header
  kicker/title/objectives). Product chrome ids (dock, consent, language bar,
  report) stay with the shell kit - one emitter per element
  (`docs/specs/frontend/shell-injection.md` §2);
- `<section class="zn-section" id="sec-NN" data-section-id="sec-NN"
  data-concept-id="…">` wrappers that own their blocks, preserving every
  `b-NN` id. A wrapper is structure only: it adds no visible text and no new
  `data-i18n` string, so wrapping cannot change what the page looks like;
- the same hooks survive a repair round: `08-fixloop` and `10-reviewfix`
  re-emit `index.html` through `render._render_body` (via the manifest's
  block -> section map), so a corrected block still lands inside its section
  and the page keeps matching `manifest.json`;
- `factory/hooks.py::hook_issues(html, manifest)` is the contract as code. The
  renderer refuses to ship a page that fails it, `08-fixloop` refuses to re-emit
  one, and P4 registers the same function as a deterministic eval checker
  (`EV-SYN-001`, `EV-VIS-002`).

Shell note: a section wrapper carries an `id`, so it is visible to consumers
that select `.zn-page [id]` (today `zivon.js::buildContextSnapshot`). The shell
must filter content blocks on `[data-block-type]`; F4 owns that one-line change
(`frontend/assets/zivon.js`), until then a `sec-NN` id can appear in the
context snapshot alongside the real `b-NN` blocks (no error, a weaker anchor).

Known gap: `EL-LES-01-005` (the objectives list) is not emitted yet because
`08-fixloop` re-extracts the objectives by matching `<ul class="zn-objectives">`
exactly; the id lands when that rebuild path is hook-aware.

### `manifest.json` v2

Additive over v1 - old manifests still load, and a v2 reader treats every new
key as optional. Unknown facts are **absent**, never placeholders.

```json
{
  "manifest_version": 2,
  "chapter_id": "class-9-motion",
  "lesson_id": "class-9-motion",
  "subject": "physics",
  "status": "lesson_only",
  "languages": {"default": "en", "available": ["en"], "missing": ["hi", "hi-Latn"]},
  "counts": {"lesson_blocks": 42, "checks": 13, "worked_examples": 8,
             "diagrams": 2, "simulations": 3, "reveals": 4, "text_blocks": 12},
  "concepts": [{"concept_id": "class-9-motion-sec-01", "section_id": "sec-01", "title": "…"}],
  "sections": [{"id": "sec-01", "title": "…", "concept_id": "…", "block_ids": ["b-01"]}],
  "blocks": {"b-01": {"type": "text", "section_id": "sec-01", "concept_id": "…"}},
  "pipeline_version": "9",
  "content_hash": "sha256:…"
}
```

- `status` is `live` | `lesson_only` | `in_development`. `06-render` writes
  `lesson_only` (a lesson exists, no practice items or series yet); P2/P3 raise it.
- `languages` reports coverage of **this artifact**; `10d-transrender` refreshes
  it from the locale bundles it wrote. A locale in `missing` gets the visible
  "not available yet" marker, never English pretending to be Hindi.
- `counts` carries only what the artifact contains. `practice_items` /
  `test_items` are absent until P2/P3 produce them - a fabricated `0` would read
  as "no practice exists" when the truth is "not produced yet".
- `exam_weight` is absent unless a syllabus source states it (P2).
- `content_hash` is `sha256:` over the lesson + block content + `chapter_id`,
  independent of render chrome and locale, so it is stable across re-renders and
  usable as a cache key (narration, i18n).

### `catalogue.json`

`factory/render.py::write_catalogue` writes one entry per topic - the manifest
v2 core plus `href` and `generated_at` - and `write_courses_js` writes both
`catalogue.json` and `courses.js` from the same manifest scan, so the browser
file and the machine catalogue can never disagree. `courses.js` keeps its
existing shape (`window.ZIVON_COURSES`); product layers that need identity,
status, counts or concepts read `catalogue.json`.

Publish handoff (P5): `catalogue.json` lands next to `courses.js` at the
staging root, so `scripts/publish-frontend.sh` must copy it in the same step as
`courses/` + `courses.js` (it currently copies only those two) and the publish
verification must treat a stale/missing `catalogue.json` as a failure.

## Localization Contracts (`SP2-TRANS`, Implemented in Wave E)

The v1 block schema above remains frozen and unmodified for English generation (`02-generate`..`10-reviewfix`). The additive localization contracts below (`CP-TRN-001`..`CP-TRN-004`, specified in [`docs/specs/translation/`](../specs/translation/README.md)) govern stages `10a-translate` through `10d-transrender`:

### CP-TRN-001: Additive Per-Block Translation Payload Schemas (`factory/schemas.py`)

- **Owner**: `EX2-TRANS` · **Status**: Implemented · **Traces to**: [`ADR-0021`](../backend/adr/0021-translation-stage-placement-and-resumability.md), [`docs/specs/translation/block-contract.md`](../specs/translation/block-contract.md)
- **Contract**: Unit-level translation schemas in `factory/schemas.py` (`TRANSLATED_META_PAYLOAD`, `TRANSLATED_TEXT_PAYLOAD`, `TRANSLATED_WORKED_EXAMPLE_PAYLOAD`, `TRANSLATED_CHECK_MCQ_PAYLOAD`, `TRANSLATED_CHECK_NUMERIC_PAYLOAD`, `TRANSLATED_REVEAL_PAYLOAD`, `TRANSLATED_DIAGRAM_PAYLOAD`, `TRANSLATED_SIMULATION_PAYLOAD`, and `TRANSLATION_REVIEW_CALL_REPORT`) validate each per-block translation without altering `BLOCKS`, `LESSON`, or `GENERATED`.
- **Rationale**: Each `10a-translate` call sends only the translatable strings of a single block to Evon v3.3 via `llm_manager`, while harness code (`reassemble_translated_unit`) preserves `id`, `type`, `citations`, `check.spec.answer_index`, `numeric` check answers (`spec.answer`), and `simulation.spec.controls[].{id, min, max, step, initial}` deterministically. This guarantees that reassembled localized blocks conform 100% to the frozen v1 `BLOCKS` schema.

### CP-TRN-002: Diagram SVG `<text>` String Table Extraction & `data-i18n` Attribute Rule

- **Owner**: `EX2-TRANS` · **Status**: Implemented · **Traces to**: [`ADR-0023`](../backend/adr/0023-physics-terminology-and-script-rendering-policy.md), [`docs/specs/translation/block-contract.md` §3.6](../specs/translation/block-contract.md)
- **Contract**: `diagram.spec.svg` stays a single self-contained `<svg>` string in v1, and the translation model never reads or emits raw `<svg>` markup:
  1. `factory/translate.py` parses `diagram.spec.svg`, extracts descriptive `<text>` node strings and root `aria-label` into `svg_texts: [{"id": "t-0", "source": "...", "max_chars": N}]` (skipping standalone math/unit tokens like `F`, `10 N`, `m₁`, `v (m/s)`).
  2. After Evon v3.3 translates `svg_texts`, `factory/translate.py` re-injects the strings into a clone of the English `<svg>` DOM, tags each localized `<text>` element with `data-i18n="<block_id>.svg_texts.t-<k>"` (presentation/DOM data attribute only — zero `<script>` or `<style>`), and re-runs `factory/checks.py::rule_diagram_svg`.

### CP-TRN-003: Simulation Canvas String Localization Hook (`ZivonSim` `ctx.t_str` + `sim_strings`)

- **Owner**: `EX2-TRANS` + `EX5-FRONT` · **Status**: Implemented (`10a-translate` / `10d-transrender` side) · **Traces to**: [`docs/specs/translation/spec.md` §5.2](../specs/translation/spec.md), [`docs/specs/translation/block-contract.md` §3.1](../specs/translation/block-contract.md)
- **Contract**: Extends the `ZivonSim` runtime context in `frontend/assets/zivon.js` from `{canvas, g, width, height, values, t}` to `{canvas, g, width, height, values, t, locale, t_str}`:
  - `ctx.t_str(key, fallback)` looks up `window.ZIVON_I18N[ctx.locale]?.sim_strings?.["<BLOCK_ID>"]?.[key] || fallback`.
  - `factory/translate.py` extracts `(key, fallback)` pairs from `page.js` via regex scan (`ctx.t_str("key", "English fallback")`) into `b-00-meta.sim_strings`. For existing v7 `page.js` files that do not yet call `ctx.t_str`, `sim_strings` defaults to `{}` while `simulation.spec` DOM chrome (`h3`, control labels, `.zn-sim-desc`, `aria-label`) still localizes in full without re-running `05-interactive`.
  - When a user clicks a `.zn-chip[data-locale]` in `.zn-lang-bar`, `zivon.js` updates `ctx.locale` and invokes `impl.draw(ctx)` once so canvas legends and `.zn-sim-read` live readouts switch language immediately without duplicating `page.js` per locale or resetting slider values (`ctx.values`).

### CP-TRN-004: Topic `manifest.json` and `courses.js` Localization Metadata

- **Owner**: `EX2-TRANS` · **Status**: Implemented · **Traces to**: [`ADR-0022`](../backend/adr/0022-translation-memory-and-cache-architecture.md), [`docs/specs/translation/spec.md` §5.1](../specs/translation/spec.md)
- **Contract**: Additive fields in `manifest.json` (emitted by `10d-transrender`) and `window.ZIVON_COURSES` entries in `courses.js`:
  ```json
  {
    "default_locale": "en",
    "locales_available": ["en", "hi", "hi-Latn"],
    "titles_by_locale": {
      "en": "Motion in a Straight Line",
      "hi": "सरल रेखा में गति (Motion in a Straight Line)",
      "hi-Latn": "Straight Line Mein Motion"
    },
    "translation_status": {
      "hi": {"status": "verified", "fallback_blocks": [], "glossary_version": "1.0.0"},
      "hi-Latn": {"status": "verified", "fallback_blocks": [], "glossary_version": "1.0.0"}
    }
  }
  ```
