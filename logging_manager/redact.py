"""Redaction: the mechanical, in-module privacy guarantee (spec.md §4).

A-02 says transcripts are DB rows and structured logs carry no transcripts;
ADR-0011/0007 make learner identity pseudonymous. This module turns those
decisions into code that runs BEFORE any sink, on every event:

1. key denylist (hard-replace with `[REDACTED:key-denylist]`) — with the
   sanctioned reference fields allowed BEFORE the denylist is applied
   (`transcript_row_id` starts with "transcript" and is exactly the
   sanctioned way to log a transcript REFERENCE, never its words);
2. value regexes (scrub in place → `[REDACTED:<kind>]`) — applied to every
   string, including strings embedded inside arrays;
3. shape guard — field values are scalars or flat arrays of scalars
   (logging-api.md §4); a dict or a deeper structure cannot be redacted
   reliably, so it is replaced whole (`[REDACTED:shape]`) rather than
   stringified (a stringify would smuggle the very text this module exists
   to keep out).

Every action is returned to the caller as a (key, kind) violation record;
`log_event` turns those into `log.redaction_violation` events carrying only
{event_ref, key, kind} — enough to fix the call site, never the payload —
deduplicated per call site (first + every 100th).
"""

from __future__ import annotations

import re
from typing import Any

# Sanctioned reference fields (spec.md §4): checked BEFORE the denylist.
REFERENCE_FIELDS = frozenset(
    {"transcript_row_id", "artifact_path", "block_id", "topic", "chapter"}
)

# Key denylist (logging-api.md §6): exact matches (case-insensitive) plus
# prefix matches for the starred patterns (`*` = any suffix).
_KEY_DENYLIST_EXACT = frozenset(
    {
        "text",
        "content",
        "prompt",
        "messages",
        "response",
        "completion",
        "answer",
        "page_html",
        "code",
        "patch",
        "wav",
        "pcm",
        "cookie",
        "token",
        "secret",
        "key",
        "authorization",
    }
)
_KEY_DENYLIST_PREFIXES = ("transcript", "audio", "speech", "utterance")

REDACTED_KEY = "[REDACTED:key-denylist]"
REDACTED_SHAPE = "[REDACTED:shape]"

# Value regexes (spec.md §4.2). Order matters only for readability; every
# pattern replaces its hit with a [REDACTED:<kind>] marker.
_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    ),
    (
        "phone",
        re.compile(r"(?:(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d))"),
    ),
    (
        "aadhaar",
        re.compile(
            r"(?i)\b(?:aadhaa?r|uid)\s*(?:no\.?|number|:|#)?\s*"
            r"\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
        ),
    ),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")),
    ("api_key", re.compile(r"\bZIVON_[A-Za-z0-9_-]{20,}")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}"),
    ),
    ("base64", re.compile(r"[A-Za-z0-9+/]{513,}={0,2}")),
)


def key_is_denied(key: str) -> bool:
    """The §6 denylist test: reference fields first, then exact + prefix."""
    if key in REFERENCE_FIELDS:
        return False
    lowered = key.lower()
    if lowered in _KEY_DENYLIST_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in _KEY_DENYLIST_PREFIXES)


def redact_text(value: str) -> str:
    """Scrub one string in place (value regexes)."""
    for kind, pattern in _VALUE_PATTERNS:
        value = pattern.sub(f"[REDACTED:{kind}]", value)
    return value


def redact_fields(
    fields: dict[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Redact a `fields` payload. Returns (clean_fields, violations) where
    each violation is (key, kind) — kind is the denylist marker, a value
    regex kind, or `shape` for un-redactable structures.

    The input dict is never mutated.
    """
    clean: dict[str, Any] = {}
    violations: list[tuple[str, str]] = []
    for key, value in fields.items():
        if key_is_denied(str(key)):
            clean[str(key)] = REDACTED_KEY
            violations.append((str(key), "key-denylist"))
            continue
        clean_value, shape_hit = _redact_value(value)
        clean[str(key)] = clean_value
        if shape_hit:
            violations.append((str(key), "shape"))
    return clean, violations


def _redact_value(value: Any) -> tuple[Any, bool]:
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    if isinstance(value, str):
        return redact_text(value), False
    if isinstance(value, list):
        # Flat arrays of scalars only (logging-api.md §4): any dict/list item
        # is not expressible in the schema and cannot be redacted reliably.
        out: list[Any] = []
        for item in value:
            if isinstance(item, (dict, list)):
                return REDACTED_SHAPE, True
            clean_item, _ = _redact_value(item)
            out.append(clean_item)
        return out, False
    # dict / tuple / set / arbitrary objects: not expressible in the schema.
    return REDACTED_SHAPE, True
