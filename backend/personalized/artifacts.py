"""Interactive artifacts (C24): validation, content-addressed cache, hard lint.

PL3 of W5.5 (`docs/specs/personalized-learning/interactive-artifacts.md`,
`data-and-api.md` §2.4/§4.8). An artifact is **untrusted generated code**: every
control here assumes the model eventually produces something unsafe, so the
guarantees live in code, never in prompt prose:

- **Spec validation** (§2): allow-listed fields only — the decide payload can
  carry no student free text by construction; `why` (the misconception label)
  is validated separately and **excluded from the content hash** so two
  students with the same visual need share one build.
- **Content addressing** (§7): `artifact_id` = first 32 hex of
  `sha256(canonical_json(spec minus why) + prompt_version + doctrine_hash +
  schema_version + lint_version)`; a doctrine/prompt/lint change invalidates
  the cache (new id, new URL).
- **Hard lint** (§3 step 3): reuses `factory/lint.py` rules plus the
  artifact-specific ones (forms, storage, parent access, top-nav,
  self-navigation, meta refresh, base, iframes, clipboards, postMessage) as a
  thin wrapper — any hit is a failure, never a warning.
- **Status machine** (§2.4): `pending → ready | failed`; `failure_reason` is
  the closed CHECK enum; failed/pending artifacts answer `409 E-CONFLICT` at
  the fetch route.
- **Shared cache + refcount** (§7): artifacts contain no student data, so
  identical specs reuse one row across students; serving is authorized by a
  message reference in one of the caller's sessions (never an open content
  proxy); `last_used_at` is the nightly refcount purge input
  (`backend/personalized/retention.py`).

No student text rule (§9, T-PL-17): `ensure_no_student_text` rejects a spec
whose strings quote the session's weakness/personal instructions, and the
builder prompt is assembled without them — the canary test
(`DET-PL03-NO-STUDENT`) proves the whole path.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any

from ..errors import APIError
from ..logging_shim import log_event

if TYPE_CHECKING:
    from db.engine import DatabaseEngine

ARTIFACT_KINDS: tuple[str, ...] = ("simulation", "diagram")

# Version pins stored per row (§7): any bump changes every future artifact id.
PROMPT_VERSION: str = "pl-art-1"
SCHEMA_VERSION: int = 1
# Keep in lockstep with the `personalized_artifact.lint_version` column default
# (db/schema_personalized.py): bump both when the artifact lint rules change.
LINT_VERSION: str = "pl-artifact-1"

MAX_TITLE_CHARS = 120
MAX_LEARNING_GOAL_CHARS = 200
MAX_WHY_CHARS = 160
MAX_CONTROL_LABEL_CHARS = 80
MAX_CONTROLS = 3
# D-PL-03 caps (interactive-artifacts.md §4 "Size"): ≤ 120 KB of HTML,
# ≤ 1,500 DOM nodes, ≤ 3 controls.
MAX_HTML_BYTES = 120 * 1024
MAX_DOM_NODES = 1500

CONTROL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
FAILURE_REASONS: tuple[str, ...] = (
    "lint",
    "render",
    "timeout",
    "budget",
    "route",
    "spec",
)

# §5.2 response CSP (header) and the in-document meta policy (§4): the meta
# carries the same fetch restrictions minus `sandbox` and `frame-ancestors`
# (browsers ignore `frame-ancestors` in a meta policy — web/render.py note).
ARTIFACT_HEADER_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "connect-src 'none'; frame-src 'none'; child-src 'none'; worker-src 'none'; "
    "media-src 'none'; form-action 'none'; base-uri 'none'"
)
ARTIFACT_META_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; connect-src 'none'; frame-src 'none'; "
    "child-src 'none'; worker-src 'none'; media-src 'none'; form-action 'none'; "
    "base-uri 'none'"
)

# Spec allow-list: the decide payload may carry NOTHING else — an extra field
# is a rejection, so student text cannot ride into a shared artifact by
# smuggling a field past the builder prompt (T-PL-17).
_SPEC_FIELDS: frozenset[str] = frozenset(
    {"kind", "title", "learning_goal", "controls", "cited_claim_ids", "why"}
)
_CONTROL_FIELDS: frozenset[str] = frozenset(
    {"id", "label", "min", "max", "step", "initial"}
)

_WS_RE = re.compile(r"\s+")


def _clean_text(value: object, limit: int) -> str:
    """Collapse whitespace and cap a model-supplied label."""
    collapsed = _WS_RE.sub(" ", str(value)).strip()
    return collapsed[:limit]


class ArtifactSpecError(APIError):
    """The artifact request failed spec validation (failure_reason='spec')."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        self.failure_reason = "spec"
        super().__init__(
            "E-VALIDATION", status_code=422, extra={"reason": "artifact_spec"}
        )


class ArtifactQuotaError(APIError):
    """The artifact budget refused the build (failure_reason='budget')."""

    def __init__(self, message_key: str) -> None:
        self.failure_reason = "budget"
        super().__init__("E-QUOTA-EXHAUSTED", status_code=403, message_key=message_key)


