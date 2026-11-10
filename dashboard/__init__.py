"""dashboard: the admin dashboard v0 (dashboard-spec.md, ADR-0026 auth).

Small FastAPI app + static UI; builds via Dockerfile.dashboard, deploys as
k8s/23 (Deployment) + k8s/24 (ClusterIP Service). Public entry point:

    from dashboard import create_app
    app = create_app()
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
