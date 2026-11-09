"""Speakable-block selection: which lesson content gets narrated, and as what
spoken form.

This module is the CODE form of the gap-register GAP-015 mini-spec (the
binding contract for EX8-NARRATION):

    text            -> full prose (every paragraph)
    animation/simulation -> spec.title + spec.description + readout strings
                       from page.js (never JS code)
    diagram         -> svg_texts only (never the SVG markup, never the caption
                       - captions are "on request only" per the features
                       states row; English v1 blocks carry no svg_texts, so
                       diagrams are simply not narrated until the translation
                       payload (CP-TRN-002) introduces them)
    check           -> question + options; answers are NEVER read aloud until
                       revealed (no answer / explanation / expected_understanding)
    metadata        -> b-00-meta: lesson title + objectives
    worked_example  -> problem + steps + answer (the features.md states row
                       lists worked_example as speakable; the full worked
                       solution IS the teaching content and is fully visible
                       on the page - the check rule about unrevealed answers
                       does not apply here)
    reveal          -> not speakable (progressive-disclosure content; the
                       mini-spec lists no speakable fields for it)

    Spoken form (the text-layer transform the factory's future equation
    RENDERING upgrade does not replace): every part is verbalized
    deterministically (LaTeX / math notation / Unicode symbols / super- and
    subscripts -> spoken words, e.g. "x squared plus one",
    "3.06 metres per second squared", "the integral of velocity with
    respect to time") and wrapped in the whitelisted Timbre v3.0 expressive
    tags below. This module is pure (no I/O, no model calls) — it reuses the
    factory's OpenRouter key path (ZIVON_API_KEY, K8s Secret zivon-factory-env)
    only INDIRECTLY by never needing it: there is no OpenRouter call here at
    all, and no second key variable (OPENROUTER_API_KEY) is introduced. If a
    future LLM verbalization fallback is ever added it MUST go through
    llm_manager (ZIVON_BASE_URL / ZIVON_MODEL / ZIVON_API_KEY — the node owns
    the OpenRouter upstream), never a direct OpenRouter POST.

All other spec fields are excluded (GAP-015: "All other spec fields are
excluded") - notably simulation controls/labels and every citation.

Nothing in this module performs I/O or calls a model: pure selection over the
02-generate block payloads plus the 05-interactive readout strings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# Timbre v3.0 expressive tags (AGENTS.md 13-tag catalog, verified against
# docs.gnani.ai 2026-11-07; Timbre v3.0 ONLY — v2.5 strips these before
# synthesis). Tags bill as characters, so the budget (budget.py) counts the
# assembled spoken text INCLUDING tags.
# The full catalog (kept here so the whitelist is auditable — anything outside
# ALLOWED_TAGS is stripped by strip_non_whitelisted_tags, mirroring the
# server-side harness strip):
TIMBRE_V3_TAGS: tuple[str, ...] = (
    "<laugh>",
    "<giggle>",
    "<sigh>",
    "<exhales>",
    "<sniffles>",
    "<yawns>",
    "<coughs>",
    "<clears throat>",
    "<whispers>",
    "<shouting>",
    "<excited>",
    "<slow>",
    "<pauses>",
)
# The tutor-style narration whitelist (SP1 Appendix A spoken contract):
# only <pauses> <slow> <excited> <whispers> may ever appear in narration.
# <whispers> is whitelisted but never auto-emitted in v1 (static read-aloud
# for a class does not whisper; it stays available for a future deliberate
# use). The other nine catalog tags (laugh/giggle/sigh/...) are voice-tutor
# vocalizations, not static-text narration.
ALLOWED_TAGS: frozenset[str] = frozenset(
    {"<pauses>", "<slow>", "<excited>", "<whispers>"}
)
PAUSE_TAG = "<pauses>"
SLOW_TAG = "<slow>"
EXCITED_TAG = "<excited>"
WHISPERS_TAG = "<whispers>"
# SP1 Appendix A + H3 caps, adapted from turn to block (the narration atom):
# at most one cue per two sentences, and never more than 8 cues per block.
SENTENCES_PER_TAG = 2
MAX_TAGS_PER_UNIT = 8

_TAG_RE = re.compile(r"<[^<>]*>")


def strip_non_whitelisted_tags(text: str) -> str:
    """Strip every angle-bracket tag except the narration whitelist.

    The harness guarantee (like SP1's T12/tag whitelist): authored content
    can never smuggle an over-tag into the synthesis request. Unknown tags
    are stripped silently (the same class of behavior as Timbre's own
    unknown-tag handling), whitelisted tags pass through untouched. Also
    used by timbre.py as the client-side defense before any POST.
    """

    def _keep(match: re.Match[str]) -> str:
        return match.group(0) if match.group(0) in ALLOWED_TAGS else ""

    cleaned = _TAG_RE.sub(_keep, text)
    return re.sub(r" {2,}", " ", cleaned)


# Unit pronunciation rules (features.md behaviour 5: "block text with
# unit-pronunciation rules", principle P7 "units spoken in full"). Ordered:
# longer patterns first so m/s2 is never eaten by m/s. SC-06 (the translation
# spec's spoken-form proposal) supersedes this table when it lands; until
# then this is the fallback the features card names.
_UNIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bm/s2\b"), "metres per second squared"),
    (re.compile(r"m/s2"), "metres per second squared"),
    (re.compile(r"m/s\u00b2"), "metres per second squared"),
    (re.compile(r"\bm/s\b"), "metres per second"),
    (re.compile(r"\bkm/h\b"), "kilometres per hour"),
    (re.compile(r"\bkm/s\b"), "kilometres per second"),
    (re.compile(r"\bcm/s\b"), "centimetres per second"),
    (re.compile(r"\bkg/m3\b"), "kilograms per cubic metre"),
    (re.compile(r"kg/m\u00b3"), "kilograms per cubic metre"),
    (re.compile(r"\bN/kg\b"), "newtons per kilogram"),
    (re.compile(r"\u00b0C"), "degrees Celsius"),
    (re.compile(r"\u00b0F"), "degrees Fahrenheit"),
)

# ---- Deterministic equation / symbol verbalization (text layer only) --------
# The factory will get a separate upgrade to RENDER equations properly in
# generated pages (future, out of scope). Until then, narration must still
# speak them: LaTeX, math notation and Unicode symbols become words
# ("x squared plus one", "the integral of velocity with respect to time").
# These tables EXTEND _UNIT_RULES (same module, same fallback path — SC-06
# supersedes both when it lands); no second spoken-form copy exists.
#
# Pipeline (order is load-bearing — see _verbalize_part):
#   1. LaTeX delimiters/commands, 2. Unicode symbols, 3. UNITS, 4. super/sub
#   scripts, 5. integral differential, 6. remaining operators. Units run
#   BEFORE generic "/" and before super/scripts so "m/s²" / "m/s2" still
#   reach the unit table intact (never "m divided by s squared").

_UNICODE_SYMBOLS: dict[str, str] = {
    "×": "times",
    "·": "times",
    "÷": "divided by",
    "±": "plus or minus",
    "∓": "minus or plus",
    "−": "minus",
    "≈": "is approximately",
    "≅": "is approximately",
    "≤": "is less than or equal to",
    "≥": "is greater than or equal to",
    "≠": "is not equal to",
    "→": "leads to",
    "←": "comes from",
    "⇒": "implies",
    "⇔": "if and only if",
    "∈": "is an element of",
    "∉": "is not an element of",
    "∋": "contains",
    "∝": "is proportional to",
    "∞": "infinity",
    "∫": "the integral of",
    "Σ": "the sum of",
    "∑": "the sum of",
    "∏": "the product of",
    "√": "the square root of",
    "∛": "the cube root of",
    "∂": "partial",
    "∇": "del",
    "′": "prime",
    # Greek letters (single-token physics symbols; TTS reads the words).
    "π": "pi",
    "Π": "pi",
    "θ": "theta",
    "Θ": "theta",
    "λ": "lambda",
    "Λ": "lambda",
    "Δ": "delta",
    "δ": "delta",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "φ": "phi",
    "Φ": "phi",
    "ψ": "psi",
    "Ψ": "psi",
    "ω": "omega",
    "Ω": "omega",
    "μ": "mu",
    "σ": "sigma",
    "ρ": "rho",
    "τ": "tau",
    "η": "eta",
    "ξ": "xi",
    "ζ": "zeta",
    "ν": "nu",
}

_LATEX_COMMANDS: dict[str, str] = {
    "pi": "pi",
    "theta": "theta",
    "lambda": "lambda",
    "Delta": "delta",
    "delta": "delta",
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "phi": "phi",
    "Phi": "phi",
    "psi": "psi",
    "omega": "omega",
    "Omega": "omega",
    "mu": "mu",
    "sigma": "sigma",
    "rho": "rho",
    "tau": "tau",
    "eta": "eta",
    "xi": "xi",
    "zeta": "zeta",
    "nu": "nu",
    "approx": "is approximately",
    "simeq": "is approximately",
    "times": "times",
    "cdot": "times",
    "div": "divided by",
    "pm": "plus or minus",
    "mp": "minus or plus",
    "rightarrow": "leads to",
    "to": "leads to",
    "leftarrow": "comes from",
    "Rightarrow": "implies",
    "Leftrightarrow": "if and only if",
    "in": "is an element of",
    "notin": "is not an element of",
    "ni": "contains",
    "leq": "is less than or equal to",
    "le": "is less than or equal to",
    "geq": "is greater than or equal to",
    "ge": "is greater than or equal to",
    "ne": "is not equal to",
    "neq": "is not equal to",
    "infty": "infinity",
    "partial": "partial",
    "nabla": "del",
    "int": "the integral of",
    "sum": "the sum of",
    "prod": "the product of",
    "propto": "is proportional to",
    "degree": "degrees",
    "circ": "degrees",
    "prime": "prime",
    "sin": "sine",
    "cos": "cosine",
    "tan": "tangent",
    "log": "log",
    "ln": "natural log",
    "exp": "exponential",
}

# LaTeX commands that wrap their braced argument (strip the wrapper).
_UNWRAP_COMMANDS: frozenset[str] = frozenset(
    {
        "text",
        "textrm",
        "textbf",
        "mathrm",
        "mathbf",
        "mathit",
        "vec",
        "hat",
        "bar",
        "tilde",
        "widehat",
        "overline",
        "underline",
        "boxed",
        "left",
        "right",
        "big",
        "Big",
        "bigg",
        "Bigg",
    }
)

_SUPER_DIGITS = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-",
    "⁺": "+",
}
_SUB_DIGITS = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
    "₋": "-",
    "₊": "+",
}
_SUPER_RE = re.compile(r"([A-Za-z0-9)\]])([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)")
_SUB_RE = re.compile(r"([A-Za-z0-9)\]])([₀₁₂₃₄₅₆₇₈₉₋₊]+)")

# page.js readout strings (CP-TRN-003 pattern): ctx.t_str("key", "fallback").
_T_STR_RE = re.compile(r'ctx\.t_str\(\s*"(?:[^"\\]|\\.)*"\s*,\s*"((?:[^"\\]|\\.)*)"')
# A readout that is a standalone math/unit token (F, 10 N, m/s, v (m/s)) is
# canvas chrome, not speakable prose - the same exclusion CP-TRN-002 applies
# to svg_texts. Speakable prose always carries an alphabetic run of >= 3
# characters (Latin or Devanagari); unit tokens never do.
_SPEAKABLE_RE = re.compile(r"[A-Za-z\u0900-\u097F]{3,}")


@dataclass(frozen=True)
class NarrationUnit:
    """One speakable unit: a block (or the lesson envelope) plus its spoken
    parts, in page order."""

    block_id: str  # "b-00-meta" or "b-01".."b-45"
    kind: str  # meta | text | worked_example | check | simulation | animation | diagram
    parts: tuple[str, ...]

    @property
    def chars(self) -> int:
        """Billable character estimate: the assembled spoken form, tags
        included (tags bill as characters per the verified Timbre v3.0
        catalog). The budget guard estimates from this."""
        return len(spoken_text(self))


def spoken_text(unit: NarrationUnit) -> str:
    """Assemble the unit's spoken form: every part is verbalized (math +
    units), then parts are joined with the whitelisted tags under the SP1
    caps: at most one cue per SENTENCES_PER_TAG sentences and at most
    MAX_TAGS_PER_UNIT cues per block. Allocation is global, delivery-first:
    <slow> before a verbalized equation and <excited> before the
    worked-example answer are funded before inter-part <pauses>, so a long
    worked example keeps its math/answer cues instead of spending its whole
    budget on early breathing pauses. Only one cue per boundary is ever
    emitted (no double-cue adjacency). <whispers> is whitelisted but never
    auto-emitted.

    This is the features.md "spoken form (SC-06 when available; else block
    text with unit-pronunciation rules)" fallback path, extended with the
    deterministic equation verbalization above — SC-06 supersedes it once
    the translation spec's spoken-form schema lands.
    """
    verbalized = [_verbalize_part(part) for part in unit.parts]
    verbalized = [(text, has_math) for text, has_math in verbalized if text]
    if not verbalized:
        return ""
    if len(verbalized) == 1:
        return verbalized[0][0]
    effective_sentences = _count_effective_sentences([text for text, _ in verbalized])
    allowed = min(MAX_TAGS_PER_UNIT, effective_sentences // SENTENCES_PER_TAG)
    if allowed <= 0:
        return " ".join(text for text, _ in verbalized)
    # Boundary candidates: index 0 is a leading prefix (only for math);
    # index i > 0 is the separator between part i-1 and part i.
    candidates: list[tuple[int, str, bool]] = []  # (index, tag, is_delivery)
    for index, (text, has_math) in enumerate(verbalized):
        if index == 0:
            if has_math:
                candidates.append((0, SLOW_TAG, True))
        elif has_math:
            candidates.append((index, SLOW_TAG, True))
        elif text.startswith("The answer is:"):
            candidates.append((index, EXCITED_TAG, True))
        else:
            candidates.append((index, PAUSE_TAG, False))
    # Delivery cues first (left to right), then breathing pauses.
    funded: dict[int, str] = {}
    budget = allowed
    for is_delivery in (True, False):
        for index, tag, delivery in candidates:
            if budget <= 0:
                break
            if delivery != is_delivery:
                continue
            funded[index] = tag
            budget -= 1
    out = ""
    for index, (text, _) in enumerate(verbalized):
        cue = funded.get(index)
        if index == 0:
            out = f"{cue} {text}" if cue else text
        else:
            out += f" {cue} {text}" if cue else f" {text}"
    return out


_SENTENCE_END_RE = re.compile(r"[.?!।…]+(?:[\"')\]])?")
_FRAGMENT_ENDS = (".", "?", "!", "।", "…", ":", ";", '"', "'", "”", "”", ")")


def _count_effective_sentences(texts: list[str]) -> int:
    """Sentence-like units for the tag cap: punctuated sentences plus parts
    that carry no terminal punctuation but are still one spoken idea each
    (options, titles, "The answer is: ..." fragments)."""
    joined = " ".join(texts)
    punctuated = len(_SENTENCE_END_RE.findall(joined))
    fragments = sum(
        1 for text in texts if text and not text.rstrip().endswith(_FRAGMENT_ENDS)
    )
    return punctuated + fragments


def _speak_part(part: str) -> str:
    """One part's spoken form (kept name for existing callers/tests)."""
    return _verbalize_part(part)[0]


