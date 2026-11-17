"""Web-shell routes. Feature workstreams add their own modules here."""

from __future__ import annotations

from fastapi import APIRouter

from .app import router as app_router
from .auth import router as auth_router
from .onboarding import router as onboarding_router
from .practice import router as practice_router
from .progress import router as progress_router
from .settings import router as settings_router

router = APIRouter()
router.include_router(app_router)
router.include_router(auth_router)
router.include_router(onboarding_router)
router.include_router(practice_router)
router.include_router(progress_router)
router.include_router(settings_router)

__all__ = ["router"]
