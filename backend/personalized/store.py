"""Owner-scoped personalized session/message storage (C23, data-and-api.md §2.2/§2.3).

Every query derives the owner from the validated account session and filters
by `user_id` — a route that bypasses these helpers is a review blocker
(security-privacy.md §4.4). Another user's id is `None` (the routes render
`404 E-NOT-FOUND`, never 403: no existence oracle). Messages are append-only:
no edits, no soft delete; the row is the unit of export and delete.

The teacher turn itself is PL2; this store is the persistence + export +
hard-delete foundation PL1 ships behind the API.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import json
import re
from typing import TYPE_CHECKING, Any

from ..errors import APIError
from ..logging_shim import log_event
from .personalization import normalize_instructions
from .state import initial_state as state_initial_state

if TYPE_CHECKING:
    from db.engine import DatabaseEngine

MAX_TITLE_CHARS = 120
MAX_MESSAGE_CHARS = 8000
MAX_WEAKNESS_CHARS = 500
SESSION_MODES = ("learning", "chat")
SESSION_STAGES = (
    "diagnose",
    "teach",
    "check",
    "adapt",
    "worked_example",
    "advance",
    "harder",
    "board",
    "mastery",
    "done",
)
MESSAGE_ROLES = ("student", "tutor", "system_event")
MESSAGE_KINDS = (
    "text",
    "check",
    "check_result",
    "artifact_ref",
    "stage_change",
    "diagnostic",
    "summary",
)
EXPORT_SCHEMA_VERSION = 1
RETENTION_SESSION_DAYS = 90

_MESSAGE_COLS = """
    message_id, session_id, turn_index, client_turn_id, role, kind, text,
    payload, answer_key, created_at
"""

_SESSION_COLS = """
    session_id, user_id, parent_session_id, title, mode, class_level,
    chapter_id, concept_ids, weakness_text, stage, difficulty_level, status,
    state, turn_count, rag_index_version, prompt_version, model,
    created_at, updated_at, last_turn_at, completed_at
