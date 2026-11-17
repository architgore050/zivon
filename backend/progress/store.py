"""Persistence and validation for progress events and bookmarks (F3).

Every write here is user-scoped and bounded. The API accepts five study event
kinds from a client; the two bookmark kinds are emitted only by the bookmark
endpoints so a client cannot claim a save it did not make.

Payloads are an allowlist, not free-form JSON: a key the kind does not declare
is rejected, strings are accepted only for ids and the `source` enum, numbers
are range-checked, and nested values are rejected. That keeps the table free
of child free text (REQUIREMENTS §11: IDs, not names).
"""

from __future__ import annotations

import datetime
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from db.engine import DatabaseEngine
from db.uuid7 import uuid7_str

EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "lesson_block_view",
        "lesson_complete",
        "practice_answer",
        "test_submit",
        "speaking_attempt",
        "bookmark_add",
        "bookmark_remove",
    }
)
CLIENT_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "lesson_block_view",
        "lesson_complete",
        "practice_answer",
        "test_submit",
        "speaking_attempt",
    }
)
BOOKMARK_TARGET_TYPES: Final[frozenset[str]] = frozenset(
    {"chapter", "concept", "block", "question"}
)
SOURCE_VALUES: Final[frozenset[str]] = frozenset({"lesson_shell", "merge"})

EVENTS_BATCH_MAX: Final[int] = 40
EVENTS_READ_LIMIT: Final[int] = 5000

_CHAPTER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,119}$")
_TARGET_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9/_:.\-]{0,159}$")
_OBJECT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,119}$"
)
_SECTION_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

_PAYLOAD_KEYS: Final[dict[str, frozenset[str]]] = {
    "lesson_block_view": frozenset(
        {"section_id", "blocks_seen", "blocks_total", "max_scroll_pct", "source"}
    ),
    "lesson_complete": frozenset(
        {"sections_seen", "sections_total", "max_scroll_pct", "source"}
    ),
    "practice_answer": frozenset({"correct", "hints_used", "time_ms", "source"}),
    "test_submit": frozenset({"correct", "answered", "total", "score", "source"}),
    "speaking_attempt": frozenset({"score", "source"}),
}


class ProgressValidationError(ValueError):
    """One event or bookmark is malformed; the API rejects just that item."""

    def __init__(self, code: str = "E-EVT-SCHEMA") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EventInput:
    """A validated event ready to be written."""

    kind: str
    chapter_id: str
    concept_id: str | None
    question_id: str | None
    payload: dict[str, Any]
    occurred_at: datetime.datetime


@dataclass(frozen=True)
class EventRow:
    """A stored `progress_event` row with its JSON payload decoded."""

    event_id: str
    kind: str
    chapter_id: str | None
    concept_id: str | None
    question_id: str | None
    payload: dict[str, Any]
    created_at: datetime.datetime


def utc_now() -> datetime.datetime:
    """Return the current UTC time (one seam for tests and callers)."""
    return datetime.datetime.now(datetime.UTC)


def to_iso(value: datetime.datetime) -> str:
    """Serialize an aware datetime the same way every backend row does."""
    normalized = value.astimezone(datetime.UTC)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{normalized.microsecond // 1000:03d}Z"
    )


def as_utc(value: object) -> datetime.datetime | None:
    """Parse a stored timestamp (TEXT on SQLite, datetime on PostgreSQL)."""
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value.astimezone(datetime.UTC)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def validate_event(
    raw: Mapping[str, Any],
    *,
    now: datetime.datetime | None = None,
) -> EventInput:
    """Validate one client event; raise `ProgressValidationError` on a defect."""
    kind = str(raw.get("kind") or "").strip()
    if kind not in CLIENT_EVENT_KINDS:
        raise ProgressValidationError()
    chapter_id = _chapter_id(raw.get("chapter_id"))
    concept_id = _object_id(raw.get("concept_id"), required=False)
    question_id = _object_id(raw.get("question_id"), required=False)
    payload = _payload(kind, raw.get("payload"))
    occurred = _occurred_at(raw.get("occurred_at"), now or utc_now())
    return EventInput(
        kind=kind,
        chapter_id=chapter_id,
        concept_id=concept_id,
        question_id=question_id,
        payload=payload,
        occurred_at=occurred,
    )


