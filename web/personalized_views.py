"""Template view models for the personalized-learning pages (PL4).

Pure read paths over the personalized-learning domain (PL1 store + quota, the
PL2 RAG catalog seam, PL3 artifact references); the route only adds the shell
context. Each `safe_*` wrapper catches a store failure and returns a
page-level error view so a broken read never turns the page into a 500 and
never invents data to fill the gap (web-shell.md §8, spec.md §7.1).

The write path (start, end, delete, preferences save/clear) stays in the
routes; the teaching turn itself is always the PL2 JSON/SSE API
(`API-PL-10`) called by `frontend/assets/personalized.js` — this module never
duplicates admission, quota reservation, or scoring.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.personalized.preferences import get_preferences_row
from backend.personalized.quota import QuotaCaps, QuotaService
from backend.personalized.store import PersonalizedStore

logger = logging.getLogger(__name__)

WEAKNESS_MAX_CHARS = 500
MESSAGE_MAX_CHARS = 2000
SOFT_TURN_NUDGE = 40
HARD_TURN_CAP = 60
DELETE_WARNING_DAYS = 7

STAGE_LABELS: dict[str, str] = {
    "diagnose": "Checking what you know",
    "teach": "Teaching",
    "check": "Checking",
    "adapt": "Explaining another way",
    "worked_example": "Worked example",
    "advance": "Next concept",
    "harder": "Harder practice",
    "board": "Board-style practice",
    "mastery": "Mastery summary",
    "done": "Finished",
}

MASTERY_LABELS: dict[str, str] = {
    "not_started": "Not started",
    "learning": "Learning",
    "practising": "Practising",
    "mastered": "Mastered",
    "board_ready": "Board-ready",
    "skipped": "Skipped",
}

HUB_DATA_ERROR = (
    "Personalized learning is unavailable right now. Your saved sessions are "
    "not lost; try again in a moment."
)
SESSION_DATA_ERROR = (
    "This session could not be read just now. It is still saved; reload to try again."
)
KILL_SWITCH_NOTICE = (
    "Personalized learning is paused right now. Your saved sessions and "
    "preferences are safe; nothing new starts until it is switched back on."
)
QUOTA_USER_COPY = (
    "You've used today's turns. Your sessions are safe; they reset at 00:00 IST."
)
QUOTA_SESSIONS_COPY = (
    "You've used today's new-session allowance. Your saved sessions are safe; "
    "teaching turns reset at 00:00 IST."
)
QUOTA_GLOBAL_COPY = (
    "Zivon is at its daily limit. Your work is saved; try again after 00:00 IST."
)
NO_CONTENT_COPY = (
    "No chapter has teaching content yet. Open the catalogue to study the "
    "published lessons meanwhile."
)


class SessionNotFound(RuntimeError):
    """The session id does not exist for this owner (rendered as a 404 page)."""


# -- shared pieces -------------------------------------------------------------


def caps_from_config(config: Any) -> QuotaCaps:
    """The configured caps (the same mapping the JSON router builds)."""
    return QuotaCaps(
        turns_per_user_per_day=int(
            getattr(config, "personalized_turns_per_user_per_day", 40)
        ),
        turn_concurrency=int(getattr(config, "personalized_turn_concurrency", 2)),
        sessions_per_user_per_day=int(
            getattr(config, "personalized_sessions_per_user_per_day", 5)
        ),
        artifacts_per_user_per_day=int(
            getattr(config, "personalized_artifacts_per_user_per_day", 12)
        ),
        turns_global_per_day=int(
            getattr(config, "personalized_turns_global_per_day", 1500)
        ),
        artifacts_global_per_day=int(
            getattr(config, "personalized_artifacts_global_per_day", 300)
        ),
    )


def _quota_view(
    db: Any,
    *,
    user_id: str,
    enabled: bool,
    caps: QuotaCaps | None = None,
) -> dict[str, Any]:
    usage = QuotaService(db, caps).get_usage(user_id, enabled=enabled)
    turns = usage["turns"]
    exhausted_scope = None
    if not usage.get("enabled", True):
        exhausted_scope = "disabled"
    elif turns["remaining"] <= 0 or turns["state"] == "exhausted":
        exhausted_scope = "user"
    elif usage.get("global", {}).get("state") == "exhausted":
        exhausted_scope = "global"
    return {
        "turns_remaining": int(turns["remaining"]),
        "turns_cap": int(turns["cap"]),
        "turns_used": int(turns["used"]),
        "turn_state": str(turns["state"]),
        "reset_at": usage.get("reset_at"),
        "enabled": bool(usage.get("enabled", True)),
        "warn": (0 < int(turns["remaining"]) <= max(1, int(int(turns["cap"]) * 0.15))),
        "exhausted_scope": exhausted_scope,
        "quota_copy": {
            None: "",
            "user": QUOTA_USER_COPY,
            "global": QUOTA_GLOBAL_COPY,
            "disabled": KILL_SWITCH_NOTICE,
        }[exhausted_scope],
    }


def _relative_when(iso: str | None, now: datetime.datetime) -> str:
    stamp = _parse_iso(iso)
    if stamp is None:
        return ""
    seconds = max((now - stamp).total_seconds(), 0)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return "1 h ago" if hours == 1 else f"{hours} h ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def _parse_iso(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.UTC)
    return stamp


def _delete_warning(row: dict[str, Any], now: datetime.datetime) -> bool:
    deletes_at = _parse_iso(row.get("deletes_at"))
    if deletes_at is None:
        return False
    remaining = deletes_at - now
    return (
        datetime.timedelta(0)
        < remaining
        <= datetime.timedelta(days=DELETE_WARNING_DAYS)
    )


def _catalog_chapters(db: Any, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Covered chapters with titles/concepts, grouped by class (§2.2).

    Only chapters the RAG index covers are offered; a chapter row that the
    syllabus no longer has is skipped rather than shown unlabelled.
    """
    covered: dict[str, dict[str, Any]] = {}
    for entry in catalog.get("chapters", []):
        chapter_id = str(entry.get("chapter_id") or "")
        if chapter_id:
            covered[chapter_id] = entry
    if not covered:
        return []
    rows = db.fetchall(
        "SELECT chapter_id, class_level, title_en FROM syllabus_chapter "
        "ORDER BY class_level, chapter_no"
    )
    concept_rows = db.fetchall(
        "SELECT concept_id, chapter_id, title_en FROM concept ORDER BY order_index"
    )
    titles = {str(r["chapter_id"]): str(r["title_en"]) for r in rows}
    levels = {str(r["chapter_id"]): r["class_level"] for r in rows}
    concepts: dict[str, list[dict[str, str]]] = {}
    for r in concept_rows:
        chapter_id = str(r["chapter_id"])
        if chapter_id in covered:
            concepts.setdefault(chapter_id, []).append(
                {"concept_id": str(r["concept_id"]), "title": str(r["title_en"])}
            )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for chapter_id, entry in covered.items():
        if chapter_id not in titles:
            continue
        class_level = levels.get(chapter_id)
        if class_level is None:
            continue
        tier = str(entry.get("tier") or "source")
        grouped.setdefault(int(class_level), []).append(
            {
                "chapter_id": chapter_id,
                "title": titles[chapter_id],
                "source_only": tier == "source",
                "concepts": concepts.get(chapter_id, []),
            }
        )
    return [
        {
            "class_level": level,
            "chapters": sorted(items, key=lambda c: str(c["title"])),
        }
        for level, items in sorted(grouped.items())
    ]


