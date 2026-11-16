"""Account self-service endpoints under `/v1/me/*` (REQUIREMENTS §9.2).

Every state-changing call requires the `X-CSRF-Token` header value returned by
register/login/session. Deleting the account also clears the cookie.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..auth.tokens import request_ip_hash_from_request, user_agent_hash
from ..config import BackendConfig
from .auth import (
    _auth_json,
    _clear_session_cookie,
    _config,
    _service,
    require_context,
    require_csrf,
)

router = APIRouter(prefix="/v1/me", tags=["account"])


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    class_level: int | None = None
    board: str | None = None
    language: str | None = None


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str | None = None
    new_password: str


class DeleteAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str
    password: str | None = None


class AttachDevice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_pseudo_id: str


@router.get("")
def get_profile(request: Request) -> JSONResponse:
    service = _service(request)
    ctx = require_context(request)
    response = JSONResponse(content=service.profile_payload(ctx))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.patch("")
def patch_profile(body: ProfilePatch, request: Request) -> JSONResponse:
    service = _service(request)
    ctx = require_context(request)
    require_csrf(request, ctx)
    patch: dict[str, Any] = body.model_dump(exclude_unset=True)
    user = service.update_profile(user_id=str(ctx.user["user_id"]), patch=patch)
    response = JSONResponse(content=service.profile_payload_for_user(user))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/password")
def change_password(body: PasswordChange, request: Request) -> JSONResponse:
    """Set (Google-created account) or change the password; rotates the session."""
    service = _service(request)
    config: BackendConfig = _config(request)
    ctx = require_context(request)
    require_csrf(request, ctx)
    grant = service.set_or_change_password(
        ctx=ctx,
        current_password=body.current_password,
        new_password=body.new_password,
        ip_hash=request_ip_hash_from_request(config, request),
        user_agent_hash=user_agent_hash(config, request.headers.get("User-Agent")),
    )
    return _auth_json(request, service, grant)


@router.post("/delete")
def delete_account(body: DeleteAccount, request: Request) -> JSONResponse:
    service = _service(request)
    ctx = require_context(request)
    require_csrf(request, ctx)
    deleted = service.delete_account(
        ctx=ctx, confirm=body.confirm, password=body.password
    )
    response = JSONResponse(content={"ok": True, "deleted": deleted})
    response.headers["Cache-Control"] = "no-store"
    _clear_session_cookie(response, _config(request))
    return response


@router.get("/export")
def export_account(request: Request) -> JSONResponse:
    service = _service(request)
    ctx = require_context(request)
    payload = service.export_account(user_id=str(ctx.user["user_id"]))
    response = JSONResponse(content=payload)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="zivon-export-{ctx.user["user_id"]}.json"'
    )
    return response


@router.post("/device")
def attach_device(body: AttachDevice, request: Request) -> JSONResponse:
    """Link a pseudonymous voice device to the signed-in account."""
    service = _service(request)
    ctx = require_context(request)
    require_csrf(request, ctx)
    service.attach_device(
        user_id=str(ctx.user["user_id"]),
        device_pseudo_id=body.device_pseudo_id,
    )
    return JSONResponse(content={"ok": True, "device_pseudo_id": body.device_pseudo_id})
