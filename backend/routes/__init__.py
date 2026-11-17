"""REST API route registration for the Zivon core backend monolith."""

from __future__ import annotations

from fastapi import FastAPI

from .admin import router as admin_router
from .auth import router as auth_router
from .catalog import router as catalog_router
from .me import router as me_router
from .practice import router as practice_router
from .progress import router as progress_router
from .student import router as student_router


def register_routes(app: FastAPI) -> None:
    """Mount student, account/auth, catalogue, progress, practice, and admin routers."""
    app.include_router(student_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(catalog_router)
    app.include_router(progress_router)
    app.include_router(practice_router)
    app.include_router(admin_router)