def validate_chapter_id(value: object) -> str:
    """Return a normalized chapter id or raise `ProgressValidationError`."""
    return _chapter_id(value)


def validate_bookmark_target(target_type: str, target_id: str) -> None:
    """Reject a bookmark whose type or target id is not a known shape."""
    if target_type not in BOOKMARK_TARGET_TYPES:
        raise ProgressValidationError()
    cleaned = str(target_id or "").strip()
    if not _TARGET_ID_RE.match(cleaned):
        raise ProgressValidationError()
    if target_type == "chapter":
        _chapter_id(cleaned)
        return
    chapter_id, _, rest = cleaned.partition(":")
    if not rest:
        raise ProgressValidationError()
    _chapter_id(chapter_id)
    if target_type == "block" and not _SECTION_ID_RE.match(rest):
        raise ProgressValidationError()
    if not _OBJECT_ID_RE.match(rest):
        raise ProgressValidationError()


def record_events(
    db: DatabaseEngine,
    user_id: str,
    events: Iterable[EventInput],
) -> int:
    """Insert validated events atomically and update the chapter counters."""
    accepted = 0
    with db.transaction() as tx:
        for event in events:
            tx.execute(
                """
                INSERT INTO progress_event (
                    event_id, user_id, kind, chapter_id, concept_id,
                    question_id, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid7_str(),
                    user_id,
                    event.kind,
                    event.chapter_id,
                    event.concept_id,
                    event.question_id,
                    json.dumps(event.payload, separators=(",", ":")),
                    to_iso(event.occurred_at),
                ),
            )
            if event.kind in ("lesson_block_view", "lesson_complete"):
                _upsert_lesson_progress(tx, user_id, event)
            accepted += 1
    return accepted


def _upsert_lesson_progress(tx: Any, user_id: str, event: EventInput) -> None:
    row = tx.fetchone(
        """
        SELECT chapter_id, status, last_block_id, blocks_seen, blocks_total,
               updated_at, completed_at
        FROM lesson_progress
        WHERE user_id = ? AND chapter_id = ?
        """,
        (user_id, event.chapter_id),
    )
    existing_updated = as_utc(row.get("updated_at")) if row else None
    payload = event.payload
    completed = event.kind == "lesson_complete" or (
        bool(row) and str(row.get("status")) == "completed"
    )
    updated = max(
        [value for value in (existing_updated, event.occurred_at) if value],
    )
    completed_at = row.get("completed_at") if row else None
    if event.kind == "lesson_complete" and not completed_at:
        completed_at = to_iso(event.occurred_at)
    last_block_id = row.get("last_block_id") if row else None
    if payload.get("section_id") and (
        existing_updated is None or event.occurred_at >= existing_updated
    ):
        last_block_id = str(payload["section_id"])
    blocks_seen = int(row.get("blocks_seen") or 0) if row else 0
    seen_value = read_count(payload, event.kind)
    if isinstance(seen_value, int):
        blocks_seen = max(blocks_seen, seen_value)
    blocks_total = int(row["blocks_total"]) if row and row.get("blocks_total") else None
    total_value = total_count(payload, event.kind)
    if isinstance(total_value, int) and total_value > 0:
        blocks_total = total_value
    status = "completed" if completed else "in_progress"
    if row:
        tx.execute(
            """
            UPDATE lesson_progress
            SET status = ?, last_block_id = ?, blocks_seen = ?,
                blocks_total = ?, updated_at = ?, completed_at = ?
            WHERE user_id = ? AND chapter_id = ?
            """,
            (
                status,
                last_block_id,
                blocks_seen,
                blocks_total,
                to_iso(updated or event.occurred_at),
                completed_at,
                user_id,
                event.chapter_id,
            ),
        )
    else:
        tx.execute(
            """
            INSERT INTO lesson_progress (
                user_id, chapter_id, status, last_block_id, blocks_seen,
                blocks_total, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                event.chapter_id,
                status,
                last_block_id,
                blocks_seen,
                blocks_total,
                to_iso(updated or event.occurred_at),
                completed_at,
            ),
        )


