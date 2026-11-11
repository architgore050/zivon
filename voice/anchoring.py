"""Anchoring — the tutor knows what is on screen (spec.md §7, ADR-0012/0014).

Three jobs:

1. **Snapshot in (ADR-0014):** parse + validate the dock's
   ``context.snapshot`` (≤ 4 KB, structured fields, latest-wins). The
   binding schema is ws-contract.md §2 (SP1 proposed payload); the
   ADR-0014 wording's richer fields (``visible_blocks``, ``block_title``,
   ``block_text``, ``sim_states``) are accepted when present — the merge
   agent reconciles the two wordings; both validate here either way.
2. **Prompt context out:** a bounded, delimited DATA block that is entirely
   **human-readable** — page/topic title, chapter/section, the visible
   content of the current part, interactive values, the names of the other
   parts on the page. Machine element ids (``b-13``, ``block_id``,
   ``block_type``) are internal protocol only: they never reach the model's
   prompt (founder requirement 2026-11-11). The grounding law in the tutor
   prompt (spec.md Appendix A) makes this the universe of the answer;
   injection hygiene = data, never instructions (ADR-0014).
3. **Highlights out (ADR-0012 + T7):** the brain's optional first line
   ``REF: <part name>[,<part name>]`` uses the human names from the context;
   the harness resolves them back to block ids against the snapshot's list
   (unknown names dropped). Ids are therefore spoken/written by nobody, while
   the page JS still receives real ids in ``highlight``. Garbled/missing REF
   degrades to no-highlight (never an error, never spoken).
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
    "resolve_refs",
    "validate_ref_ids",
]

# Machine block types → the words a tutor would use. Anything unknown becomes
# a plain "section", so a vendor/client token can never leak into the prompt.
_TYPE_PHRASES = {
    "text": "text",
    "paragraph": "text",
    "animation": "animation",
    "simulation": "interactive simulation",
    "sim": "interactive simulation",
    "diagram": "diagram",
    "figure": "diagram",
    "check": "quick-check question",
    "quiz": "quick-check question",
    "worked_example": "worked example",
    "example": "worked example",
}

_MAX_PART_NAMES = 8


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
    # (name, id) pairs for the parts the client described — the only way the
    # model's human-readable REF names resolve back to highlight ids.
    part_names: tuple[tuple[str, str], ...] = ()
    topic_title: str = ""  # human page title (client-supplied; falls back)

    @property
    def block_list(self) -> tuple[str, ...]:
        """The page's block ids (for REF validation, spec.md §7)."""
        if self.visible_blocks:
            return self.visible_blocks
        return (self.block_id,)

    @property
    def label_map(self) -> dict[str, str]:
        """Case-folded human name → block id (REF resolution).

        The current part's own title is always resolvable; ``part_names``
        carries the rest of the page when the dock described the page.
        """
        mapping: dict[str, str] = {}
        for name, block_id in self.part_names:
            key = name.strip().casefold()
            if key:
                mapping.setdefault(key, block_id)
        if self.block_title:
            mapping.setdefault(self.block_title.strip().casefold(), self.block_id)
        return mapping


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
    names: list[tuple[str, str]] = []
    if isinstance(visible, list) and visible and isinstance(visible[0], dict):
        # ADR-0014 wording: visible_blocks[{id, type, title}]
        ids = tuple(
            str(b.get("id")) for b in visible if isinstance(b, dict) and b.get("id")
        )
        names = [
            (str(b.get("title")).strip(), str(b.get("id")))
            for b in visible
            if isinstance(b, dict)
            and b.get("id")
            and isinstance(b.get("title"), str)
            and b.get("title").strip()
        ]
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
    block_id = str(payload["block_id"])
    block_title = str(payload.get("block_title") or "")
    # The current part resolves by its own title even when the client sent
    # visible_blocks as bare ids (the pre-ADR-0014 wording).
    if block_title:
        names.append((block_title.strip(), block_id))
    return ContextSnapshot(
        topic_id=str(payload["topic_id"]),
        class_name=str(class_name or ""),
        chapter=str(payload["chapter"]),
        block_id=block_id,
        block_type=str(payload["block_type"]),
        sim_id=str(payload.get("sim_id") or ""),
        sim_vars={str(k): str(v) for k, v in sim_vars.items()},
        scroll_pct=scroll_pct,
        lang_pref=str(payload.get("lang_pref") or "hi-en"),
        ts=ts,
        block_title=block_title,
        block_text=block_text,
        visible_blocks=ids,
        part_names=tuple(names),
        topic_title=str(
            payload.get("topic_title")
            or payload.get("page_title")
            or payload.get("title")
            or ""
        ),
    )


