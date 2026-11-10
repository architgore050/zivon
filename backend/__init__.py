"""Zivon core backend monolith package (ADR-0005).

Exposes `create_app` for the FastAPI modular monolith (`zivon-backend`).
"""

from __future__ import annotations

from .app import create_app
from .config import BackendConfig, BackendConfigError

__all__ = [
    "BackendConfig",
    "BackendConfigError",
    "create_app",
]