def read_count(payload: Mapping[str, Any], kind: str) -> int | None:
    """The absolute "how far in" count a lesson event reports.

    `lesson_block_view` reports `blocks_seen`; `lesson_complete` reports the
    same fact as `sections_seen` (the surfaces label the stored counter
    "sections read"). The caller keeps the maximum, so a stale merge cannot
    lower it.
    """
    value = payload.get("sections_seen" if kind == "lesson_complete" else "blocks_seen")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def total_count(payload: Mapping[str, Any], kind: str) -> int | None:
    """The absolute chapter total the event reports, if it reports one."""
    value = payload.get(
        "sections_total" if kind == "lesson_complete" else "blocks_total"
    )
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def list_events(
    db: DatabaseEngine, user_id: str, *, limit: int = EVENTS_READ_LIMIT
) -> list[EventRow]:
    """Return the most recent events for one account, newest first."""
    rows = db.fetchall(
        """
        SELECT event_id, kind, chapter_id, concept_id, question_id, payload,
               created_at
        FROM progress_event
        WHERE user_id = ?
        ORDER BY created_at DESC, event_id DESC
        LIMIT ?
        """,
        (user_id, int(limit)),
    )
    events: list[EventRow] = []
    for row in rows:
        created = as_utc(row.get("created_at"))
        if created is None:
            continue
        events.append(
            EventRow(
                event_id=str(row["event_id"]),
                kind=str(row["kind"]),
                chapter_id=row.get("chapter_id"),
                concept_id=row.get("concept_id"),
                question_id=row.get("question_id"),
                payload=_load_payload(row.get("payload")),
                created_at=created,
            )
        )
    return events


def list_lesson_progress(db: DatabaseEngine, user_id: str) -> list[dict[str, Any]]:
    """Return the per-chapter counters used by the continue card."""
    return db.fetchall(
        """
        SELECT chapter_id, status, last_block_id, blocks_seen, blocks_total,
               updated_at, completed_at
        FROM lesson_progress
        WHERE user_id = ?
        ORDER BY updated_at DESC
        """,
        (user_id,),
    )


