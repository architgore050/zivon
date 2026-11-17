"""Template view models for the speaking hub, recorder, and history (F6).

Read paths only: the store owns SQL, `web/routes/speaking.py` owns the shell
context, and this module turns stored prompts/attempts into the small dicts a
template may render. Two privacy rules are structural here:

- the prompt *header* never carries `key_ideas` or `model_answer` — those are
  the expected answer, and the store's list shape withholds them; a recorder
  only builds the full result view from an attempt the student already made;
- transcripts are user text: templates render them through Jinja autoescape
  and the island through `textContent`, never as markup.

Each `safe_*` wrapper catches a store failure and returns a page-level error
view, so a broken prompt table never blanks the shell or invents a result.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from backend.assessment import (
    PACK_LANGUAGES,
    fetch_speaking_prompt,
    list_speaking_attempts,
    list_speaking_prompts,
)
from backend.progress import INDIA_TZ, as_utc, catalogue_snapshot, utc_now
from backend.speaking import BAND_LABELS, BAND_NOTES, key_ideas

logger = logging.getLogger(__name__)

LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "hi": "हिन्दी",
    "hi-Latn": "Hinglish",
}
UI_TO_PACK: dict[str, str] = {"en": "en", "hi": "hi", "hi-Latn": "hi-Latn"}
SELF_CHECK_LABELS: dict[str, str] = {
    "explained_fully": "You said you explained it fully.",
    "missed_a_part": "You said you missed a part.",
    "practise_again": "You said you want to practise again.",
}
BOOK_LABELS: dict[str, str] = {
    "ncert-science-9": "NCERT Science Class 9",
    "ncert-science-10": "NCERT Science Class 10",
}
DATA_ERROR = (
    "Your explain-back prompts could not be read just now. Nothing was lost; "
    "this page will show them again on the next successful load."
)
ATTEMPT_DATA_ERROR = (
    "Your explain-back attempts could not be read just now. Nothing was lost; "
    "this page will show them again on the next successful load."
)
MAX_HISTORY = 50


def pack_language(ui_locale: str | None) -> str:
    """Map the shell's UI locale to the pack's authored language variant."""
    return UI_TO_PACK.get(str(ui_locale or "en"), "en")


def language_label(value: str | None) -> str:
    return LANGUAGE_LABELS.get(str(value or ""), str(value or "English"))


def html_lang(value: str | None) -> str:
    """BCP-47 hint for the prompt/transcript text (hi-Latn is its own tag)."""
    cleaned = str(value or "en")
    if cleaned == "hi":
        return "hi"
    if cleaned == "hi-Latn":
        return "hi-Latn"
    return "en"


def build_hub_view(
    db: Any,
    *,
    user_id: str,
    ui_language: str,
    frontend_dir: str,
) -> dict[str, Any]:
    """Chapter-grouped prompts with the student's last attempt per prompt."""
    requested = pack_language(ui_language)
    snapshot = catalogue_snapshot(db, frontend_dir)
    by_language: dict[str, list[dict[str, Any]]] = {}
    for language in PACK_LANGUAGES:
        by_language[language] = list_speaking_prompts(db, language=language)
    attempts = list_speaking_attempts(db, user_id, limit=MAX_HISTORY)
    latest: dict[str, dict[str, Any]] = {}
    for attempt in attempts:  # newest first
        latest.setdefault(str(attempt["prompt_id"]), attempt)

    groups: dict[str, dict[str, Any]] = {}
    for rows in by_language.values():
        for row in rows:
            prompt_id = str(row["prompt_id"])
            entry = groups.setdefault(
                prompt_id,
                {
                    "prompt_id": prompt_id,
                    "chapter_id": str(row["chapter_id"]),
                    "class_level": row.get("class_level"),
                    "variants": {},
                },
            )
            entry["variants"][str(row["language"])] = row

    grouped: dict[str, dict[str, Any]] = {}
    for prompt_id, entry in groups.items():
        variants = entry["variants"]
        chosen = _choose_language(variants, requested)
        if chosen is None:
            continue
        row = variants[chosen]
        chapter_id = entry["chapter_id"]
        meta = snapshot.chapters.get(chapter_id)
        chapter_title = meta.title if meta else _humanize(chapter_id)
        group = grouped.setdefault(
            chapter_id,
            {
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "class_level": entry.get("class_level"),
                "prompts": [],
            },
        )
        last = latest.get(prompt_id)
        group["prompts"].append(
            {
                "prompt_id": prompt_id,
                "prompt": str(row["prompt"]),
                "language": chosen,
                "language_label": language_label(chosen),
                "lang": html_lang(chosen),
                "available_languages": sorted(variants),
                "key_idea_count": int(row.get("key_idea_count") or 0),
                "href": f"/app/speaking/{prompt_id}?language={chosen}",
                "language_note": _language_note(requested, chosen),
                "last": attempt_summary(last) if last else None,
            }
        )
    ordered = sorted(
        grouped.values(),
        key=lambda group: (
            group["class_level"] if group["class_level"] is not None else 99,
            group["chapter_title"].lower(),
        ),
    )
    for group in ordered:
        group["prompts"].sort(key=lambda item: item["prompt_id"])
    overall = attempt_summary(attempts[0]) if attempts else None
    return {
        "data_error": None,
        "groups": ordered,
        "has_prompts": bool(ordered),
        "total_prompts": sum(len(group["prompts"]) for group in ordered),
        "last_attempt": overall,
        "language": requested,
        "language_label": language_label(requested),
        "language_note": (
            f"Prompts missing a {language_label(requested)} version are shown "
            f"in English and say so."
            if requested != "en"
            else None
        ),
    }


