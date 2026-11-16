"""Accessibility gate for rendered lesson pages (`EV-VIS-002`).

Two layers, both key-free:

1. `check_static_a11y` - a dependency-free WCAG-subset audit over the page
   HTML (accessible names, landmarks, live regions, keyboard reachability,
   duplicate ids, positive tabindex, aria-hidden focusables). It is the CI
   gate: zero network, zero browser, zero model calls.
2. `check_axe_serious_critical` - the real axe-core engine, run through
   headless Chromium when an `axe.min.js` is resolvable locally
   (`ZIVON_AXE_JS` env var, or `node -e require.resolve('axe-core')`). When
   axe is not installed the check is honestly SKIPPED (recorded in
   `skipped_checks`) instead of pretending the page is clean. No npm install
   is required for CI: the static engine is the always-on gate.

Impact mapping matches axe's: `critical`/`serious` findings block the card,
`moderate`/`minor` are advisory. Every rule names the WCAG criterion it
approximates so a reviewer can dispute the rule, not the verdict.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord

CHECK_ID = "DET-VIS02-A11Y-STATIC"
AXE_CHECK_ID = "DET-VIS02-A11Y-AXE"

_VOID_TAGS = {
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
_FOCUSABLE = {"a", "button", "input", "select", "textarea", "summary"}
_INPUT_EXEMPT = {"hidden", "submit", "reset", "button", "image"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    line: int
    parent: Node | None = None
    children: list[Node] = field(default_factory=list)
    text: list[str] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def attr(self, name: str) -> str:
        return (self.attrs.get(name) or "").strip()

    def descendants(self) -> list[Node]:
        out: list[Node] = []
        for child in self.children:
            out.append(child)
            out.extend(child.descendants())
        return out

    def text_content(self) -> str:
        parts = list(self.text)
        for child in self.children:
            parts.append(child.text_content())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    def ancestors(self) -> list[Node]:
        node = self.parent
        out: list[Node] = []
        while node is not None:
            out.append(node)
            node = node.parent
        return out


class _Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[Node] = []
        self.stack: list[Node] = []
        self.by_id: dict[str, Node] = {}
        self.all_nodes: list[Node] = []

    def _add(self, tag: str, attrs: list[tuple[str, str | None]], line: int) -> Node:
        node = Node(
            tag=tag,
            attrs={k: (v or "") for k, v in attrs},
            line=line,
            parent=self.stack[-1] if self.stack else None,
        )
        if node.parent is not None:
            node.parent.children.append(node)
        else:
            self.roots.append(node)
        self.all_nodes.append(node)
        node_id = node.attr("id")
        if node_id and node_id not in self.by_id:
            self.by_id[node_id] = node
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._add(tag, attrs, self.getpos()[0])
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs, self.getpos()[0])

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack and data.strip():
            self.stack[-1].text.append(data)


@dataclass(frozen=True)
class Finding:
    rule: str
    impact: str  # critical | serious | moderate | minor
    message: str
    line: int


def parse_html(html: str) -> _Document:
    doc = _Document()
    doc.feed(html)
    doc.close()
    return doc


def _by_id_text(doc: _Document, node_id: str) -> str:
    node = doc.by_id.get(node_id)
    return node.text_content() if node is not None else ""


def _accessible_name(node: Node, doc: _Document) -> str:
    labelledby = node.attr("aria-labelledby")
    if labelledby:
        text = " ".join(_by_id_text(doc, i) for i in labelledby.split()).strip()
        if text:
            return text
    if node.attr("aria-label"):
        return node.attr("aria-label")
    if node.tag == "img":
        return node.attr("alt")
    if node.tag in ("svg", "canvas"):
        title = next(
            (c for c in node.children if c.tag == "title" and c.text_content()),
            None,
        )
        if title is not None:
            return title.text_content()
    if node.attr("title"):
        return node.attr("title")
    text = node.text_content()
    if text:
        return text
    if node.tag == "svg":
        return ""
    if node.tag == "canvas":
        # A canvas inside a labelled .zn-sim region is named by that region
        # (its aria-label or its visible heading); an unrelated ancestor
        # heading does not name it.
        for ancestor in node.ancestors():
            if "zn-sim" not in ancestor.classes():
                continue
            if ancestor.attr("aria-label"):
                return ancestor.attr("aria-label")
            heading = next(
                (c for c in ancestor.children if c.tag in ("h1", "h2", "h3", "h4")),
                None,
            )
            if heading is not None and heading.text_content():
                return heading.text_content()
        for sibling in node.parent.children if node.parent else []:
            if "zn-sim-desc" in sibling.classes() and sibling.text_content():
                return sibling.text_content()
    return ""


def _labelled_control(node: Node, doc: _Document) -> bool:
    if node.attr("aria-label") or node.attr("aria-labelledby") or node.attr("title"):
        return True
    node_id = node.attr("id")
    if node_id and any(
        n.tag == "label" and node_id in (n.attr("for") or "").split()
        for n in doc.all_nodes
    ):
        return True
    return any(a.tag == "label" for a in node.ancestors())


def _is_focusable(node: Node) -> bool:
    if node.tag in _FOCUSABLE:
        # Only a hidden input is non-focusable; submit/reset/button inputs are
        # focusable even though they need no explicit label.
        if node.tag == "input" and node.attr("type").lower() == "hidden":
            return False
        return not node.attrs.get("disabled")
    tabindex = node.attr("tabindex")
    if tabindex:
        try:
            return int(tabindex) >= 0
        except ValueError:
            return False
    if node.attrs.get("contenteditable", "").lower() in ("", "false"):
        return False
    return node.attrs.get("contenteditable") is not None


def audit_html(html: str) -> list[Finding]:
    """Run the WCAG-subset rules over one document."""
    doc = parse_html(html)
    findings: list[Finding] = []

    def add(rule: str, impact: str, message: str, node: Node | None) -> None:
        findings.append(
            Finding(rule, impact, message, node.line if node is not None else 0)
        )

    html_node = next((n for n in doc.all_nodes if n.tag == "html"), None)
    if html_node is None or not html_node.attr("lang"):
        add("html-has-lang", "serious", "<html> has no lang attribute", html_node)
    title = next((n for n in doc.all_nodes if n.tag == "title"), None)
    if title is None or not title.text_content():
        add("document-title", "serious", "document has no non-empty <title>", title)

    if not any(n.tag == "main" or n.attr("role") == "main" for n in doc.all_nodes):
        add("landmark-one-main", "moderate", "no <main> landmark", None)
    h1s = [n for n in doc.all_nodes if n.tag == "h1"]
    if not h1s:
        add("page-has-heading-one", "moderate", "no <h1> heading", None)
    elif len(h1s) > 1:
        add(
            "page-has-heading-one",
            "minor",
            f"{len(h1s)} <h1> headings (expected exactly one)",
            h1s[1],
        )

    # Duplicate ids: HTML must be unique-by-id for label/ARIA references.
    seen_ids: dict[str, Node] = {}
    for node in doc.all_nodes:
        node_id = node.attr("id")
        if not node_id:
            continue
        if node_id in seen_ids:
            add("duplicate-id", "serious", f"duplicate id={node_id!r}", node)
        else:
            seen_ids[node_id] = node

    headings = [n for n in doc.all_nodes if re.fullmatch(r"h[1-6]", n.tag)]
    previous_level = 0
    for heading in headings:
        level = int(heading.tag[1])
        if not heading.text_content():
            add("empty-heading", "minor", f"empty <{heading.tag}>", heading)
        if previous_level and level > previous_level + 1:
            add(
                "heading-order",
                "minor",
                f"<{heading.tag}> follows <h{previous_level}> (skipped level)",
                heading,
            )
        previous_level = level

    for node in doc.all_nodes:
        tabindex = node.attr("tabindex")
        if tabindex:
            try:
                if int(tabindex) > 0:
                    add(
                        "tabindex-positive",
                        "serious",
                        f"positive tabindex={tabindex} breaks natural focus order",
                        node,
                    )
            except ValueError:
                pass

        if node.attr("aria-hidden").lower() == "true":
            for child in node.descendants():
                if _is_focusable(child):
                    add(
                        "aria-hidden-focusable",
                        "serious",
                        f"aria-hidden container holds focusable <{child.tag}>",
                        child,
                    )
                    break

        if node.tag == "img" and "alt" not in node.attrs:
            add("image-alt", "critical", "<img> has no alt attribute", node)

        if (
            node.tag == "svg"
            and node.attr("aria-hidden").lower() != "true"
            and not _accessible_name(node, doc)
        ):
            add(
                "svg-img-alt",
                "serious",
                "<svg> has no accessible name (aria-label/labelledby/<title>) "
                "and is not aria-hidden",
                node,
            )

        if node.tag == "canvas" and not _accessible_name(node, doc):
            add("canvas-name", "serious", "<canvas> has no accessible name", node)

        if node.tag == "button" and not _accessible_name(node, doc):
            add("button-name", "critical", "<button> has no accessible name", node)

        if node.tag == "a" and node.attr("href") and not _accessible_name(node, doc):
            add("link-name", "serious", "<a href> has no accessible name", node)

        if node.tag in ("input", "select", "textarea"):
            # Hidden/submit/reset/button inputs have no user-visible label to
            # provide (implicit names or no UI); do not turn them into a fatal
            # false positive.
            exempt = node.tag == "input" and node.attr("type").lower() in _INPUT_EXEMPT
            if not exempt and not _labelled_control(node, doc):
                kind = node.attr("type").lower() or node.tag
                add(
                    "label",
                    "critical",
                    f"<{node.tag} type={kind!r}> has no label/aria-label",
                    node,
                )

        if (
            node.tag == "fieldset"
            and "zn-check" in node.classes()
            and not any(c.tag == "legend" for c in node.children)
        ):
            add(
                "fieldset-legend",
                "serious",
                "quiz <fieldset.zn-check> has no <legend>",
                node,
            )

        if "zn-check-feedback" in node.classes() and (
            node.attr("aria-live") not in ("polite", "assertive")
            and node.attr("role") != "status"
        ):
            add(
                "aria-live-feedback",
                "serious",
                "check feedback region has no aria-live/role=status",
                node,
            )

        if "zn-sim-read" in node.classes() and (
            node.attr("aria-live") not in ("polite", "assertive")
            and node.attr("role") != "status"
        ):
            add(
                "aria-live-sim-readout",
                "serious",
                "simulation readout has no aria-live/role=status",
                node,
            )

        if "zn-sim" in node.classes():
            canvas = next((c for c in node.descendants() if c.tag == "canvas"), None)
            if canvas is not None and not any(
                _is_focusable(c) for c in node.descendants()
            ):
                add(
                    "sim-keyboard",
                    "serious",
                    f"simulation {node.attr('id') or '?'} has a canvas but no "
                    "keyboard-focusable control",
                    node,
                )

    return findings


_IMPACT_SEVERITY = {
    "critical": "fatal",
    "serious": "major",
    "moderate": "minor",
    "minor": "minor",
}


def _golden_pages(cfg: EvalConfig, card: EvalCard) -> list[tuple[str, Path, bool]]:
    """`(label, path, blocking)` for every golden page.

    `blocking=False` marks the hand-maintained doctrine example (GT-03): it is
    a reference artifact, not pipeline output, so its findings are reported as
    non-blocking debt for the doctrine owner instead of failing a generation.
    """
    pages: list[tuple[str, Path, bool]] = []
    for topic_rel in card.golden_inputs.get("topics", []):
        tdir = cfg.repo_root / topic_rel
        ref_path = tdir / "artifact_ref.json"
        if not ref_path.is_file():
            continue
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        if ref.get("reference_html"):
            page = cfg.repo_root / ref["reference_html"]
            if page.is_file():
                pages.append((str(ref.get("golden_id") or topic_rel), page, False))
            continue
        published = ref.get("published_dir")
        if not published:
            continue
        page = cfg.repo_root / published / "index.html"
        if page.is_file():
            pages.append((str(ref.get("golden_id") or topic_rel), page, True))
        topic_dir = cfg.repo_root / published
        for locale_dir in sorted(p for p in topic_dir.iterdir() if p.is_dir()):
            localized = locale_dir / "index.html"
            if locale_dir.name in ("i18n", "audio") or not localized.is_file():
                continue
            pages.append((f"{ref.get('golden_id')}:{locale_dir.name}", localized, True))
    return pages


def check_static_a11y(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-VIS02-A11Y-STATIC`: WCAG-subset audit over the rendered golden pages."""
    issues: list[IssueRecord] = []
    pages = _golden_pages(cfg, card)
    metrics = context.setdefault("metrics", {})
    totals = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    audited = 0
    for label, page, blocking in pages:
        audited += 1
        findings = audit_html(page.read_text(encoding="utf-8", errors="replace"))
        for finding in findings:
            totals[finding.impact] = totals.get(finding.impact, 0) + 1
            severity = _IMPACT_SEVERITY[finding.impact]
            if not blocking and severity in ("fatal", "major"):
                # Reference artifact: report, never block a generation run.
                severity = "minor"
            note = "" if blocking else " (reference page - doctrine owner)"
            issues.append(
                IssueRecord(
                    severity=severity,
                    check_id=CHECK_ID,
                    category="accessibility",
                    message=(
                        f"{label} line {finding.line}: [{finding.rule}] "
                        f"{finding.message}{note}"
                    ),
                )
            )
    metrics["a11y_pages_audited"] = audited
    metrics["a11y_critical"] = totals["critical"]
    metrics["a11y_serious"] = totals["serious"]
    metrics["a11y_moderate"] = totals["moderate"]
    metrics["a11y_minor"] = totals["minor"]
    if not pages:
        context.setdefault("skipped_checks", {})[CHECK_ID] = (
            "no rendered golden page found to audit"
        )
    return issues