# -- hub (SCR-PL-01) -----------------------------------------------------------


def build_hub_view(
    db: Any,
    *,
    user_id: str,
    index_catalog: Any,
    enabled: bool,
    caps: QuotaCaps | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """The hub view model; raises only on a storage failure (use `safe_hub_view`)."""
    current = now or datetime.datetime.now(datetime.UTC)
    quota = _quota_view(db, user_id=user_id, enabled=enabled, caps=caps)
    sessions: list[dict[str, Any]] = []
    try:
        rows, _cursor = PersonalizedStore(db).list_sessions(user_id)
        for row in rows:
            # Completed rows carry a real Resume action (API-PL-16); a
            # cap-exhausted one shows the start-new explanation instead of a
            # dead Resume button (spec.md §2.6, frontend personalized.md §2).
            completed = str(row["status"]) == "completed"
            cap_exhausted = completed and int(row["turn_count"]) >= HARD_TURN_CAP
            sessions.append(
                {
                    "session_id": str(row["session_id"]),
                    "title": str(row["title"]),
                    "stage": str(row["stage"]),
                    "stage_label": STAGE_LABELS.get(
                        str(row["stage"]), str(row["stage"])
                    ),
                    "status": str(row["status"]),
                    "turn_count": int(row["turn_count"]),
                    "can_resume": completed and not cap_exhausted,
                    "cap_exhausted": cap_exhausted,
                    "resume_url": (
                        "/app/personalized/" + str(row["session_id"]) + "/resume"
                    ),
                    "chapter_id": str(row["chapter_id"]),
                    "when": _relative_when(row.get("last_turn_at"), current),
                    "deletes_at": row.get("deletes_at"),
                    "delete_soon": _delete_warning(row, current),
                    "export_url": (
                        "/v1/personalized/sessions/"
                        + str(row["session_id"])
                        + "/export"
                    ),
                    "session_url": ("/app/personalized/" + str(row["session_id"])),
                }
            )
    except Exception:
        logger.exception("personalized session list failed")
        sessions = []
        sessions_error = True
    else:
        sessions_error = False

    catalog_error = False
    catalog: dict[str, Any] | None = None
    if index_catalog is not None:
        try:
            catalog = index_catalog()
        except Exception:
            logger.exception("personalized catalog failed")
            catalog = None
            catalog_error = True
    class_groups = _catalog_chapters(db, catalog) if catalog else []

    # The hub Start gate is separate from the turns strip: a new session
    # consumes the daily session allowance (API-PL-05), turns the teaching.
    sessions_cap = int(caps.sessions_per_user_per_day) if caps else 5
    sessions_left = max(
        0, sessions_cap - QuotaService(db, caps).sessions_created_today(user_id)
    )
    start_note = ""
    if not enabled:
        start_note = KILL_SWITCH_NOTICE
    elif quota["exhausted_scope"] in ("user", "global"):
        start_note = quota["quota_copy"]
    elif sessions_left <= 0:
        start_note = QUOTA_SESSIONS_COPY
    start_blocked = bool(start_note) or not class_groups

    return {
        "quota": quota,
        "sessions_left": sessions_left,
        "start_blocked": start_blocked,
        "start_note": start_note,
        "sessions": sessions,
        "sessions_error": sessions_error,
        "class_groups": class_groups,
        "catalog_available": bool(class_groups),
        "catalog_error": catalog_error or index_catalog is None,
        "no_content": bool(catalog) and not class_groups,
        "no_content_copy": NO_CONTENT_COPY,
        "weakness_max_chars": WEAKNESS_MAX_CHARS,
        "form": {"class_level": "", "chapter_id": "", "concept_id": "", "weakness": ""},
        "field_errors": {},
        "page_error": None,
    }


def safe_hub_view(
    db: Any,
    *,
    user_id: str,
    index_catalog: Any,
    enabled: bool,
    caps: QuotaCaps | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """`build_hub_view` with the honest page-level error state on failure."""
    try:
        return build_hub_view(
            db,
            user_id=user_id,
            index_catalog=index_catalog,
            enabled=enabled,
            caps=caps,
            now=now,
        )
    except Exception:
        logger.exception("personalized hub view failed")
        return {
            "quota": None,
            "sessions": [],
            "sessions_error": True,
            "class_groups": [],
            "catalog_available": False,
            "catalog_error": True,
            "no_content": False,
            "no_content_copy": NO_CONTENT_COPY,
            "weakness_max_chars": WEAKNESS_MAX_CHARS,
            "form": {
                "class_level": "",
                "chapter_id": "",
                "concept_id": "",
                "weakness": "",
            },
            "field_errors": {},
            "page_error": HUB_DATA_ERROR,
        }


# -- session (SCR-PL-02) -------------------------------------------------------


def _artifact_card(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an `artifact_ref` payload for the PL3 viewer partial.

    `src` is carried through only when the payload says ready — the viewer
    never constructs an artifact URL (data-and-api.md §4.8).
    """
    artifact_id = str(payload.get("artifact_id") or "").strip()
    if not artifact_id:
        return None
    status = str(payload.get("status") or "pending")
    ready = status == "ready"
    fallback = payload.get("fallback") or {}
    fallback_kind = str(fallback.get("kind") or "text")
    return {
        "artifact_id": artifact_id,
        "kind": str(payload.get("kind") or "simulation"),
        "title": str(payload.get("title") or "Generated visual"),
        "status": status,
        "src": str(payload.get("src") or "") if ready else "",
        "fallback_kind": fallback_kind,
        # The validated fallback ships with the card in every state; the viewer
        # reveals it only when the frame fails or the build never lands.
        "fallback_svg": fallback.get("svg"),
    }


def _message_cards(
    db: Any,
    messages: list[dict[str, Any]],
    *,
    chapter_id: str,
) -> list[dict[str, Any]]:
    """Turn the stored message rows into the transcript cards (§6.2)."""
    feedback_by_check: dict[str, dict[str, Any]] = {}
    concept_titles: dict[str, str] = {}
    for message in messages:
        payload = message.get("payload") or {}
        if message.get("kind") == "check_result":
            check_id = str(payload.get("check_id") or "")
            if check_id:
                feedback_by_check[check_id] = payload
    if chapter_id:
        try:
            rows = db.fetchall(
                "SELECT concept_id, title_en FROM concept WHERE chapter_id = ?",
                (chapter_id,),
            )
            concept_titles = {str(r["concept_id"]): str(r["title_en"]) for r in rows}
        except Exception:
            logger.exception("concept titles unavailable for the transcript")

    cards: list[dict[str, Any]] = []
    for message in messages:
        kind = str(message.get("kind"))
        role = str(message.get("role"))
        payload = message.get("payload") or {}
        text = message.get("text")
        turn_index = int(message.get("turn_index") or 0)
        message_id = str(message.get("message_id") or "")
        if kind == "text" and role == "student":
            cards.append(
                {
                    "type": "student",
                    "text": str(text or ""),
                    "turn_index": turn_index,
                    "message_id": message_id,
                }
            )
        elif kind == "text" and role == "tutor":
            teaching = payload.get("teaching") or {}
            paragraphs = teaching.get("paragraphs")
            if not paragraphs:
                paragraphs = [str(text or "")] if text else []
            cards.append(
                {
                    "type": "teach",
                    "text": str(text or ""),
                    "paragraphs": [str(p) for p in paragraphs],
                    "key_statement": teaching.get("key_statement"),
                    "citations": [
                        {
                            "label": str(c.get("label") or ""),
                            "locator": str(c.get("locator") or ""),
                        }
                        for c in (payload.get("citations") or [])
                    ],
                    # §2.4: a slice with no resolved citation is honest —
                    # "no page reference found", never a fabricated source.
                    "ungrounded": bool(payload.get("ungrounded")),
                    "turn_index": turn_index,
                    "message_id": message_id,
                }
            )
        elif kind == "check":
            check_id = str(payload.get("check_id") or "")
            source = payload.get("source") or {}
            options = [
                {"id": str(o.get("id")), "text": str(o.get("text"))}
                for o in (payload.get("options") or [])
            ]
            cards.append(
                {
                    "type": "check",
                    "check_id": check_id,
                    "kind": str(payload.get("kind") or "mcq"),
                    "question": str(payload.get("question") or ""),
                    "options": options,
                    "unit": payload.get("unit"),
                    "level": payload.get("level"),
                    "concept_id": payload.get("concept_id"),
                    "generated": str(source.get("kind") or "") == "generated",
                    "feedback": feedback_by_check.get(check_id),
                    "turn_index": turn_index,
                    "message_id": message_id,
                }
            )
        elif kind == "check_result":
            # Attached to its check card above when the check is in the same
            # window; a result without its check still shows its feedback.
            check_id = str(payload.get("check_id") or "")
            attached = any(
                c["type"] == "check" and str(c.get("check_id")) == check_id
                for c in cards
            )
            if not attached:
                cards.append(
                    {
                        "type": "feedback",
                        "feedback": payload,
                        "turn_index": turn_index,
                        "message_id": message_id,
                    }
                )
        elif kind == "artifact_ref":
            artifact = _artifact_card(payload)
            if artifact is not None:
                cards.append(
                    {
                        "type": "artifact",
                        "artifact": artifact,
                        "turn_index": turn_index,
                        "message_id": message_id,
                    }
                )
        elif kind == "stage_change":
            concept_id = str(
                payload.get("to_concept_id") or payload.get("concept_id") or ""
            )
            cards.append(
                {
                    "type": "stage_change",
                    "to": str(payload.get("to") or ""),
                    "label": STAGE_LABELS.get(str(payload.get("to") or ""), ""),
                    "concept": concept_titles.get(concept_id, ""),
                    "turn_index": turn_index,
                    "message_id": message_id,
                }
            )
        elif kind == "summary":
            mastery = [
                {
                    "concept_id": str(row.get("concept_id") or ""),
                    "status": str(row.get("status") or "not_started"),
                    "label": MASTERY_LABELS.get(
                        str(row.get("status") or ""), str(row.get("status") or "")
                    ),
                    "attempts": int(row.get("attempts") or 0),
                    "first_try_correct": int(row.get("first_try_correct") or 0),
                    "levels_passed": [int(l) for l in (row.get("levels_passed") or [])],
                    "skipped": bool(row.get("skipped")),
                }
                for row in (payload.get("mastery") or [])
            ]
            cards.append(
                {
                    "type": "summary",
                    "mastery": mastery,
                    "turn_count": int(payload.get("turn_count") or 0),
                    "turn_index": turn_index,
                    "message_id": message_id,
                }
            )
        # `diagnostic` and unknown kinds carry no visible card (honest: the
        # transcript shows only what the contract defines).
    return cards


def build_session_view(
    db: Any,
    *,
    user_id: str,
    session_id: str,
    enabled: bool,
    caps: QuotaCaps | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """The session view model; raises `SessionNotFound` when not owned."""
    del now  # cards render stored timestamps server-side as plain dates
    store = PersonalizedStore(db)
    session = store.get_session(user_id, session_id)
    if session is None:
        raise SessionNotFound()
    messages = store.last_messages(user_id, session_id, limit=50)
    cards = _message_cards(db, messages, chapter_id=str(session["chapter_id"]))
    open_check = None
    for card in cards:
        if card["type"] == "check" and card.get("feedback") is None:
            open_check = card
    prefs_row = get_preferences_row(db, user_id)
    turn_count = int(session["turn_count"])
    active = str(session["status"]) == "active"
    at_cap = turn_count >= HARD_TURN_CAP
    completed = str(session["status"]) == "completed"
    cap_exhausted = completed and at_cap
    has_ready_artifacts = any(
        card["type"] == "artifact" and card["artifact"]["status"] == "ready"
        for card in cards
    )
    return {
        "session": {
            "session_id": str(session["session_id"]),
            "title": str(session["title"]),
            "chapter_id": str(session["chapter_id"]),
            "stage": str(session["stage"]),
            "stage_label": STAGE_LABELS.get(
                str(session["stage"]), str(session["stage"])
            ),
            "status": str(session["status"]),
            "active": active,
            "mode": str(session["mode"]),
            "turn_count": turn_count,
            # The finished notice offers the real Resume action only when the
            # session can honestly reopen (completed, under the 60-turn cap).
            "can_resume": completed and not cap_exhausted,
            "cap_exhausted": cap_exhausted,
            "report_course_id": f"personalized/{session['chapter_id']}",
        },
        "cards": cards,
        "open_check": open_check,
        "has_artifacts": has_ready_artifacts,
        "quota": _quota_view(db, user_id=user_id, enabled=enabled, caps=caps),
        "preferences_active": bool(
            prefs_row and prefs_row.get("personal_instructions")
        ),
        "soft_nudge": active and SOFT_TURN_NUDGE <= turn_count < HARD_TURN_CAP,
        "at_cap": at_cap,
        "can_send": active and not at_cap,
        "weakness_max_chars": WEAKNESS_MAX_CHARS,
        "message_max_chars": MESSAGE_MAX_CHARS,
        "page_error": None,
    }


def safe_session_view(
    db: Any,
    *,
    user_id: str,
    session_id: str,
    enabled: bool,
    caps: QuotaCaps | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any] | None:
    """`build_session_view`; None means "not this owner's session" (a 404 page).

    A storage failure degrades to the honest error view instead of a 500.
    """
    try:
        return build_session_view(
            db,
            user_id=user_id,
            session_id=session_id,
            enabled=enabled,
            caps=caps,
            now=now,
        )
    except SessionNotFound:
        return None
    except Exception:
        logger.exception("personalized session view failed")
        return {
            "session": None,
            "session_id": session_id,
            "cards": [],
            "open_check": None,
            "has_artifacts": False,
            "quota": None,
            "preferences_active": False,
            "soft_nudge": False,
            "at_cap": False,
            "can_send": False,
            "weakness_max_chars": WEAKNESS_MAX_CHARS,
            "message_max_chars": MESSAGE_MAX_CHARS,
            "page_error": SESSION_DATA_ERROR,
        }


__all__ = [
    "HARD_TURN_CAP",
    "HUB_DATA_ERROR",
    "KILL_SWITCH_NOTICE",
    "MASTERY_LABELS",
    "MESSAGE_MAX_CHARS",
    "QUOTA_SESSIONS_COPY",
    "SOFT_TURN_NUDGE",
    "STAGE_LABELS",
    "WEAKNESS_MAX_CHARS",
    "SessionNotFound",
    "build_hub_view",
    "build_session_view",
    "caps_from_config",
    "safe_hub_view",
    "safe_session_view",
]