def build_recorder_view(
    db: Any,
    *,
    user_id: str,
    prompt_id: str,
    ui_language: str,
    frontend_dir: str,
) -> dict[str, Any]:
    """One prompt (answer material withheld until an attempt exists) + history."""
    requested = pack_language(ui_language)
    variants: dict[str, dict[str, Any]] = {}
    for language in (requested, "en", "hi", "hi-Latn"):
        if language in variants:
            continue
        prompt = fetch_speaking_prompt(db, prompt_id, language)
        if prompt is not None:
            variants[language] = prompt
    if not variants:
        return {"not_found": True, "data_error": None}
    chosen = _choose_language(variants, requested)
    assert chosen is not None
    prompt = variants[chosen]
    snapshot = catalogue_snapshot(db, frontend_dir)
    chapter_id = str(prompt["chapter_id"])
    meta = snapshot.chapters.get(chapter_id)
    attempts = list_speaking_attempts(
        db, user_id, prompt_id=prompt_id, limit=MAX_HISTORY
    )
    last = attempts[0] if attempts else None
    return {
        "not_found": False,
        "data_error": None,
        "prompt": {
            "prompt_id": prompt_id,
            "chapter_id": chapter_id,
            "chapter_title": meta.title if meta else _humanize(chapter_id),
            "class_level": prompt.get("class_level"),
            "prompt": str(prompt["prompt"]),
            "language": chosen,
            "language_label": language_label(chosen),
            "lang": html_lang(chosen),
            "available_languages": sorted(variants),
            "key_idea_count": int(prompt.get("key_idea_count") or 0),
            "max_seconds": int(_threshold_seconds(prompt)),
        },
        "language_note": _language_note(requested, chosen),
        "last_result": result_view(last, prompt) if last else None,
        "history": [
            attempt_summary(attempt, prompt=prompt) for attempt in attempts[1:]
        ],
    }