def _verbalize_part(part: str) -> tuple[str, bool]:
    """Verbalize one part deterministically; returns (spoken, has_math).

    has_math marks parts whose equation/symbol verbalization changed
    something (it drives the <slow> cue). Pure unit pronunciation is not
    math. Source TTS tags are neutralized first (only the whitelist is
    re-emitted by the spoken_text assembler).
    """
    text = re.sub(r"\s+", " ", str(part)).strip()
    text = strip_non_whitelisted_tags(text)
    has_math = False

    # 1. LaTeX: delimiters and commands.
    if "$" in text or "\\" in text or r"\(" in text or r"\[" in text:
        expanded = _expand_latex(text)
        if expanded != text:
            has_math = True
        text = expanded

    # 2. Unicode symbols (runs before UNITS so unit slashes/degrees are safe;
    # note "°" and super/sub digit glyphs are deliberately NOT here).
    if any(symbol in text for symbol in _UNICODE_SYMBOLS):
        for symbol, spoken in _UNICODE_SYMBOLS.items():
            if symbol in text:
                has_math = True
                text = text.replace(symbol, f" {spoken} ")

    # 3. UNITS: the existing unit-pronunciation table (before any generic
    # "/" or super/script handling eats its patterns).
    for pattern, spoken in _UNIT_RULES:
        text = pattern.sub(spoken, text)

    # 4. Super/subscripts (Unicode then ASCII caret/underscore forms).
    text, changed = _expand_scripts(text)
    has_math = has_math or changed

    # 5. Integral differential: "dt" -> "with respect to time", etc.
    if "the integral of" in text:
        renamed, changed = _expand_differential(text)
        text = renamed
        has_math = has_math or changed

    # 6. Remaining operators.
    text, changed = _expand_operators(text)
    has_math = has_math or changed

    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text, has_math


