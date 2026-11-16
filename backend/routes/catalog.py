"""`/v1/catalog` stub (REQUIREMENTS §9.3; P1/P2 fill the DB, F1/F3 consume it)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..catalog.store import catalogue, chapter_detail
from ..errors import APIError

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


def _db(request: Request):
    return getattr(request.app.state, "db", None)


@router.get("")
def get_catalogue(request: Request) -> JSONResponse:
    """Classes 9–12 with chapters, status, languages, and lesson links."""
    response = JSONResponse(content=catalogue(_db(request)))
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@router.get("/chapters/{slug}")
def get_chapter(slug: str, request: Request) -> JSONResponse:
    detail = chapter_detail(_db(request), slug)
    if detail is None:
        raise APIError("E-NOT-FOUND", status_code=404)
    response = JSONResponse(content=detail)
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
