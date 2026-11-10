"""REST API route registration for the Zivon core backend monolith."""

from __future__ import annotations

from fastapi import FastAPI

from .admin import router as admin_router
from .student import router as student_router


def register_routes(app: FastAPI) -> None:
    """Mount student (`/v1/*`, `/api/v1/*`) and admin (`/v1/admin/*`) routers."""
    app.include_router(student_router)
    app.include_router(admin_router)
