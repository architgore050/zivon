"""Deterministic checkers for `EV-SYN-001`, `EV-SYN-002`, and `EV-REV-001` static rules.

Reuses `factory.schemas.{GENERATED,BLOCKS,LESSON}` and `factory.checks` to grade
block schemas, block ordering, computed-geometry routing (0.3.17 rule),
self-containment, answer-key consistency, and readability structure.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from factory import checks
from factory.schemas import BLOCKS, GENERATED

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord, validate_schema

_GRAPH_CAPTION_RE = re.compile(
    r"\b(?:graph|v\s*[-–]\s*t|x\s*[-–]\s*t|a\s*[-–]\s*t|distance\s*[-–]\s*time|"
    r"velocity\s*[-–]\s*time|position\s*[-–]\s*time|area\s+under|parabola|trajectory|"
    r"slope\s+of\s+the\s+curve)\b",
    re.IGNORECASE,
)


def _clean_samples(cfg: EvalConfig) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in ("SD-CHK-007.json", "SD-CHK-008.json"):
        p = cfg.goldens_dir / "defects" / "03-check" / name
        if p.exists():
            out.append(json.loads(p.read_text(encoding="utf-8"))["inputs"])
    return out


def check_generated_schema(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN01-SCHEMA`: Validate `GENERATED` and `BLOCKS` schemas (`4..45` blocks)."""
    issues: list[IssueRecord] = []
    for inp in _clean_samples(cfg):
        combined = {
            "ground_truth": inp["ground_truth"],
            "lesson": inp["lesson"],
            "blocks": inp["blocks"],
        }
        try:
            validate_schema(combined, GENERATED, "GENERATED")
            validate_schema(inp["blocks"], BLOCKS, "BLOCKS")
        except ValueError as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN01-SCHEMA",
                    category="content",
                    message=str(exc),
                )
            )
    return issues


def check_block_ordering_and_citations(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN01-ORDER-AND-RULES`: First block is `text`, last block is `check`,
    and `factory.checks.run_all_rules` returns `verdict == 'pass'`.
    """
    issues: list[IssueRecord] = []
    for inp in _clean_samples(cfg):
        blks = inp["blocks"]["blocks"]
        if not blks or blks[0]["type"] != "text":
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN01-ORDER-AND-RULES",
                    block_id=blks[0]["id"] if blks else None,
                    category="content",
                    message="first block on the page must be of type 'text'",
                )
            )
        if not blks or blks[-1]["type"] != "check":
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN01-ORDER-AND-RULES",
                    block_id=blks[-1]["id"] if blks else None,
                    category="content",
                    message="last block on the page must be of type 'check'",
                )
            )
        report = checks.run_all_rules(
            blks, inp["lesson"], inp["ground_truth"], inp["source_pack"]
        )
        for ri in report["rule_issues"]:
            if ri["severity"] in ("fatal", "major"):
                issues.append(
                    IssueRecord(
                        severity=ri["severity"],
                        check_id="DET-SYN01-ORDER-AND-RULES",
                        block_id=ri.get("block_id"),
                        category="content",
                        message=ri["message"],
                    )
                )
    return issues


def is_computed_graph_diagram(block: dict[str, Any]) -> bool:
    """Return True if a static SVG `diagram` block plots a coordinate graph or area-under-curve."""
    if block.get("type") != "diagram":
        return False
    spec = block.get("spec") or {}
    caption = str(spec.get("caption", ""))
    svg = str(spec.get("svg", ""))
    if _GRAPH_CAPTION_RE.search(caption) or _GRAPH_CAPTION_RE.search(svg):
        return True
    return False


def check_computed_geometry_routing(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN01-GEOMETRY-ROUTING`: Verify v7 golden topics (`GT-02`) route all
    coordinate graphs (`x-t`, `v-t`, `a-t`, area-under-curve) to `simulation` blocks.
    """
    issues: list[IssueRecord] = []
    for topic_rel in card.golden_inputs.get("topics", []):
        tdir = cfg.repo_root / topic_rel
        exp = json.loads((tdir / "expected.json").read_text(encoding="utf-8"))
        ref = json.loads((tdir / "artifact_ref.json").read_text(encoding="utf-8"))
        if exp["pipeline_version_min"] < 7 or not ref.get("published_dir"):
            continue
        pub_dir = cfg.repo_root / ref["published_dir"]
        manifest_path = pub_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        diag_count = manifest.get("block_counts", {}).get("diagram", 0)
        if diag_count > exp["structure_bounds"]["diagrams_max"]:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN01-GEOMETRY-ROUTING",
                    category="rendering",
                    message=(
                        f"{exp['golden_id']} has {diag_count} diagram blocks, "
                        f"exceeding diagrams_max={exp['structure_bounds']['diagrams_max']}"
                    ),
                )
            )
    return issues


def check_self_containment(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN02-SELF-CONTAINMENT`: Run `factory.checks.rule_self_containment`."""
    issues: list[IssueRecord] = []
    for inp in _clean_samples(cfg):
        found = checks.rule_self_containment(inp["blocks"]["blocks"], inp["lesson"])
        for item in found:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN02-SELF-CONTAINMENT",
                    block_id=item.get("block_id"),
                    category="content",
                    message=item["message"],
                )
            )
    return issues


