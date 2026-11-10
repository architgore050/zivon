"""FastAPI modular monolith application factory (backend-spec §4.2/§4.3, ADR-0005)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import BackendConfig
from .errors import (
    APIError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .logging_shim import context_scope
from .voice_stub import mount_voice_channel

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def create_app(
    config: BackendConfig | None = None,
    *,
    db_engine: Any | None = None,
    credit_guard: Any | None = None,
) -> FastAPI:
    """Construct the Zivon core backend FastAPI application."""
    cfg = config or BackendConfig.from_env()
    app = FastAPI(
        title="zivon-core-backend",
        version=cfg.release_tag,
        docs_url="/v1/openapi/docs" if cfg.env == "dev" else None,
        redoc_url=None,
    )
    app.state.config = cfg
    app.state.db = db_engine
    app.state.guard = credit_guard

    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def trace_and_rate_limit_middleware(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        inbound_req_id = request.headers.get("X-Request-Id", "").strip()
        trace_id = (
            inbound_req_id if _UUID_RE.match(inbound_req_id) else str(uuid.uuid4())
        )
        request.state.trace_id = trace_id

        rate_limiter = getattr(app.state, "rate_limiter", None)
        if rate_limiter is not None:
            decision = rate_limiter.check_http_request(request)
            if not decision.allowed:
                err = APIError(
                    "E-RATE-LIMIT",
                    status_code=429,
                    retryable=True,
                    retry_after=decision.retry_after,
                )
                return await api_error_handler(request, err)

        with context_scope(request_id=trace_id):
            response: Response = await call_next(request)
            response.headers["X-Request-Id"] = trace_id
            return response

    @app.get("/healthz")
    def liveness_probe() -> JSONResponse:
        """Process liveness probe (skills/zivon-backend-engineering-skills §6)."""
        return JSONResponse(
            content={"ok": True, "status": "ok", "release": cfg.release_tag}
        )

    @app.get("/readyz")
    def readiness_probe() -> JSONResponse:
        """Readiness probe checking database connectivity when configured."""
        db = getattr(app.state, "db", None)
        if db is not None and hasattr(db, "ping") and not db.ping():
            return JSONResponse(
                status_code=503,
                content={"ok": False, "status": "degraded", "db": "unreachable"},
            )
        return JSONResponse(content={"ok": True, "status": "ok", "db": "ok"})

    _wire_components(app, cfg, db_engine=db_engine, credit_guard=credit_guard)

    app.state.voice_mount_mode = mount_voice_channel(app)
    return app


def _wire_components(
    app: FastAPI,
    cfg: BackendConfig,
    *,
    db_engine: Any | None = None,
    credit_guard: Any | None = None,
) -> None:
    """Lazy-wire database, guard, privacy, abuse limiter, and routers."""
    if db_engine is None:
        try:
            from db.engine import DatabaseEngine

            db_engine = DatabaseEngine.from_url(cfg.db_url, auto_migrate=True)
            app.state.db = db_engine
        except ImportError:
            pass

    if app.state.db is not None:
        from .logging_shim import register_db_sink

        register_db_sink(
            writer=getattr(app.state.db, "write_log_event", None),
            delete_hook=getattr(app.state.db, "delete_subject_logs", None),
        )

    if credit_guard is None and app.state.db is not None:
        try:
            from guard.service import CreditGuard

            credit_guard = CreditGuard(app.state.db)
            app.state.guard = credit_guard
        except ImportError:
            pass

    if app.state.db is not None:
        try:
            from .privacy import DeletionAndRetentionService

            app.state.privacy = DeletionAndRetentionService(app.state.db)
        except ImportError:
            pass

    try:
        from .identity import IdentityManager

        identity_mgr = IdentityManager(cfg, app.state.db)
        app.state.identity = identity_mgr
        app.state.verify_session_token = identity_mgr.verify_session_token
    except ImportError:
        pass

    try:
        from .abuse import AbuseRateLimiter

        app.state.rate_limiter = AbuseRateLimiter(cfg, app.state.db)
    except ImportError:
        pass

    try:
        from .routes import register_routes

        register_routes(app)
    except ImportError:

        @app.get("/v1/health")
        def fallback_v1_health() -> JSONResponse:
            return JSONResponse(
                content={
                    "status": "ok",
                    "db": "ok",
                    "schema_version": "0000",
                    "release": cfg.release_tag,
                    "guard_profile_mode": "normal",
                }
            )
