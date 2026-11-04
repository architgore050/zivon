"""Design context loader - the single point where the factory touches design.

The design doctrine (markdown) and its example pages are the single source of
truth for visual style. The factory never copies doctrine text into prompts or
code: it hands the LIVE documents to the model stages at build time. A doctrine
edit therefore flows into every future run with no pipeline change, and new
example files are picked up by the examples glob automatically.

The shell stylesheet's CSS custom properties (zivon.css) are parsed and handed
over too: canvas code needs concrete colour values, and parsing keeps generated
colours identical to the shell that renders around them.

Budget: the composed block must fit limits.max_chars_design_context. A doctrine
that outgrows the model's context fails loudly with the numbers - never
silently truncated.
"""

from __future__ import annotations

import re

from .config import Config
from .errors import ConfigError


def doctrine_text(cfg: Config) -> str:
    path = cfg.repo_path(cfg.paths["doctrine"])
    if not path.is_file():
        raise ConfigError(f"design doctrine not found at {path}")
    return path.read_text(encoding="utf-8")


def examples_text(cfg: Config) -> str:
    """Every doctrine example page, by glob - open-ended: a new example file
    matching the pattern joins every future run without a pipeline change."""
    pattern = cfg.paths["doctrine_examples"]
    files = sorted(cfg.root.glob(pattern))
    if not files:
        raise ConfigError(
            f"no design doctrine examples match '{pattern}' under {cfg.root}"
        )
    return "\n\n".join(
        f"=== {f.name} ===\n{f.read_text(encoding='utf-8')}" for f in files
    )


def palette_text(cfg: Config) -> str:
    """The shell stylesheet's custom properties, verbatim: the exact tokens
    (colours and font stacks) the generated page is rendered with."""
    css_path = cfg.repo_path(cfg.paths["frontend"]) / "assets" / "zivon.css"
    if not css_path.is_file():
        raise ConfigError(f"shell stylesheet not found at {css_path}")
    pairs = re.findall(
        r"(--[a-z][a-z0-9-]*)\s*:\s*([^;]+);",
        css_path.read_text(encoding="utf-8"),
    )
    if not pairs:
        raise ConfigError(f"no CSS custom properties found in {css_path}")
    return "\n".join(f"{name}: {value.strip()}" for name, value in pairs)


def design_context(cfg: Config, *, with_examples: bool) -> str:
    """The doctrine (and optionally its example pages) as one labelled block,
    budget-checked."""
    parts = [f"--- design doctrine: {cfg.paths['doctrine']} ---", doctrine_text(cfg)]
    if with_examples:
        parts.append(
            "--- doctrine example pages: VISUAL STYLING REFERENCE ONLY ---\n"
            "These pages show how a finished lesson page LOOKS (paper, ink, cards, "
            "hand strokes, feedback) and how COMPLETE a finished page is. Their "
            "topic, facts, numbers, questions and examples belong to an unrelated "
            "chapter: never reuse or imitate their content, and never let their "
            "scope decide what your chapter should or should not cover - content "
            "coverage is dictated by the SOURCE MATERIAL, never by these pages."
        )
        parts.append(examples_text(cfg))
    block = "\n\n".join(parts)
    budget = cfg.limits["max_chars_design_context"]
    if len(block) > budget:
        raise ConfigError(
            f"design context is {len(block)} chars but "
            f"limits.max_chars_design_context is {budget}. Trim the doctrine/"
            "examples or raise the limit to fit the model's context."
        )
    return block
