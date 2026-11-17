"""Server-rendered web shell for the Zivon consumer app (F0 foundation).

`web/` owns the FastAPI routers, the Jinja2 environment, and the shared
templates that `/app/*` pages use. Feature workstreams add their routes and
templates under this package (F2 auth, F3 dashboard/progress, F5 practice,
F6 speaking, F7 tests/series); this module only mounts the shell.

Public pages (landing, catalogue, lessons) stay static in `frontend/`. The
shell renders the base Field Notes §1-§9 identity from F1's
`frontend/assets/product.css` and never the §10 lesson devices
(`docs/frontend/design-doctrine.md` §0).
"""

from __future__ import annotations

from .mount import mount_web

__all__ = ["mount_web"]