"""

# Deterministic lexical match stop set (chapter-title words carry the signal;
# the student's glue words must not match everything).
_WEAKNESS_STOPWORDS = frozenset(
    {
        "i",
        "a",
        "an",
        "the",
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "dont",
        "not",
        "get",
        "got",
        "how",
        "what",
        "why",
        "when",
        "which",
        "and",
        "or",
        "of",
        "in",
        "on",
        "to",
        "for",
        "with",
        "it",
        "its",
        "this",
        "that",
        "my",
        "me",
        "we",
        "you",
        "about",
        "pls",
        "please",
        "help",
        "understand",
        "know",
        "cant",
        "confused",
    }
)


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _load_json(value: object) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return None


class PersonalizedStore:
    """Owner-scoped CRUD, idempotent message append, export, hard delete."""

    def __init__(self, db: DatabaseEngine) -> None:
        self.db = db

    # --- chapter / concept resolution (create-time validation) --------------

    def get_chapter(self, chapter_id: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            "SELECT chapter_id, class_level, slug, title_en FROM syllabus_chapter WHERE chapter_id = ?",
            (chapter_id,),
        )

    def match_chapter_by_weakness(self, weakness_text: str) -> tuple[str | None, int]:
        """Deterministic lexical match of free text to one chapter (no model call).

        Token-overlap score over the chapter and concept titles (data-and-api.md
        §4.4): exactly one clear winner resolves the chapter; 0 or ≥2 candidates
        return None and the API answers `422` with the chapter-picker hint —
        never a guess.
        """
        tokens = {
            tok
            for tok in re.findall(r"[a-z0-9]+", weakness_text.lower())
            if tok not in _WEAKNESS_STOPWORDS and len(tok) > 2
        }
        if not tokens:
            return None, 0
        chapters = self.db.fetchall(
            "SELECT chapter_id, title_en FROM syllabus_chapter ORDER BY chapter_id"
        )
        concepts = self.db.fetchall("SELECT chapter_id, title_en FROM concept")
        concepts_by_chapter: dict[str, list[str]] = {}
        for row in concepts:
            concepts_by_chapter.setdefault(str(row["chapter_id"]), []).append(
                str(row["title_en"])
            )
        scores: list[tuple[int, str]] = []
        for row in chapters:
            chapter_id = str(row["chapter_id"])
            hay = {t for t in re.findall(r"[a-z0-9]+", str(row["title_en"]).lower())}
            for title in concepts_by_chapter.get(chapter_id, []):
                hay |= set(re.findall(r"[a-z0-9]+", title.lower()))
            scores.append((len(tokens & hay), chapter_id))
        scores.sort(reverse=True)
        if not scores or scores[0][0] == 0:
            return None, 0
        if len(scores) > 1 and scores[1][0] == scores[0][0]:
            return None, len([1 for score, _ in scores if score == scores[0][0]])
        return scores[0][1], scores[0][0]

    def concepts_of_chapter(self, chapter_id: str) -> list[str]:
        rows = self.db.fetchall(
            "SELECT concept_id FROM concept WHERE chapter_id = ? ORDER BY order_index",
            (chapter_id,),
        )
        return [str(r["concept_id"]) for r in rows]

    # --- create / read --------------------------------------------------------

    def create_session(
        self,
        *,
        user_id: str,
        chapter_id: str,
        class_level: int,
        title: str,
        concept_ids: list[str] | None = None,
        weakness_text: str | None = None,
        skip_diagnostic: bool = False,
        parent_session_id: str | None = None,
        mode: str = "learning",
        now_dt: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Insert one saved session; the title is server-generated (never free text)."""
        del now_dt
        if mode not in SESSION_MODES:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "invalid_mode"}
            )
        clean_weakness: str | None = None
        if weakness_text:
            normalized_weakness = normalize_instructions(weakness_text)
            if len(normalized_weakness) > MAX_WEAKNESS_CHARS:
                raise APIError(
                    "E-VALIDATION",
                    status_code=422,
                    extra={"reason": "weakness_too_long"},
                )
            clean_weakness = normalized_weakness
        session_id = _uuid7_str()
        now = _utc_now_iso()
        stage = "teach" if skip_diagnostic else "diagnose"
        # The machine's memory (agent-and-rag.md §2.4) starts consistent with
        # the stage column: skip_diagnostic starts at teach, else diagnose.
        initial = state_initial_state(
            list(concept_ids or []), skip_diagnostic=skip_diagnostic
        )
        with self.db.transaction() as tx:
            tx.execute(
                """
                INSERT INTO personalized_session (
                    session_id, user_id, parent_session_id, title, mode,
                    class_level, chapter_id, concept_ids, weakness_text, stage,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    parent_session_id,
                    title[:MAX_TITLE_CHARS],
                    mode,
                    class_level,
                    chapter_id,
                    json.dumps(concept_ids or []),
                    clean_weakness,
                    stage,
                    json.dumps(initial),
                    now,
                    now,
                ),
            )
        log_event(
            "personalized.session.created",
            {
                "chapter_id": chapter_id,
                "mode": mode,
                "stage": stage,
                "concept_count": len(concept_ids or []),
            },
        )
        return self.get_session(user_id, session_id)  # type: ignore[return-value]

    def get_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """Owner-scoped fetch: another user's id is None → the route answers 404."""
        row = self.db.fetchone(
            f"SELECT {_SESSION_COLS} FROM personalized_session "
            "WHERE session_id = ? AND user_id = ?",
            (session_id, user_id),
        )
        if row is None:
            return None
        return self._session_out(row)

    def list_sessions(
        self,
        user_id: str,
        *,
        status: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """`updated_at DESC` list; the cursor is an opaque base64 page key.

        Never includes `weakness_text` or message text (§4.5).
        """
        params: list[Any] = [user_id]
        where = "user_id = ?"
        if status:
            if status not in ("active", "completed", "abandoned"):
                raise APIError(
                    "E-VALIDATION", status_code=422, extra={"reason": "invalid_status"}
                )
            where += " AND status = ?"
            params.append(status)
        if cursor:
            after_updated, after_id = _decode_cursor(cursor)
            where += " AND (updated_at < ? OR (updated_at = ? AND session_id < ?))"
            params.extend([after_updated, after_updated, after_id])
        params.append(min(max(1, limit), 50) + 1)
        rows = self.db.fetchall(
            "SELECT session_id, title, chapter_id, mode, stage, status, "
            "turn_count, concept_ids, created_at, updated_at, last_turn_at, "
            "completed_at FROM personalized_session WHERE "
            + where
            + " ORDER BY updated_at DESC, session_id DESC LIMIT ?",
            tuple(params),
        )
        next_cursor = None
        if len(rows) > min(max(1, limit), 50):
            rows = rows[: min(max(1, limit), 50)]
            last = rows[-1]
            next_cursor = _encode_cursor(
                str(last["updated_at"]), str(last["session_id"])
            )
        return [self._session_summary(row) for row in rows], next_cursor

    def messages_page(
        self,
        user_id: str,
        session_id: str,
        *,
        before: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Earlier turns (≤ 50), newest-first page ending just before `before`."""
        if self.get_session(user_id, session_id) is None:
            return []
        capped = min(max(1, limit), 50)
        params: list[Any] = [session_id]
        where = "session_id = ?"
        if before is not None:
            where += " AND turn_index < ?"
            params.append(before)
        params.append(capped)
        rows = self.db.fetchall(
            f"SELECT {_MESSAGE_COLS} FROM personalized_message WHERE {where} "
            "ORDER BY turn_index DESC LIMIT ?",
            tuple(params),
        )
        return [self._message_out(r) for r in reversed(rows)]

    def last_messages(
        self, user_id: str, session_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """The last `limit` messages, oldest first (detail view, §4.5)."""
        if self.get_session(user_id, session_id) is None:
            return []
        rows = self.db.fetchall(
            f"SELECT {_MESSAGE_COLS} FROM personalized_message WHERE session_id = ? "
            "ORDER BY turn_index DESC LIMIT ?",
            (session_id, min(max(1, limit), 50)),
        )
        return [self._message_out(r) for r in reversed(rows)]

    # --- append (idempotent by client_turn_id) --------------------------------

    def append_message(
        self,
        *,
        session_id: str,
        role: str,
        kind: str,
        text: str | None = None,
        payload: dict[str, Any] | None = None,
        answer_key: str | None = None,
        client_turn_id: str | None = None,
        message_id: str | None = None,
        now_dt: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Append one message row; replays by `client_turn_id` return the original.

        `turn_index` is the MESSAGE sequence within the session (one value per
        row, so the UNIQUE holds even though one turn appends several rows);
        the logical turn number lives in `payload.turn_no` (§2.3).
        `message_id` may be supplied by the caller (the turn engine
        pre-generates the anchor row's id so `turn.teach.start` can carry it
        before the stream ends); ids are still generated by `db.uuid7`.
        """
        del now_dt
        if role not in MESSAGE_ROLES or kind not in MESSAGE_KINDS:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "invalid_message"}
            )
        if text is not None and len(text) > MAX_MESSAGE_CHARS:
            raise APIError(
                "E-VALIDATION", status_code=422, extra={"reason": "message_too_long"}
            )
        if client_turn_id:
            existing = self.db.fetchone(
                f"SELECT {_MESSAGE_COLS} FROM personalized_message "
                "WHERE session_id = ? AND client_turn_id = ?",
                (session_id, client_turn_id),
            )
            if existing is not None:
                return self._message_out(existing)
        with self.db.transaction() as tx:
            seq_row = tx.fetchone(
                "SELECT COALESCE(MAX(turn_index), -1) AS last FROM personalized_message "
                "WHERE session_id = ?",
                (session_id,),
            )
            next_index = int(seq_row["last"]) + 1 if seq_row else 0
            row_id = message_id or _uuid7_str()
            tx.execute(
                """
                INSERT INTO personalized_message (
                    message_id, session_id, turn_index, client_turn_id, role, kind,
                    text, payload, answer_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    session_id,
                    next_index,
                    client_turn_id,
                    role,
                    kind,
                    text,
                    json.dumps(payload or {}),
                    answer_key,
                    _utc_now_iso(),
                ),
            )
            tx.execute(
                """
                UPDATE personalized_session
                SET updated_at = ?, last_turn_at = ?
                WHERE session_id = ?
                """,
                (_utc_now_iso(), _utc_now_iso(), session_id),
            )
        row = self.db.fetchone(
            f"SELECT {_MESSAGE_COLS} FROM personalized_message WHERE message_id = ?",
            (row_id,),
        )
        assert row is not None
        return self._message_out(row)

    # --- end / delete / export --------------------------------------------------

    def end_session(
        self, user_id: str, session_id: str, *, now_dt: datetime.datetime | None = None
    ) -> dict[str, Any]:
        """API-PL-11: end + summary; idempotent (re-ending returns the same summary)."""
        del now_dt
        session = self.get_session(user_id, session_id)
        if session is None:
            raise APIError("E-NOT-FOUND", status_code=404)
        if session["status"] != "completed":
            self.db.execute(
                """
                UPDATE personalized_session
                SET status = 'completed', stage = 'done', completed_at = ?, updated_at = ?
                WHERE session_id = ? AND user_id = ?
                """,
                (_utc_now_iso(), _utc_now_iso(), session_id, user_id),
            )
            log_event(
                "personalized.session.ended",
                {
                    "chapter_id": session["chapter_id"],
                    "turn_count": session["turn_count"],
                },
            )
        return self.get_session(user_id, session_id)  # type: ignore[return-value]

    def delete_session(self, user_id: str, session_id: str) -> bool:
        """API-PL-08: hard delete in ONE transaction (§4.7).

        Messages cascade (explicitly first, so the delete works with foreign
        keys off too); usage rows keep their counts with `session_id` set NULL;
        the shared artifact rows remain for the refcount job.
        """
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "SELECT session_id FROM personalized_session WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            )
            if row is None:
                return False
            tx.execute(
                "DELETE FROM personalized_message WHERE session_id = ?", (session_id,)
            )
            tx.execute(
                "UPDATE personalized_usage SET session_id = NULL WHERE session_id = ?",
                (session_id,),
            )
            tx.execute(
                "DELETE FROM personalized_session WHERE session_id = ?", (session_id,)
            )
        log_event("personalized.session.deleted", {"session_id": session_id})
        return True

    def export_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """API-PL-09: owner-only JSON export (§4.7 schema).

        No prompts, no internal-only ids, and never the `answer_key` column: a
        check that was never submitted exports without its key, while a
        submitted one already carries `expected` in its payload.
        """
        session = self.get_session(user_id, session_id)
        if session is None:
            return None
        # The export is the student's own transcript: page ALL messages, not
        # only the detail view's last-50 window (bounded by the 60-turn cap).
        all_rows = self.db.fetchall(
            f"SELECT {_MESSAGE_COLS} FROM personalized_message WHERE session_id = ? "
            "ORDER BY turn_index ASC",
            (session_id,),
        )
        messages = [self._message_out(r) for r in all_rows]
        mastery_rows = self.db.fetchall(
            "SELECT concept_id, payload, created_at FROM progress_event "
            "WHERE user_id = ? AND kind = 'personalized_mastery' AND chapter_id = ? "
            "ORDER BY created_at ASC",
            (user_id, session["chapter_id"]),
        )
        artifact_ids: list[str] = []
        artifacts: list[dict[str, Any]] = []
        for row in all_rows:
            if row["kind"] != "artifact_ref":
                continue
            payload = _load_json(row.get("payload")) or {}
            artifact_id = str(payload.get("artifact_id") or "")
            if not artifact_id or artifact_id in artifact_ids:
                continue
            artifact_ids.append(artifact_id)
            artifact_row = self.db.fetchone(
                "SELECT artifact_id, kind, title FROM personalized_artifact WHERE artifact_id = ?",
                (artifact_id,),
            )
            if artifact_row is not None:
                artifacts.append(
                    {
                        "artifact_id": str(artifact_row["artifact_id"]),
                        "kind": str(artifact_row["kind"]),
                        "title": str(artifact_row["title"]),
                    }
                )
        from .preferences import get_preferences_row

        prefs_row = get_preferences_row(self.db, user_id)
        return {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": _utc_now_iso(),
            "session": {
                "session_id": session["session_id"],
                "title": session["title"],
                "chapter_id": session["chapter_id"],
                "stage": session["stage"],
                "status": session["status"],
                "created_at": session["created_at"],
                "last_turn_at": session["last_turn_at"],
            },
            "preferences": {
                "personal_instructions": (
                    prefs_row.get("personal_instructions") if prefs_row else None
                )
            },
            "messages": messages,
            "mastery": [
                {
                    "concept_id": str(r["concept_id"]),
                    "status": str(
                        (_load_json(r.get("payload")) or {}).get("status", "")
                    ),
                    "attempts": int(
                        (_load_json(r.get("payload")) or {}).get("attempts", 0)
                    ),
                    "created_at": r.get("created_at"),
                }
                for r in mastery_rows
            ],
            "artifacts": artifacts,
        }

    # --- serializers ------------------------------------------------------------

    @staticmethod
    def _session_out(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": str(row["session_id"]),
            "user_id": str(row["user_id"]),
            "parent_session_id": row.get("parent_session_id"),
            "title": str(row["title"]),
            "mode": str(row["mode"]),
            "class_level": int(row["class_level"]),
            "chapter_id": str(row["chapter_id"]),
            "concept_ids": _load_json(row.get("concept_ids")) or [],
            "weakness_text": row.get("weakness_text"),
            "stage": str(row["stage"]),
            "difficulty_level": int(row["difficulty_level"]),
            "status": str(row["status"]),
            "state": _load_json(row.get("state")) or {},
            "turn_count": int(row["turn_count"]),
            "rag_index_version": row.get("rag_index_version"),
            "prompt_version": str(row["prompt_version"]),
            "model": row.get("model"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "last_turn_at": row.get("last_turn_at"),
            "completed_at": row.get("completed_at"),
        }

    @staticmethod
    def _session_summary(row: dict[str, Any]) -> dict[str, Any]:
        deletes_at = None
        if row.get("last_turn_at"):
            try:
                last_turn = datetime.datetime.fromisoformat(str(row["last_turn_at"]))
                if last_turn.tzinfo is None:
                    last_turn = last_turn.replace(tzinfo=datetime.UTC)
                deletes_at = (
                    last_turn + datetime.timedelta(days=RETENTION_SESSION_DAYS)
                ).astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
            except ValueError:
                deletes_at = None
        return {
            "session_id": str(row["session_id"]),
            "title": str(row["title"]),
            "chapter_id": str(row["chapter_id"]),
            "mode": str(row["mode"]),
            "stage": str(row["stage"]),
            "status": str(row["status"]),
            "turn_count": int(row["turn_count"]),
            "concept_count": len(_load_json(row.get("concept_ids")) or []),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "last_turn_at": row.get("last_turn_at"),
            "completed_at": row.get("completed_at"),
            "deletes_at": deletes_at,
        }

    @staticmethod
    def _message_out(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "message_id": str(row["message_id"]),
            "session_id": str(row["session_id"]),
            "turn_index": int(row["turn_index"]),
            "client_turn_id": row.get("client_turn_id"),
            "role": str(row["role"]),
            "kind": str(row["kind"]),
            "text": row.get("text"),
            "payload": _load_json(row.get("payload")) or {},
            "created_at": row.get("created_at"),
        }


def _uuid7_str() -> str:
    from db.uuid7 import uuid7_str

    return uuid7_str()


def _encode_cursor(updated_at: str, session_id: str) -> str:
    raw = f"{updated_at}|{session_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_cursor"}
        ) from exc
    if "|" not in raw:
        raise APIError(
            "E-VALIDATION", status_code=422, extra={"reason": "invalid_cursor"}
        )
    updated_at, session_id = raw.split("|", 1)
    return updated_at, session_id
