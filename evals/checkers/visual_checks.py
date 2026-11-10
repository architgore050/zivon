"""Deterministic checkers for `EV-VIS-001` and `EV-REV-002` Part A (`SD-SEC-001..005`).

Reuses `factory.lint`, `factory.checks.rule_diagram_svg`, and
`factory.review._static_review_findings`, plus AST/regex verification of computed
simulation loops and DOM/a11y/kit-chrome invariants.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from factory.checks import rule_diagram_svg
from factory.lint import lint_css, lint_html, lint_js, lint_page_css_scope
from factory.review import _static_review_findings

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord


def _resolve_topic_dir(
    cfg: EvalConfig, topic_rel: str
) -> tuple[dict[str, Any], Path | None]:
    tdir = cfg.repo_root / topic_rel
    exp = json.loads((tdir / "expected.json").read_text(encoding="utf-8"))
    ref = json.loads((tdir / "artifact_ref.json").read_text(encoding="utf-8"))
    if ref.get("published_dir"):
        return exp, cfg.repo_root / ref["published_dir"]
    if ref.get("reference_html"):
        return exp, (cfg.repo_root / ref["reference_html"]).parent
    return exp, None


def check_hard_lints_and_kit_scope(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-VIS01-LINTS-AND-SCOPE`: Run `lint_html`, `lint_js`, `lint_css`, and
    `lint_page_css_scope` on published golden topics.
    """
    issues: list[IssueRecord] = []
    for topic_rel in card.golden_inputs.get("topics", []):
        exp, pub_dir = _resolve_topic_dir(cfg, topic_rel)
        if pub_dir is None or not pub_dir.exists():
            continue
        if exp["golden_id"] == "GT-03":
            ref_html = pub_dir / "design-doctrine-lesson-example.html"
            if ref_html.exists():
                ref_text = ref_html.read_text(encoding="utf-8")
                for bad_pat in (r"\beval\s*\(", r"\bnew\s+Function\b", r"\bfetch\s*\("):
                    if re.search(bad_pat, ref_text):
                        issues.append(
                            IssueRecord(
                                severity="fatal",
                                check_id="DET-VIS01-LINTS-AND-SCOPE",
                                category="other",
                                message=f"GT-03: forbidden pattern {bad_pat} in {ref_html.name}",
                            )
                        )
            continue
        html_path = pub_dir / "index.html"
        if html_path.exists():
            for hit in lint_html(html_path.name, html_path.read_text(encoding="utf-8")):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-VIS01-LINTS-AND-SCOPE",
                        category="other",
                        message=f"{exp['golden_id']}: {hit}",
                    )
                )
        js_path = pub_dir / "page.js"
        if js_path.exists():
            for hit in lint_js("page.js", js_path.read_text(encoding="utf-8")):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-VIS01-LINTS-AND-SCOPE",
                        category="other",
                        message=f"{exp['golden_id']}: {hit}",
                    )
                )
        css_path = pub_dir / "page.css"
        if css_path.exists():
            css_text = css_path.read_text(encoding="utf-8")
            for hit in lint_css("page.css", css_text):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-VIS01-LINTS-AND-SCOPE",
                        category="other",
                        message=f"{exp['golden_id']}: {hit}",
                    )
                )
            # Kit scope check applies to pipeline_version >= 7 (doctrine v1.6)
            if exp["pipeline_version_min"] >= 7:
                for hit in lint_page_css_scope("page.css", css_text):
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id="DET-VIS01-LINTS-AND-SCOPE",
                            category="frame",
                            message=f"{exp['golden_id']}: {hit}",
                        )
                    )
    return issues


_LITERAL_MOVETO_CHAIN_RE = re.compile(
    r"(?:moveTo|lineTo)\(\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*\)\s*;\s*"
    r"(?:lineTo\(\s*\d+(?:\.\d+)?\s*,\s*\d+(?:\.\d+)?\s*\)\s*;\s*){3,}"
)


