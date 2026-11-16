"""The renderer hook contract, as a deterministic check (P1, 2026-11-15).

A generated lesson page is consumed by code that must never guess: the shell
kit keys read-aloud controls and the tutor anchor off ``id="b-NN"``, the lesson
drawer keys off ``data-section-id``, and the product layers read
``manifest.json`` instead of re-parsing HTML. Those hooks are the page's public
interface, so they are checked mechanically - by the unit tests today, and by
P4's deterministic eval checkers (``EV-SYN-001`` render contract,
``EV-VIS-002`` visual/metadata conformance) once registered.

Why this lives in ``factory/`` rather than ``testing/``: the renderer owns the
contract, and ``evals/`` must not import the test tree. ``hook_issues`` takes
plain strings/dicts, so an eval checker can call it on a golden page with zero
setup - no model, no network, no browser.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

SECTION_ID_RE = re.compile(r"^sec-[0-9]{2}$")
BLOCK_ID_RE = re.compile(r"^b-[0-9]{2}$")

# class -> the block type it must declare (mirrors factory/schemas.BLOCK_TYPES
# and the product inventory's element names).
BLOCK_CLASS_TYPES = {
    "zn-text": "text",
    "zn-example": "worked_example",
    "zn-check": "check",
    "zn-reveal": "reveal",
    "zn-diagram": "diagram",
    "zn-sim": "simulation",
}

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _HookScan(HTMLParser):
    """Collect every block element and the section wrapper that owns it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str], dict[str, str]]] = []
        self.blocks: list[dict[str, Any]] = []
        self.sections: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        classes = set(attr_map.get("class", "").split())
        is_section = tag == "section" and "zn-section" in classes
        block_type = next(
            (btype for cls, btype in BLOCK_CLASS_TYPES.items() if cls in classes),
            None,
        )
        if block_type is not None:
            owner = next(
                (
                    entry
                    for entry in reversed(self.stack)
                    if entry[0] == "section" and "zn-section" in entry[1]
                ),
                None,
            )
            self.blocks.append(
                {
                    "tag": tag,
                    "attrs": attr_map,
                    "type": block_type,
                    "section": owner[2].get("data-section-id", "") if owner else "",
                }
            )
        if is_section:
            self.sections.append(attr_map)
        if tag not in _VOID_TAGS:
            self.stack.append((tag, classes, attr_map))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return


def hook_issues(html: str, manifest: dict[str, Any] | None = None) -> list[str]:
    """Return every hook-contract violation in ``html`` (empty = conformant).

    Each item names the rule it broke, so an eval report reads as a list of
    concrete defects rather than "page invalid".
    """
    scan = _HookScan()
    scan.feed(html)
    issues: list[str] = []
    if not scan.blocks:
        issues.append("no block elements found (expected data-block-type blocks)")

    seen_ids: set[str] = set()
    for block in scan.blocks:
        attrs = block["attrs"]
        block_id = attrs.get("id", "")
        where = f"<{block['tag']} id={block_id or '?'}>"
        if not BLOCK_ID_RE.match(block_id):
            issues.append(f"{where}: block id is not b-NN (stable block id rule)")
        elif block_id in seen_ids:
            issues.append(f"{where}: duplicate block id")
        seen_ids.add(block_id)
        declared = attrs.get("data-block-type", "")
        if declared != block["type"]:
            issues.append(
                f"{where}: data-block-type={declared!r}, expected {block['type']!r}"
            )
        concept = attrs.get("data-concept-id", "")
        if not concept:
            issues.append(f"{where}: missing data-concept-id")
        if not block["section"]:
            issues.append(f'{where}: not inside a <section class="zn-section"> wrapper')
        elif not concept.endswith(block["section"]):
            issues.append(
                f"{where}: data-concept-id={concept!r} does not end with the "
                f"owning section {block['section']!r}"
            )

    for section in scan.sections:
        section_id = section.get("id", "")
        if not SECTION_ID_RE.match(section_id):
            issues.append(
                f"section wrapper id={section_id!r}: not sec-NN "
                "(section wrapper id rule)"
            )
        if section.get("data-section-id") != section_id:
            issues.append(
                f"section wrapper id={section_id!r}: data-section-id "
                f"{section.get('data-section-id')!r} does not match its id"
            )
        if not section.get("data-concept-id"):
            issues.append(f"section wrapper id={section_id!r}: missing data-concept-id")

    if manifest is None:
        return issues

    block_map = manifest.get("blocks")
    if not isinstance(block_map, dict) or not block_map:
        issues.append("manifest has no blocks map (block -> section)")
        return issues
    for block in scan.blocks:
        block_id = block["attrs"].get("id", "")
        entry = block_map.get(block_id)
        if entry is None:
            issues.append(f"{block_id}: rendered block is absent from manifest blocks")
            continue
        if entry.get("type") != block["type"]:
            issues.append(
                f"{block_id}: manifest type {entry.get('type')!r} != {block['type']!r}"
            )
        if entry.get("section_id") != block["section"]:
            issues.append(
                f"{block_id}: manifest section {entry.get('section_id')!r} != "
                f"owning section {block['section']!r}"
            )
    for section in manifest.get("sections", []):
        for block_id in section.get("block_ids", []):
            if block_id not in block_map:
                issues.append(
                    f"section {section.get('id')!r}: block {block_id!r} is not in "
                    "the manifest blocks map"
                )
    return issues