def build_history_view(
    db: Any, *, user_id: str, ui_language: str, frontend_dir: str
) -> dict[str, Any]:
    """Every kept attempt, newest first, with its prompt and AI feedback."""
    del ui_language  # attempt rows already carry the language they were made in
    snapshot = catalogue_snapshot(db, frontend_dir)
    attempts = list_speaking_attempts(db, user_id, limit=MAX_HISTORY)
    rows: list[dict[str, Any]] = []
    prompts: dict[tuple[str, str], dict[str, Any] | None] = {}
    for attempt in attempts:
        key = (str(attempt["prompt_id"]), str(attempt["language"]))
        if key not in prompts:
            prompts[key] = fetch_speaking_prompt(db, key[0], key[1])
        prompt = prompts[key]
        chapter_id = str(prompt["chapter_id"]) if prompt else ""
        meta = snapshot.chapters.get(chapter_id) if chapter_id else None
        feedback = _object(attempt.get("feedback"))
        rubric = _object(attempt.get("rubric_scores"))
        summary = attempt_summary(attempt, prompt=prompt)
        assert summary is not None
        summary.update(
            {
                "chapter_title": (
                    meta.title if meta else _humanize(chapter_id) if chapter_id else ""
                ),
                "prompt_text": str(prompt["prompt"]) if prompt else "",
                "model_answer": str(prompt["model_answer"]) if prompt else "",
                "model_answer_source": (
                    _model_source_label(prompt.get("model_answer_source"))
                    if prompt
                    else ""
                ),
                "transcript": str(attempt.get("transcript") or ""),
                "what_went_well": str(feedback.get("what_went_well") or ""),
                "next_step": str(feedback.get("next_step") or ""),
                "evaluation_available": bool(rubric.get("ideas_total")),
                "prompt_available": prompt is not None,
                "mock": bool(feedback.get("mock")),
            }
        )
        rows.append(summary)
    return {
        "data_error": None,
        "attempts": rows,
        "count": len(rows),
        "empty": not rows,
    }


def result_view(
    attempt: Mapping[str, Any] | None,
    prompt: Mapping[str, Any],
    *,
    mock: bool | None = None,
) -> dict[str, Any] | None:
    """The post-attempt result (transcript + ideas + feedback + model answer)."""
    if attempt is None:
        return None
    feedback = _object(attempt.get("feedback"))
    rubric = _object(attempt.get("rubric_scores"))
    saved = {
        str(row.get("idea_id")): row
        for row in _list(rubric.get("ideas"))
        if isinstance(row, Mapping)
    }
    ideas: list[dict[str, Any]] = []
    for idea in key_ideas(prompt):
        row = saved.get(idea["idea_id"], {})
        present = row.get("present") is True
        ideas.append(
            {
                "idea_id": idea["idea_id"],
                "text": idea["text"],
                "present": present,
                "evidence": str(row.get("evidence") or "") if present else "",
            }
        )
    band = str(feedback.get("band") or rubric.get("band") or "")
    evaluation_available = bool(rubric.get("ideas_total") or feedback.get("band"))
    choice = str(_object(attempt.get("self_check")).get("choice") or "")
    return {
        "attempt_id": str(attempt["attempt_id"]),
        "when": _when(attempt.get("created_at")),
        "transcript": str(attempt.get("transcript") or ""),
        "language": str(attempt.get("language") or ""),
        "lang": html_lang(str(attempt.get("language") or "en")),
        "duration_ms": attempt.get("duration_ms"),
        "evaluation_available": evaluation_available,
        "band": band,
        "band_label": BAND_LABELS.get(band, ""),
        "band_note": BAND_NOTES.get(band, ""),
        "ideas_present": int(rubric.get("ideas_present") or 0),
        "ideas_total": int(rubric.get("ideas_total") or 0),
        "ideas": ideas,
        "what_went_well": str(feedback.get("what_went_well") or ""),
        "next_step": str(feedback.get("next_step") or ""),
        "model_answer": str(prompt.get("model_answer") or ""),
        "model_answer_source": _model_source_label(prompt.get("model_answer_source")),
        "self_check": choice,
        "self_check_label": SELF_CHECK_LABELS.get(choice, ""),
        "mock": bool(feedback.get("mock")) if mock is None else bool(mock),
    }


