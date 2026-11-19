"""The artifact builder: Visual Builder prompt + build loop (PL3, §3 step 1–2).

Reuses the content factory's discipline (`factory/interactive.py`,
`factory/design.py`) without forking it: the prompt hands the LIVE design
doctrine's §10.6/§10.7 device rules and the parsed shell palette (artifacts are
lesson-page devices, so §10 applies even though the session chrome is §1–§9),
pins the artifact output contract (`interactive-artifacts.md` §4), and runs the
hard lint INSIDE the retry loop — the model sees its own violations and gets up
to 2 rebuilds, exactly like `05-interactive`.

The route is the accepted founder decision D-PL-07 (ADR-0030): DeepSeek V4.1
Flash via the OpenCode API through the in-process `llm_manager` OpenAI-format
path, its own runtime secret/config (`ZIVON_PERSONALIZED_*`), one model call at
`reasoning_effort=medium` with a 120 s wall-clock deadline (the D-PL-06
recommendation). No completion cap is ever sent (repo law: the deadline is the
honest bound). This module never opens a second HTTP client; the only seam is
`LLMManager.complete`, and tests inject fakes behind the `ArtifactBuilder`
protocol (`backend/personalized/artifacts.py`).

The prompt carries **no student free text**: only the concept-level spec, the
cited claims and a generic misconception label ride in (`T-PL-17`,
`DET-PL03-NO-STUDENT`).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

from llm_manager import (
    LLMConfig,
    LLMManager,
    NonRetryableHTTPError,
    TransportError,
    ValidationExhaustedError,
    run_validation_rounds,
)

from ..logging_shim import log_event
from .artifacts import (
    ARTIFACT_META_CSP,
    LINT_VERSION,
    MAX_CONTROLS,
    MAX_DOM_NODES,
    MAX_HTML_BYTES,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    ArtifactBuilder,
    ArtifactBuildError,
    count_dom_nodes,
    doctrine_hash_of,
    lint_artifact_html,
)

STAGE_ID = "pl-artifact-build"
# §3.2: lint-in-retry — the first build plus at most 2 rebuilds.
MAX_BUILD_ROUNDS = 3
MAX_REBUILD_FEEDBACK_CHARS = 1200

ARTIFACT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["html"],
    "additionalProperties": False,
    "properties": {
        "html": {"type": "string", "minLength": 1},
    },
}

_ARTIFACT_SKELETON = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="<META_CSP>">
  <style>/* artifact-local only; doctrine palette values; no @import */</style>
</head>
<body>
  <main class="zn-art" aria-labelledby="art-title">
    <h1 id="art-title">…</h1>
    <!-- simulation only: one label + one range input per control -->
    <label for="u">…</label>
    <input id="u" type="range" min="0" max="1" step="0.01" value="0.5">
    <canvas width="480" height="320" role="img"
            aria-label="…names the current state…"></canvas>
    <p class="zn-art-read" aria-live="polite">…text mirror of the canvas state…</p>
  </main>
  <script>
    /* artifact-local only; no network/storage/parent access; the ONLY
       allowed parent call is the harness channel:
       window.parent.postMessage({source:"zivon-artifact", v:1, type:"ready"}, "*");
       then type:"state" (throttled >= 250 ms) and type:"fps" samples. */
  </script>
</body>
</html>
"""


def _skeleton() -> str:
    return _ARTIFACT_SKELETON.replace("<META_CSP>", ARTIFACT_META_CSP)


class ArtifactDesignContext:
    """The design material handed to the builder prompt, with the doctrine
    hash that pins the cache (§7). Tests inject fixed text; production reads
    the live files (a doctrine edit flows into every future build)."""

    def __init__(self, *, doctrine_block: str, palette_block: str, doctrine_hash: str):
        self.doctrine_block = doctrine_block
        self.palette_block = palette_block
        self.doctrine_hash = doctrine_hash