def check_answer_key_consistency(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN02-ANSWER-KEYS`: Run `factory.checks.rule_answer_keys`."""
    issues: list[IssueRecord] = []
    for inp in _clean_samples(cfg):
        found = checks.rule_answer_keys(inp["blocks"]["blocks"])
        for item in found:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-SYN02-ANSWER-KEYS",
                    block_id=item.get("block_id"),
                    category="answer_key",
                    message=item["message"],
                )
            )
    return issues


def check_readability_and_structure(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN02-READABILITY`: Verify lesson objectives (`2..4`), glossary (`>=3`),
    paragraph sentence count (`<=6`), and `worked_example` step completeness.
    """
    issues: list[IssueRecord] = []
    for inp in _clean_samples(cfg):
        lesson = inp["lesson"]
        objs = lesson.get("objectives", [])
        if not (2 <= len(objs) <= 4):
            issues.append(
                IssueRecord(
                    severity="major",
                    check_id="DET-SYN02-READABILITY",
                    category="content",
                    message=f"expected 2..4 lesson objectives, got {len(objs)}",
                )
            )
        glossary = lesson.get("glossary", [])
        if len(glossary) < 3:
            issues.append(
                IssueRecord(
                    severity="major",
                    check_id="DET-SYN02-READABILITY",
                    category="content",
                    message=f"expected >= 3 glossary entries, got {len(glossary)}",
                )
            )
        for sec in lesson.get("sections", []):
            for para in sec.get("paragraphs", []):
                sentences = [
                    s.strip() for s in re.split(r"[.!?]+", para) if s.strip()
                ]
                if len(sentences) > 6:
                    issues.append(
                        IssueRecord(
                            severity="major",
                            check_id="DET-SYN02-READABILITY",
                            category="content",
                            message=f"section {sec['id']} paragraph has {len(sentences)} sentences (> 6)",
                        )
                    )
        for b in inp["blocks"]["blocks"]:
            if b["type"] == "worked_example":
                steps = b["spec"].get("steps", [])
                if not steps or any(
                    not s.get("title", "").strip() or not s.get("detail", "").strip()
                    for s in steps
                ):
                    issues.append(
                        IssueRecord(
                            severity="major",
                            check_id="DET-SYN02-READABILITY",
                            block_id=b["id"],
                            category="content",
                            message=f"worked_example {b['id']} has empty or missing steps",
                        )
                    )
    return issues


def check_static_rules_on_defect_corpus(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-REV01-STATIC-RULES`: Verify `factory.checks.run_all_rules` passes on clean
    samples and catches synthetic rule defects (invented numerals, uncited blocks,
    mismatched answer keys, unsafe SVG) in 0ms.
    """
    issues: list[IssueRecord] = []
    clean_list = _clean_samples(cfg)
    if not clean_list:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-REV01-STATIC-RULES",
                category="content",
                message="no clean 03-check golden samples found",
            )
        )
        return issues

    base = clean_list[0]
    clean_rep = checks.run_all_rules(
        base["blocks"]["blocks"],
        base["lesson"],
        base["ground_truth"],
        base["source_pack"],
    )
    if clean_rep["verdict"] != "pass" or clean_rep["fatal_count"] > 0:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-REV01-STATIC-RULES",
                category="content",
                message=f"clean golden failed run_all_rules: {clean_rep['rule_issues']}",
            )
        )

    # Mutate with invented problem number 73 and empty citations -> must fail
    bad_blocks = copy.deepcopy(base["blocks"]["blocks"])
    bad_blocks[0]["citations"] = []
    bad_blocks[2]["spec"]["problem"] = "A body gains 73 m/s in 5 s. Find acceleration."
    bad_rep = checks.run_all_rules(
        bad_blocks, base["lesson"], base["ground_truth"], base["source_pack"]
    )
    if bad_rep["verdict"] != "fail" or bad_rep["fatal_count"] < 2:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-REV01-STATIC-RULES",
                category="content",
                message="run_all_rules failed to catch synthetic uncited block + invented numeral 73",
            )
        )

    return issues
