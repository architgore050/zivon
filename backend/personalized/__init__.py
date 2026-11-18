"""Personalized learning backend (W5.5 PL1 data/auth/preferences/quota).

Owns the persistence and non-model API surface of
`docs/specs/personalized-learning/data-and-api.md`: the 0005 tables, the
preferences store, owner-scoped session/message storage, the free-tier quota
counters, retention, and the shared personal-instructions helper used by both
the personalized path and the voice tutor injection. The teaching turn itself
stays a `503 E-PL-MODEL-DOWN` stub until PL2 wires the `TurnEngine`.
"""

from __future__ import annotations

from .personalization import (
    SAFETY_CORE,
    Personalization,
    assert_safety_parity,
    normalize_instructions,
    personal_block,
    validate_instructions,
)
from .preferences import (
    clear_preferences,
    get_preferences,
    get_preferences_row,
    save_preferences,
)

__all__ = [
    "SAFETY_CORE",
    "Personalization",
    "assert_safety_parity",
    "clear_preferences",
    "get_preferences",
    "get_preferences_row",
    "normalize_instructions",
    "personal_block",
    "save_preferences",
    "validate_instructions",
]
