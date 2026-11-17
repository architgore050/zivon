"""Template view models for the SWOT page and its "How this works" page (F8).

Pure read paths over the SWOT domain; the routes only add the shell context.
Each `safe_*` wrapper catches a failure and returns a page-level error view,
so a broken computation never turns the page into a 500 and never invents a
placement to fill the gap.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.logging_shim import Severity, log_event
from backend.swot import (
    QUADRANT_BLURBS,
    QUADRANT_LABELS,
    SwotModeError,
    build_swot,
    build_swot_explain,
    gather_input,
)

logger = logging.getLogger(__name__)

DATA_ERROR = (
    "Your SWOT could not be built just now. Nothing was lost; this page will "
    "show it again on the next successful load."
)
MODE_ERROR = "The SWOT configuration is invalid; ask the operator to check SWOT_MODE."

# One shared entry point for the four quadrant boxes, in display order:
# Strengths -> Weaknesses -> Opportunities -> Threats (360 px stacks in this
# order with the heading repeated per block).
QUADRANT_ORDER: tuple[str, ...] = ("strength", "weakness", "opportunity", "threat")


def build_swot_view(
    db: Any,
    *,
    user_id: str,
    frontend_dir: str,
    mode: str,
    now: Any | None = None,
) -> dict[str, Any]:
    """Return the `/app/swot` view model (or raise; callers use `safe_swot_view`)."""
    data = gather_input(
        db, user_id=user_id, frontend_dir=frontend_dir, mode=mode, now=now
    )
    payload = build_swot(data=data)
    quadrants = []
    for name in QUADRANT_ORDER:
        quadrants.append(
            {
                "key": name,
                "label": QUADRANT_LABELS[name],
                "blurb": QUADRANT_BLURBS[name],
                "cards": payload["quadrants"][name],
            }
        )
    return {
        "data_error": None,
        "mode_error": None,
        "mode": payload["mode"],
        "rules": payload["rules"],
        "enough_data": payload["enough_data"],
        "is_new": payload["is_new"],
        "rated_chapter_count": payload["rated_chapter_count"],
        "rated_min_chapters": payload["rated_min_chapters"],
        "quadrants": quadrants,
        "unrated": payload["unrated"],
        "snapshot": _snapshot_rows(payload["snapshot"]),
    }


def build_swot_how_view(
    db: Any,
    *,
    user_id: str,
    frontend_dir: str,
    mode: str,
    now: Any | None = None,
) -> dict[str, Any]:
    """Return the `/app/swot/how` view model (explainability)."""
    data = gather_input(
        db, user_id=user_id, frontend_dir=frontend_dir, mode=mode, now=now
    )
    payload = build_swot_explain(data=data)
    return {
        "data_error": None,
        "mode_error": None,
        "mode": payload["mode"],
        "rules": payload["rules"],
        "method": payload["method"],
        "metric_definitions": payload["metric_definitions"],
        "medians": payload["medians"],
        "enough_data": payload["enough_data"],
        "rated_chapter_count": payload["rated_chapter_count"],
        "chapters": [
            {
                "title": entry["title"],
                "chapter_id": entry["chapter_id"],
                "quadrant": QUADRANT_LABELS.get(entry["quadrant"])
                if entry["quadrant"]
                else None,
                "metrics": entry["metrics"],
            }
            for entry in payload["unrated"] + _rated_flat(payload)
        ],
    }


def safe_swot_view(
    db: Any, *, user_id: str, frontend_dir: str, mode: str
) -> dict[str, Any]:
    now = None
    try:
        return build_swot_view(
            db, user_id=user_id, frontend_dir=frontend_dir, mode=mode, now=now
        )
    except SwotModeError:
        logger.error("invalid SWOT_MODE %r", mode)
        return {
            "data_error": None,
            "mode_error": MODE_ERROR,
            "enough_data": False,
            "quadrants": [],
            "unrated": [],
            "snapshot": [],
        }
    except Exception:
        logger.exception("swot view failed")
        return {
            "data_error": DATA_ERROR,
            "mode_error": None,
            "enough_data": False,
            "quadrants": [],
            "unrated": [],
            "snapshot": [],
        }


def safe_swot_how_view(
    db: Any, *, user_id: str, frontend_dir: str, mode: str
) -> dict[str, Any]:
    try:
        return build_swot_how_view(
            db, user_id=user_id, frontend_dir=frontend_dir, mode=mode, now=None
        )
    except SwotModeError:
        logger.error("invalid SWOT_MODE %r", mode)
        return {
            "data_error": None,
            "mode_error": MODE_ERROR,
            "method": [],
            "metric_definitions": [],
            "medians": None,
            "chapters": [],
            "enough_data": False,
        }
    except Exception:
        logger.exception("swot explain view failed")
        return {
            "data_error": DATA_ERROR,
            "mode_error": None,
            "method": [],
            "metric_definitions": [],
            "medians": None,
            "chapters": [],
            "enough_data": False,
        }


def build_dashboard_snapshot(
    db: Any,
    *,
    user_id: str,
    frontend_dir: str,
    mode: str,
    now: Any | None = None,
) -> dict[str, Any]:
    """The dashboard's one-line-per-quadrant SWOT panel (never raises)."""
    try:
        data = gather_input(
            db, user_id=user_id, frontend_dir=frontend_dir, mode=mode, now=now
        )
        payload = build_swot(data=data)
    except Exception:
        logger.exception("dashboard swot snapshot failed")
        return {"data_error": True, "enough_data": False, "rows": []}
    log_event(
        "swot.snapshot.served",
        {"mode": payload["mode"], "enough_data": payload["enough_data"]},
        severity=Severity.INFO,
    )
    rows = _snapshot_rows(payload["snapshot"])
    return {
        "data_error": False,
        "enough_data": payload["enough_data"],
        "is_new": payload["is_new"],
        "rows": rows,
    }


def _rated_flat(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for name in QUADRANT_ORDER for entry in payload["quadrants"][name]]


def _snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in QUADRANT_ORDER:
        entry = snapshot.get(name)
        rows.append(
            {
                "key": name,
                "label": QUADRANT_LABELS[name],
                "card": entry,
            }
        )
    return rows


__all__ = [
    "DATA_ERROR",
    "MODE_ERROR",
    "QUADRANT_ORDER",
    "build_dashboard_snapshot",
    "build_swot_how_view",
    "build_swot_view",
    "safe_swot_how_view",
    "safe_swot_view",
]
