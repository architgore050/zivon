"""REST API route registration for the Zivon core backend monolith."""

from __future__ import annotations

from fastapi import FastAPI

from .admin import router as admin_router
from .auth import router as auth_router
from .catalog import router as catalog_router
from .me import router as me_router
from .practice import router as practice_router
from .progress import router as progress_router
from .speaking import router as speaking_router
from .student import router as student_router
from .swot import router as swot_router
from .tests import router as tests_router


def register_routes(app: FastAPI) -> None:
    """Mount student, account/auth, catalogue, progress, practice, speaking, swot, tests,
    admin, and personalized."""
    app.include_router(student_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(catalog_router)
    app.include_router(progress_router)
    app.include_router(practice_router)
    app.include_router(speaking_router)
    app.include_router(swot_router)
    app.include_router(tests_router)
    app.include_router(admin_router)
    # Personalized learning (W5.5 PL1): preferences live under /v1/me, the
    # session surface under /v1/personalized (data-and-api.md §4.2). Imported
    # lazily: the personalized router reuses this package's auth helpers, so
    # an eager import here would be circular.
    # PL3 (API-PL-13/14): the artifact fetch/status routes live in their own
    # module — same lazy mount, same auth helpers.
    from ..personalized.artifact_router import router as artifact_router
    from ..personalized.router import (
        preferences_router as personalized_preferences_router,
    )
    from ..personalized.router import router as personalized_router

    # PL2: the teaching turn (API-PL-10, SSE) is its own router module,
    # mounted after the session router so it owns the /turns path.
    from ..personalized.turn_router import router as personalized_turn_router

    app.include_router(personalized_preferences_router)
    app.include_router(personalized_router)
    app.include_router(personalized_turn_router)
    app.include_router(artifact_router)