def attempt_summary(
    attempt: Mapping[str, Any] | None,
    *,
    prompt: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """One compact attempt row (hub, recorder history, history page)."""
    if attempt is None:
        return None
    feedback = _object(attempt.get("feedback"))
    rubric = _object(attempt.get("rubric_scores"))
    band = str(feedback.get("band") or rubric.get("band") or "")
    total = int(
        rubric.get("ideas_total")
        or (prompt.get("key_idea_count") if prompt else 0)
        or 0
    )
    present = int(rubric.get("ideas_present") or 0)
    choice = str(_object(attempt.get("self_check")).get("choice") or "")
    return {
        "attempt_id": str(attempt["attempt_id"]),
        "when": _when(attempt.get("created_at")),
        "language": str(attempt.get("language") or ""),
        "language_label": language_label(str(attempt.get("language") or "")),
        "band": band,
        "band_label": BAND_LABELS.get(band, ""),
        "ideas_present": present,
        "ideas_total": total,
        "evaluation_available": bool(rubric.get("ideas_total")),
        "self_check": choice,
        "self_check_label": SELF_CHECK_LABELS.get(choice, ""),
    }


def safe_hub_view(
    db: Any, *, user_id: str, ui_language: str, frontend_dir: str
) -> dict[str, Any]:
    try:
        return build_hub_view(
            db, user_id=user_id, ui_language=ui_language, frontend_dir=frontend_dir
        )
    except Exception:
        logger.exception("speaking hub view failed")
        return {
            "data_error": DATA_ERROR,
            "groups": [],
            "has_prompts": False,
            "total_prompts": 0,
            "last_attempt": None,
            "language": pack_language(ui_language),
            "language_label": language_label(pack_language(ui_language)),
            "language_note": None,
        }


def safe_recorder_view(
    db: Any,
    *,
    user_id: str,
    prompt_id: str,
    ui_language: str,
    frontend_dir: str,
) -> dict[str, Any]:
    try:
        return build_recorder_view(
            db,
            user_id=user_id,
            prompt_id=prompt_id,
            ui_language=ui_language,
            frontend_dir=frontend_dir,
        )
    except Exception:
        logger.exception("speaking recorder view failed")
        return {"not_found": False, "data_error": ATTEMPT_DATA_ERROR}


def safe_history_view(
    db: Any, *, user_id: str, ui_language: str, frontend_dir: str
) -> dict[str, Any]:
    try:
        return build_history_view(
            db, user_id=user_id, ui_language=ui_language, frontend_dir=frontend_dir
        )
    except Exception:
        logger.exception("speaking history view failed")
        return {
            "data_error": ATTEMPT_DATA_ERROR,
            "attempts": [],
            "count": 0,
            "empty": True,
        }


# --- helpers ---------------------------------------------------------------


def _choose_language(variants: Mapping[str, Any], requested: str) -> str | None:
    if requested in variants:
        return requested
    if "en" in variants:
        return "en"
    for fallback in ("hi", "hi-Latn"):
        if fallback in variants:
            return fallback
    return next(iter(variants), None)


def _language_note(requested: str, chosen: str) -> str | None:
    if requested == chosen:
        return None
    return (
        f"{language_label(requested)} is not loaded for this prompt yet, so it "
        f"is shown in {language_label(chosen)}."
    )


def _threshold_seconds(prompt: Mapping[str, Any]) -> float:
    rubric = prompt.get("rubric")
    raw = rubric.get("max_duration_s") if isinstance(rubric, Mapping) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 45.0
    return min(60.0, max(10.0, float(raw)))


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _when(value: Any) -> str:
    parsed = as_utc(value)
    if parsed is None:
        return ""
    now = utc_now()
    local = parsed.astimezone(INDIA_TZ).date()
    today = now.astimezone(INDIA_TZ).date()
    delta = (today - local).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta < 7:
        return local.strftime("%a")
    return local.strftime("%d %b")


def _model_source_label(source: Any) -> str:
    if not isinstance(source, Mapping):
        return ""
    book_id = str(source.get("book_id") or "").strip()
    book = BOOK_LABELS.get(book_id, _humanize(book_id) if book_id else "")
    section = str(source.get("section") or "").strip()
    example = str(source.get("example") or "").strip()
    parts = [part for part in (book, f"§{section}" if section else "", example) if part]
    return " · ".join(parts)


def _humanize(identifier: str) -> str:
    words = [
        word for word in str(identifier or "").replace("_", "-").split("-") if word
    ]
    if len(words) >= 2 and words[0] == "class" and words[1].isdigit():
        words = words[2:]
    text = " ".join(words).strip()
    return text[:1].upper() + text[1:] if text else ""


__all__ = [
    "DATA_ERROR",
    "LANGUAGE_LABELS",
    "MAX_HISTORY",
    "SELF_CHECK_LABELS",
    "attempt_summary",
    "build_history_view",
    "build_hub_view",
    "build_recorder_view",
    "html_lang",
    "language_label",
    "pack_language",
    "result_view",
    "safe_history_view",
    "safe_hub_view",
    "safe_recorder_view",
]
