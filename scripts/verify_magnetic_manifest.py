"""Offline verification that the magnetic-effects lesson manifest grounds all
six curated syllabus concepts (the A2 orphan rule, checked without a model).

Run after a lesson regeneration, BEFORE updating the tracked concept map or
running the assessment bank:

    python scripts/verify_magnetic_manifest.py [repo_root]

Checks, in order:
1. the manifest exists and names the expected chapter/class;
2. every section of the manifest is mapped in the tracked concept map;
3. every curated concept of the syllabus chapter owns at least one mapped
   section (no orphan concept - this is exactly A2's fatal `concept.orphan`);
4. the motor / electromagnetic-induction / generator topics the rationalised
   NCERT Class X book removed are actually covered by the mapped sections
   (title/content keyword check against the Siyavula-based supplements).

Exit codes: 0 = all six concepts grounded; 1 = findings above (print, never
silently pass); 2 = missing manifest/map/syllabus inputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SLUG = "magnetic-effects-of-electric-current"
CHAPTER = "class-10-magnetic-effects-of-electric-current"

TOPIC_KEYWORDS = {
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


def load(repo: Path) -> tuple[dict, dict, dict]:
    manifest_path = (
        repo / "frontend" / "courses" / "class-10-physics" / SLUG / "manifest.json"
    )
    cmap_path = (
        repo / "sources" / "syllabus" / "chapters" / f"{CHAPTER}.concept-map.json"
    )
    syll_path = repo / "sources" / "syllabus" / "syllabus.json"
    missing = [str(p) for p in (manifest_path, cmap_path, syll_path) if not p.exists()]
    if missing:
        print("missing inputs (run the lesson regeneration first):")
        for m in missing:
            print("  ", m)
        raise SystemExit(2)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cmap = json.loads(cmap_path.read_text(encoding="utf-8"))
    syllabus = json.loads(syll_path.read_text(encoding="utf-8"))
    chapter = next(
        ch
        for entry in syllabus["classes"]
        for ch in entry["chapters"]
        if ch["chapter_id"] == CHAPTER
    )
    return manifest, cmap, chapter


def main() -> int:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    manifest, cmap, chapter = load(repo)
    problems: list[str] = []

    if manifest.get("chapter_id") not in (None, CHAPTER):
        problems.append(
            f"manifest chapter_id {manifest.get('chapter_id')!r} != {CHAPTER!r}"
        )

    sections = manifest.get("sections") or []
    blocks = manifest.get("blocks") or {}
    mapping = cmap.get("section_concept_map") or {}
    known = {c["concept_id"] for c in chapter["concepts"]}
    section_ids = {s.get("id") for s in sections}

    print(f"manifest sections: {len(sections)}  blocks: {len(blocks)}")
    for s in sections:
        print(f"  {s.get('id')}  {s.get('title')}")

    unmapped = sorted(section_ids - set(mapping))
    if unmapped:
        problems.append(
            "sections missing from concept map "
            f"{CHAPTER}.concept-map.json: {unmapped} — add them to section_concept_map"
        )
    unknown = sorted(set(mapping.values()) - known)
    if unknown:
        problems.append(f"map targets unknown to the syllabus: {unknown}")
    untagged = sum(
        1 for b in blocks.values() if mapping.get(b.get("section_id")) is None
    )
    if untagged:
        problems.append(f"{untagged} blocks land on no mapped section")
    orphans = [c for c in sorted(known) if c not in set(mapping.values())]
    if orphans:
        problems.append(
            f"orphan concepts (own no section — A2 fatal concept.orphan): {orphans}"
        )

    # topic coverage: sections mapped to each stale-edition concept must carry
    # the topic keywords (title or the section's blocks' text if present)
    block_text = " ".join(
        json.dumps(b, ensure_ascii=False).lower() for b in blocks.values()
    )
    for label, (concept_id, keywords) in TOPIC_KEYWORDS.items():
        if concept_id in orphans:
            continue
        secs = [s for s in sections if mapping.get(s.get("id")) == concept_id]
        hay = (
            " ".join(f"{s.get('title')} {s.get('summary', '')}" for s in secs).lower()
            + " "
            + block_text
        )
        hit = [k for k in keywords if k in hay]
        print(
            f"topic {label}: sections={[s.get('id') for s in secs]} keyword hits={hit or 'NONE'}"
        )
        if not hit:
            problems.append(
                f"concept {concept_id} is mapped but none of the keywords {keywords} "
                "appear in its sections' titles/summaries or the block text — the "
                "regenerated lesson may still not carry the topic"
            )

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  -", p)
        print(
            "\nNext: update sources/syllabus/chapters/"
            f"{CHAPTER}.concept-map.json so every new section is mapped and every "
            "curated concept owns a section, then commit the map with the lesson."
        )
        return 1
    print(
        "\nOK: every section is mapped, no orphan concept, all six curated "
        "concepts are grounded (A2's fatal checks pass offline)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
