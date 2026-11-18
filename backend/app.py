"""FastAPI modular monolith application factory (backend-spec §4.2/§4.3, ADR-0005)."""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from voice.config import VoiceSettings
from voice.ws_api import mount_voice
from web import mount_web

from .config import BackendConfig
from .errors import (
    APIError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .logging_shim import context_scope

logger = logging.getLogger(__name__)

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
    app.state.db_boot_error = None
    app.state.auth = None
    # Personalized learning (W5.5 PL1): the teaching turn and the RAG-backed
    # catalog stay honest 503s until PL2 injects these seams.
    app.state.personalized_turn_engine = None
    app.state.personalized_index_catalog = None

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
        db_boot_error = getattr(app.state, "db_boot_error", None)
        if db_boot_error is not None:
            # The process is alive (liveness stays green) but it booted without
            # its database, so it must not receive traffic until redeployed/
            # fixed. Never report "ok" for a store that failed to initialize.
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "status": "degraded",
                    "db": "boot_failed",
                    "error_class": db_boot_error,
                },
            )
        db = getattr(app.state, "db", None)
        if db is not None and hasattr(db, "ping") and not db.ping():
            return JSONResponse(
                status_code=503,
                content={"ok": False, "status": "degraded", "db": "unreachable"},
            )
        return JSONResponse(content={"ok": True, "status": "ok", "db": "ok"})

    _wire_components(app, cfg, db_engine=db_engine, credit_guard=credit_guard)

    # The voice loop (ADR-0020): voice/ mounts into this monolith. Settings come
    # from the ZIVON_VOICE_* env family; the session-token/IP-salt secrets fall
    # back to the backend's own config so both halves verify the same tokens.
    # Profile is SERVER-asserted (ws-contract §2, spec.md §11): the judged demo
    # link sets ZIVON_VOICE_PROFILE=demo so judge traffic gets the bounded demo
    # tranche instead of the 30-credit free-trial cap. The client can never
    # claim it.
    demo_profile = (
        os.environ.get("ZIVON_VOICE_PROFILE", "normal").strip().lower() == "demo"
    )
    app.state.voice = mount_voice(
        app,
        settings=_voice_settings(cfg),
        profile_for=(lambda _identity: "demo") if demo_profile else None,
    )
    _wire_voice_personal_instructions(app, cfg)

    # The server-rendered consumer shell (`/app`, and later the auth/app pages
    # from F2/F3/F5/F6/F7). It is HTML only: the JSON API stays under /v1 and
    # the voice loop under /voice. Mounted last (after the API routers and the
    # voice mount) so the shell can never shadow either (`web/` has no
    # catch-all route).
    mount_web(app)
    return app


def _voice_settings(cfg: BackendConfig) -> VoiceSettings:
    """Voice settings from the environment, sharing the backend's auth secrets."""
    settings = VoiceSettings.from_env()
    overrides: dict[str, Any] = {}
    if not settings.session_token_key:
        overrides["session_token_key"] = cfg.session_token_key
    if not settings.ip_hash_salt:
        overrides["ip_hash_salt"] = cfg.ip_hash_salt
    return dataclasses.replace(settings, **overrides) if overrides else settings


def _wire_voice_personal_instructions(app: FastAPI, cfg: BackendConfig) -> None:
    """PL1 voice injection (data-and-api.md §5.1): resolve the account cookie on
    the voice WS and hand the tutor the sanitized personal-instructions block.

    Additive (ADR-0029 rule): a broken auth or store leaves the voice loop
    untouched — the resolver is simply not wired and every session behaves as
    a guest (no block, byte-identical prompts)."""
    if app.state.auth is None or app.state.db is None:
        return
    try:
        from .personalized.preferences import build_voice_preferences_resolver

        voice_app = app.state.voice
        voice_app.preferences_for = build_voice_preferences_resolver(
            app.state.auth, app.state.db
        )
        voice_app.account_cookie_name = cfg.auth_cookie_name
    except Exception as exc:  # noqa: BLE001 — same additive posture as the auth seam
        logger.warning(
            "personal-instructions injection not wired (%s); the voice tutor "
            "runs without the personal block",
            type(exc).__name__,
        )


