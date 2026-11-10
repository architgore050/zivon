"""Container and CLI entry point: `python -m backend`.

Uses `ZIVON_BACKEND_HOST` (default `0.0.0.0`) and `ZIVON_BACKEND_PORT`
(default `8000`) to avoid K8s legacy service-link collisions (`gotcha 16`).
Supports `--smoke` for the container smoke test in CI and Kubernetes Jobs.
"""

from __future__ import annotations

import os
import sys

import uvicorn

from .app import create_app
from .config import BackendConfig


def run_smoke_check() -> int:
    """Execute an in-process self-test of the backend app shell and DB."""
    cfg = BackendConfig(db_url="sqlite:///:memory:", env="dev")
    app = create_app(cfg)
    if app.title != "zivon-core-backend":
        raise RuntimeError("Unexpected app title")
    print("[smoke] zivon-core-backend app factory initialized ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--smoke" in args:
        return run_smoke_check()
    if "--help" in args or "-h" in args:
        print("usage: python -m backend [--smoke]")
        return 0

    # Config via env only, no silent defaults (repo rule; CI's
    # refuse-without-config smoke gate): the long-running server must be told
    # which environment it is in. ZIVON_DB_URL keeps its documented dev
    # fallback once ZIVON_ENV=dev is explicit, but a bare container refuses.
    if not os.environ.get("ZIVON_ENV", "").strip():
        print(
            "config error: ZIVON_ENV is required (dev|cluster|prod); "
            "the server never boots on implicit defaults — set ZIVON_ENV "
            "and ZIVON_DB_URL from the environment",
            file=sys.stderr,
        )
        return 2

    strict = os.environ.get("ZIVON_ENV", "dev").strip() in ("cluster", "prod")
    cfg = BackendConfig.from_env(strict_secrets=strict)
    app = create_app(cfg)
    host = os.environ.get("ZIVON_BACKEND_HOST", "0.0.0.0")
    port = int(os.environ.get("ZIVON_BACKEND_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