def default_design_context(
    *,
    repo_root: Path | None = None,
) -> ArtifactDesignContext:
    """Read the LIVE doctrine §10.6/§10.7 + the shell palette tokens.

    Mirrors `factory/design.py` (parse, never copy) at the backend's smaller
    budget: the artifact document is one canvas card, so only the two device
    sections are handed over — not the whole doctrine.
    """
    root = repo_root or Path(__file__).resolve().parents[2]
    doctrine_path = root / "docs" / "frontend" / "design-doctrine.md"
    if not doctrine_path.is_file():
        raise FileNotFoundError(f"design doctrine not found at {doctrine_path}")
    doctrine_text = doctrine_path.read_text(encoding="utf-8")
    sections = _doctrine_device_sections(doctrine_text)
    css_path = root / "frontend" / "assets" / "zivon.css"
    if not css_path.is_file():
        raise FileNotFoundError(f"shell stylesheet not found at {css_path}")
    pairs = re.findall(
        r"(--[a-z][a-z0-9-]*)\s*:\s*([^;]+);",
        css_path.read_text(encoding="utf-8"),
    )
    if not pairs:
        raise ValueError(f"no CSS custom properties found in {css_path}")
    palette = "\n".join(f"{name}: {value.strip()}" for name, value in pairs)
    return ArtifactDesignContext(
        doctrine_block=sections,
        palette_block=palette,
        doctrine_hash=doctrine_hash_of(doctrine_text),
    )


def _doctrine_device_sections(doctrine_text: str) -> str:
    """§10.6 (paper cards) + §10.7 (diagrams): the two sections an artifact
    must follow, verbatim from the live doctrine."""
    parts: list[str] = []
    for start, end in (("### 10.6", "### 10.8"), ("### 10.7", "### 10.8")):
        begin = doctrine_text.find(start)
        if begin == -1:
            raise ValueError(f"design doctrine is missing {start!r}")
        stop = doctrine_text.find(end, begin + len(start))
        parts.append(doctrine_text[begin:stop].rstrip())
    return "\n\n".join(parts)


# --- prompt assembly (§3 step 1; factory/interactive.py discipline) ---------


def builder_system_message() -> str:
    return (
        f"[ZIVON STAGE: {STAGE_ID}] You are the Visual Builder agent writing ONE "
        "self-contained interactive artifact for a Zivon personalized-learning "
        "session (a canvas simulation or a static SVG diagram).\n"
        "RULES:\n"
        "- Plain JavaScript, canvas 2D / inline SVG only, no libraries, no network, "
        "no storage, no eval, no parent access beyond the harness channel.\n"
        "- Never invent physics facts: the behaviour you draw must follow the CLAIMS "
        "in the user message. Your knowledge of Physics does NOT count beyond them.\n"
        '- Output exactly ONE JSON object of shape {"html": "<the full '
        'self-contained document>"}. No markdown, no commentary.\n'
    )


