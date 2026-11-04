"""Hard lints for generated code. Any hit is a LintError - never a warning.

The repo rule is "no eval, no external calls". These rules make it mechanical:
- JS: eval, new Function, document.write, dynamic import/require, any network
  API, string-literal URLs, inline <script> injection.
- HTML: any <script> tag (all JS lives in page.js / zivon.js, loaded from
  'self'), any http(s) URL in src/href except SVG/xml namespaces.
- CSS: @import and url(http...) - external fetches.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

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


def lint_css(filename: str, code: str) -> list[str]:
    hits = []
    for m in re.finditer(r"@import\b", code):
        line = code[: m.start()].count("\n") + 1
        hits.append(f"{filename}:{line}: @import is forbidden (external fetch)")
    for m in re.finditer(r"url\(\s*[\"']?https?://", code, re.IGNORECASE):
        line = code[: m.start()].count("\n") + 1
        hits.append(f"{filename}:{line}: url(http...) is forbidden (external fetch)")
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
        + lint_html("index.html", html)
    )
