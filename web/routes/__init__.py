"""Web-shell routes. Feature workstreams add their own modules here."""

from __future__ import annotations

from fastapi import APIRouter

from .app import router as app_router

router = APIRouter()
router.include_router(app_router)

__all__ = ["router"]
