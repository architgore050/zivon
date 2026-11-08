"""Hard lints for generated code. Any hit is a LintError - never a warning.

The repo rule is "no eval, no external calls". These rules make it mechanical:
- JS: eval, new Function, document.write, dynamic import/require, any network
  API, string-literal URLs, inline <script> injection.
- HTML: any <script> tag (all JS lives in page.js / zivon.js, loaded from
  'self'), any http(s) URL in src/href except SVG/xml namespaces.
- CSS: @import and url(http...) - external fetches; plus the kit contract
  (doctrine v1.6) via lint_page_css_scope - page.css may style ONLY inside
  the .zn-sim-<id> scope and may never size the canvas (zivon.css owns
  that), enforced at authoring sites only (05-interactive, 06-render,
  08-fixloop, 10-reviewfix), never on files being read back.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

_JS_PATTERNS: list[tuple[str, str]] = [
    (r"\beval\s*\(", "eval() is forbidden"),
    (r"\bnew\s+Function\b", "new Function() is forbidden"),
    (r"\bdocument\.write\b", "document.write is forbidden"),
    (r"\bfetch\s*\(", "fetch() is forbidden (pages make no network calls)"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest is forbidden"),
    (r"\bWebSocket\b", "WebSocket is forbidden"),
    (r"\bEventSource\b", "EventSource is forbidden"),
    (r"\bnavigator\.sendBeacon\b", "sendBeacon is forbidden"),
    (r"\bimport\s*\(", "dynamic import() is forbidden"),
    (r"\brequire\s*\(", "require() is forbidden"),
    (r"\bimportScripts\b", "importScripts is forbidden"),
    (r"[\"']https?://", "string-literal http(s) URL in JS is forbidden"),
    (r"<\s*script", "inline <script> creation is forbidden"),
]

_HTML_ALLOWED_URL_RE = re.compile(
    r"""(?ix)
    (?:^|\s)(?:src|href)\s*=\s*["'](https?://[^"']*)["']
    """
)
_HTML_NS_ALLOWLIST = (
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xhtml",
    "http://www.w3.org/2000/xmlns/",
    "http://www.w3.org/1999/xlink",
)


def lint_js(filename: str, code: str) -> list[str]:
    hits = []
    for pattern, why in _JS_PATTERNS:
        for m in re.finditer(pattern, code):
            line = code[: m.start()].count("\n") + 1
            hits.append(f"{filename}:{line}: {why} (matched {m.group(0)!r})")
    return hits


class _CssRule(NamedTuple):
    selector: str
    body: str
    line: int


def _css_rules(code: str) -> list[_CssRule]:
    """Yield every style rule (selector, body, line) at any nesting depth.

    The scan walks brace pairs: a segment start after the last `{`/`}`; a
    prelude that starts with `@` is a container - we descend into it -
    and a style rule's body is taken flat (a style rule's body is flat
    CSS by syntax), then the scan advances PAST the rule's closing brace.
    (Getting `boundary` wrong glues the previous rule's declarations into
    the next selector - caught by the scope tests.)
    """
    out: list[_CssRule] = []
    i = 0
    n = len(code)
    keyframe_depth = 0  # >0 while inside an @keyframes block (its steps are
    # not selectors - `from`/`to`/`50%` must never be checked for scoping)
    while i < n:
        o = code.find("{", i)
        if o == -1:
            break
        prelude = code[i:o].strip()
        depth, k = 1, o + 1
        while k < n and depth:
            if code[k] == "{":
                depth += 1
            elif code[k] == "}":
                depth -= 1
            k += 1
        if prelude and not prelude.startswith("@") and keyframe_depth == 0:
            out.append(
                _CssRule(prelude, code[o + 1 : k - 1], code.count("\n", 0, o) + 1)
            )
        if "keyframes" in prelude:
            keyframe_depth += 1
        elif keyframe_depth and prelude == "":
            keyframe_depth -= 1
        i = o + 1 if prelude.startswith("@") else k
    return out


def lint_css(filename: str, code: str) -> list[str]:
    hits = []
    for m in re.finditer(r"@import\b", code):
        line = code[: m.start()].count("\n") + 1
        hits.append(f"{filename}:{line}: @import is forbidden (external fetch)")
    for m in re.finditer(r"url\(\s*[\"']?https?://", code, re.IGNORECASE):
        line = code[: m.start()].count("\n") + 1
        hits.append(f"{filename}:{line}: url(http...) is forbidden (external fetch)")
    return hits


def lint_page_css_scope(
    filename: str, code: str, block_id: str | None = None
) -> list[str]:
    """Kit contract (doctrine v1.6): model-authored page.css may style ONLY
    inside the simulation's `.zn-sim-<id>` scope; cards, tape, quiz chrome,
    the language bar and canvas sizing are kit-owned (zivon.css). Every
    selector of a generated page.css either references a `.zn-sim-` scope
    class or is rejected; a canvas sizing declaration inside scope is also
    rejected (the kit sizes the canvas - see `.zn-sim .zn-sim-canvas`).
    When `block_id` is known (05-interactive builds one sim per call) the
    scope class must match it; when None (concatenated topic CSS) any
    `.zn-sim-*` scope is accepted.

    ENFORCEMENT SITES (deliberate): authoring/rewriting sites only -
    05-interactive's retry loop + backstop, 06-render, 08-fixloop and
    10-reviewfix via lint_generated. Files READ by 09-review's mechanical
    pass are NOT scope-checked (`lint_file` keeps the original rules):
    grandfathered page.css from before the kit contract must not hard-fail a
    resumed run - the contract applies to new authorship, not re-judgment.
    """
    hits: list[str] = []
    stripped = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    for rule in _css_rules(stripped):
        for sel in rule.selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            classes = re.findall(r"\.([A-Za-z][\w-]*)", sel)
            scoped = [c for c in classes if c.startswith("zn-sim")]
            if block_id is not None:
                ok = f"zn-sim-{block_id}" in scoped
            else:
                ok = bool(scoped)
            if not ok:
                want = f".zn-sim-{block_id}" if block_id is not None else ".zn-sim-<id>"
                hits.append(
                    f"{filename}:{rule.line}: page.css selector '{sel}' is not "
                    f"scoped under {want} (the kit owns cards, tape, quiz "
                    "chrome, the language bar and canvas sizing - zivon.css)"
                )
            if re.search(r"(?<![\w-])canvas(?![\w-])", sel) and re.search(
                r"(?<![\w-])(width|height|min-height|max-height|aspect-ratio)\s*:",
                rule.body,
            ):
                hits.append(
                    f"{filename}:{rule.line}: page.css must not size the "
                    "canvas (the kit sizes it: .zn-sim .zn-sim-canvas)"
                )
    return hits


class _InlineScriptBodyParser(HTMLParser):
    """Parser-based inline-script-body detection. A regex over raw HTML can be
    evaded by markup a browser parses differently (CodeQL py/bad-tag-filter);
    the parser sees the document the way a browser does. Catches any <script>
    element carrying non-whitespace text, including unclosed ones a regex miss."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_script = False
        self.body_lines: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._in_script = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # HTML does not self-close <script/>: browsers treat it as an open tag.
        if tag == "script":
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            self.body_lines.append(self.getpos()[0])


