"""Zivon core backend monolith package (ADR-0005).

Exposes `create_app` for the FastAPI modular monolith (`zivon-backend`).

`create_app` is resolved lazily (PEP 562): the application factory imports the
`web` shell, and the shell's auth pages import backend modules, so an eager
`from .app import create_app` here would make `import web` fail with a circular
import depending on which side was imported first. `from backend import
create_app` and `backend.create_app` both still work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import BackendConfig, BackendConfigError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .app import create_app

__all__ = [
    "BackendConfig",
    "BackendConfigError",
    "create_app",
]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
