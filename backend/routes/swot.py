"""SWOT APIs (F8): `/v1/swot` and `/v1/swot/explain`.

Authenticated, user-scoped, read-only JSON under `/v1`. Auth is F0's account
guard (`require_context`); both routes are GETs, so no CSRF write check, and
the global `/v1/*` rate-limit family (30/min per IP hash) applies with no
second limiter. There is no parent, share, or leaderboard surface anywhere
in this module, and nothing here calls a model or a vendor.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..errors import APIError
from ..logging_shim import ErrorClass, Severity, log_event
from ..swot import SwotModeError, build_swot, build_swot_explain, gather_input
from .auth import _config, require_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["swot"])


@router.get("/v1/swot")
def get_swot(request: Request) -> JSONResponse:
    """The student's own SWOT grid, snapshot, and unrated row."""
    payload = _swot_payload(request, builder=build_swot, event="swot.view.served")
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/v1/swot/explain")
def get_swot_explain(request: Request) -> JSONResponse:
    """How this SWOT was computed: the method plus this student's numbers."""
    payload = _swot_payload(
        request, builder=build_swot_explain, event="swot.explain.served"
    )
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    return response


def _swot_payload(
    request: Request,
    *,
    builder: Any,
    event: str,
) -> dict[str, Any]:
    ctx = require_context(request)
    db = request.app.state.db
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    config = _config(request)
    try:
        data = gather_input(
            db,
            user_id=str(ctx.user["user_id"]),
            frontend_dir=config.frontend_dir,
            mode=config.swot_mode,
        )
        payload = builder(data=data)
    except SwotModeError as exc:
        raise APIError("E-VALIDATION", status_code=422) from exc
    except Exception:
        log_event(
            "swot.compute.failed",
            {"reason_code": "compute_error"},
            severity=Severity.WARNING,
            error_class=ErrorClass.STORE_ERROR,
        )
        logger.exception("swot computation failed")
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503) from None
    log_event(
        event,
        {
            "mode": payload["mode"],
            "rated_count": payload["rated_chapter_count"],
            "unrated_count": len(payload["unrated"]),
            "enough_data": payload["enough_data"],
        },
        severity=Severity.INFO,
    )
    return payload


__all__ = ["router"]