def lint_html(filename: str, code: str) -> list[str]:
    hits = []
    # <script> tags: allowed ONLY with a self-relative src and no inline body.
    for m in re.finditer(r"<\s*script\b[^>]*>", code, re.IGNORECASE):
        tag = m.group(0)
        line = code[: m.start()].count("\n") + 1
        src = re.search(r"""src\s*=\s*["']([^"']+)["']""", tag, re.IGNORECASE)
        if src:
            value = src.group(1)
            if value.startswith(("http://", "https://", "//")):
                hits.append(f"{filename}:{line}: external <script src>: {value}")
        else:
            hits.append(
                f"{filename}:{line}: <script> without src (inline JS is forbidden; JS lives in .js files)"
            )
    parser = _InlineScriptBodyParser()
    parser.feed(code)
    parser.close()
    for line in parser.body_lines:
        hits.append(
            f"{filename}:{line}: inline script body is forbidden (JS lives in .js files)"
        )
    for m in _HTML_ALLOWED_URL_RE.finditer(code):
        url = m.group(1)
        if url not in _HTML_NS_ALLOWLIST:
            line = code[: m.start()].count("\n") + 1
            hits.append(f"{filename}:{line}: external URL in attribute: {url}")
    # bare url() forms (svg xmlns via attr uses xmlns=..., covered above for src/href only)
    for m in re.finditer(r"""(?:src|href)\s*=\s*["'](https?:)?//[^"']+["']""", code):
        line = code[: m.start()].count("\n") + 1
        hits.append(f"{filename}:{line}: protocol-relative external URL")
    return hits


def lint_file(path: Path) -> list[str]:
    name = path.name
    code = path.read_text(encoding="utf-8")
    if name.endswith(".js"):
        return lint_js(name, code)
    if name.endswith(".css"):
        return lint_css(name, code)
    if name.endswith(".html"):
        return lint_html(name, code)
    return []


def lint_generated(pages_js: str, pages_css: str, html: str) -> list[str]:
    """Lint the three generated artifact strings for one topic page."""
    return (
        lint_js("page.js", pages_js)
        + lint_css("page.css", pages_css)
        # Kit contract (doctrine v1.6): concatenated topic CSS must still
        # be .zn-sim-scoped (05-interactive already checked per block, THIS
        # is the write-path guarantee for 06-render/08/10). Files READ
        # back by 09-review are NOT scope-checked (grandfathered CSS must
        # not hard-fail a resumed run).
        + lint_page_css_scope("page.css", pages_css)
        + lint_html("index.html", html)
    )