def build_user_message(
    spec: dict[str, Any],
    claims: list[dict[str, Any]],
    design: ArtifactDesignContext,
) -> str:
    """The build prompt: goal first, the rigid contract near the end, zero
    student free text (§2, §9)."""
    controls = spec.get("controls", [])
    kind = str(spec.get("kind", "simulation"))
    control_lines = (
        "\n".join(
            f'  - id "{c["id"]}", label "{c["label"]}", range {c["min"]}..{c["max"]}, '
            f"step {c['step']}, initial {c['initial']}"
            for c in controls
        )
        or "  - (none: this is a static diagram)"
    )
    claim_lines = (
        "\n".join(
            f"- {c.get('id')}: {c.get('statement', '')}"
            + (f" [{c.get('locator')}]" if c.get("locator") else "")
            for c in claims
        )
        or "- (no cited claims: draw exactly what LEARNING GOAL states)"
    )
    why = str(spec.get("why", "")).strip()
    why_line = f"\nWHY THIS VISUAL (the misconception it fixes): {why}\n" if why else ""

    return (
        f'GOAL: build ONE {kind} artifact titled "{spec.get("title")}". Success '
        "test: a Class 9–12 student manipulates it and SEES the relationship the "
        f'learning goal names: "{spec.get("learning_goal")}". The artefact runs '
        "in a sandboxed iframe with no network and no account data, on a low-end "
        "Android phone at 360 px." + why_line + "\n"
        f"CONTROLS:\n{control_lines}\n\n"
        "CLAIMS THE ARTIFACT MUST OBEY (ground truth — the drawn behaviour must be "
        f"physically correct per these):\n{claim_lines}\n\n"
        "DESIGN DOCTRINE — LESSON-DEVICE SECTIONS (the visual language of the card; "
        "flat paper, clean geometry, ink structure, graphite guides, pen-blue live "
        "quantity; no gradients/shadows/blur/grain):\n"
        f"{design.doctrine_block}\n\n"
        "PALETTE (exact values from the shell stylesheet; use these in CSS and on "
        "canvas, invent nothing):\n"
        f"{design.palette_block}\n\n"
        "CONTRACT (hard; the linter rejects violations back to you):\n"
        f"- OUTPUT SHAPE: exactly one HTML document following this skeleton (fill the "
        f"marked parts; keep the meta CSP byte-exact):\n{_skeleton()}\n"
        "- PHYSICS: compute geometry from the cited claims' equations in JS at draw "
        "time — loop the domain and evaluate; never hand-place plotted points or "
        "hand-write tick numbers. The quantity the learning goal names must visibly "
        "change with the inputs (value readout + moving point/curve). AXES ARE DATA: "
        "recompute axis range/ticks/labels every frame when a control changes a "
        "plotted quantity; label every axis with quantity + unit.\n"
        "- ACCESSIBILITY: exactly one <h1>; one <label for> per control; the canvas "
        'carries role="img" + an aria-label naming the current state; an '
        'aria-live="polite" text mirror (class zn-art-read) reflects live values '
        "throttled to >= 250 ms; keyboard-operable; a prefers-reduced-motion: reduce "
        "branch renders a static first frame with a visible Play control (listen to "
        "window.matchMedia('(prefers-reduced-motion: reduce)')).\n"
        "- RESPONSIVE: 100% width, fixed-aspect box, no horizontal overflow at 360 "
        "px; the canvas backing store stays 480x320 and is scaled by CSS; touch "
        "targets >= 40 px.\n"
        "- HARNESS CHANNEL: the only allowed parent interaction is "
        'window.parent.postMessage({source:"zivon-artifact", v:1, type:"ready"|"state"|"fps"|"error", ...}, "*") '
        "— post `ready` immediately on load, `state` summaries throttled >= 250 ms, "
        "an `fps` sample about every 1 s ({frames, elapsed_ms}). Never listen for "
        'privileged commands except {source:"zivon-host", type:"pause"|"resume"|"reload"}; '
        "never touch window.parent or window.top any other way.\n"
        "- SECURITY: no eval, no new Function, no fetch/XHR/WebSocket/EventSource/"
        "sendBeacon, no import/require, no localStorage/sessionStorage/indexedDB/"
        "document.cookie, no <form>, no <iframe>/<object>/<embed>, no window.top/"
        "window.open/location navigation/history pushState, no <meta refresh>, no "
        "<base>, no external URL anywhere, no javascript: URL, no data: URL except "
        "img/font, no clipboard, no Notification, no fullscreen, no inline on*= "
        "handlers (use addEventListener), no <a> links. Exactly ONE inline <script> "
        "block and ONE inline <style> block.\n"
        f"- BUDGETS: <= {MAX_HTML_BYTES // 1024} KB of HTML, <= {MAX_DOM_NODES} DOM "
        f"nodes, <= {MAX_CONTROLS} controls; requestAnimationFrame only; no timers "
        "shorter than 16 ms; stop the loop when paused.\n"
        "- COLOUR: use only PALETTE values (hex on canvas, variables in CSS). "
        "Invent no colours. Clean geometry: straight lines, true arcs and circles, "
        "one consistent corner style — annotation arrows are the only hand-drawn "
        "element.\n"
        f"- VERSIONS: prompt_version {PROMPT_VERSION}, schema_version {SCHEMA_VERSION}, "
        f"lint_version {LINT_VERSION} (recorded in the cache row; do not embed them "
        "in the document).\n"
        'Return ONE JSON object: {"html": "<full document>"}.'
    )


# --- the engine ---------------------------------------------------------------


