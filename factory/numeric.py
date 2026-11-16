"""Deterministic numeric/unit verification for worked examples and checks (P4).

The 03-check model reviewer recomputes every worked example and numeric check,
but a model verdict is not a harness guarantee. This module recomputes the
machine-checkable subset with a hand-written arithmetic parser (never `eval`):

- numeric equality chains: `90 x 200 N = 18000 N` -> both sides evaluate and
  must agree (same unit token, or none on both sides);
- answers reproducible from the stated arithmetic: at least one computed value
  must match a stated answer value within tolerance.

Dimensional sanity is deliberately NOT enabled yet: the published pages quote
several quantities per explanation, so "which unit belongs to the answer" is
not deterministic without a stated-answer unit field. A wrong guess there is a
false blocker, which the brief forbids; the unit table below is the substrate
for the check once numeric answers carry a unit field.

Honesty rules (P4 brief, 2026-11-15): a hint that cannot be parsed is never a
fatal. Methods that are ambiguous (scientific notation, `sqrt()`, `times`,
symbolic algebra) are skipped and reported as unverifiable, so the review
never gains a false blocker. Only a provable arithmetic contradiction is
fatal/major.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

REL_TOL = 0.01
# Arithmetic contradictions get a wider band: generator text rounds to 2-3
# significant figures, and a rounded equality is not a wrong equation.
CONTRADICTION_TOL = 0.02

# Unicode operators the generator emits, normalized before parsing.
_OPERATOR_MAP = {
    "−": "-",
    "–": "-",
    "—": "-",
    "×": "*",
    "÷": "/",
    "·": "*",
    "⋅": "*",
}

# A conservative multiplication shorthand: a standalone "x" between numbers.
_X_TIMES_RE = re.compile(r"(?<=\d)\s*[xX]\s*(?=[\d(])")

# Scientific notation / physics constants we deliberately do not evaluate:
# "2.24 x 10-2", "6.022 x 1023", "10^3", "1e-10", "sqrt(...)", "pi".
_UNSAFE_EXPR_RE = re.compile(
    r"(?:\d\s*[xX*]\s*10(?:\d|\b)|\b10\s*[-−^]\s*\d|\b10\s*\*\*\s*\d|"
    r"\d[eE][-+]?\d{1,2}\b|\bsqrt\b|\bpi\b|\bπ\b|\bsquare root\b|\btimes\b)",
    re.IGNORECASE,
)

_EXPR_TOKEN_RE = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([-+*/^()]))")


def normalize_text(text: str) -> str:
    """Normalize operator glyphs and the `x` multiplication shorthand."""
    out = text
    for src, dst in _OPERATOR_MAP.items():
        out = out.replace(src, dst)
    return _X_TIMES_RE.sub(" * ", out)


@dataclass
class _Parser:
    """Recursive-descent arithmetic parser (numbers, + - * / ^, parentheses)."""

    text: str
    pos: int = 0

    def parse(self) -> float | None:
        try:
            value = self._expr()
            self._skip_ws()
            if self.pos != len(self.text):
                return None
            if not math.isfinite(value) or abs(value) > 1e12:
                return None
            return value
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str | None:
        self._skip_ws()
        return self.text[self.pos] if self.pos < len(self.text) else None

    def _expr(self) -> float:
        value = self._term()
        while True:
            op = self._peek()
            if op in ("+", "-"):
                self.pos += 1
                rhs = self._term()
                value = value + rhs if op == "+" else value - rhs
            else:
                return value

    def _term(self) -> float:
        value = self._power()
        while True:
            op = self._peek()
            if op in ("*", "/"):
                self.pos += 1
                rhs = self._power()
                value = value * rhs if op == "*" else value / rhs
            else:
                return value

    def _power(self) -> float:
        base = self._unary()
        if self._peek() == "^":
            self.pos += 1
            exponent = self._power()
            if abs(exponent) > 8:
                raise ValueError("exponent out of range")
            return base**exponent
        return base

    def _unary(self) -> float:
        op = self._peek()
        if op == "-":
            self.pos += 1
            return -self._unary()
        if op == "+":
            self.pos += 1
            return self._unary()
        return self._atom()

    def _atom(self) -> float:
        self._skip_ws()
        if self._peek() == "(":
            self.pos += 1
            value = self._expr()
            if self._peek() != ")":
                raise ValueError("unbalanced parenthesis")
            self.pos += 1
            return value
        match = re.match(r"\d+(?:\.\d+)?", self.text[self.pos :])
        if not match:
            raise ValueError("expected a number")
        self.pos += len(match.group(0))
        return float(match.group(0))


def evaluate(expr: str) -> float | None:
    """Evaluate a pure-arithmetic expression, or None when not evaluable.

    Deliberately refuses anything containing letters, function names,
    scientific notation or a comparison: an expression we cannot fully parse
    must never become evidence against the content.
    """
    text = normalize_text(expr).strip().rstrip(".,;:")
    if not text or not re.search(r"\d", text):
        return None
    if re.search(r"[A-Za-z]", text) or _UNSAFE_EXPR_RE.search(text):
        return None
    if not re.fullmatch(r"[\d\s.+\-*/^()]+", text):
        return None
    return _Parser(text).parse()


_RUN_RE = re.compile(r"(?<![A-Za-z0-9_])[-+(]*\d[\d\s.+\-*/^()]*")
_UNIT_AFTER_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9/\-^]*(?:\s+[A-Za-z0-9/\-^]+){0,2})"
)
_CLAUSE_SPLIT_RE = re.compile(
    r";|\.(?=\s|$)|,\s+(?=[A-Za-z])|"
    r"\b(?:so|then|giving|hence|thus|which|but|approx(?:imately)?)\b",
    re.IGNORECASE,
)


@dataclass
class Chain:
    """One `lhs = rhs` arithmetic statement found in a step or explanation."""

    lhs_text: str
    rhs_text: str
    lhs_value: float | None
    rhs_value: float | None
    lhs_unit: str
    rhs_unit: str
    evaluable: bool

    @property
    def agrees(self) -> bool:
        """True unless the two sides disagree by more than the rounding band."""
        if self.lhs_value is None or self.rhs_value is None:
            return True
        scale = max(1.0, abs(self.lhs_value), abs(self.rhs_value))
        return abs(self.lhs_value - self.rhs_value) <= CONTRADICTION_TOL * scale


def _close(a: float, b: float) -> bool:
    scale = max(1.0, abs(a), abs(b))
    return abs(a - b) <= REL_TOL * scale


def _normalize_unit(raw: str) -> str:
    unit = re.sub(r"\s+", "", normalize_text(raw or "")).lower()
    return unit.rstrip(".,;:")


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPERATOR_RE = re.compile(r"[+\-*/^]|\d\s*[()]")


def _clean_run(raw: str) -> str:
    text = raw.strip()
    while text and text[-1] in "+-*/^(":
        text = text[:-1].rstrip()
    return text


def _has_binary_operator(text: str) -> bool:
    """True when `text` computes something (a unary sign is not an operator)."""
    body = text.lstrip("+-").strip()
    return bool(re.search(r"[+\-*/^]|\d\s*[()]", body))


def _eval_run(raw: str) -> float | None:
    cleaned = _clean_run(raw)
    if not _has_binary_operator(cleaned):
        # A lone number is a value, never a computation.
        return None
    return evaluate(cleaned)


def _unit_after(tail: str) -> str | None:
    """The recognized unit after an expression.

    `""` = no unit at all; `None` = something trailing that is neither a unit
    nor punctuation (a variable like `a`/`t`, prose, or an unlisted unit).
    A chain with an unrecognized trailing token is not comparable: `30 - 8 =
    23a` must never be read as `22 = 23`.
    """
    match = _UNIT_AFTER_RE.match(tail)
    if not match:
        return ""
    unit = _normalize_unit(match.group(1))
    if unit and unit_dimension(unit) is None:
        return None
    return unit


def _left_side(fragment: str) -> tuple[float | None, str, str]:
    runs = list(_RUN_RE.finditer(fragment))
    if not runs:
        return None, "", ""
    match = runs[-1]
    prefix = fragment[: match.start()].strip()
    if ":" in prefix:
        # "Average speed is total distance / total time: 100 / 20" - the
        # label before the colon frames the computation, it is not part of it.
        prefix = prefix.rsplit(":", 1)[1].strip()
    if prefix and not _IDENTIFIER_RE.match(prefix):
        # Text before the computation ("x at 2.0 s", "tan inverse (4/3)")
        # means the number is a description, not a computed left-hand side.
        return None, "", ""
    value = _eval_run(match.group(0))
    if value is None:
        return None, "", ""
    unit = _unit_after(fragment[match.end() :])
    if unit is None:
        return None, "", ""
    return value, unit, _clean_run(match.group(0))


def _right_side(fragment: str) -> tuple[float | None, str, str]:
    values = list(_RUN_RE.finditer(fragment))
    if not values:
        return None, "", ""
    match = values[0]
    tail = fragment[match.end() :]
    unit = _unit_after(tail)
    if unit is None:
        return None, "", ""
    unit_match = _UNIT_AFTER_RE.match(tail)
    remainder = tail[unit_match.end() :] if unit_match else tail
    if re.search(r"[A-Za-z0-9]", remainder):
        # The right side keeps talking after the expression: a variable, a
        # second clause or prose - not a comparison we can trust.
        return None, "", ""
    cleaned = _clean_run(match.group(0))
    right_value: float | None
    if not _has_binary_operator(cleaned):
        # A lone number is allowed on the right: it is the stated result.
        try:
            right_value = float(cleaned)
        except ValueError:
            return None, "", ""
    else:
        right_value = evaluate(cleaned)
    if right_value is None:
        return None, "", ""
    return right_value, unit, cleaned


def _chain_at(fragment: str, eq_index: int) -> Chain | None:
    lhs_value, lhs_unit, lhs_text = _left_side(fragment[:eq_index])
    rhs_value, rhs_unit, rhs_text = _right_side(fragment[eq_index + 1 :])
    if lhs_value is None or rhs_value is None:
        return None
    if lhs_unit and rhs_unit and lhs_unit != rhs_unit:
        # A unit conversion (`0.5 h = 30 min`) is not an arithmetic claim.
        return None
    if _UNSAFE_EXPR_RE.search(f"{lhs_text} {rhs_text}"):
        return None
    return Chain(
        lhs_text=lhs_text,
        rhs_text=rhs_text,
        lhs_value=lhs_value,
        rhs_value=rhs_value,
        lhs_unit=lhs_unit,
        rhs_unit=rhs_unit,
        evaluable=True,
    )


def find_chains(text: str) -> list[Chain]:
    """Every evaluable `lhs = rhs` arithmetic statement in `text`."""
    normalized = normalize_text(text or "")
    chains: list[Chain] = []
    for clause in _CLAUSE_SPLIT_RE.split(normalized):
        eq_positions = [m.start() for m in re.finditer(r"=", clause)]
        for index, position in enumerate(eq_positions):
            start = eq_positions[index - 1] + 1 if index else 0
            end = (
                eq_positions[index + 1]
                if index + 1 < len(eq_positions)
                else len(clause)
            )
            chain = _chain_at(clause[start:end], position - start)
            if chain is not None:
                chains.append(chain)
    return chains


_VALUE_RE = re.compile(r"-?\d+(?:\.\d+)?")


def answer_values(answer_text: Any) -> list[float]:
    """Every numeric value stated in an answer string."""
    values: list[float] = []
    for match in _VALUE_RE.finditer(normalize_text(str(answer_text or ""))):
        try:
            value = float(match.group(0))
        except ValueError:
            continue
        if math.isfinite(value) and abs(value) <= 1e12:
            values.append(value)
    return values


# --------------------------------------------------------------------- units
# Dimension vectors are (length, mass, time) exponents. Only units that map
# unambiguously are listed; anything else is "unrecognized" and never checked.
_UNIT_DIMENSIONS: dict[str, tuple[float, float, float]] = {
    "m": (1, 0, 0),
    "cm": (1, 0, 0),
    "mm": (1, 0, 0),
    "km": (1, 0, 0),
    "metre": (1, 0, 0),
    "metres": (1, 0, 0),
    "meter": (1, 0, 0),
    "meters": (1, 0, 0),
    "s": (0, 0, 1),
    "min": (0, 0, 1),
    "h": (0, 0, 1),
    "hr": (0, 0, 1),
    "kg": (0, 1, 0),
    "g": (0, 1, 0),
    "m/s": (1, 0, -1),
    "km/h": (1, 0, -1),
    "ms-1": (1, 0, -1),
    "m/s2": (1, 0, -2),
    "m/s^2": (1, 0, -2),
    "ms-2": (1, 0, -2),
    "m/s²": (1, 0, -2),
    "n": (1, 1, -2),
    "ns": (1, 1, -1),
    "n s": (1, 1, -1),
    "kgm/s": (1, 1, -1),
    "j": (2, 1, -2),
    "w": (2, 1, -3),
    "hz": (0, 0, -1),
    "m2": (2, 0, 0),
    "m3": (3, 0, 0),
    "l": (3, 0, 0),
    "rad": (0, 0, 0),
    "degree": (0, 0, 0),
    "degrees": (0, 0, 0),
}

_UNIT_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(re.escape(u) for u in sorted(_UNIT_DIMENSIONS, key=len, reverse=True))
    + r")(?![A-Za-z])",
    re.IGNORECASE,
)


def unit_dimension(unit_text: str) -> tuple[float, float, float] | None:
    key = _normalize_unit(unit_text)
    if not key:
        return None
    return _UNIT_DIMENSIONS.get(key)


def find_unit(text: str) -> str:
    """The longest recognized unit token in `text` ('' when none)."""
    match = _UNIT_TOKEN_RE.search(normalize_text(text or ""))
    return match.group(1) if match else ""


# ------------------------------------------------------------ per-block checks
@dataclass
class BlockNumericResult:
    block_id: str | None
    kind: str  # "numeric_check" | "worked_example"
    checked: bool
    verified: bool
    issues: list[dict[str, Any]] = field(default_factory=list)


def _numeric_check_issues(block: dict[str, Any]) -> BlockNumericResult:
    spec = block.get("spec") or {}
    block_id = block.get("id")
    answer = answer_values(spec.get("answer"))
    if not answer:
        return BlockNumericResult(block_id, "numeric_check", False, False)
    texts = [str(spec.get("question") or ""), str(spec.get("explanation") or "")]
    chains = [c for text in texts for c in find_chains(text)]
    issues: list[dict[str, Any]] = []
    contradictions = [c for c in chains if c.evaluable and not c.agrees]
    for chain in contradictions:
        issues.append(
            _issue(
                block_id,
                "fatal",
                "numeric_recompute",
                f"arithmetic does not hold: {chain.lhs_text} = {chain.rhs_text} "
                f"(left evaluates to {chain.lhs_value:g}, right to "
                f"{chain.rhs_value:g})",
            )
        )
    values = [
        value
        for chain in chains
        for value in (chain.lhs_value, chain.rhs_value)
        if value is not None
    ]
    if answer and any(_close(value, target) for value in values for target in answer):
        return BlockNumericResult(
            block_id, "numeric_check", True, not contradictions, issues
        )
    if contradictions:
        return BlockNumericResult(block_id, "numeric_check", True, False, issues)
    issues.append(
        _issue(
            block_id,
            "minor",
            "numeric_recompute",
            "unverified: numeric answer could not be recomputed from the stated "
            "working (no purely arithmetic equality reproduces it)",
        )
    )
    return BlockNumericResult(block_id, "numeric_check", False, False, issues)


def _worked_example_issues(block: dict[str, Any]) -> BlockNumericResult:
    spec = block.get("spec") or {}
    block_id = block.get("id")
    answer = answer_values(spec.get("answer"))
    steps = spec.get("steps") or []
    texts = [str(spec.get("problem") or "")]
    for step in steps:
        if isinstance(step, dict):
            texts.append(str(step.get("detail") or ""))
    chains = [c for text in texts for c in find_chains(text)]
    issues: list[dict[str, Any]] = []

    # Provable arithmetic contradictions: both sides evaluate, the unit
    # tokens agree (or only one side states one), and the values differ.
    contradictions = [c for c in chains if c.evaluable and not c.agrees]
    for chain in contradictions:
        issues.append(
            _issue(
                block_id,
                "fatal",
                "numeric_recompute",
                f"arithmetic does not hold: {chain.lhs_text} = {chain.rhs_text} "
                f"(left evaluates to {chain.lhs_value:g}, right to "
                f"{chain.rhs_value:g})",
            )
        )
    if contradictions:
        return BlockNumericResult(block_id, "worked_example", True, False, issues)

    values = [
        value
        for chain in chains
        for value in (chain.lhs_value, chain.rhs_value)
        if value is not None
    ]
    if answer and any(_close(value, target) for value in values for target in answer):
        return BlockNumericResult(block_id, "worked_example", True, True)
    issues.append(
        _issue(
            block_id,
            "minor",
            "numeric_recompute",
            "unverified: worked_example answer is not reproduced by a purely "
            "arithmetic step (symbolic, multi-part or scientific-notation "
            "working) - 03-check's reviewer recompute remains authoritative",
        )
    )
    return BlockNumericResult(block_id, "worked_example", False, False, issues)


def _issue(block_id: Any, severity: str, rule: str, message: str) -> dict[str, Any]:
    """Issue dict in the shape factory.checks.run_all_rules already emits."""
    from .issue_categories import categorize

    return {
        "block_id": block_id,
        "severity": severity,
        "rule": rule,
        "category": categorize(rule),
        "message": message,
    }


def recompute_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Report for every worked example / numeric check on the page.

    Returns the issue list plus an honest coverage summary: `checked` counts
    blocks the rule could actually verify, `unverifiable` counts the ones the
    way-out rule reported as `unverified:`.
    """
    results: list[BlockNumericResult] = []
    issues: list[dict[str, Any]] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "worked_example":
            result = _worked_example_issues(block)
        elif btype == "check" and (block.get("spec") or {}).get("format") == "numeric":
            result = _numeric_check_issues(block)
        else:
            continue
        results.append(result)
        issues.extend(result.issues)
    return {
        "issues": issues,
        "blocks": len(results),
        "checked": sum(1 for r in results if r.checked),
        "verified": sum(1 for r in results if r.verified),
        "unverifiable": sum(
            1
            for r in results
            if not r.verified
            and any(
                str(i.get("message", "")).startswith("unverified:") for i in r.issues
            )
        ),
    }
