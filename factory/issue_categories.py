"""Deterministic issue-category mapping for the run ledgers (P4, 2026-11-15).

The 09-review model tags every issue with a category from
`factory.schemas.REVIEW_CATEGORIES`; 03-check issues and the code-side rule
issues do not carry one. Without a category the ledger aggregates everything
as `other`/`content`, which hides the failure classes prompting should target.

This module is the single mapping: a code rule id (or an eval `DET-*` check id)
maps to exactly one ledger category, deterministically, with no model call.
`factory/ledger.py` consults it for issues that arrive without a category and
`scripts/issue_report.py` uses the same table to normalize historical rows, so
old and new ledgers group the same way.

`LEDGER_CATEGORIES` is a SUPERSET of `factory.schemas.REVIEW_CATEGORIES`: the
model-review vocabulary is kept verbatim (so a 09-review issue always keeps
its own category), plus the code-side-only classes `content`, `numeric` and
`glossary`. Additions here are additive; a removal would silently re-label
history, so don't.
"""

from __future__ import annotations

from typing import Any

# Model-review categories (verbatim copy of factory.schemas.REVIEW_CATEGORIES;
# kept in sync by testing/content_factory/unit/test_issue_categories.py).
MODEL_REVIEW_CATEGORIES: tuple[str, ...] = (
    "answer_key",
    "fact",
    "drawn_behaviour",
    "inconsistency",
    "visual_language",
    "frame",
    "accessibility",
    "rendering",
    "concept_map",
    "other",
)

# Code-side-only ledger classes.
CODE_CATEGORIES: tuple[str, ...] = ("content", "numeric", "glossary")

LEDGER_CATEGORIES: tuple[str, ...] = MODEL_REVIEW_CATEGORIES + CODE_CATEGORIES

DEFAULT_CATEGORY = "other"

# Rule id -> ledger category. Rule ids are the stable names carried on the
# issue dict's "rule" key (factory/checks.py) or the eval check id
# ("check_id", DET-*). Keep this table exhaustive for the rules that exist;
# an unmapped id falls back to the issue's own category, then the stage
# default.
RULE_CATEGORY: dict[str, str] = {
    # factory/checks.py code rules
    "shape": "content",
    "answer_key": "answer_key",
    "citations": "fact",
    "self_containment": "content",
    "numbers": "fact",
    "numeric_recompute": "numeric",
    "glossary_coverage": "glossary",
    "diagram_svg": "visual_language",
    # factory/review.py static pass (its issues already carry a category)
    "static_review": "rendering",
    # eval deterministic check ids (evals/checkers/**)
    "DET-CUR01-PROVENANCE": "fact",
    "DET-CUR01-TABLE-GLYPHS": "content",
    "DET-CUR01-CITATIONS": "fact",
    "DET-SYN01-SCHEMA": "content",
    "DET-SYN01-ORDER-AND-RULES": "content",
    "DET-SYN01-GEOMETRY-ROUTING": "rendering",
    "DET-SYN02-SELF-CONTAINMENT": "content",
    "DET-SYN02-ANSWER-KEYS": "answer_key",
    "DET-SYN02-READABILITY": "content",
    "DET-SYN03-NUMERIC-RECOMPUTE": "numeric",
    "DET-SYN03-WAY-OUT": "numeric",
    "DET-SYN03-UNITS": "numeric",
    "DET-VIS01-LINTS-AND-SCOPE": "rendering",
    "DET-VIS01-COMPUTED-SIM-LOOPS": "drawn_behaviour",
    "DET-VIS01-DOM-AND-A11Y": "accessibility",
    "DET-VIS02-A11Y-STATIC": "accessibility",
    "DET-VIS02-A11Y-AXE": "accessibility",
    "DET-PERF01-BUDGET-GATE": "frame",
    "DET-PERF01-PEDAGOGY-GUARD": "drawn_behaviour",
    "DET-REV02-SECURITY-DEFECTS": "rendering",
    "DET-E2E01-PUBLISHED-INTEGRITY": "rendering",
    "DET-E2E02-CATALOGUE-INTEGRITY": "rendering",
    "DET-E2E02-GLOSSARY-COVERAGE": "glossary",
    "DET-E2E02-GLOSSARY-LAUNCH": "glossary",
    "DET-KID01-GATE-B-COHORT": "content",
}

# Prefix fallbacks for ids not listed above (keeps a new check from silently
# landing in "other" when its family is obvious).
_RULE_PREFIX_CATEGORY: tuple[tuple[str, str], ...] = (
    ("DET-VIS02-", "accessibility"),
    ("DET-SYN03-", "numeric"),
    ("DET-PERF", "frame"),
    ("DET-E2E02-", "rendering"),
    ("DET-E2E01-", "rendering"),
)

# Shorthands the model reviewer has used in the wild, normalized to the
# closed vocabulary instead of being counted as a separate class.
_CATEGORY_ALIASES: dict[str, str] = {
    "answerkey": "answer_key",
    "answer-key": "answer_key",
    "drawing": "drawn_behaviour",
    "visual": "visual_language",
    "layout": "frame",
    "a11y": "accessibility",
    "unit": "numeric",
    "units": "numeric",
    "math": "numeric",
    "translation": "content",
}


def categorize(rule_id: str | None) -> str | None:
    """The ledger category for a rule/check id, or None when unmapped."""
    if not rule_id:
        return None
    key = str(rule_id).strip()
    if key in RULE_CATEGORY:
        return RULE_CATEGORY[key]
    for prefix, category in _RULE_PREFIX_CATEGORY:
        if key.upper().startswith(prefix):
            return category
    return None


def normalize_category(raw: Any) -> str | None:
    """Coerce an issue's own category into the closed ledger vocabulary.

    Unknown strings are NOT silently dropped to `other` here - the caller
    decides the fallback (a model category outside the enum is a schema bug
    worth seeing, not worth crashing a report over).
    """
    if not raw:
        return None
    value = str(raw).strip().lower().replace(" ", "_")
    if value in LEDGER_CATEGORIES:
        return value
    return _CATEGORY_ALIASES.get(value)


def issue_category(issue: dict[str, Any], default: str = DEFAULT_CATEGORY) -> str:
    """Category for one issue dict, by precedence:

    1. the issue's own category when it is in the closed vocabulary (model
       reviewer output keeps its class verbatim),
    2. the deterministic rule/check-id mapping,
    3. an alias-normalized category,
    4. the caller's stage default.
    """
    explicit = normalize_category(issue.get("category"))
    if explicit is not None:
        return explicit
    for key in ("rule", "check_id", "rule_id"):
        mapped = categorize(issue.get(key))
        if mapped is not None:
            return mapped
    return default