class ArtifactBuildError(Exception):
    """The build pipeline failed after (or without reaching) the model call.

    `failure_reason` is the closed enum stored in `personalized_artifact`:
    `lint` (a hard-lint hit survived the rebuilds), `render` (the headless
    gate failed), `timeout` (the call deadline), `route` (a transport error —
    the one reason a retry is allowed, D-PL-03).
    """

    def __init__(
        self,
        failure_reason: str,
        detail: str = "",
        lint_hits: int = 0,
        render_ms: int | None = None,
        model: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if failure_reason not in FAILURE_REASONS:
            raise ValueError(f"unknown artifact failure_reason {failure_reason!r}")
        self.failure_reason = failure_reason
        self.detail = detail
        self.lint_hits = lint_hits
        self.render_ms = render_ms
        self.model = model
        self.extra: dict[str, Any] = extra or {}
        super().__init__(f"artifact build failed ({failure_reason}): {detail[:200]}")


class _TagCounter(HTMLParser):
    """Static DOM-node count: one entry per start tag (self-closing included).

    The cap is a build-time approximation of §4's "≤ 1,500 DOM nodes"; the
    render gate measures the real DOM in the browser as the authoritative
    check."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs
        self.count += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs
        self.count += 1


def count_dom_nodes(html: str) -> int:
    counter = _TagCounter()
    counter.feed(html)
    counter.close()
    return counter.count


# --- spec validation (§2) -----------------------------------------------------


def validate_artifact_spec(
    raw: object,
    *,
    available_claim_ids: set[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Validate a decide-payload artifact request. Returns the clean spec and
    the `weak_grounding` flag.

    Rules (§2): `kind` ∈ {simulation, diagram}; `title` ≤ 120; `learning_goal`
    ≤ 200; controls ≤ 3 for a simulation, 0 for a diagram; `min < max`,
    `step > 0`, `initial` inside the range; ids `[a-z][a-z0-9_]{0,15}`;
    allow-listed fields only; unknown `cited_claim_ids` are dropped and zero
    remaining marks the artifact `weak_grounding` (the build proceeds).

    Raises `ArtifactSpecError` (→ failure_reason='spec') on any structural
    violation. `why` is validated but never enters the content hash.
    """
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise ArtifactSpecError(["spec must be a JSON object"])
    unknown = sorted(set(raw) - _SPEC_FIELDS)
    if unknown:
        problems.append(f"unexpected spec field(s): {', '.join(unknown)}")

    kind = raw.get("kind")
    if kind not in ARTIFACT_KINDS:
        problems.append(f"kind must be one of {'|'.join(ARTIFACT_KINDS)}")

    title = _clean_text(raw.get("title", ""), MAX_TITLE_CHARS)
    if not title:
        problems.append("title is required")
    elif len(_WS_RE.sub(" ", str(raw.get("title", ""))).strip()) > MAX_TITLE_CHARS:
        problems.append(f"title must be at most {MAX_TITLE_CHARS} characters")
    learning_goal = _clean_text(raw.get("learning_goal", ""), MAX_LEARNING_GOAL_CHARS)
    if not learning_goal:
        problems.append("learning_goal is required")
    elif (
        len(_WS_RE.sub(" ", str(raw.get("learning_goal", ""))).strip())
        > MAX_LEARNING_GOAL_CHARS
    ):
        problems.append(
            f"learning_goal must be at most {MAX_LEARNING_GOAL_CHARS} characters"
        )

    controls_raw = raw.get("controls", [])
    if controls_raw is None:
        controls_raw = []
    if not isinstance(controls_raw, list):
        problems.append("controls must be a list")
        controls_raw = []
    if kind == "diagram" and controls_raw:
        problems.append("a diagram carries no controls")
    if len(controls_raw) > MAX_CONTROLS:
        problems.append(f"at most {MAX_CONTROLS} controls are allowed")
    controls: list[dict[str, Any]] = []
    for ctrl in controls_raw[:MAX_CONTROLS]:
        if not isinstance(ctrl, dict):
            problems.append("each control must be an object")
            continue
        unknown_ctrl = sorted(set(ctrl) - _CONTROL_FIELDS)
        if unknown_ctrl:
            problems.append(f"unexpected control field(s): {', '.join(unknown_ctrl)}")
        cid = str(ctrl.get("id", ""))
        if not CONTROL_ID_RE.match(cid):
            problems.append(f"control id {cid!r} must match [a-z][a-z0-9_]{{0,15}}")
        label = _clean_text(ctrl.get("label", ""), MAX_CONTROL_LABEL_CHARS)
        if not label:
            problems.append(f"control {cid!r} needs a label")
        lo, hi, step, initial = (
            _as_number(ctrl.get("min")),
            _as_number(ctrl.get("max")),
            _as_number(ctrl.get("step")),
            _as_number(ctrl.get("initial")),
        )
        if lo is None or hi is None or step is None or initial is None:
            problems.append(f"control {cid!r} needs numeric min/max/step/initial")
            continue
        if not lo < hi:
            problems.append(f"control {cid!r}: min must be < max")
        if step <= 0:
            problems.append(f"control {cid!r}: step must be > 0")
        if not lo <= initial <= hi:
            problems.append(f"control {cid!r}: initial must be inside [min, max]")
        controls.append(
            {
                "id": cid,
                "label": label,
                "min": lo,
                "max": hi,
                "step": step,
                "initial": initial,
            }
        )

    cited_raw = raw.get("cited_claim_ids", [])
    if cited_raw is None:
        cited_raw = []
    if not isinstance(cited_raw, list):
        problems.append("cited_claim_ids must be a list")
        cited_raw = []
    cited = [str(c) for c in cited_raw if isinstance(c, (str, int))]
    weak_grounding = False
    if available_claim_ids is not None:
        cited = [c for c in cited if c in available_claim_ids]
        weak_grounding = not cited

    why_raw = raw.get("why")
    why = _clean_text(why_raw, MAX_WHY_CHARS) if why_raw else ""
    if why_raw and not why:
        problems.append("why must be a non-empty short label when present")
    elif why_raw and len(_WS_RE.sub(" ", str(why_raw)).strip()) > MAX_WHY_CHARS:
        problems.append(f"why must be at most {MAX_WHY_CHARS} characters")

    if problems:
        raise ArtifactSpecError(problems)

    clean: dict[str, Any] = {
        "kind": str(kind),
        "title": title,
        "learning_goal": learning_goal,
        "controls": controls,
        "cited_claim_ids": cited,
    }
    if why:
        clean["why"] = why
    return clean, weak_grounding


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def ensure_no_student_text(spec: dict[str, Any], forbidden_texts: list[str]) -> None:
    """Cross-student-leak guard (T-PL-17, DET-PL03-NO-STUDENT).

    The shared cache means a spec quoting one student's words would serve that
    quote to every student with the same visual need. Any forbidden text
    (normalized, ≥ 12 chars so single words like "image" cannot trip it) that
    appears in the spec's strings is a hard rejection.
    """
    spec_strings: list[str] = [
        str(spec.get("title", "")),
        str(spec.get("learning_goal", "")),
    ]
    spec_strings.extend(str(c.get("label", "")) for c in spec.get("controls", []))
    if spec.get("why"):
        spec_strings.append(str(spec["why"]))
    haystack = " \n ".join(spec_strings).lower()
    for forbidden in forbidden_texts:
        needle = _WS_RE.sub(" ", str(forbidden)).strip().lower()
        if len(needle) >= 12 and needle in haystack:
            raise ArtifactSpecError(
                ["spec must not contain session free text (no-student-text rule)"]
            )


def normalize_fallback(fallback: object) -> dict[str, Any]:
    """§8: the server-stored fallback, downgraded to `text` when unsafe.

    A diagram fallback is a model-supplied static SVG rendered in the session
    page (outside the artifact sandbox), so it carries the diagram-block SVG
    rules (blocks-schema.md): no script, no external URL, no event handlers —
    anything else downgrades to the honest text fallback.
    """
    if not isinstance(fallback, dict):
        return {"kind": "text"}
    kind = fallback.get("kind")
    svg = fallback.get("svg")
    if kind == "diagram" and isinstance(svg, str) and svg.strip():
        if _svg_is_safe(svg):
            return {"kind": "diagram", "svg": svg}
        log_event(
            "personalized.artifact.failed",
            {"stage": "fallback", "reason_code": "unsafe_fallback_svg"},
        )
    return {"kind": "text"}


def _svg_is_safe(svg: str) -> bool:
    low = svg.lower()
    if "<script" in low or "javascript:" in low or " foreignobject" in low:
        return False
    return not (
        re.search(r"\son[a-z]+\s*=", low)
        or re.search(r"""(?:src|href|xlink:href)\s*=\s*["']\s*(?:https?:)?//""", low)
    )


# --- content addressing (§7) ---------------------------------------------------


def doctrine_hash_of(doctrine_text: str) -> str:
    """SHA-256 of the design doctrine: any doctrine edit invalidates the cache."""
    return hashlib.sha256(doctrine_text.encode("utf-8")).hexdigest()


def compute_artifact_id(
    spec: dict[str, Any],
    *,
    prompt_version: str = PROMPT_VERSION,
    doctrine_hash: str = "",
    schema_version: int = SCHEMA_VERSION,
    lint_version: str = LINT_VERSION,
) -> tuple[str, str]:
    """The content-addressed identity (§7 key formula).

    `why` is excluded from the hash: two students with the same visual need
    share one build; the misconception label is not part of the document.
    Returns `(artifact_id, content_hash)`.
    """
    payload = {k: v for k, v in spec.items() if k != "why"}
    canonical = json.dumps(
        {
            "spec": payload,
            "prompt_version": prompt_version,
            "doctrine_hash": doctrine_hash,
            "schema_version": schema_version,
            "lint_version": lint_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return content_hash[:32], content_hash


# --- hard lint (§3 step 3) ------------------------------------------------------
#
# Rule ids are stable: the seeded defects (evals/goldens/personalized/
# artifacts/defects/) and DET-PL03-LINT assert them. Reuse of factory/lint.py:
# the JS/CSS base rules below ARE factory rules; the artifact-specific ones
# wrap them without forking the semantics.

_JS_FORBIDDEN: tuple[tuple[str, str, str], ...] = (
    # factory/lint.py base rules (factory semantics, artifact scope)
    (r"\beval\s*\(", "LINT_EVAL", "eval() is forbidden"),
    (r"\bnew\s+Function\b", "LINT_EVAL", "new Function() is forbidden"),
    (r"\bdocument\.write\b", "LINT_DOCUMENT_WRITE", "document.write is forbidden"),
    (r"\bfetch\s*\(", "LINT_NETWORK_FETCH", "fetch() is forbidden (no network)"),
    (r"\bXMLHttpRequest\b", "LINT_NETWORK_XHR", "XMLHttpRequest is forbidden"),
    (r"\bWebSocket\b", "LINT_NETWORK_WS", "WebSocket is forbidden"),
    (r"\bEventSource\b", "LINT_NETWORK_SSE", "EventSource is forbidden"),
    (r"\bnavigator\.sendBeacon\b", "LINT_NETWORK_BEACON", "sendBeacon is forbidden"),
    (r"\bimport\s*\(", "LINT_DYNAMIC_IMPORT", "dynamic import() is forbidden"),
    (r"\brequire\s*\(", "LINT_REQUIRE", "require() is forbidden"),
    (r"\bimportScripts\b", "LINT_IMPORT_SCRIPTS", "importScripts is forbidden"),
    (r"[\"']https?://", "LINT_URL_STRING", "string-literal http(s) URL is forbidden"),
    (r"<\s*script", "LINT_SCRIPT_CREATE", "inline <script> creation is forbidden"),
    # artifact-specific (interactive-artifacts.md §3 step 3)
    (r"\blocalStorage\b", "LINT_STORAGE", "localStorage is forbidden"),
    (r"\bsessionStorage\b", "LINT_STORAGE", "sessionStorage is forbidden"),
    (r"\bindexedDB\b", "LINT_STORAGE", "indexedDB is forbidden"),
    (r"document\s*\.\s*cookie", "LINT_STORAGE", "document.cookie is forbidden"),
    (r"\bwindow\.top\b", "LINT_PARENT", "window.top access is forbidden"),
    (r"\bwindow\.open\b", "LINT_POPUP", "window.open is forbidden"),
    (
        r"\bhistory\s*\.\s*(pushState|replaceState|go|back|forward)\b",
        "LINT_SELFNAV",
        "history navigation is forbidden",
    ),
    (
        r"\blocation\s*(?:=|\.(?:href|assign|replace|reload|hash|search|pathname|origin))\b",
        "LINT_SELFNAV",
        "self-navigation via location is forbidden",
    ),
    (r"\bwindow\.location\b", "LINT_SELFNAV", "window.location is forbidden"),
    (r"\bdocument\.location\b", "LINT_SELFNAV", "document.location is forbidden"),
    (
        r"\bnavigator\.clipboard\b|\bdocument\.execCommand\s*\(",
        "LINT_CLIPBOARD",
        "clipboard APIs are forbidden",
    ),
    (
        r"\bnew\s+Notification\b|\bNotification\.requestPermission\b",
        "LINT_NOTIFICATION",
        "Notification is forbidden",
    ),
    (
        r"\b(?:webkit)?requestFullscreen\b",
        "LINT_FULLSCREEN",
        "fullscreen is forbidden",
    ),
)

_HTML_FORBIDDEN_TAGS: tuple[tuple[str, str, str], ...] = (
    (r"<\s*form\b", "LINT_FORM", "<form> is forbidden"),
    (r"<\s*iframe\b", "LINT_IFRAME", "<iframe> is forbidden"),
    (r"<\s*object\b", "LINT_EMBED", "<object> is forbidden"),
    (r"<\s*embed\b", "LINT_EMBED", "<embed> is forbidden"),
    (r"<\s*base\b", "LINT_BASE", "<base href> is forbidden"),
    (
        r"<\s*meta[^>]*http-equiv\s*=\s*[\"']?refresh",
        "LINT_META_REFRESH",
        "meta refresh is forbidden",
    ),
)

_EXTERNAL_ATTR_RE = re.compile(
    r"""(?:src|href|action|formaction|xlink:href)\s*=\s*["']\s*(?:https?:)?//[^"']*["']""",
    re.IGNORECASE,
)
_JS_URL_RE = re.compile(
    r"""(?:src|href|action)\s*=\s*["']\s*javascript:""", re.IGNORECASE
)
_DATA_HTML_RE = re.compile(r"data:\s*text/html", re.IGNORECASE)
_DATA_NAV_RE = re.compile(r"""<a\b[^>]*href\s*=\s*["']data:""", re.IGNORECASE)
_ONHANDLER_RE = re.compile(
    r"\son[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE
)
_SRCDOC_RE = re.compile(r"\bsrcdoc\s*=", re.IGNORECASE)
_ANCHOR_RE = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_SCRIPT_TAG_RE = re.compile(r"<\s*script\b[^>]*>", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(
    r"""<\s*script\b[^>]*\bsrc\s*=\s*["'][^"']*["']""", re.IGNORECASE
)
_RANGE_INPUT_RE = re.compile(
    r"""<input\b[^>]*type\s*=\s*["']range["'][^>]*>""", re.IGNORECASE
)
_INPUT_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_LABEL_FOR_RE = re.compile(
    r"""<label\b[^>]*\bfor\s*=\s*["']([^"']+)["']""", re.IGNORECASE
)
_CANVAS_RE = re.compile(r"<canvas\b[^>]*>", re.IGNORECASE)
_CANVAS_ROLE_RE = re.compile(r"""\brole\s*=\s*["']img["']""", re.IGNORECASE)
_CANVAS_ARIA_RE = re.compile(r"""\baria-label\s*=\s*["'][^"']+["']""", re.IGNORECASE)
_H1_RE = re.compile(r"<h1\b", re.IGNORECASE)
_PARENT_RE = re.compile(r"\bwindow\.parent\b")
_POSTMESSAGE_RE = re.compile(r"\bpostMessage\s*\(")
_HARNESS_POSTMESSAGE = "window.parent.postMessage("


def _script_bodies(html: str) -> list[tuple[str, int]]:
    """Inline <script> bodies with their line offsets (parser-based: a regex
    over raw HTML is evadable; the parser sees what the browser sees)."""
    bodies: list[tuple[str, int]] = []
    lower = html.lower()
    pos = 0
    while True:
        open_m = _SCRIPT_TAG_RE.search(html, pos)
        if open_m is None:
            break
        src_external = _SCRIPT_SRC_RE.match(open_m.group(0))
        close = lower.find("</script", open_m.end())
        if src_external:
            # An external script src is itself a lint hit (LINT_SCRIPT_SRC);
            # its remote body is not available to lint, so skip past it.
            pos = (close + 1) if close != -1 else open_m.end()
            continue
        end = open_m.end()  # the match includes the tag's closing '>'
        if close == -1:
            body, pos = html[end:], len(html)
        else:
            body, pos = html[end:close], close + 1
        if body.strip():
            bodies.append((body, html[: open_m.start()].count("\n") + 1))
    return bodies


def _style_bodies(html: str) -> list[tuple[str, int]]:
    bodies: list[tuple[str, int]] = []
    for m in re.finditer(
        r"<style\b[^>]*>(.*?)</style>", html, re.IGNORECASE | re.DOTALL
    ):
        if m.group(1).strip():
            bodies.append((m.group(1), html[: m.start()].count("\n") + 1))
    return bodies


def lint_artifact_html(html: str, *, kind: str = "simulation") -> list[str]:
    """The hard artifact lint: every hit is a failure, never a warning.

    Returns a list of `"<line>: <message> [rule_id]"` strings. Rules reuse
    `factory/lint.py` semantics; the one deliberate relaxation of the lesson
    rules is that the artifact document carries exactly one inline `<script>`
    block (it is self-contained) while inline `on*=` handlers stay rejected.
    """
    hits: list[str] = []
    kind = kind if kind in ARTIFACT_KINDS else "simulation"

    def hit(match_at: int, rule: str, message: str) -> None:
        line = html[:match_at].count("\n") + 1
        hits.append(f"{line}: {message} [{rule}]")

    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        hits.append(
            f"1: artifact is {len(html.encode('utf-8'))} bytes, cap is "
            f"{MAX_HTML_BYTES} [LINT_SIZE]"
        )
    nodes = count_dom_nodes(html)
    if nodes > MAX_DOM_NODES:
        hits.append(
            f"1: artifact has {nodes} DOM nodes, cap is {MAX_DOM_NODES} [LINT_DOM_NODES]"
        )

    for m in _EXTERNAL_ATTR_RE.finditer(html):
        hit(m.start(), "LINT_EXTERNAL_URL", "external URL in an attribute is forbidden")
    for m in _JS_URL_RE.finditer(html):
        hit(m.start(), "LINT_JS_URL", "javascript: URL is forbidden")
    for m in _DATA_HTML_RE.finditer(html):
        hit(m.start(), "LINT_DATA_HTML", "data:text/html is forbidden")
    for m in _DATA_NAV_RE.finditer(html):
        hit(m.start(), "LINT_DATA_NAV", "data: navigation from an anchor is forbidden")
    for m in _ONHANDLER_RE.finditer(html):
        hit(
            m.start(),
            "LINT_ONHANDLER",
            "inline on*= handlers are forbidden (addEventListener)",
        )
    for m in _SRCDOC_RE.finditer(html):
        hit(m.start(), "LINT_SRCDOC", "srcdoc is forbidden")
    for pattern, rule, message in _HTML_FORBIDDEN_TAGS:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            hit(m.start(), rule, message)
    for m in _ANCHOR_RE.finditer(html):
        if m.group(1) != "#":
            hit(m.start(), "LINT_ANCHOR", '<a> links are forbidden (only href="#")')

    # Scripts: exactly one inline block, never an external src.
    script_tags = list(_SCRIPT_TAG_RE.finditer(html))
    if len(script_tags) != 1:
        hit(
            script_tags[0].start() if script_tags else 0,
            "LINT_SCRIPT_COUNT",
            f"the document carries exactly one inline <script> block (found {len(script_tags)})",
        )
    for m in _SCRIPT_SRC_RE.finditer(html):
        hit(m.start(), "LINT_SCRIPT_SRC", "external <script src> is forbidden")

    # JS rules over every inline body (base factory rules + artifact rules).
    for body, base_line in _script_bodies(html):
        for pattern, rule, message in _JS_FORBIDDEN:
            for m in re.finditer(pattern, body):
                hits.append(
                    f"{base_line + body[: m.start()].count('\n')}: {message} [{rule}]"
                )
        # Parent access: only the harness channel may touch window.parent.
        for m in _PARENT_RE.finditer(body):
            if not body[m.end() :].startswith(".postMessage("):
                hits.append(
                    f"{base_line + body[: m.start()].count('\n')}: window.parent is "
                    "allowed only as the harness channel window.parent.postMessage(...) "
                    "[LINT_PARENT]"
                )
        for m in _POSTMESSAGE_RE.finditer(body):
            head_start = max(0, m.start() - len("window.parent."))
            if body[head_start : m.start()] != "window.parent.":
                hits.append(
                    f"{base_line + body[: m.start()].count('\n')}: postMessage is allowed "
                    "only as the harness channel window.parent.postMessage(...) "
                    "[LINT_POSTMESSAGE]"
                )

    # CSS rules reuse factory/lint.lint_css (@import + url(http...) are the
    # external fetches the artifact must never make).
    from factory.lint import lint_css

    for body, _base_line in _style_bodies(html):
        for css_hit in lint_css("artifact-inline-style", body):
            rule = "LINT_CSS_URL" if "url(http" in css_hit else "LINT_CSS_IMPORT"
            hits.append(f"{css_hit} [{rule}]")

    # Accessibility is lint too (§4): labels on controls, named canvas, one h1.
    labelled_ids = {m.group(1) for m in _LABEL_FOR_RE.finditer(html)}
    for m in _RANGE_INPUT_RE.finditer(html):
        tag = m.group(0)
        found = _INPUT_ID_RE.search(tag)
        input_id = found.group(1) if found else None
        if not input_id or input_id not in labelled_ids:
            hit(m.start(), "LINT_LABEL_MISSING", "every control needs a <label for=…>")
    for m in _CANVAS_RE.finditer(html):
        tag = m.group(0)
        if not _CANVAS_ROLE_RE.search(tag) or not _CANVAS_ARIA_RE.search(tag):
            hit(
                m.start(),
                "LINT_CANVAS_A11Y",
                'canvas needs role="img" and an aria-label',
            )
    h1_count = len(_H1_RE.findall(html))
    if h1_count != 1:
        hit(0, "LINT_H1", f"the document needs exactly one <h1> (found {h1_count})")
    return hits


# --- store (cache rows, status machine, refcount, purge) -------------------------


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _uuid7_str() -> str:
    from db.uuid7 import uuid7_str

    return uuid7_str()


_ARTIFACT_COLS = (
    "artifact_id, content_hash, kind, title, spec, html, fallback, status, "
    "failure_reason, model, prompt_version, doctrine_hash, schema_version, "
    "lint_version, lint_hits, render_ms, created_at, ready_at, last_used_at"
)


class ArtifactStore:
    """Cache-row operations for `personalized_artifact` (no user_id column:
    artifacts are shared content; authorization is the caller's reference)."""

    def __init__(self, db: DatabaseEngine) -> None:
        self.db = db

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            f"SELECT {_ARTIFACT_COLS} FROM personalized_artifact WHERE artifact_id = ?",
            (artifact_id,),
        )
        return self._out(row) if row else None

    def create_pending(
        self,
        *,
        artifact_id: str,
        content_hash: str,
        spec: dict[str, Any],
        fallback: dict[str, Any],
        doctrine_hash: str,
        prompt_version: str = PROMPT_VERSION,
        schema_version: int = SCHEMA_VERSION,
        lint_version: str = LINT_VERSION,
    ) -> dict[str, Any]:
        """Insert the pending build record; a re-built identical spec is a no-op
        (the UNIQUE content_hash wins and the existing row is returned)."""
        now = _utc_now_iso()
        self.db.execute(
            """
            INSERT INTO personalized_artifact (
                artifact_id, content_hash, kind, title, spec, fallback, status,
                prompt_version, doctrine_hash, schema_version, lint_version,
                created_at, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            ON CONFLICT (content_hash) DO NOTHING
            """,
            (
                artifact_id,
                content_hash,
                str(spec["kind"]),
                str(spec["title"])[:MAX_TITLE_CHARS],
                json.dumps(spec),
                json.dumps(fallback),
                prompt_version,
                doctrine_hash,
                schema_version,
                lint_version,
                now,
                now,
            ),
        )
        row = self.get(artifact_id) or self._by_hash(content_hash)
        assert row is not None
        return row

    def _by_hash(self, content_hash: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            f"SELECT {_ARTIFACT_COLS} FROM personalized_artifact WHERE content_hash = ?",
            (content_hash,),
        )
        return self._out(row) if row else None

    def mark_ready(
        self,
        artifact_id: str,
        *,
        html: str,
        model: str | None = None,
        lint_hits: int = 0,
        render_ms: int | None = None,
    ) -> None:
        self.db.execute(
            """
            UPDATE personalized_artifact
            SET status = 'ready', html = ?, model = ?, lint_hits = ?,
                render_ms = ?, ready_at = ?, last_used_at = ?
            WHERE artifact_id = ? AND status = 'pending'
            """,
            (
                html,
                model,
                lint_hits,
                render_ms,
                _utc_now_iso(),
                _utc_now_iso(),
                artifact_id,
            ),
        )

    def mark_failed(
        self,
        artifact_id: str,
        *,
        failure_reason: str,
        model: str | None = None,
        lint_hits: int = 0,
        render_ms: int | None = None,
    ) -> None:
        if failure_reason not in FAILURE_REASONS:
            raise ValueError(f"unknown artifact failure_reason {failure_reason!r}")
        self.db.execute(
            """
            UPDATE personalized_artifact
            SET status = 'failed', failure_reason = ?, model = ?, lint_hits = ?,
                render_ms = ?
            WHERE artifact_id = ? AND status = 'pending'
            """,
            (failure_reason, model, lint_hits, render_ms, artifact_id),
        )

    def reset_to_pending(self, artifact_id: str) -> None:
        """Transient-route rebuild path: return a failed row to pending."""
        self.db.execute(
            """
            UPDATE personalized_artifact
            SET status = 'pending', failure_reason = NULL
            WHERE artifact_id = ? AND status = 'failed'
            """,
            (artifact_id,),
        )

    def touch_last_used(self, artifact_id: str) -> None:
        """Every authorized serve refreshes the refcount purge input (§7)."""
        self.db.execute(
            "UPDATE personalized_artifact SET last_used_at = ? WHERE artifact_id = ?",
            (_utc_now_iso(), artifact_id),
        )

    def is_referenced_for_user(self, artifact_id: str, user_id: str) -> bool:
        """§7 authorization: a message of kind `artifact_ref` in one of the
        caller's sessions references the artifact (same payload LIKE pattern
        as the retention refcount, so both engines agree)."""
        row = self.db.fetchone(
            """
            SELECT 1 AS ref
            FROM personalized_message m
            JOIN personalized_session s ON s.session_id = m.session_id
            WHERE s.user_id = ? AND m.kind = 'artifact_ref'
              AND REPLACE(m.payload, ' ', '') LIKE ?
            LIMIT 1
            """,
            (user_id, f'%"artifact_id":"{artifact_id}"%'),
        )
        return row is not None

    def purge(self, artifact_id: str) -> bool:
        """Operator purge (§7): delete the row and mark every referencing
        message `artifact_missing` so the fallback renders honestly. Audit
        event: `personalized.artifact.purged`."""
        row = self.get(artifact_id)
        if row is None:
            return False
        refs = self.db.fetchall(
            "SELECT message_id, payload FROM personalized_message "
            "WHERE kind = 'artifact_ref' AND REPLACE(payload, ' ', '') LIKE ?",
            (f'%"artifact_id":"{artifact_id}"%',),
        )
        with self.db.transaction() as tx:
            tx.execute(
                "DELETE FROM personalized_artifact WHERE artifact_id = ?",
                (artifact_id,),
            )
            for ref in refs:
                payload = _load_json(ref.get("payload")) or {}
                if payload.get("artifact_missing"):
                    continue
                payload["artifact_missing"] = True
                tx.execute(
                    "UPDATE personalized_message SET payload = ? WHERE message_id = ?",
                    (json.dumps(payload), str(ref["message_id"])),
                )
        log_event("personalized.artifact.purged", {"artifact_id": artifact_id})
        return True

    @staticmethod
    def _out(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_id": str(row["artifact_id"]),
            "content_hash": str(row["content_hash"]),
            "kind": str(row["kind"]),
            "title": str(row["title"]),
            "spec": _load_json(row.get("spec")) or {},
            "html": row.get("html"),
            "fallback": _load_json(row.get("fallback")),
            "status": str(row["status"]),
            "failure_reason": row.get("failure_reason"),
            "model": row.get("model"),
            "prompt_version": str(row["prompt_version"]),
            "doctrine_hash": str(row["doctrine_hash"]),
            "schema_version": int(row["schema_version"]),
            "lint_version": str(row["lint_version"]),
            "lint_hits": int(row.get("lint_hits") or 0),
            "render_ms": row.get("render_ms"),
            "created_at": row.get("created_at"),
            "ready_at": row.get("ready_at"),
            "last_used_at": row.get("last_used_at"),
        }


def _load_json(value: object) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return None


def record_usage(
    db: DatabaseEngine,
    *,
    user_id: str,
    session_id: str | None,
    turn_index: int | None,
    artifact_build: bool,
    cache_hit: bool,
    outcome: str,
    model: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """One C25 cost-ledger row per artifact decision (§2.5; counts only)."""
    db.execute(
        """
        INSERT INTO personalized_usage (
            usage_id, user_id, session_id, turn_index, stage, model,
            artifact_build, cache_hit, outcome, latency_ms, created_at
        ) VALUES (?, ?, ?, ?, 'artifact', ?, ?, ?, ?, ?, ?)
        """,
        (
            _uuid7_str(),
            user_id,
            session_id,
            turn_index,
            model,
            bool(artifact_build),
            bool(cache_hit),
            outcome,
            latency_ms,
            _utc_now_iso(),
        ),
    )


# --- internal generation interface for PL2 (§3) ---------------------------------


class ArtifactHandle:
    """What PL2's turn loop receives back from `ensure_artifact`."""

    def __init__(
        self,
        *,
        artifact_id: str | None,
        status: str,
        failure_reason: str | None = None,
        fallback: dict[str, Any] | None = None,
        weak_grounding: bool = False,
        cache_hit: bool = False,
    ) -> None:
        self.artifact_id = artifact_id
        self.status = status
        self.failure_reason = failure_reason
        self.fallback = fallback or {}
        self.weak_grounding = weak_grounding
        self.cache_hit = cache_hit

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "fallback": self.fallback,
            "weak_grounding": self.weak_grounding,
        }


class ArtifactBuilder:
    """The seam PL2 injects (the default engine lives in `artifact_prompt.py`;
    tests inject fakes). One call: model build → lint retry → render gate."""

    def build(
        self, spec: dict[str, Any], claims: list[dict[str, Any]]
    ) -> tuple[str, int, int | None, str | None]:
        """Return `(html, lint_hits, render_ms, model)` or raise
        `ArtifactBuildError`."""
        raise NotImplementedError


def ensure_artifact(
    *,
    db: DatabaseEngine,
    quota: Any,
    user_id: str,
    session_id: str,
    turn_index: int | None,
    raw_spec: object,
    available_claims: dict[str, dict[str, Any]],
    forbidden_texts: list[str],
    fallback: object,
    builder: ArtifactBuilder | None,
    doctrine_hash: str,
) -> ArtifactHandle:
    """The internal generation pipeline (§3): validate → hash → cache →
    quota → build → lint → render → store.

    PL2 calls this from the teaching turn; the default `builder` runs the
    DeepSeek/OpenCode route (`artifact_prompt.py`) and tests inject fakes.
    `available_claims` maps the retrieved claim ids to their records (only
    cited ones reach the builder prompt). The turn itself is never blocked by
    an artifact failure: every rejection path raises
    `ArtifactSpecError`/`ArtifactQuotaError`/`ArtifactBuildError` with the
    fallback attached for the caller to render.

    A previously `failed` row is rebuilt only for a transient route error
    (D-PL-03: one retry, never for lint/render — those are deterministic).
    """
    norm_fallback = normalize_fallback(fallback)
    try:
        spec, weak_grounding = validate_artifact_spec(
            raw_spec, available_claim_ids=set(available_claims)
        )
        ensure_no_student_text(spec, forbidden_texts)
    except ArtifactSpecError as exc:
        record_usage(
            db,
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            artifact_build=False,
            cache_hit=False,
            outcome="rejected",
        )
        exc.extra = {**exc.extra, "fallback": norm_fallback}
        log_event(
            "personalized.artifact.failed",
            {"reason_code": "spec"},
        )
        raise
    artifact_id, content_hash = compute_artifact_id(spec, doctrine_hash=doctrine_hash)
    store = ArtifactStore(db)

    existing = store.get(artifact_id)
    if existing is not None and existing["status"] == "ready":
        # Cache hit: zero model calls, zero quota (§7, §9).
        store.touch_last_used(artifact_id)
        record_usage(
            db,
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            artifact_build=False,
            cache_hit=True,
            outcome="ok",
        )
        log_event(
            "personalized.artifact.requested",
            {
                "artifact_id": artifact_id,
                "kind": str(spec["kind"]),
                "cache_hit": True,
                "weak_grounding": weak_grounding,
            },
        )
        return ArtifactHandle(
            artifact_id=artifact_id,
            status="ready",
            fallback=norm_fallback,
            weak_grounding=weak_grounding,
            cache_hit=True,
        )
    if (
        existing is not None
        and existing["status"] == "failed"
        and existing["failure_reason"] != "route"
    ):
        # A deterministic failure stays failed until its 7-day TTL: the same
        # spec would fail the same way, and rebuilding it would burn quota.
        return ArtifactHandle(
            artifact_id=artifact_id,
            status="failed",
            failure_reason=str(existing["failure_reason"]),
            fallback=norm_fallback,
            weak_grounding=weak_grounding,
        )
    if builder is None:
        # The route is not wired (no secret/config): fail closed BEFORE any
        # row or quota movement — the honest fallback is the turn's answer
        # (§8), and no stale pending row can leak (no pending TTL exists).
        raise ArtifactBuildError(
            "route",
            "artifact builder not configured",
            extra={"fallback": norm_fallback},
        )

    decision = quota.reserve_artifact(user_id)
    if not decision.allowed:
        record_usage(
            db,
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            artifact_build=False,
            cache_hit=False,
            outcome="quota_blocked",
        )
        raise ArtifactQuotaError(
            "error.pl.quota_global"
            if decision.reason == "global_artifact_cap"
            else "error.pl.quota_user"
        )

    if existing is not None:
        # Transient-route rebuild: the row already exists (UNIQUE hash), so
        # return it to pending instead of inserting a duplicate.
        store.reset_to_pending(artifact_id)
    else:
        store.create_pending(
            artifact_id=artifact_id,
            content_hash=content_hash,
            spec=spec,
            fallback=norm_fallback,
            doctrine_hash=doctrine_hash,
        )
    log_event(
        "personalized.artifact.requested",
        {
            "artifact_id": artifact_id,
            "kind": str(spec["kind"]),
            "cache_hit": False,
            "weak_grounding": weak_grounding,
        },
    )
    try:
        html, lint_hits, render_ms, model = builder.build(
            spec,
            [
                available_claims[cid]
                for cid in spec.get("cited_claim_ids", [])
                if cid in available_claims
            ],
        )
    except ArtifactBuildError as exc:
        store.mark_failed(
            artifact_id,
            failure_reason=exc.failure_reason,
            model=exc.model,
            lint_hits=exc.lint_hits,
            render_ms=exc.render_ms,
        )
        record_usage(
            db,
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            artifact_build=True,
            cache_hit=False,
            outcome="model_error"
            if exc.failure_reason == "route"
            else "artifact_failed",
            model=exc.model,
            latency_ms=exc.render_ms,
        )
        log_event(
            "personalized.artifact.failed",
            {
                "artifact_id": artifact_id,
                "reason_code": exc.failure_reason,
                "lint_hits": exc.lint_hits,
            },
            error_class="gate_fail",
        )
        # The reservation was consumed by the attempt: D-PL-03 allows one
        # retry for a transient route error only, and that retry re-reserves.
        if exc.failure_reason != "route":
            quota.commit_artifact(user_id)
        else:
            quota.release_artifact(user_id)
        if not exc.extra:
            exc.extra = {"fallback": norm_fallback}
        raise
    # Backstop lint (the 05-interactive pattern): the builder engine already
    # ran lint-in-retry, but the row is never marked ready on a document the
    # hard lint rejects — whatever produced it.
    backstop = lint_artifact_html(html)
    if backstop:
        store.mark_failed(
            artifact_id,
            failure_reason="lint",
            model=model,
            lint_hits=len(backstop),
            render_ms=render_ms,
        )
        record_usage(
            db,
            user_id=user_id,
            session_id=session_id,
            turn_index=turn_index,
            artifact_build=True,
            cache_hit=False,
            outcome="artifact_failed",
            model=model,
            latency_ms=render_ms,
        )
        log_event(
            "personalized.artifact.failed",
            {
                "artifact_id": artifact_id,
                "reason_code": "lint",
                "lint_hits": len(backstop),
            },
            error_class="gate_fail",
        )
        quota.commit_artifact(user_id)
        raise ArtifactBuildError(
            "lint",
            "; ".join(backstop[:3]),
            lint_hits=len(backstop),
            render_ms=render_ms,
            model=model,
            extra={"fallback": norm_fallback},
        )
    store.mark_ready(
        artifact_id, html=html, model=model, lint_hits=lint_hits, render_ms=render_ms
    )
    quota.commit_artifact(user_id)
    record_usage(
        db,
        user_id=user_id,
        session_id=session_id,
        turn_index=turn_index,
        artifact_build=True,
        cache_hit=False,
        outcome="ok",
        model=model,
        latency_ms=render_ms,
    )
    log_event(
        "personalized.artifact.ready",
        {
            "artifact_id": artifact_id,
            "kind": str(spec["kind"]),
            "lint_hits": lint_hits,
            "render_ms": render_ms,
            "cache_hit": False,
        },
        latency_ms=render_ms,
    )
    return ArtifactHandle(
        artifact_id=artifact_id,
        status="ready",
        fallback=norm_fallback,
        weak_grounding=weak_grounding,
    )
