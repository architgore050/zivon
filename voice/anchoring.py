"""Anchoring — the tutor knows what is on screen (spec.md §7, ADR-0012/0014).

Three jobs:

1. **Snapshot in (ADR-0014):** parse + validate the dock's
   ``context.snapshot`` (≤ 4 KB, structured fields, latest-wins). The
   binding schema is ws-contract.md §2 (SP1 proposed payload); the
   ADR-0014 wording's richer fields (``visible_blocks``, ``block_title``,
   ``block_text``, ``sim_states``) are accepted when present — the merge
   agent reconciles the two wordings; both validate here either way.
2. **Prompt context out:** a bounded, delimited DATA block (topic/chapter,
   current block, sim variables, the page's block-id list). The grounding
   law in the tutor prompt (spec.md Appendix A) makes this the universe of
   the answer; injection hygiene = data, never instructions (ADR-0014).
3. **Highlights out (ADR-0012 + T7):** the brain's ``REF:`` ids are
   validated against the snapshot's block list — unknown ids dropped,
   garbled/missing REF degrades to no-highlight (never an error, never
   spoken).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import VoiceSettings

__all__ = [
    "ContextSnapshot",
    "SnapshotError",
    "build_prompt_context",
    "parse_snapshot",
    "validate_ref_ids",
]


class SnapshotError(ValueError):
    """The snapshot payload is malformed or oversized (F7 posture)."""


@dataclass(frozen=True)
class ContextSnapshot:
    topic_id: str
    class_name: str  # 'class' is a keyword; wire name stays "class"
    chapter: str
    block_id: str
    block_type: str
    sim_id: str = ""
    sim_vars: dict[str, str] | None = None
    scroll_pct: int = 0
    lang_pref: str = "hi-en"
    ts: float = 0.0
    block_title: str = ""
    block_text: str = ""
    visible_blocks: tuple[str, ...] = ()  # page block ids, for REF validation

    @property
    def block_list(self) -> tuple[str, ...]:
        """The page's block ids (for REF validation, spec.md §7)."""
        if self.visible_blocks:
            return self.visible_blocks
        return (self.block_id,)


def parse_snapshot(
    payload: dict[str, Any], *, max_bytes: int = 4096
) -> ContextSnapshot:
    """Validate a ``context.snapshot`` payload server-side (ADR-0014).

    Raises SnapshotError on malformed/oversized payloads — the WS handler
    keeps the last good snapshot and answers generically (F7), never crashes.
    """
    if not isinstance(payload, dict):
        raise SnapshotError("snapshot must be an object")
    if len(json.dumps(payload, separators=(",", ":"))) > max_bytes:
        raise SnapshotError("snapshot exceeds the 4 KB bound (ADR-0014)")
    for required in ("topic_id", "chapter", "block_id", "block_type"):
        value = payload.get(required)
        if not isinstance(value, str) or not value:
            raise SnapshotError(f"snapshot.{required} must be a non-empty string")
    class_name = payload.get("class")
    if class_name is None and "class_name" in payload:
        class_name = payload["class_name"]
    sim_vars = payload.get("sim_vars") or {}
    if not isinstance(sim_vars, dict) or not all(
        isinstance(k, str) and isinstance(v, (str, int, float, bool))
        for k, v in sim_vars.items()
    ):
        raise SnapshotError("snapshot.sim_vars must be a flat string/number map")
    visible = payload.get("visible_blocks") or ()
    if isinstance(visible, list) and visible and isinstance(visible[0], dict):
        # ADR-0014 wording: visible_blocks[{id, type, title}]
        ids = tuple(
            str(b.get("id")) for b in visible if isinstance(b, dict) and b.get("id")
        )
    elif isinstance(visible, list):
        ids = tuple(str(b) for b in visible if b)
    else:
        ids = ()
    block_text = str(payload.get("block_text", "") or "")
    try:
        scroll_pct = int(payload.get("scroll_pct") or 0)
        ts = float(payload.get("ts") or 0.0)
    except (TypeError, ValueError) as exc:
        # int("abc") / float({...}) must surface as SnapshotError, never as a
        # bare ValueError that escapes the WS handler (F7 posture).
        raise SnapshotError(f"snapshot.scroll_pct/ts must be numeric: {exc}") from exc
    return ContextSnapshot(
        topic_id=str(payload["topic_id"]),
        class_name=str(class_name or ""),
        chapter=str(payload["chapter"]),
        block_id=str(payload["block_id"]),
        block_type=str(payload["block_type"]),
        sim_id=str(payload.get("sim_id") or ""),
        sim_vars={str(k): str(v) for k, v in sim_vars.items()},
        scroll_pct=scroll_pct,
        lang_pref=str(payload.get("lang_pref") or "hi-en"),
        ts=ts,
        block_title=str(payload.get("block_title") or ""),
        block_text=block_text,
        visible_blocks=ids,
    )


def build_prompt_context(
    snapshot: ContextSnapshot | None,
    settings: VoiceSettings,
    *,
    stale: bool,
) -> str:
    """Bounded prompt context block (spec.md §7; ≤ 600-char block text).

    Empty string when there is no snapshot — the caller adds the honest F7
    note ("page ka context nahi mil raha") instead of pretending to anchor.
    """
    if snapshot is None:
        return ""
    lines: list[str] = []
    title_bits = [bit for bit in (snapshot.chapter, snapshot.class_name) if bit]
    if title_bits:
        lines.append(f"topic: {' — '.join(title_bits)} ({snapshot.topic_id})")
    block_head = snapshot.block_title or snapshot.block_id
    lines.append(
        f"current block: [{snapshot.block_id}] {snapshot.block_type} — {block_head}"
    )
    if snapshot.block_text:
        text = snapshot.block_text[: settings.context_block_text_max]
        lines.append(f"block text: {text}")
    if snapshot.sim_id:
        vars_text = ", ".join(f"{k}={v}" for k, v in (snapshot.sim_vars or {}).items())
        lines.append(f"sim {snapshot.sim_id}: {vars_text or '(no vars reported)'}")
    ids = ", ".join(snapshot.block_list[:24])
    lines.append(f"block ids on page (REF targets): {ids}")
    if stale:
        lines.append(
            "NOTE: this snapshot is stale — answer generically and say you "
            "cannot see the page clearly (never claim to see its current state)."
        )
    return "\n".join(lines)


def validate_ref_ids(
    raw_ids: tuple[str, ...], snapshot: ContextSnapshot | None
) -> tuple[str, ...]:
    """Validate the brain's REF ids against the snapshot's block list.

    Unknown ids are dropped; with no snapshot or nothing valid the result is
    empty — no-highlight is the honest degrade (spec.md §7, never an error).
    """
    if snapshot is None or not raw_ids:
        return ()
    known = set(snapshot.block_list)
    return tuple(ref for ref in raw_ids if ref in known)