def build_prompt_context(
    snapshot: ContextSnapshot | None,
    settings: VoiceSettings,
    *,
    stale: bool,
) -> str:
    """Bounded, human-readable prompt context (spec.md §7; ≤ 600-char text).

    Deliberately id-free: no ``b-NN``, no ``block_id``/``block_type`` token,
    no visible-blocks id list. The model sees what a tutor standing next to
    the student would see — the page, the section, the content on screen —
    and refers to parts by their names. Empty string when there is no
    snapshot — the caller adds the honest F7 note ("page ka context nahi mil
    raha") instead of pretending to anchor.
    """
    if snapshot is None:
        return ""
    lines: list[str] = []
    page_title = snapshot.topic_title or snapshot.chapter
    title_bits = [page_title] if page_title else []
    if snapshot.class_name:
        title_bits.append(f"Class {snapshot.class_name}")
    page_line = " · ".join(title_bits)
    if page_line:
        lines.append(f"page: {page_line}")
    if snapshot.block_title:
        lines.append(f"section the student is looking at: {snapshot.block_title}")
    kind = _TYPE_PHRASES.get(snapshot.block_type.strip().lower(), "section")
    content = snapshot.block_text.strip()[: settings.context_block_text_max]
    if content:
        lines.append(f"what is on screen now ({kind}): {content}")
    elif not snapshot.block_title:
        # Never emit a bare id: describe the position honestly instead.
        lines.append(
            f"what is on screen now ({kind}): the part of the page the "
            "student is currently reading"
        )
    if snapshot.sim_id and snapshot.sim_vars:
        vars_text = ", ".join(f"{k}={v}" for k, v in snapshot.sim_vars.items())
        lines.append(f"interactive values on screen: {vars_text}")
    others = [
        name
        for name, _block_id in snapshot.part_names
        if name and name.strip().casefold() != snapshot.block_title.strip().casefold()
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for name in others:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    unique = unique[:_MAX_PART_NAMES]
    if unique:
        lines.append(f"other parts visible on this page: {'; '.join(unique)}")
    if stale:
        lines.append(
            "NOTE: this snapshot is stale — answer generically and say you "
            "cannot see the page clearly (never claim to see its current state)."
        )
    return "\n".join(lines)


def resolve_refs(
    raw_refs: tuple[str, ...], snapshot: ContextSnapshot | None
) -> tuple[str, ...]:
    """Resolve the brain's REF names (or legacy ids) to validated block ids.

    The prompt asks for human names from the context; a model that echoes an
    id anyway is still honoured (backwards-compatible with the pre-2026-11-11
    prompt). Unknown values are dropped; with no snapshot or nothing valid the
    result is empty — no-highlight is the honest degrade (spec.md §7).
    """
    if snapshot is None or not raw_refs:
        return ()
    known = set(snapshot.block_list)
    labels = snapshot.label_map
    resolved: list[str] = []
    for raw in raw_refs:
        ref = raw.strip()
        if not ref:
            continue
        if ref in known:
            block_id = ref
        else:
            block_id = labels.get(ref.casefold(), "")
        if block_id and block_id in known and block_id not in resolved:
            resolved.append(block_id)
    return tuple(resolved)


def validate_ref_ids(
    raw_ids: tuple[str, ...], snapshot: ContextSnapshot | None
) -> tuple[str, ...]:
    """Back-compat alias for :func:`resolve_refs` (ids or human names)."""
    return resolve_refs(raw_ids, snapshot)
