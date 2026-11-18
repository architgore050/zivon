"""Account personal-instructions store (C22, data-and-api.md §2.1/§4.3).

One `user_preferences` row per account, created lazily on first save. Every
save/clear bumps `instructions_version` (cache-busting); clear keeps the row
with `personal_instructions = NULL`; deletion cascades with the account
(ADR-0029) and the row rides in the account export. Validation happens before
any write, so a rejected save leaves the previous value untouched.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ..logging_shim import log_event
from .personalization import (
    MAX_INSTRUCTION_CHARS,
    Personalization,
    personal_block,
    validate_instructions,
)

if TYPE_CHECKING:
    from db.engine import DatabaseEngine

_PREFERENCES_CACHE_TTL_S = 60.0  # §5.1: load once per session, 60 s staleness bound


def _utc_now_iso() -> str:
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def get_preferences_row(db: DatabaseEngine, user_id: str) -> dict[str, Any] | None:
    """Return the raw `user_preferences` row, or None when never saved."""
    return db.fetchone(
        """
        SELECT user_id, personal_instructions, instructions_version,
               created_at, updated_at
        FROM user_preferences WHERE user_id = ?
        """,
        (user_id,),
    )


def get_preferences(
    db: DatabaseEngine, user_id: str, *, available: bool = True
) -> dict[str, Any]:
    """API-PL-01 payload: instructions + max length + availability."""
    row = get_preferences_row(db, user_id)
    value = row.get("personal_instructions") if row else None
    return {
        "personal_instructions": value,
        "max_chars": MAX_INSTRUCTION_CHARS,
        "updated_at": row.get("updated_at") if row else None,
        "available": available,
    }


def save_preferences(
    db: DatabaseEngine,
    user_id: str,
    raw_text: str,
    *,
    now_dt: Any = None,
) -> dict[str, Any]:
    """API-PL-02: normalize + validate, then upsert with a version bump.

    An empty normalized value saves as NULL (a save-shaped clear) and still
    bumps the version. Raises `PreferencesRejected` before any write.
    """
    del now_dt  # the timestamp comes from the DB clock helper below
    normalized = validate_instructions(raw_text)
    now = _utc_now_iso()
    value: str | None = normalized or None
    db.execute(
        """
        INSERT INTO user_preferences (
            user_id, personal_instructions, instructions_version, created_at, updated_at
        ) VALUES (?, ?, 1, ?, ?)
        ON CONFLICT (user_id) DO UPDATE SET
            personal_instructions = excluded.personal_instructions,
            instructions_version = user_preferences.instructions_version + 1,
            updated_at = excluded.updated_at
        """,
        (user_id, value, now, now),
    )
    log_event(
        "personalized.prefs.saved",
        {"char_count": len(normalized), "cleared": value is None},
    )
    return get_preferences(db, user_id)


def clear_preferences(db: DatabaseEngine, user_id: str, *, now_dt: Any = None) -> None:
    """API-PL-03: clear (idempotent — no row is a no-op, still 204)."""
    del now_dt
    row = get_preferences_row(db, user_id)
    if row is None:
        return
    db.execute(
        """
        UPDATE user_preferences
        SET personal_instructions = NULL,
            instructions_version = instructions_version + 1,
            updated_at = ?
        WHERE user_id = ?
        """,
        (_utc_now_iso(), user_id),
    )
    log_event("personalized.prefs.cleared", {})


def build_voice_preferences_resolver(
    auth: Any,
    db: DatabaseEngine,
    *,
    cache_ttl_s: float = _PREFERENCES_CACHE_TTL_S,
    clock: Any = None,
) -> Any:
    """Resolver injected into `voice.VoiceApp.preferences_for` (§5.1).

    Given the raw account cookie, resolve it with `AuthService.resolve`, load
    the instructions once per session (60 s cache bounds the staleness), and
    return the sanitized `Personalization`. Guests and cleared accounts get an
    empty block, so the assembled prompt stays byte-identical to pre-PL1.
    Storage/auth failures propagate: `voice/ws_api.py` catches them, keeps the
    session working without the block, and logs a count — never the error text.
    """
    monotonic = clock if clock is not None else time.monotonic
    cache: dict[str, tuple[float, str]] = {}

    def resolve(raw_cookie: str | None) -> Personalization:
        if not raw_cookie:
            return Personalization()
        ctx = auth.resolve(raw_cookie)
        if ctx is None:
            return Personalization()
        user_id = str(ctx.user["user_id"])
        now = monotonic()
        cached = cache.get(user_id)
        if cached is not None and now < cached[0]:
            return Personalization(user_id, cached[1])
        row = get_preferences_row(db, user_id)
        text = row.get("personal_instructions") if row else None
        block = personal_block(text)
        cache[user_id] = (now + cache_ttl_s, block)
        return Personalization(user_id, block)

    return resolve