# --------------------------------------------------------------- LaTeX

_FRAC_RE = re.compile(r"\\(?:d|t)?frac\{([^{}]*)\}\{([^{}]*)\}")
_SQRT_RE = re.compile(r"\\sqrt(?:\[([^\]]*)\])?\{([^{}]*)\}")


def _expand_latex(text: str) -> str:
    """Strip LaTeX delimiters and expand the physics-command subset.

    Handles display/inline delimiters ($$, $, \\( \\), \\[ \\]), \\frac,
    \\sqrt, wrapper commands (\\vec{X} -> X) and the symbol-command table.
    Anything unknown is unwrapped or dropped, never spoken as backslash
    noise. Iteration is bounded: each pass removes at least one backslash.
    """
    text = text.replace("$$", " ")
    text = text.replace("$", " ")
    text = re.sub(r"\\\(|\\\)|\\\[|\\\]", " ", text)
    for _ in range(8):
        if "\\" not in text:
            break
        before = text

        def _frac_sub(match: re.Match[str]) -> str:
            return f"{match.group(1)} divided by {match.group(2)}"

        def _sqrt_sub(match: re.Match[str]) -> str:
            root = (match.group(1) or "").strip()
            inner = match.group(2)
            if not root:
                return f"the square root of {inner}"
            if root == "3":
                return f"the cube root of {inner}"
            return f"the {root} root of {inner}"

        text = _FRAC_RE.sub(_frac_sub, text)
        text = _SQRT_RE.sub(_sqrt_sub, text)
        for command in _UNWRAP_COMMANDS:
            pattern = re.compile(rf"\\{re.escape(command)}\{{([^{{}}]*)\}}")
            text = pattern.sub(r"\1", text)

        def _command_sub(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in _LATEX_COMMANDS:
                return f" {_LATEX_COMMANDS[name]} "
            return " "

        text = re.sub(r"\\([A-Za-z]+)", _command_sub, text)
        text = re.sub(r"\\.", " ", text)  # spacing commands \, \; \: \! \\
        if text == before:
            break
    return text


# --------------------------------------------------------------- scripts


def _power_phrase(exp: str) -> str:
    if exp == "2":
        return "squared"
    if exp == "3":
        return "cubed"
    return f"to the power of {exp}"


def _expand_scripts(text: str) -> tuple[str, bool]:
    before = text

    def _sup_sub(match: re.Match[str]) -> str:
        base, run = match.group(1), match.group(2)
        ascii_run = "".join(_SUPER_DIGITS.get(ch, ch) for ch in run)
        return f"{base} {_power_phrase(ascii_run)}"

    def _sub_sub(match: re.Match[str]) -> str:
        base, run = match.group(1), match.group(2)
        ascii_run = "".join(_SUB_DIGITS.get(ch, ch) for ch in run)
        return f"{base} sub {ascii_run}"

    text = _SUPER_RE.sub(_sup_sub, text)
    text = _SUB_RE.sub(_sub_sub, text)
    # Tighten spaced carets/underscores ("x ^ 2" -> "x^2"), then ASCII forms.
    text = re.sub(r"(\S)\s+\^\s*(\S)", r"\1^\2", text)
    text = re.sub(r"(\S)\s+_\s*(\S)", r"\1_\2", text)

    def _ascii_sup(match: re.Match[str]) -> str:
        return f"{match.group(1)} {_power_phrase(match.group(2))}"

    def _ascii_sub(match: re.Match[str]) -> str:
        return f"{match.group(1)} sub {match.group(2)}"

    text = re.sub(r"([A-Za-z0-9)\]])\^\{([A-Za-z0-9+\-]+)\}", _ascii_sup, text)
    text = re.sub(r"([A-Za-z0-9)\]])\^([A-Za-z0-9])", _ascii_sup, text)
    text = re.sub(r"([A-Za-z0-9)\]])_[\{]?([A-Za-z0-9+\-]+)\}?", _ascii_sub, text)
    return text, text != before


_DIFF_NAMES = {"t": "time", "x": "x", "y": "y", "z": "z", "s": "s"}


def _expand_differential(text: str) -> tuple[str, bool]:
    before = text

    def _attached(match: re.Match[str]) -> str:
        name = match.group(1)
        spelled = _DIFF_NAMES.get(name, name)
        return f" with respect to {spelled} "

    text = re.sub(r"\bd([a-zA-Z])\b", _attached, text)

    def _spaced(match: re.Match[str]) -> str:
        spelled = _DIFF_NAMES.get(match.group(1), match.group(1))
        return f" with respect to {spelled} "

    text = re.sub(r"\bd\s+(time|theta|lambda|pi|x|y|z|s|t)\b", _spaced, text)
    return text, text != before


# --------------------------------------------------------------- operators


def _expand_operators(text: str) -> tuple[str, bool]:
    before = text
    # Minus: spaced hyphen, digit/letter-digit mixes. Letter-letter hyphens
    # ("well-known", "x-axis") are prose, never minus.
    text = re.sub(r"(\S)\s+-\s+(\S)", r"\1 minus \2", text)
    text = re.sub(r"(\d)\s*-\s*(\d)", r"\1 minus \2", text)
    text = re.sub(r"([A-Za-z])\s*-\s*(\d)", r"\1 minus \2", text)
    text = re.sub(r"(\d)\s*-\s*([A-Za-z])", r"\1 minus \2", text)
    text = re.sub(r"\s*==\s*", " equals ", text)
    text = re.sub(r"\s*=\s*", " equals ", text)
    text = re.sub(r"\s*\+\s*", " plus ", text)
    text = re.sub(r"\s*/\s*", " divided by ", text)
    text = re.sub(r"\s*\*\s*", " times ", text)
    text = re.sub(r"\s*<=\s*", " is less than or equal to ", text)
    text = re.sub(r"\s*>=\s*", " is greater than or equal to ", text)
    text = re.sub(r"\s*<>\s*", " is not equal to ", text)
    text = re.sub(r"\s*<\s*", " is less than ", text)
    text = re.sub(r"\s*>\s*", " is greater than ", text)
    text = re.sub(r"\s*%\s*", " percent ", text)
    text = re.sub(r"\s*&\s*", " and ", text)
    text = re.sub(r"\s*~\s*", " approximately ", text)
    text = text.replace("$", " ")
    text = text.replace("°", " degrees")
    text = text.replace("_", " ")
    text = text.replace("{", " ").replace("}", " ")
    text = text.replace("\\", " ")
    return text, text != before


def speakable_units(
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    interactive: dict[str, Any] | None = None,
) -> list[NarrationUnit]:
    """Ordered speakable units for one lesson: b-00-meta first (title +
    objectives), then every content block that has something speakable, in
    page order. Blocks with nothing speakable (diagrams without svg_texts,
    reveal blocks, empty prose) are simply absent - the availability flag
    for them is false by construction."""
    units: list[NarrationUnit] = []
    meta_parts = _meta_parts(lesson)
    if meta_parts:
        units.append(NarrationUnit("b-00-meta", "meta", tuple(meta_parts)))
    interactive = interactive or {}
    for block in blocks.get("blocks", []):
        parts = _block_parts(block, interactive.get(block.get("id"), {}))
        if parts:
            units.append(
                NarrationUnit(str(block["id"]), str(block["type"]), tuple(parts))
            )
    return units


def _meta_parts(lesson: dict[str, Any]) -> list[str]:
    """b-00-meta (GAP-015: metadata -> title + objectives)."""
    parts: list[str] = []
    title = str(lesson.get("title", "")).strip()
    if title:
        parts.append(title)
    for objective in lesson.get("objectives", []):
        text = str(objective).strip()
        if text:
            parts.append(text)
    return parts


def _block_parts(block: dict[str, Any], interactive_out: dict[str, Any]) -> list[str]:
    """GAP-015 per-type extraction. Returns [] when the block has nothing
    speakable."""
    btype, spec = block.get("type"), block.get("spec", {})
    if btype == "text":
        return [str(p).strip() for p in spec.get("paragraphs", []) if str(p).strip()]
    if btype == "worked_example":
        return _worked_example_parts(spec)
    if btype == "check":
        return _check_parts(spec)
    if btype in ("simulation", "animation"):
        return _simulation_parts(spec, interactive_out)
    if btype == "diagram":
        # svg_texts ONLY (the CP-TRN-002 payload shape: [{id, source}, ...]).
        # The caption and the SVG markup are never spoken.
        return [
            str(t.get("source", "")).strip()
            for t in spec.get("svg_texts", [])
            if str(t.get("source", "")).strip()
        ]
    # reveal and any future type: not speakable until GAP-015 says so.
    return []


def _worked_example_parts(spec: dict[str, Any]) -> list[str]:
    parts = ["Worked example"]
    problem = str(spec.get("problem", "")).strip()
    if problem:
        parts.append(problem)
    for step in spec.get("steps", []):
        title = str(step.get("title", "")).strip()
        detail = str(step.get("detail", "")).strip()
        if title:
            parts.append(title)
        if detail:
            parts.append(detail)
    answer = str(spec.get("answer", "")).strip()
    if answer:
        parts.append(f"The answer is: {answer}")
    return parts


def _check_parts(spec: dict[str, Any]) -> list[str]:
    """question + options; the answer, explanation and expected_understanding
    are excluded (nothing is read aloud until revealed - GAP-015)."""
    parts: list[str] = []
    question = str(spec.get("question", "")).strip()
    if question:
        parts.append(question)
    for option in spec.get("options", []):
        text = str(option).strip()
        if text:
            parts.append(text)
    return parts


def _simulation_parts(
    spec: dict[str, Any], interactive_out: dict[str, Any]
) -> list[str]:
    """title + description + page.js readout strings (never JS code). The
    readouts come from the 05-interactive output via the CP-TRN-003
    ctx.t_str("key", "fallback") pattern; pages that predate it simply have
    none (sim_strings defaults to {})."""
    parts: list[str] = []
    for field in ("title", "description"):
        text = str(spec.get(field, "")).strip()
        if text:
            parts.append(text)
    page_js = interactive_out.get("files", {}).get("page.js", "")
    for fallback in _T_STR_RE.findall(page_js):
        # Unescape the JSON string literal properly (\" \\ \n \uXXXX):
        # unicode_escape would mangle any non-ASCII fallback (Hindi readouts
        # would arrive as mojibake). A malformed escape skips the readout -
        # a corrupt canvas string never becomes narration.
        try:
            text = json.loads(f'"{fallback}"')
        except json.JSONDecodeError:
            continue
        text = text.strip()
        if text and _SPEAKABLE_RE.search(text):
            parts.append(text)
    return parts
