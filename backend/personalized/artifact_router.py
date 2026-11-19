"""Artifact fetch/status API (PL3, API-PL-13/14, data-and-api.md §4.8).

The artifact document is served same-origin with the §5.2 sandbox headers
(strict CSP including `sandbox allow-scripts`, `nosniff`, `no-referrer`,
`private, max-age=86400, immutable` for content-addressed ids, `noindex`,
`Cross-Origin-Resource-Policy: same-origin) until the dedicated artifact
origin deploys (D-PL-09) — the iframe's opaque origin (`sandbox="allow-scripts"`,
never `allow-same-origin`) is the boundary, and it stays in every mode.

Authorization (§4.8/§7, DET-PL05-ARTIFACT-REF): the caller's validated session
must own a message that references the artifact — the shared cache stays
global but never becomes an open content proxy. Another user's unreferenced
id is **404** (no existence oracle). An operator/admin token may fetch for
inspection (§4.8 "or the caller must be an admin"). A `pending`/`failed`
artifact answers `409 E-CONFLICT` with `{status, failure_reason}` — the
client renders the fallback/loader, never a half-built document.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..auth.service import AuthContext
from ..errors import APIError
from ..routes.admin import require_admin_auth
from ..routes.auth import resolve_context
from .artifacts import (
    ARTIFACT_HEADER_CSP,
    ArtifactStore,
)

router = APIRouter(tags=["personalized"])

# Same-origin serving (D-PL-09 interim posture): the app origin is `self`, so
# `frame-ancestors 'self'` pins the embedding without naming the origin twice.
# Dedicated-origin mode appends the app origin here (a deployment change).
_FRAME_ANCESTORS = "frame-ancestors 'self'"
CACHE_CONTROL_READY = "private, max-age=86400, immutable"


def _user_id(ctx: AuthContext) -> str:
    return str(ctx.user["user_id"])


def _owner_or_admin(request: Request, artifact_id: str) -> dict[str, Any]:
    """The §4.8 reference check: a message in one of the caller's sessions, or
    an admin token (fail-closed constant-time) for operator inspection."""
    store = ArtifactStore(_db_or_503(request))
    ctx: AuthContext | None = resolve_context(request)
    if ctx is None:
        require_admin_auth(
            request,
            authorization=request.headers.get("Authorization"),
            x_admin_token=request.headers.get("X-Admin-Token"),
        )
        row = store.get(artifact_id)
        if row is None:
            raise APIError("E-NOT-FOUND", status_code=404)
        return row
    if store.is_referenced_for_user(artifact_id, _user_id(ctx)):
        row = store.get(artifact_id)
        if row is not None:
            return row
    # Unreferenced or unknown: 404 either way (§4.1 — no existence oracle).
    raise APIError("E-NOT-FOUND", status_code=404)


def _db_or_503(request: Request) -> Any:
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return db


def _sandbox_headers(response: Any, *, cacheable: bool) -> None:
    response.headers["Content-Security-Policy"] = (
        f"{ARTIFACT_HEADER_CSP}; {_FRAME_ANCESTORS}"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = CACHE_CONTROL_READY if cacheable else "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"


@router.get("/v1/personalized/artifacts/{artifact_id}")
def fetch_artifact(request: Request, artifact_id: str) -> Any:
    """API-PL-13: the sandboxed artifact document (or its 409 conflict state)."""
    # Resolve (not require) the account: a guest falls through to the
    # admin-token path below, which fails closed (401/503) — the outcome is
    # still an authentication error before any artifact question.
    resolve_context(request)
    row = _owner_or_admin(request, artifact_id)
    if row["status"] != "ready":
        # §4.8: the client shows the fallback/loader for a half-built artifact;
        # the HTML is withheld because there is nothing honest to render yet.
        response = JSONResponse(
            status_code=409,
            content={
                "code": "E-CONFLICT",
                "message_key": "error.conflict",
                "trace_id": getattr(request.state, "trace_id", ""),
                "retryable": True,
                "status": row["status"],
                "failure_reason": row["failure_reason"],
            },
        )
        _sandbox_headers(response, cacheable=False)
        return response
    store = ArtifactStore(_db_or_503(request))
    store.touch_last_used(artifact_id)
    html_response = HTMLResponse(content=str(row["html"] or ""))
    _sandbox_headers(html_response, cacheable=True)
    return html_response


@router.get("/v1/personalized/artifacts/{artifact_id}/status")
def artifact_status(request: Request, artifact_id: str) -> JSONResponse:
    """API-PL-14: pending/ready/failed — what the polling client needs, with
    no HTML and no artifact content.

    A `ready` response carries the server-issued `src` (data-and-api.md §4.8:
    the src is the only URL the viewer uses; there is no client-side URL
    construction). Same-origin mode serves the route path; dedicated-origin
    mode (D-PL-09) will issue the signed URL here instead — the viewer code
    does not change."""
    resolve_context(request)
    row = _owner_or_admin(request, artifact_id)
    payload: dict[str, Any] = {
        "artifact_id": str(row["artifact_id"]),
        "status": str(row["status"]),
        "kind": str(row["kind"]),
        "title": str(row["title"]),
    }
    if row["status"] == "ready":
        payload["src"] = f"/v1/personalized/artifacts/{artifact_id}"
    elif row["status"] == "failed":
        payload["failure_reason"] = row["failure_reason"]
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    return response