def add_bookmark(
    db: DatabaseEngine,
    user_id: str,
    target_type: str,
    target_id: str,
    *,
    now: datetime.datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Save a bookmark idempotently; return `(row, created)`."""
    validate_bookmark_target(target_type, target_id)
    created_at = to_iso(now or utc_now())
    with db.transaction() as tx:
        existing = tx.fetchone(
            """
            SELECT bookmark_id, target_type, target_id, created_at
            FROM bookmark
            WHERE user_id = ? AND target_type = ? AND target_id = ?
            """,
            (user_id, target_type, target_id),
        )
        if existing:
            return _bookmark_public(existing), False
        bookmark_id = uuid7_str()
        tx.execute(
            """
            INSERT INTO bookmark (
                bookmark_id, user_id, target_type, target_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (bookmark_id, user_id, target_type, target_id, created_at),
        )
        _record_bookmark_event(
            tx, user_id, "bookmark_add", target_type, target_id, created_at
        )
        return (
            {
                "bookmark_id": bookmark_id,
                "target_type": target_type,
                "target_id": target_id,
                "created_at": created_at,
            },
            True,
        )


def remove_bookmark(
    db: DatabaseEngine,
    user_id: str,
    target_type: str,
    target_id: str,
    *,
    now: datetime.datetime | None = None,
) -> bool:
    """Delete a bookmark if it exists; return whether a row was removed."""
    validate_bookmark_target(target_type, target_id)
    with db.transaction() as tx:
        existing = tx.fetchone(
            """
            SELECT bookmark_id FROM bookmark
            WHERE user_id = ? AND target_type = ? AND target_id = ?
            """,
            (user_id, target_type, target_id),
        )
        if not existing:
            return False
        tx.execute(
            "DELETE FROM bookmark WHERE bookmark_id = ?",
            (str(existing["bookmark_id"]),),
        )
        _record_bookmark_event(
            tx,
            user_id,
            "bookmark_remove",
            target_type,
            target_id,
            to_iso(now or utc_now()),
        )
    return True


def list_bookmarks(db: DatabaseEngine, user_id: str) -> list[dict[str, Any]]:
    """Return the account's bookmarks, newest first."""
    rows = db.fetchall(
        """
        SELECT bookmark_id, target_type, target_id, created_at
        FROM bookmark
        WHERE user_id = ?
        ORDER BY created_at DESC, bookmark_id DESC
        """,
        (user_id,),
    )
    return [_bookmark_public(row) for row in rows]


def _record_bookmark_event(
    tx: Any,
    user_id: str,
    kind: str,
    target_type: str,
    target_id: str,
    created_at: str,
) -> None:
    chapter_id, _, rest = target_id.partition(":")
    concept_id = rest if target_type == "concept" else None
    question_id = rest if target_type == "question" else None
    tx.execute(
        """
        INSERT INTO progress_event (
            event_id, user_id, kind, chapter_id, concept_id,
            question_id, payload, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid7_str(),
            user_id,
            kind,
            chapter_id if chapter_id else target_id,
            concept_id,
            question_id,
            "{}",
            created_at,
        ),
    )


def _bookmark_public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "bookmark_id": str(row["bookmark_id"]),
        "target_type": str(row["target_type"]),
        "target_id": str(row["target_id"]),
        "created_at": to_iso(as_utc(row.get("created_at")) or utc_now()),
    }


def _chapter_id(value: object) -> str:
    cleaned = str(value or "").strip()
    if not _CHAPTER_ID_RE.match(cleaned):
        raise ProgressValidationError()
    return cleaned


def _object_id(value: object, *, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise ProgressValidationError()
        return None
    cleaned = str(value).strip()
    if not _OBJECT_ID_RE.match(cleaned):
        raise ProgressValidationError()
    return cleaned


def _payload(kind: str, value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProgressValidationError()
    allowed = _PAYLOAD_KEYS[kind]
    payload: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            raise ProgressValidationError()
        payload[str(key)] = _payload_value(str(key), item)
    if (
        kind == "practice_answer"
        and "correct" in payload
        and not isinstance(payload["correct"], bool)
    ):
        raise ProgressValidationError()
    if (
        kind == "test_submit"
        and "correct" in payload
        and (
            isinstance(payload["correct"], bool)
            or not isinstance(payload["correct"], int)
        )
    ):
        raise ProgressValidationError()
    return payload


def _payload_value(key: str, value: object) -> Any:
    if value is None:
        return None
    if key == "source":
        if not isinstance(value, str) or value not in SOURCE_VALUES:
            raise ProgressValidationError()
        return value
    if key == "section_id":
        if not isinstance(value, str) or not _SECTION_ID_RE.match(value):
            raise ProgressValidationError()
        return value
    if isinstance(value, bool):
        if key != "correct":
            raise ProgressValidationError()
        return value
    if isinstance(value, int):
        return _bounded_int(key, value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProgressValidationError()
        return _bounded_number(key, value)
    raise ProgressValidationError()


def _bounded_int(key: str, value: int) -> int:
    minimum, maximum = _BOUNDS.get(key, (0, 10_000))
    if value < minimum or value > maximum:
        raise ProgressValidationError()
    return value


def _bounded_number(key: str, value: float) -> float:
    minimum, maximum = _BOUNDS.get(key, (0.0, 100.0))
    if value < minimum or value > maximum:
        raise ProgressValidationError()
    return value


_BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "blocks_seen": (0, 10_000),
    "blocks_total": (0, 10_000),
    "sections_seen": (0, 10_000),
    "sections_total": (0, 10_000),
    "max_scroll_pct": (0, 100),
    "hints_used": (0, 20),
    "time_ms": (0, 3_600_000),
    "correct": (0, 1000),
    "answered": (0, 1000),
    "total": (0, 1000),
    "score": (0, 100),
}


def _occurred_at(value: object, now: datetime.datetime) -> datetime.datetime:
    """Use the client time when it is sane, otherwise the server receipt time."""
    raw = str(value or "").strip()
    if not raw:
        return now
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    parsed = parsed.astimezone(datetime.UTC)
    if parsed < datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC):
        return now
    if parsed > now + datetime.timedelta(minutes=5):
        return now
    return parsed


def _load_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


__all__ = [
    "BOOKMARK_TARGET_TYPES",
    "CLIENT_EVENT_KINDS",
    "EVENTS_BATCH_MAX",
    "EVENTS_READ_LIMIT",
    "EVENT_KINDS",
    "EventInput",
    "EventRow",
    "ProgressValidationError",
    "add_bookmark",
    "as_utc",
    "list_bookmarks",
    "list_events",
    "list_lesson_progress",
    "record_events",
    "remove_bookmark",
    "to_iso",
    "utc_now",
    "validate_bookmark_target",
    "validate_chapter_id",
    "validate_event",
]
