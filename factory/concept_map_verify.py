"""Deterministic concept-map coverage checks (09-review concept_map gate + offline verify).

One shared checker, no test-specific fork, no weakening. The same
`concept_coverage_problems` is called by:

- **09-review** (`factory/review.py::run`) on EVERY round, re-deriving findings
  from the CURRENT (possibly 10-reviewfix-corrected) blocks, the rendered
  `render_out["manifest"]`, the EFFECTIVE concept map (the map the last
  10-reviewfix round corrected, else the map the last 09-review report judged,
  else the 02-generate map - re-derived from run artifacts on resume; see
  `factory.stages._effective_concept_map`), and the curated
  `factory.syllabus.curated_concept_ids`. Every finding is emitted as a FATAL
  `concept_map` issue; verdict=fail routes to the bounded 10-reviewfix catcher.
- **`scripts/verify_magnetic_manifest.py`**, the offline checkpoint, which
  stays a thin CLI over this function (unchanged semantics; exit 1 findings /
  0 pass / 2 missing).

Findings (one string per problem, stable ordering):

1. sections missing from the concept map (every manifest section id must be a key);
2. concept-map keys that match no current section id;
3. map targets unknown to the syllabus (not a curated concept id);
4. blocks landing on no mapped section;
5. orphan concepts (a curated concept id owning no mapped section - A2's fatal
   `concept.orphan`);
6. keyword coverage for `topic_keywords`: a curated concept that owns a mapped
   section must have at least one of its keywords in its sections' titles /
   summaries or in the block text (an orphan concept is reported once as an
   orphan, not again for keywords).

`TOPIC_KEYWORDS` (the three rationalised-NCERT Class-X topics - electric motor,
electromagnetic induction, electric generator - whose concept ids the curated
syllabus keeps although the rationalised book removed them) is importable for
callers; `topic_keywords` defaults to it.
"""

from __future__ import annotations

from typing import Any

# The three topics the rationalised NCERT Class X book removed but the curated
# syllabus keeps; the concept is covered by the Siyavula-based supplements and
# the mapped section must actually carry at least one keyword.
# keyword matching is case-insensitive; the concept id is the curated value.
TOPIC_KEYWORDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "electric-motor (curated: force-on-a-conductor-and-motor)": (
        "class-10-magnetic-effects-of-electric-current-force-on-a-conductor-and-motor",
        ("motor", "armature", "split ring", "commutator"),
    ),
    "electromagnetic-induction": (
        "class-10-magnetic-effects-of-electric-current-electromagnetic-induction",
        (
            "induction",
            "induced",
            "fleming's right-hand rule",
            "faraday",
        ),
    ),
    "electric-generator": (
        "class-10-magnetic-effects-of-electric-current-electric-generator",
        ("generator", "alternating current", "dynamo"),
    ),
}


