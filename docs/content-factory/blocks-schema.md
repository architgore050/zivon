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

## Change Proposals (Wave S1 — `SP2-TRANS`)

The v1 block schema above remains frozen and unmodified for English generation (`02-generate`..`10-reviewfix`). The numbered change proposals below specify the additive localization schemas and handoff contracts to be implemented by `EX2-TRANS` and `EX5-FRONT` (full details in [`docs/specs/translation/`](../specs/translation/README.md)):

### CP-TRN-001: Additive Per-Block Translation Payload Schemas (`factory/schemas.py`)

- **Owner**: `EX2-TRANS` · **Traces to**: [`ADR-0017`](../backend/adr/0017-translation-stage-placement-and-resumability.md), [`docs/specs/translation/block-contract.md`](../specs/translation/block-contract.md)
- **Proposal**: Add unit-level translation schemas to `factory/schemas.py` (`TRANSLATED_META_PAYLOAD`, `TRANSLATED_TEXT_PAYLOAD`, `TRANSLATED_WORKED_EXAMPLE_PAYLOAD`, `TRANSLATED_CHECK_MCQ_PAYLOAD`, `TRANSLATED_CHECK_NUMERIC_PAYLOAD`, `TRANSLATED_REVEAL_PAYLOAD`, `TRANSLATED_DIAGRAM_PAYLOAD`, `TRANSLATED_SIMULATION_PAYLOAD`, and `TRANSLATION_REVIEW_CALL_REPORT`) without altering `BLOCKS`, `LESSON`, or `GENERATED`.
- **Rationale**: Each `10a-translate` call sends only the translatable strings of a single block to Evon v3.3 via `llm_manager`, while harness code (`reassemble_translated_unit`) preserves `id`, `type`, `citations`, `check.spec.answer_index`, `numeric` check answers (`spec.answer`), and `simulation.spec.controls[].{id, min, max, step, initial}` deterministically. This guarantees that reassembled localized blocks conform 100% to the frozen v1 `BLOCKS` schema.

### CP-TRN-002: Diagram SVG `<text>` String Table Extraction & `data-i18n` Attribute Rule

- **Owner**: `EX2-TRANS` · **Traces to**: [`ADR-0019`](../backend/adr/0019-physics-terminology-and-script-rendering-policy.md), [`docs/specs/translation/block-contract.md` §3.6](../specs/translation/block-contract.md)
- **Proposal**: Keep `diagram.spec.svg` as a single self-contained `<svg>` string in v1, but forbid the translation model from reading or emitting raw `<svg>` markup. Instead:
  1. `factory/translate.py` parses `diagram.spec.svg`, extracts descriptive `<text>` node strings and root `aria-label` into `svg_texts: [{"id": "t-0", "source": "...", "max_chars": N}]` (skipping standalone math/unit tokens like `F`, `10 N`, `m₁`, `v (m/s)`).
  2. After Evon v3.3 translates `svg_texts`, `factory/translate.py` re-injects the strings into a clone of the English `<svg>` DOM, tags each localized `<text>` element with `data-i18n="<block_id>.svg_texts.t-<k>"` (presentation/DOM data attribute only — zero `<script>` or `<style>`), and re-runs `factory/checks.py::rule_diagram_svg`.

### CP-TRN-003: Simulation Canvas String Localization Hook (`ZivonSim` `ctx.t_str` + `sim_strings`)

- **Owner**: `EX2-TRANS` + `EX5-FRONT` · **Traces to**: [`docs/specs/translation/spec.md` §5.2](../specs/translation/spec.md), [`docs/specs/translation/block-contract.md` §3.1](../specs/translation/block-contract.md)
- **Proposal**: Extend the `ZivonSim` runtime context in `frontend/assets/zivon.js` from `{canvas, g, width, height, values, t}` to `{canvas, g, width, height, values, t, locale, t_str}`:
  - `ctx.t_str(key, fallback)` looks up `window.ZIVON_I18N[ctx.locale]?.sim_strings?.["<BLOCK_ID>"]?.[key] || fallback`.
  - `factory/translate.py` extracts `(key, fallback)` pairs from `page.js` via regex scan (`ctx.t_str("key", "English fallback")`) into `b-00-meta.sim_strings`. For existing v7 `page.js` files that do not yet call `ctx.t_str`, `sim_strings` defaults to `{}` while `simulation.spec` DOM chrome (`h3`, control labels, `.zn-sim-desc`, `aria-label`) still localizes in full without re-running `05-interactive`.
  - When a user clicks a `.zn-chip[data-locale]` in `.zn-lang-bar`, `zivon.js` updates `ctx.locale` and invokes `impl.draw(ctx)` once so canvas legends and `.zn-sim-read` live readouts switch language immediately without duplicating `page.js` per locale or resetting slider values (`ctx.values`).

### CP-TRN-004: Topic `manifest.json` and `courses.js` Localization Metadata

- **Owner**: `EX2-TRANS` · **Traces to**: [`ADR-0018`](../backend/adr/0018-translation-memory-and-cache-architecture.md), [`docs/specs/translation/spec.md` §5.1](../specs/translation/spec.md)
- **Proposal**: Add optional additive fields to `manifest.json` (emitted by `10d-transrender` / `06-render`) and `window.ZIVON_COURSES` entries in `courses.js`:
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
