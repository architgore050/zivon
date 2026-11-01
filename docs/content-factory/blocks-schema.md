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
| `citations` | `[{"claim_id": "claim-01"}]` - must reference ground-truth claim ids; required on all factual blocks |

## text

    {"paragraphs": ["...", ...]}

## worked_example

    {"problem": "...", "steps": [{"title": "...", "detail": "..."}], "answer": "..."}
Every number in `answer` must be traceable to the ground truth or the primary
source (enforced by `factory/checks.py::rule_numbers`).

## check

    {"question": "...", "format": "mcq", "options": ["A", "B", "C", "D"],
     "answer_index": 1, "answer": "B's text", "explanation": "...",
     "expected_understanding": "..."}
or `"format": "numeric"` with `"answer": "5"` (a number) and no options.
`answer` must equal `options[answer_index]` for mcq (hard rule). One option
should address a listed misconception where possible.

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