def concept_coverage_problems(
    manifest: dict[str, Any] | None,
    blocks: Any,
    concept_map: dict[str, Any] | None,
    curated_concepts: Any,
    topic_keywords: dict[str, tuple[str, tuple[str, ...]]] = TOPIC_KEYWORDS,
) -> list[str]:
    """Deterministic concept-map coverage findings (no model call).

    `manifest` - rendered manifest v2 (`sections`, `blocks`, `chapter_id`).
    `blocks` - current block draft: `{"blocks": [...]}`, a block list, or a
        rendered block-id -> info map (the manifest `blocks` shape). Section
        ids are resolved from explicit `section_id`, then the rendered
        `manifest["blocks"]` map, then reader-order inheritance (the renderer's
        own rule); full block payloads count toward keyword coverage.
    `concept_map` - section id -> curated concept id (the EFFECTIVE map).
    `curated_concepts` - the curated concept-id vocabulary (iterable).
    `topic_keywords` - concept id -> keywords; `{}` disables keyword checks.
    """
    manifest = manifest if isinstance(manifest, dict) else {}
    mapping = {
        str(k): str(v)
        for k, v in (concept_map or {}).items()
        if k is not None and v is not None
    }
    known = {str(c) for c in (curated_concepts or []) if c}

    # Concept-map coverage is a contract against the curated syllabus. With no
    # curated concept vocabulary for the chapter AND no emitted map there is
    # nothing to verify (`_concept_map_check_data`: an absent or hand-curated
    # map is not a failure; `write_tracked_map` persists nothing). The check is
    # never weakened for a chapter that has curated concepts.
    if not known and not mapping:
        return []

    sections = [
        s
        for s in (manifest.get("sections") or [])
        if isinstance(s, dict) and s.get("id")
    ]
    section_ids = [str(s["id"]) for s in sections]
    section_id_set = set(section_ids)
    rendered_map = manifest.get("blocks") or {}
    if not isinstance(rendered_map, dict):
        rendered_map = {}

    block_entries = _block_list(blocks)
    # Union with the rendered blocks so a check sees every block that ships;
    # current draft entries win on a shared id.
    by_id: dict[str, dict[str, Any]] = {}
    for entry in _block_list(rendered_map):
        by_id[_bid(entry) or f"_rendered_{len(by_id)}"] = entry
    for entry in block_entries:
        by_id[_bid(entry) or f"_block_{len(by_id)}"] = entry
    all_blocks = list(by_id.values()) or block_entries

    assigned = _assign_sections(section_ids, all_blocks, rendered_map)

    problems: list[str] = []

    # 1. sections missing from the concept map
    unmapped = sorted(section_id_set - set(mapping))
    if unmapped:
        problems.append(
            "sections missing from concept map: "
            + str(unmapped)
            + " - add them to section_concept_map"
        )

    # 2. concept-map keys that match no current section id
    extra_keys = sorted(set(mapping) - section_id_set)
    if extra_keys:
        problems.append(
            "concept-map keys match no current section id: "
            + str(extra_keys)
            + " - keys must be current lesson section ids"
        )

    # 3. map targets unknown to the syllabus
    unknown = sorted(set(mapping.values()) - known)
    if unknown:
        problems.append("map targets unknown to the syllabus: " + str(unknown))

    # 4. blocks landing on no mapped section
    untagged = sum(
        1 for b in all_blocks if mapping.get(assigned.get(_bid(b)) or "") is None
    )
    if untagged:
        problems.append(f"{untagged} blocks land on no mapped section")

    # 5. orphan concepts (a curated concept id owning no mapped section)
    mapped_values = set(mapping.values())
    orphans = sorted(c for c in known if c not in mapped_values)
    if orphans:
        problems.append(
            "orphan concepts (own no section - A2 fatal concept.orphan): "
            + str(orphans)
        )

    # 6. keyword coverage for the named curated topics
    block_text = " ".join(_json_lower(b) for b in all_blocks)
    for concept_id, keywords in (topic_keywords or {}).values():
        if concept_id in orphans:
            continue  # already reported as an orphan; keywords can't fire either
        if concept_id not in known or concept_id not in mapped_values:
            continue  # not a curated concept for this chapter / not mapped
        secs = [s for s in sections if mapping.get(str(s["id"])) == concept_id]
        hay = (
            " ".join(
                f"{s.get('title') or ''} {s.get('summary') or ''}" for s in secs
            ).lower()
            + " "
            + block_text
        )
        hit = [k for k in keywords if k.lower() in hay]
        if not hit:
            problems.append(
                f"concept {concept_id} is mapped but none of the keywords "
                f"{keywords} appear in its sections' titles/summaries or the "
                "block text - the lesson may still not carry the topic"
            )

    return problems


def _bid(block: dict[str, Any]) -> str:
    return str(block.get("id") or "")


def _json_lower(obj: Any) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False).lower()
    except (TypeError, ValueError):
        return str(obj).lower()


def _block_list(blocks: Any) -> list[dict[str, Any]]:
    """Normalize a block draft to a list of dicts."""
    if blocks is None:
        return []
    if isinstance(blocks, list):
        return [b for b in blocks if isinstance(b, dict)]
    if isinstance(blocks, dict):
        inner = blocks.get("blocks")
        if isinstance(inner, list):
            return [b for b in inner if isinstance(b, dict)]
        # rendered block-id -> info map (manifest v2 `blocks`)
        out: list[dict[str, Any]] = []
        for bid, info in blocks.items():
            if isinstance(info, dict):
                entry = dict(info)
                entry.setdefault("id", bid)
                out.append(entry)
        return out
    return []


def _assign_sections(
    section_ids: list[str],
    block_entries: list[dict[str, Any]],
    rendered_map: dict[str, Any],
) -> dict[str, str | None]:
    """section id per block, mirroring the renderer (`_body_from_blocks`):
    explicit `section_id` wins when it names a known section, then the rendered
    manifest block map, then reader-order inheritance; monotone."""
    section_set = set(section_ids)
    out: dict[str, str | None] = {}
    current: str | None = section_ids[0] if section_ids else None
    for block in block_entries:
        declared = str(block.get("section_id") or "")
        if declared not in section_set:
            rendered = rendered_map.get(_bid(block)) or {}
            declared = str(rendered.get("section_id") or "")
        if declared in section_set:
            current = declared
        out[_bid(block)] = current if current in section_set else None
    return out


__all__ = ["TOPIC_KEYWORDS", "concept_coverage_problems"]
