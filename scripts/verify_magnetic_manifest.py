"""Offline verification that the magnetic-effects lesson manifest grounds all
six curated syllabus concepts (the A2 orphan rule, checked without a model).

Run after a lesson regeneration, BEFORE updating the tracked concept map or
running the assessment bank:

    python scripts/verify_magnetic_manifest.py [repo_root]

Thin CLI over `factory.concept_map_verify.concept_coverage_problems` - the SAME
deterministic checker the 09-review concept-map gate runs inside the pipeline
(no test-specific fork, no weakening). The checker's findings, in order:

1. the manifest names the expected chapter/class (checked here, CLI-level);
2. every section of the manifest is mapped in the tracked concept map;
3. every curated concept of the syllabus chapter owns at least one mapped
   section (no orphan concept - this is exactly A2's fatal `concept.orphan`);
4. the motor / electromagnetic-induction / generator topics the rationalised
   NCERT Class X book removed are actually covered by the mapped sections
   (title/content keyword check against the Siyavula-based supplements -
   `factory.concept_map_verify.TOPIC_KEYWORDS`).

Exit codes: 0 = all six concepts grounded; 1 = findings above (print, never
silently pass); 2 = missing manifest/map/syllabus inputs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Run as `python scripts/verify_magnetic_manifest.py [repo]`; make the repo
# root importable so `factory` resolves regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from factory.concept_map_verify import TOPIC_KEYWORDS, concept_coverage_problems

SLUG = "magnetic-effects-of-electric-current"
CHAPTER = "class-10-magnetic-effects-of-electric-current"

__all__ = ["CHAPTER", "SLUG", "TOPIC_KEYWORDS", "load", "main"]


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
    concept_map = cmap.get("section_concept_map") or {}
    known = [c["concept_id"] for c in chapter["concepts"]]

    print(f"manifest sections: {len(sections)}  blocks: {len(blocks)}")
    for s in sections:
        print(f"  {s.get('id')}  {s.get('title')}")

    problems.extend(
        concept_coverage_problems(
            manifest,
            blocks,
            concept_map,
            known,
            topic_keywords=TOPIC_KEYWORDS,
        )
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