def _resolve_axe_js() -> Path | None:
    env_path = os.environ.get("ZIVON_AXE_JS", "").strip()
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run(
            [
                node,
                "-e",
                "process.stdout.write(require.resolve('axe-core/axe.min.js'))",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    path = out.stdout.strip()
    if out.returncode == 0 and path and Path(path).is_file():
        return Path(path)
    return None


def check_axe_serious_critical(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-VIS02-A11Y-AXE`: real axe-core run, serious/critical only.

    Skipped (never reported as passing) when axe-core or headless Chromium is
    not installed: the static engine above remains the always-on gate.
    """
    issues: list[IssueRecord] = []
    pages = _golden_pages(cfg, card)
    axe_js = _resolve_axe_js()
    if not pages or axe_js is None:
        context.setdefault("skipped_checks", {})[AXE_CHECK_ID] = (
            "axe-core not installed (set ZIVON_AXE_JS or `npm i axe-core`); "
            "the static a11y engine is the active gate"
        )
        return issues
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        context.setdefault("skipped_checks", {})[AXE_CHECK_ID] = (
            "playwright not installed; axe run not available"
        )
        return issues

    metrics = context.setdefault("metrics", {})
    violations = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                for label, page_path, _blocking in pages:
                    page.goto(page_path.resolve().as_uri(), wait_until="load")
                    page.add_script_tag(path=str(axe_js))
                    result = page.evaluate(
                        """async () => {
                          const res = await axe.run(document, {
                            runOnly: {type: 'tag',
                              values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}
                          });
                          return res.violations.map(v => ({
                            id: v.id, impact: v.impact, help: v.help,
                            nodes: v.nodes.length
                          }));
                        }"""
                    )
                    for violation in result:
                        if violation.get("impact") not in ("critical", "serious"):
                            continue
                        violations += 1
                        issues.append(
                            IssueRecord(
                                severity="major"
                                if violation["impact"] == "serious"
                                else "fatal",
                                check_id=AXE_CHECK_ID,
                                category="accessibility",
                                message=(
                                    f"{label}: axe {violation['id']} "
                                    f"({violation['impact']}) - {violation['help']} "
                                    f"on {violation['nodes']} node(s)"
                                ),
                            )
                        )
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - browser/tooling failure is a skip, not a page verdict
        context.setdefault("skipped_checks", {})[AXE_CHECK_ID] = (
            f"axe-core run could not start: {type(exc).__name__}"
        )
        return []
    metrics["axe_serious_critical"] = violations
    return issues
