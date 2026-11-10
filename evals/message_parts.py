"""Multimodal message-content helpers for eval checkers and judges.

Since main's visual-review upgrade (2026-11-09/10) the factory's `09-review`
DESIGN call is multimodal: a chat message's ``content`` is a list of parts
(rendered screenshots + text parts), not a plain string. Eval prompt-contract
checks and judge calibration care only about the text parts; screenshots are
not text.

Kept deliberately tiny and dependency-free so both `evals.checkers` and
`evals.judges` can import it without a checker->judge dependency.
"""

from __future__ import annotations

from typing import Any


def message_text(content: Any) -> str:
    """Return the text carried by one chat message's ``content``.

    Accepts a plain string (pre-visual-review shape) or a list of content
    parts, joining the text parts and ignoring image parts.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
        return "\n".join(texts)
    return str(content)
