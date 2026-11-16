"""Account auth endpoints under `/v1/auth/*` (REQUIREMENTS §9.1, ADR-0029).

HTTP translation only: request models, cookie/CSRF handling, and status codes.
All security decisions live in `backend/auth/service.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict

from ..auth.service import AuthContext, AuthService, SessionGrant
from ..auth.tokens import request_ip_hash_from_request, user_agent_hash
from ..config import BackendConfig
from ..errors import APIError

router = APIRouter(prefix="/v1/auth", tags=["auth"])

OAUTH_STATE_COOKIE = "zivon_oauth_state"
OAUTH_STATE_COOKIE_PATH = "/v1/auth/google"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    display_name: str | None = None
    class_level: int | None = None
    board: str = "CBSE"
    language: str = "en-IN"
    device_pseudo_id: str | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    device_pseudo_id: str | None = None


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    new_password: str


def _service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth", None)
    if service is None:
        raise APIError("E-SERVICE-UNAVAILABLE", status_code=503)
    return service


def _config(request: Request) -> BackendConfig:
    return request.app.state.config


def resolve_context(request: Request) -> AuthContext | None:
    """Resolve the account cookie; None means guest (not an error)."""
    service = _service(request)
    raw = request.cookies.get(_config(request).auth_cookie_name)
    return service.resolve(raw)


def require_context(request: Request) -> AuthContext:
    ctx = resolve_context(request)
    if ctx is None:
        raise APIError("E-AUTH-REQUIRED", status_code=401)
    return ctx


def require_csrf(request: Request, ctx: AuthContext) -> None:
    service = _service(request)
    header = request.headers.get("X-CSRF-Token")
    if not service.verify_csrf(ctx, header):
        raise APIError("E-AUTH-CSRF", status_code=403)


def _set_session_cookie(
    response: Response, config: BackendConfig, grant: SessionGrant
) -> None:
    response.set_cookie(
        key=config.auth_cookie_name,
        value=grant.raw_token,
        max_age=config.auth_session_ttl_seconds,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        path="/",
        domain=config.auth_cookie_domain,
    )


def _clear_session_cookie(response: Response, config: BackendConfig) -> None:
    response.delete_cookie(
        key=config.auth_cookie_name,
        path="/",
        domain=config.auth_cookie_domain,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
    )


def _auth_json(
    request: Request,
    service: AuthService,
    grant: SessionGrant,
    *,
    status_code: int = 200,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code, content=service.grant_payload(grant)
    )
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, _config(request), grant)
    return response


@router.post("/register")
def register(body: RegisterRequest, request: Request) -> JSONResponse:
    """Create the one account for this email, sign in, and send a verify mail."""
    service = _service(request)
    config = _config(request)
    service.check_rate_limit("register", request_ip_hash_from_request(config, request))
    grant = service.register(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        class_level=body.class_level,
        board=body.board,
        language=body.language,
        device_pseudo_id=body.device_pseudo_id,
        ip_hash=request_ip_hash_from_request(config, request),
        user_agent_hash=user_agent_hash(config, request.headers.get("User-Agent")),
    )
    return _auth_json(request, service, grant, status_code=201)


@router.post("/login")
def login(body: LoginRequest, request: Request) -> JSONResponse:
    """Email + password login. Wrong password and unknown email look identical."""
    service = _service(request)
    config = _config(request)
    service.check_rate_limit("login", request_ip_hash_from_request(config, request))
    grant = service.login(
        email=body.email,
        password=body.password,
        device_pseudo_id=body.device_pseudo_id,
        ip_hash=request_ip_hash_from_request(config, request),
        user_agent_hash=user_agent_hash(config, request.headers.get("User-Agent")),
    )
    return _auth_json(request, service, grant)


@router.post("/logout")
def logout(request: Request) -> JSONResponse:
    """Revoke the current session and clear the cookie (idempotent)."""
    service = _service(request)
    config = _config(request)
    raw = request.cookies.get(config.auth_cookie_name)
    ctx = service.resolve(raw)
    if ctx is not None:
        require_csrf(request, ctx)
        service.revoke_session(str(ctx.session["session_id"]))
    response = JSONResponse(content={"ok": True})
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response, config)
    return response


@router.get("/session")
def session(request: Request) -> JSONResponse:
    """Probe the current account session. Guests get `authenticated: false`."""
    service = _service(request)
    raw = request.cookies.get(_config(request).auth_cookie_name)
    ctx = service.resolve(raw)
    response = JSONResponse(content=service.session_payload(ctx, raw))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/verify-email")
def verify_email(body: TokenRequest, request: Request) -> JSONResponse:
    service = _service(request)
    config = _config(request)
    service.check_rate_limit("verify", request_ip_hash_from_request(config, request))
    return JSONResponse(content=service.verify_email(body.token))


@router.post("/request-password-reset")
def request_password_reset(body: ResetRequest, request: Request) -> Response:
    """Always 202: the response never reveals whether the address exists."""
    service = _service(request)
    config = _config(request)
    service.check_rate_limit("reset", request_ip_hash_from_request(config, request))
    service.request_password_reset(body.email)
    return JSONResponse(status_code=202, content={"ok": True})


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, request: Request) -> JSONResponse:
    service = _service(request)
    config = _config(request)
    service.check_rate_limit("reset", request_ip_hash_from_request(config, request))
    result = service.reset_password(token=body.token, new_password=body.new_password)
    response = JSONResponse(content=result)
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response, config)
    return response


@router.get("/google/start")
def google_start(
    request: Request,
    intent: str = "login",
    next: str = "/app",
) -> Response:
    """Redirect to Google with signed state + PKCE. 503 when unconfigured."""
    service = _service(request)
    config = _config(request)
    service.check_rate_limit("google", request_ip_hash_from_request(config, request))
    current = resolve_context(request)
    url, state_cookie = service.google_start(
        intent=intent, next_path=next, current=current
    )
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state_cookie,
        max_age=600,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        path=OAUTH_STATE_COOKIE_PATH,
        domain=config.auth_cookie_domain,
    )
    return response


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
) -> Response:
    """Finish the Google flow and redirect back into the app.

    Failures redirect to `/login?error=<code>`; the browser flow never renders
    a raw JSON error page, and no account detail crosses the redirect.
    """
    service = _service(request)
    config = _config(request)
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    try:
        service.check_rate_limit(
            "google", request_ip_hash_from_request(config, request)
        )
        result = service.google_callback(
            code=code,
            state=state,
            state_cookie=state_cookie,
            current=resolve_context(request),
            ip_hash=request_ip_hash_from_request(config, request),
            user_agent_hash=user_agent_hash(config, request.headers.get("User-Agent")),
        )
    except APIError as exc:
        response = RedirectResponse(url=f"/login?error={exc.code}", status_code=303)
        response.delete_cookie(
            key=OAUTH_STATE_COOKIE,
            path=OAUTH_STATE_COOKIE_PATH,
            domain=config.auth_cookie_domain,
        )
        return response
    response = RedirectResponse(url=result.next_path, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, config, result.grant)
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        path=OAUTH_STATE_COOKIE_PATH,
        domain=config.auth_cookie_domain,
    )
    return response
