"""Stage 06-interactive: the Visual Builder agent.

One model request per simulation block ("animation" is a simulation with zero
controls). The model writes topic-local JS/CSS under a strict skeleton; the
result is linted before anything proceeds. Diagrams are NOT model calls here -
their SVG comes from the draft stage and is rendered (and linted) as-is.

The prompt pins the shared contract (zivon.css / zivon.js class names) and
points at the design doctrine; the model never writes global styles.
"""

from __future__ import annotations

from typing import Any

from .artifacts import RunContext
from .config import Config
from .errors import LintError
from .lint import lint_css, lint_js
from .llm import LLMClient
from .schemas import INTERACTIVE

STAGE_ID = "06-interactive"

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
    cfg: Config, run_ctx: RunContext, llm: LLMClient, blocks: dict[str, Any]
) -> dict[str, Any]:
    sims = [b for b in blocks["blocks"] if b["type"] == "simulation"]
    results: dict[str, Any] = {}
    for b in sims:
        results[b["id"]] = _build_simulation(cfg, run_ctx, llm, b)
    return results


def _build_simulation(
    cfg: Config, run_ctx: RunContext, llm: LLMClient, block: dict[str, Any]
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
    doctrine_path = cfg.repo_path(cfg.paths["doctrine"])

    user = (
        f"Build ONE self-contained canvas simulation for block {block['id']}.\n"
        f"TITLE: {spec.get('title')}\n"
        f"DESCRIPTION: {spec.get('description')}\n"
        f"LEARNING GOAL: {spec.get('learning_goal')}\n"
        f"DEFAULT BEHAVIOUR: {spec.get('default_behaviour')}\n"
        f"CONTROLS:\n{control_lines}\n\n"
        "CONTRACT (hard):\n"
        "- page.js MUST define exactly one registration using this skeleton:\n"
        f"{_skeleton_for(block['id'])}\n"
        "- Plain canvas 2D and requestAnimationFrame only. ctx.g is the 2d context.\n"
        "- No eval, no new Function, no fetch/XHR/WebSocket/import/require, no URL strings, "
        "no document.write, no inline <script>.\n"
        "- Use only CSS classes scoped under .zn-sim-" + block["id"] + " in page.css; "
        "never define global styles, never touch elements outside the simulation container.\n"
        f"- Visual style: use the shared Field Notes tokens via CSS variables "
        "(var(--ink), var(--paper), var(--graphite), var(--pen-blue)) from zivon.css. "
        f"Reference: {doctrine_path}. Do not invent new colours beyond the doctrine tokens.\n"
        "- The runtime wires the range inputs to ctx.values[controlId] automatically.\n"
        'Return a JSON object: {"id": "' + block["id"] + '", "files": '
        '{"page.js": "<full file content>", "page.css": "<full file content or empty string>"}}.'
    )
    out = llm.call(
        "06-interactive",
        [
            {"role": "system", "content": _system_msg()},
            {"role": "user", "content": user},
        ],
        INTERACTIVE,
        "interactive output",
    )

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


def _system_msg() -> str:
    return (
        "[ZIVON STAGE: 06-interactive] You are the Visual Builder agent in the Zivon content "
        "factory. You write canvas simulations for study pages.\n"
        "RULES:\n- Plain JavaScript, canvas 2D only, no libraries, no network, no eval.\n"
        "- Output exactly ONE JSON object. No markdown, no commentary.\n"
    )


def _skeleton_for(block_id: str) -> str:
    return SIM_SKELETON.replace("<BLOCK_ID>", block_id).strip()
