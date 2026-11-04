"""Stage 05-interactive: the Visual Builder agent.

One model request per simulation block ("animation" is a simulation with zero
controls). The model writes topic-local JS/CSS under a strict skeleton; the
result is linted before anything proceeds. Diagrams are NOT model calls here -
their SVG comes from 02-generate and is rendered (and linted) as-is.

The prompt pins the shared contract (zivon.css / zivon.js class names), hands
the model the ground-truth facts its simulation must obey, and injects the
LIVE design doctrine, its example pages and the parsed palette (factory/
design.py); the model never writes global styles. Lint runs INSIDE the retry
loop, so the model sees and fixes its own violations.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .artifacts import RunContext
from .config import Config
from .design import design_context, palette_text
from .errors import LintError
from .lint import lint_css, lint_js
from .llm import LLMClient
from .schemas import INTERACTIVE

STAGE_ID = "05-interactive"

SIM_SKELETON = """
// Required skeleton for every simulation (the agent fills the marked parts):
ZivonSim.register("<BLOCK_ID>", {
  init: function (ctx) {
    // ctx: {canvas, width, height, values: {controlId: number}, t: seconds since start}
    // draw(ctx) is called every animation frame by the ZivonSim runtime.
  },
  draw: function (ctx) {
    // ctx is the same object; mutate it in init, read ctx.values here.
    // Use plain canvas 2D (ctx.canvas.getContext('2d') is available as ctx.g).
  }
});
"""


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    blocks: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    sims = [b for b in blocks["blocks"] if b["type"] == "simulation"]
    results: dict[str, Any] = {}
    for b in sims:
        results[b["id"]] = _build_simulation(cfg, run_ctx, llm, b, ground_truth)
    return results


def _facts_text(block: dict[str, Any], ground_truth: dict[str, Any]) -> str:
    """The claims this block cites, plus every equation: the physics the
    draw loop must obey. Equations are few and central, so all are included."""
    cited = {c.get("claim_id") for c in block.get("citations", [])}
    lines = [
        f"- {c['id']}: {c['statement']} ["
        + ", ".join(f"{x['source_id']} {x['locator']}" for x in c["citations"])
        + "]"
        for c in ground_truth["claims"]
        if c["id"] in cited
    ]
    for e in ground_truth.get("equations", []):
        lines.append(f"- {e['id']}: {e['expression']} ({e['description']})")
    return (
        "\n".join(lines)
        or "- (no cited claims: obey DESCRIPTION and DEFAULT BEHAVIOUR exactly)"
    )


def _build_simulation(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    block: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    spec = block["spec"]
    controls = spec.get("controls", [])
    control_lines = (
        "\n".join(
            f'  - id "{c.get("id")}", label "{c.get("label")}", range {c.get("min")}..{c.get("max")}, '
            f"step {c.get('step')}, initial {c.get('initial')}"
            for c in controls
        )
        or "  - (no controls: this is an animation)"
    )
    facts = _facts_text(block, ground_truth)

    user = (
        f"Build ONE self-contained canvas simulation for block {block['id']}.\n"
        f"TITLE: {spec.get('title')}\n"
        f"DESCRIPTION: {spec.get('description')}\n"
        f"LEARNING GOAL: {spec.get('learning_goal')}\n"
        f"DEFAULT BEHAVIOUR: {spec.get('default_behaviour')}\n"
        f"CONTROLS:\n{control_lines}\n\n"
        "FACTS THE SIMULATION MUST OBEY (ground truth - the drawn behaviour "
        f"must be physically correct per these):\n{facts}\n\n"
        "DESIGN DOCTRINE + EXAMPLES (the visual language of the page this sim "
        "lives on):\n"
        + design_context(cfg, with_examples=True)
        + "\n\nPALETTE (exact values from the page stylesheet; use these, "
        "invent nothing):\n"
        + palette_text(cfg)
        + "\nBRIDGE (medium translation, not doctrine): the doctrine and "
        "examples describe the whole page; the shell (grid, cards, tape, "
        "controls) is built for you by the renderer. You fill ONE canvas "
        "simulation inside a paper card: apply the doctrine's visual language "
        "in canvas 2D. In page.css use the palette variables by name; on "
        "canvas use the PALETTE hex values. The examples are single-file "
        "shell demos - read them for the visual language, never copy their "
        "structure.\n\n"
        "CONTRACT (hard):\n"
        "- PHYSICS CONTRACT: the behaviour you draw must follow the FACTS above. "
        "When a control changes a value, the on-screen relationship must match "
        "the stated equations and DEFAULT BEHAVIOUR. Never invent physics "
        "beyond these facts; where the facts do not pin a detail, draw exactly "
        "what DESCRIPTION and DEFAULT BEHAVIOUR state.\n"
        "- page.js MUST define exactly one registration using this skeleton:\n"
        f"{_skeleton_for(block['id'])}\n"
        "- Plain canvas 2D and requestAnimationFrame only. ctx.g is the 2d context.\n"
        "- No eval, no new Function, no fetch/XHR/WebSocket/import/require, no URL strings, "
        "no document.write, no inline <script>.\n"
        "- Use only CSS classes scoped under .zn-sim-" + block["id"] + " in page.css; "
        "never define global styles, never touch elements outside the simulation container.\n"
        "- Colours: use only PALETTE values (hex on canvas, variables by name "
        "in page.css). Invent no colours.\n"
        "- The runtime wires the range inputs to ctx.values[controlId] automatically.\n"
        "- The canvas buffer is fixed 480x320 and the shell scales it to fit any frame "
        "(phone ~360 px to laptop) without distortion: draw in that coordinate space, "
        "keep drawn text 14 px or larger in it, few on-screen labels, nothing essential "
        "smaller than that.\n"
        "- Clean geometry on canvas too (doctrine v1.3): straight lines, true arcs and "
        "circles, one consistent corner style; no hand wobble - annotation arrows are "
        "the only hand-drawn element.\n"
        'Return a JSON object: {"id": "' + block["id"] + '", "files": '
        '{"page.js": "<full file content>", "page.css": "<full file content or empty string>"}}.'
    )
    out = llm.call(
        "05-interactive",
        [
            {"role": "system", "content": _system_msg()},
            {"role": "user", "content": user},
        ],
        INTERACTIVE,
        "interactive output",
        extra_validator=_lint_feedback(block["id"]),
    )

    # Backstop only: _lint_feedback already fed any violation back into the
    # retry transcript, so reaching here means the stage output is lint-clean.
    js = out["files"].get("page.js", "")
    css = out["files"].get("page.css", "")
    if not js.strip():
        raise LintError(
            STAGE_ID,
            f"block {block['id']}: model returned an empty page.js",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    hits = lint_js(f"{block['id']}/page.js", js) + lint_css(
        f"{block['id']}/page.css", css
    )
    if hits:
        raise LintError(
            STAGE_ID,
            f"block {block['id']} generated code violates hard lints:\n"
            + "\n".join(hits),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    return out


def _lint_feedback(block_id: str) -> Callable[[dict[str, Any]], list[str]]:
    """Lint INSIDE the retry loop (same machinery as 04-draft's rule feedback):
    the model sees its own lint violations in the transcript and fixes them,
    instead of the run dying on a post-call LintError."""

    def check(parsed: dict[str, Any]) -> list[str]:
        js = parsed.get("files", {}).get("page.js", "")
        css = parsed.get("files", {}).get("page.css", "")
        if not js.strip():
            return [f"block {block_id}: page.js must be a non-empty file"]
        return lint_js(f"{block_id}/page.js", js) + lint_css(
            f"{block_id}/page.css", css
        )

    return check


def _system_msg() -> str:
    return (
        "[ZIVON STAGE: 05-interactive] You are the Visual Builder agent in the Zivon content "
        "factory. You write canvas simulations for study pages.\n"
        "RULES:\n- Plain JavaScript, canvas 2D only, no libraries, no network, no eval.\n"
        "- Never invent physics facts: the behaviour you draw must follow the "
        "FACTS in the user message.\n"
        "- Output exactly ONE JSON object. No markdown, no commentary.\n"
    )


def _skeleton_for(block_id: str) -> str:
    return SIM_SKELETON.replace("<BLOCK_ID>", block_id).strip()