class LLMManagerArtifactBuilder(ArtifactBuilder):
    """The default engine: one D-PL-07 route call + lint-in-retry + render gate.

    `render_gate` is the injectable headless check (`artifact_sandbox.py`);
    when it is `None` (browser tooling absent) the gate is skipped and the
    artifact ships on lint alone — recorded, not silent, in the row's
    `render_ms = NULL`."""

    def __init__(
        self,
        llm_config: LLMConfig,
        design: ArtifactDesignContext,
        *,
        render_gate: Any | None = None,
        rounds: int = MAX_BUILD_ROUNDS,
        temperature: float = 0.2,
    ) -> None:
        self._config = llm_config
        self._design = design
        self._render_gate = render_gate
        self._rounds = max(1, rounds)
        self._temperature = temperature

    def build(
        self, spec: dict[str, Any], claims: list[dict[str, Any]]
    ) -> tuple[str, int, int | None, str | None]:
        messages = [
            {"role": "system", "content": builder_system_message()},
            {"role": "user", "content": build_user_message(spec, claims, self._design)},
        ]
        lint_hits_latest: list[str] = []
        model_seen: str | None = None

        def call_fn(
            round_no: int, transcript: list[dict[str, str]]
        ) -> tuple[str, str | None]:
            nonlocal model_seen
            manager = LLMManager(self._config)
            try:
                result = manager.complete(transcript, temperature=self._temperature)
            except TransportError as exc:
                reason = "timeout" if "deadline" in str(exc).lower() else "route"
                raise ArtifactBuildError(reason, str(exc)) from exc
            except NonRetryableHTTPError as exc:
                raise ArtifactBuildError("route", str(exc)) from exc
            model_seen = result.model
            # No per-round event here: `personalized.artifact.requested` is the
            # map-declared request edge emitted once by ensure_artifact (its
            # required fields artifact_id/kind/weak_grounding are unknown at
            # this seam), and a rejected round already rides
            # `personalized.artifact.retry` via on_reject below.
            return result.text, result.finish_reason

        def lint_feedback(parsed: dict[str, Any]) -> list[str]:
            nonlocal lint_hits_latest
            html = parsed.get("html")
            if not isinstance(html, str) or not html.strip():
                return ["html must be a non-empty string carrying the full document"]
            hits = lint_artifact_html(html)
            nodes = count_dom_nodes(html)
            if nodes > MAX_DOM_NODES:
                hits.append(
                    f"1: {nodes} DOM nodes exceed {MAX_DOM_NODES} [LINT_DOM_NODES]"
                )
            lint_hits_latest = hits
            return hits

        try:
            parsed = run_validation_rounds(
                call_fn,
                messages,
                ARTIFACT_OUTPUT_SCHEMA,
                "artifact html",
                rounds=self._rounds,
                extra_validator=lint_feedback,
                on_reject=lambda no, err: log_event(
                    "personalized.artifact.retry",
                    {
                        "stage": STAGE_ID,
                        "round": no,
                        "reason_code": "lint",
                        "first_violation": err[:MAX_REBUILD_FEEDBACK_CHARS],
                    },
                ),
            )
        except ValidationExhaustedError as exc:
            raise ArtifactBuildError(
                "lint",
                str(exc),
                lint_hits=len(lint_hits_latest),
                model=model_seen,
            ) from exc

        html = str(parsed["html"])
        # The render gate runs OUTSIDE the student request path and never
        # changes the physics contract — it is the headless proof of §3 step 4.
        render_ms: int | None = None
        if self._render_gate is not None:
            report = self._render_gate(html)
            render_ms = getattr(report, "render_ms", None)
            failures = list(getattr(report, "failures", []) or [])
            if failures:
                raise ArtifactBuildError(
                    "render",
                    "; ".join(failures[:5]),
                    render_ms=render_ms,
                    model=model_seen,
                )
        # No `personalized.artifact.ready` here: the row-backed event is
        # emitted once by ensure_artifact when the row is actually marked
        # ready (its required fields ride the row, not the builder seam).
        return html, 0, render_ms, model_seen


def builder_from_config(
    llm_config: LLMConfig,
    design: ArtifactDesignContext,
    *,
    render_gate: Any | None = None,
) -> LLMManagerArtifactBuilder:
    """Wire the D-PL-06 recommendation: medium reasoning effort, 120 s deadline.
    Everything else carries over from the caller's route config untouched."""
    cfg = dataclasses.replace(
        llm_config,
        reasoning_effort=llm_config.reasoning_effort or "medium",
        call_deadline_s=llm_config.call_deadline_s or 120.0,
    )
    return LLMManagerArtifactBuilder(cfg, design, render_gate=render_gate)