def _wire_personalized_agent(app: FastAPI, cfg: BackendConfig) -> None:
    """PL2 boot wiring (agent-and-rag.md §6.4/§7.3): load the newest valid RAG
    index, build the query embedder, and wire the teaching-turn engine.

    Honest degradation (§7.5): no index ⇒ the catalog seam stays None (the
    routes answer 503 E-CONTENT-UNAVAILABLE and the turn engine is not wired);
    an unavailable embedding backend ⇒ lexical retrieval fallback, marked on
    every turn; the turn engine is wired only when the DeepSeek route is
    fully configured (`BackendConfig` already refuses an incomplete route at
    boot)."""
    if app.state.db is None:
        return
    from pathlib import Path

    from .logging_shim import ErrorClass as _ErrorClass
    from .logging_shim import log_event

    index_dir = cfg.personalized_index_dir or str(
        Path(cfg.runs_dir) / "personalized-index"
    )
    index = None
    embedder = None
    try:
        from .personalized.rag import RagIndex

        root = Path(index_dir)
        if root.is_dir():
            versions = sorted(
                (d for d in root.iterdir() if d.is_dir()),
                key=lambda d: d.name,
                reverse=True,
            )
            for version_dir in versions:
                try:
                    index = RagIndex.load(version_dir)
                    break
                except Exception as exc:  # noqa: BLE001 — try the next version
                    logger.warning(
                        "personalized index version %s refused to load (%s)",
                        version_dir.name,
                        type(exc).__name__,
                    )
            if index is not None:
                log_event(
                    "personalized.index.loaded",
                    {
                        "index_version": index.version,
                        "chunk_count": index.manifest.get("chunk_count"),
                    },
                )
            else:
                log_event(
                    "personalized.index.missing",
                    {},
                    error_class=_ErrorClass.INFRA_ERROR,
                )
        else:
            log_event(
                "personalized.index.missing",
                {},
                error_class=_ErrorClass.INFRA_ERROR,
            )
    except ImportError:
        return
    if index is not None:
        try:
            from .personalized.rag import get_embedder

            embedder = get_embedder("intfloat/multilingual-e5-small")
        except Exception as exc:  # noqa: BLE001 — §7.5.5 lexical fallback
            logger.warning(
                "embedding backend unavailable (%s); personalized retrieval "
                "runs in the marked lexical fallback",
                type(exc).__name__,
            )
            embedder = None
        from .personalized.rag import RetrievalPorts

        retrieval = RetrievalPorts(index=index, embedder=embedder)
        app.state.personalized_retrieval = retrieval
        app.state.personalized_index_catalog = index.catalog

    if not cfg.personalized_turn_engine_enabled or index is None:
        return
    try:
        from .personalized.agent import LLMManagerClient, PersonalizedAgent
        from .personalized.bank import QuestionBank
        from .personalized.store import PersonalizedStore

        store = PersonalizedStore(app.state.db)
        app.state.personalized_turn_engine = PersonalizedAgent(
            store=store,
            config=cfg,
            retrieval=app.state.personalized_retrieval,
            model_client=LLMManagerClient(cfg),
            bank=QuestionBank(app.state.db),
        )
    except Exception as exc:
        logger.exception(
            "personalized turn engine not wired (%s); the turn endpoint "
            "answers 503 E-PL-MODEL-DOWN",
            type(exc).__name__,
        )


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
            app.state.db_boot_error = None
        except ImportError:
            app.state.db_boot_error = None
        except Exception as exc:
            # Liveness is a process check (backend-spec §6): a dead database
            # must not make /healthz unreachable (the k8s liveness probe would
            # kill-loop a healthy process while Postgres restarts). Record the
            # failure loudly, serve /healthz, and fail /readyz 503 until fixed.
            logger.exception(
                "database initialization failed at boot (%s); "
                "serving liveness only, readiness is degraded",
                type(exc).__name__,
            )
            app.state.db_boot_error = type(exc).__name__

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

    # Account auth is additive (ADR-0029): a broken email/Google config must not
    # take the guest voice stack down with it, so the failure is loud in the log
    # and the /v1/auth + /v1/me routes answer 503 until it is fixed.
    if app.state.db is not None:
        try:
            from .auth.email import build_email_sender
            from .auth.service import AuthService

            app.state.auth = AuthService(
                cfg, app.state.db, email_sender=build_email_sender(cfg)
            )
        except ImportError:
            app.state.auth = None
        except Exception as exc:
            logger.exception(
                "account auth disabled at boot (%s); /v1/auth and /v1/me will "
                "answer 503",
                type(exc).__name__,
            )
            app.state.auth = None

    try:
        from .abuse import AbuseRateLimiter

        app.state.rate_limiter = AbuseRateLimiter(cfg, app.state.db)
    except ImportError:
        pass

    # Personalized learning PL2 (D-PL-07/ADR-0030): the RAG index + the
    # teaching-turn engine. Additive by contract: a missing index or an
    # unavailable embedder leaves the honest 503 seams in place (§7.5).
    _wire_personalized_agent(app, cfg)

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