def check_computed_sim_loop(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-VIS01-COMPUTED-SIM-LOOPS`: Verify each `ZivonSim.register` in `page.js`
    computes geometry using `for`/`while` loops and has `0` sequences of >= 4
    hardcoded literal `moveTo`/`lineTo` coordinate pairs.
    """
    issues: list[IssueRecord] = []
    for topic_rel in card.golden_inputs.get("topics", []):
        exp, pub_dir = _resolve_topic_dir(cfg, topic_rel)
        if pub_dir is None or not (pub_dir / "page.js").exists():
            continue
        js_text = (pub_dir / "page.js").read_text(encoding="utf-8")
        regs = re.findall(r'ZivonSim\.register\(\s*["\']([^"\']+)["\']', js_text)
        if not regs:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-VIS01-COMPUTED-SIM-LOOPS",
                    category="drawn_behaviour",
                    message=f"{exp['golden_id']}: page.js has no ZivonSim.register calls",
                )
            )
            continue
        if not re.search(r"\b(?:for|while)\s*\(", js_text):
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-VIS01-COMPUTED-SIM-LOOPS",
                    category="drawn_behaviour",
                    message=f"{exp['golden_id']}: page.js contains no domain loop (for/while)",
                )
            )
        if _LITERAL_MOVETO_CHAIN_RE.search(js_text):
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-VIS01-COMPUTED-SIM-LOOPS",
                    category="drawn_behaviour",
                    message=f"{exp['golden_id']}: page.js contains >= 4 consecutive literal moveTo/lineTo pairs",
                )
            )
    return issues


def check_dom_and_a11y_invariants(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-VIS01-DOM-AND-A11Y`: Static DOM/a11y probe over the rendered HTML.

    Verifies kit chrome (`.zn-lang-bar`), `<svg>` `viewBox` without fixed
    width/height, and the `.zn-check` `<legend>` float rule in `zivon.css`.
    This is a regex/CSS probe, not a headless-Chromium run; the Chromium CDP
    instrumentation lives in `perf_harness.py` (`EV-PERF-001`).
    """
    issues: list[IssueRecord] = []

    # 1. Verify kit CSS has the float-legend fix for .zn-check legend
    zivon_css = cfg.frontend_dir / "assets" / "zivon.css"
    if not zivon_css.exists():
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-VIS01-DOM-AND-A11Y",
                category="frame",
                message="frontend/assets/zivon.css missing",
            )
        )
        return issues
    css_text = zivon_css.read_text(encoding="utf-8")
    if "float: left" not in css_text or "width: 100%" not in css_text:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-VIS01-DOM-AND-A11Y",
                category="frame",
                message="zivon.css missing float-legend geometry rule (legend { float: left; width: 100% })",
            )
        )

    # 2. Check each golden topic's HTML & SVG & kit chrome invariants
    for topic_rel in card.golden_inputs.get("topics", []):
        exp, pub_dir = _resolve_topic_dir(cfg, topic_rel)
        if pub_dir is None or not pub_dir.exists():
            continue
        html_path = (
            pub_dir / "design-doctrine-lesson-example.html"
            if exp["golden_id"] == "GT-03"
            else pub_dir / "index.html"
        )
        if not html_path.exists():
            continue
        html_text = html_path.read_text(encoding="utf-8")
        inv = exp["visual_and_kit_invariants"]

        if inv.get("requires_lang_bar") and "zn-lang-bar" not in html_text:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-VIS01-DOM-AND-A11Y",
                    category="accessibility",
                    message=f"{exp['golden_id']}: missing .zn-lang-bar kit chrome",
                )
            )

        # Check all <svg> tags have viewBox and no fixed width/height attributes
        for svg_match in re.finditer(r"<svg\b[^>]*>", html_text, re.IGNORECASE):
            tag = svg_match.group(0)
            if "viewbox=" not in tag.lower():
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-VIS01-DOM-AND-A11Y",
                        category="frame",
                        message=f"{exp['golden_id']}: <svg> tag missing viewBox attribute",
                    )
                )
            if re.search(r'\s(?:width|height)\s*=\s*["\']\d+', tag, re.IGNORECASE):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-VIS01-DOM-AND-A11Y",
                        category="frame",
                        message=f"{exp['golden_id']}: <svg> has fixed width/height attribute: {tag}",
                    )
                )

    return issues


def check_security_defect_corpus(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-REV02-SECURITY-DEFECTS`: Run deterministic lint and static review gates
    against `SD-SEC-001..005` (`0` model calls) and require `5/5` (`100%`) catch rate.
    """
    issues: list[IssueRecord] = []
    sec_dir = cfg.goldens_dir / "defects" / "09-review"
    caught = 0
    total = 0

    for i in range(1, 6):
        sample_id = f"SD-SEC-{i:03d}"
        spath = sec_dir / f"{sample_id}.json"
        if not spath.exists():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-REV02-SECURITY-DEFECTS",
                    category="other",
                    message=f"missing security defect sample {sample_id}",
                )
            )
            continue
        total += 1
        sample = json.loads(spath.read_text(encoding="utf-8"))
        files = sample["inputs"].get("files", {})
        blocks = sample["inputs"].get("blocks", {}).get("blocks", [])

        hits: list[str] = []
        hits.extend(lint_js("page.js", files.get("page.js", "")))
        hits.extend(lint_css("page.css", files.get("page.css", "")))
        hits.extend(lint_page_css_scope("page.css", files.get("page.css", "")))
        hits.extend(lint_html("index.html", files.get("index.html", "")))
        for svg_issue in rule_diagram_svg(blocks):
            hits.append(svg_issue["message"])

        with tempfile.TemporaryDirectory(prefix="zivon-sec-") as td:
            tpath = Path(td)
            (tpath / "index.html").write_text(
                files.get("index.html", ""), encoding="utf-8"
            )
            if "manifest.json" in files:
                (tpath / "manifest.json").write_text(
                    json.dumps(files["manifest.json"]), encoding="utf-8"
                )
            hits.extend(_static_review_findings(tpath))

        if hits:
            caught += 1
        else:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-REV02-SECURITY-DEFECTS",
                    category="other",
                    message=f"deterministic security/scope grader failed to catch {sample_id} ({sample['defect_class']})",
                )
            )

    metrics = context.setdefault("metrics", {})
    metrics["security_defects_total"] = total
    metrics["security_defects_caught"] = caught
    metrics["security_catch_rate"] = round(caught / total, 4) if total else 0.0
    return issues
