"""`/app/settings` and `/app/settings/privacy` (F2, REQUIREMENTS §10.21).

The student's own account screen. It renders the profile through the F0 shell
and changes it through the F0 account service (`update_profile`,
`set_or_change_password`, `delete_account`); export is the existing
`GET /v1/me/export` download. Every state-changing form verifies the
session-derived CSRF token with `AuthService.verify_csrf`.

The account email appears here, on the student's own authenticated page,
because the screen must answer "which identity am I signed in as?"
(REQUIREMENTS §10.21). It is passed to this template only; the shared shell
(`ShellUser`) still never carries an email, so `/app` and every other page
remain free of account identifiers.
"""

from __future__ import annotations

from functools import partial
from typing import Final
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from backend.auth import AuthService
from backend.auth.tokens import request_ip_hash_from_request, user_agent_hash
from backend.config import BackendConfig
from backend.errors import APIError
from backend.personalized.preferences import get_preferences_row  # PL4: C22 field

from ..context import FlashMessage, LoginRequired
from ..flow import (
    BOARD_CHOICES,
    CLASS_CHOICES,
    LANGUAGE_CHOICES,
    PageAccount,
    account_shell,
    config_for,
    notice,
    page_account,
    password_reason_copy,
    rate_limit_copy,
    redirect_and_clear_session,
    redirect_with_session,
    render_error_page,
    retry_after_seconds,
    validation_copy,
)
from ..forms import FormBadEncoding, FormTooLarge, read_form
from ..render import render_page

router = APIRouter(tags=["web"])

SETTINGS_PATH: Final[str] = "/app/settings"
PRIVACY_PATH: Final[str] = "/app/settings/privacy"
SETTINGS_TITLE: Final[str] = "Settings"
PRIVACY_TITLE: Final[str] = "Privacy and data"
_FORM_EXPIRED_TEXT: Final[str] = (
    "Reload the page and submit again. If it keeps happening, check that this "
    "browser allows cookies for Zivon."
)


# -- view model -------------------------------------------------------------


def _settings_values(
    service: AuthService,
    account: PageAccount,
    config: BackendConfig,
    *,
    form: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
    password_error: str | None = None,
    delete_error: str | None = None,
) -> dict[str, object]:
    payload = service.profile_payload_for_user(account.context.user)
    public = payload["user"]
    # PL4 (personalized learning): the account's own personal instructions
    # (C22) feed the included `personal_instructions` partial. A missing row
    # renders the empty state; no other field or row is exposed here.
    prefs_row = get_preferences_row(service.db, str(account.context.user["user_id"]))
    personal_instructions = (
        str(prefs_row.get("personal_instructions") or "") if prefs_row else ""
    )
    # The template gets an explicit allow-list, never the user row or
    # `user_id`; the settings page only needs the fields it renders.
    profile = {
        "email": public["email"],
        "email_verified": public["email_verified"],
        "display_name": public.get("display_name"),
        "class_level": public.get("class_level"),
        "board": public.get("board"),
        "language": public.get("language"),
    }
    board = str(profile.get("board") or "CBSE")
    board_options = list(BOARD_CHOICES)
    if board not in board_options:
        board_options.append(board)
    language = str(profile.get("language") or "en-IN")
    language_options = list(LANGUAGE_CHOICES)
    if language not in {value for value, _ in language_options}:
        # A locale saved through `/v1/me` (e.g. `ta-IN`) keeps its value here
        # instead of re-saving the first option when another field changes.
        language_options.append((language, language))
    return {
        "profile": profile,
        "personal_instructions": personal_instructions,
        "password_set": bool(payload["password_set"]),
        "google_linked": bool(payload["google_linked"]),
        "google_available": bool(
            config.google_client_id and config.google_client_secret
        ),
        "google_link_href": (
            "/v1/auth/google/start?intent=link&next="
            + quote(f"{SETTINGS_PATH}?linked=1", safe="")
        ),
        "class_choices": CLASS_CHOICES,
        "board_choices": tuple(board_options),
        "language_choices": tuple(language_options),
        "form": form
        or {
            "display_name": str(profile.get("display_name") or ""),
            "class_level": str(profile.get("class_level") or ""),
            "board": board,
            "language": language,
        },
        "field_errors": field_errors or {},
        "password_error": password_error,
        "delete_error": delete_error,
    }


def _flash(request: Request) -> tuple[FlashMessage, ...]:
    saved = (request.query_params.get("saved") or "").strip()
    messages = {
        "profile": "Profile saved.",
        "password": "Password updated. Other devices were signed out.",
    }
    if saved in messages:
        return (notice(messages[saved]),)
    if request.query_params.get("verified"):
        return (notice("Email verified."),)
    if request.query_params.get("linked"):
        return (notice("Google is now connected to this account."),)
    return ()


def _require_account(request: Request) -> PageAccount:
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    return account


async def _read_or_error(request: Request) -> dict[str, str] | HTMLResponse:
    try:
        return await read_form(request)
    except (FormBadEncoding, FormTooLarge):
        return render_error_page(
            request,
            status_code=400,
            title="That form did not arrive",
            message="Go back, reload the page, and submit again.",
        )


def _csrf_error(request: Request) -> HTMLResponse:
    return render_error_page(
        request,
        status_code=403,
        title="This form expired",
        message=_FORM_EXPIRED_TEXT,
    )


def _reason(exc: APIError) -> str | None:
    value = exc.extra.get("reason")
    return str(value) if value is not None else None


def _canonical_language(value: str) -> str | None:
    return {
        "en-IN": "en-IN",
        "hi-IN": "hi-IN",
        "hinglish": "hinglish",
        "hi-Latn": "hinglish",
    }.get(value.strip())


def _parse_class(value: str) -> int | None:
    try:
        level = int(value.strip())
    except (TypeError, ValueError):
        return None
    return level if level in CLASS_CHOICES else None


# -- profile and security ---------------------------------------------------


@router.get(SETTINGS_PATH, response_class=HTMLResponse, include_in_schema=False)
def settings_page(request: Request) -> Response:
    account = _require_account(request)
    values = _settings_values(account.service, account, config_for(request))
    return render_page(
        request,
        "app/settings.html",
        shell=account_shell(request, account, SETTINGS_TITLE, flash=_flash(request)),
        extra=values,
    )


@router.post(SETTINGS_PATH, response_class=HTMLResponse, include_in_schema=False)
async def settings_profile_submit(request: Request) -> Response:
    """Display name, class, board, and language through `update_profile`."""
    account = _require_account(request)
    config = config_for(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)

    board = (form.get("board") or "").strip()
    raw_language = (form.get("language") or "").strip()
    language = _canonical_language(raw_language)
    if language is None and raw_language == str(
        account.context.user.get("language") or ""
    ):
        # A locale saved through `/v1/me` (e.g. `ta-IN`) is not one of the three
        # shipped UI choices; keeping it unchanged is allowed, picking another
        # unsupported value is not.
        language = raw_language
    class_level = _parse_class(form.get("class_level") or "")
    display_name = (form.get("display_name") or "").strip()
    field_errors: dict[str, str] = {}
    if len(display_name) > 80:
        field_errors["display_name"] = validation_copy("display_name_too_long")
    if class_level is None:
        field_errors["class_level"] = "Choose your class."
    if not board:
        field_errors["board"] = "Choose your board."
    if language is None:
        field_errors["language"] = "Choose English, Hindi, or Hinglish."
    values = {
        "display_name": display_name,
        "class_level": form.get("class_level") or "",
        "board": board,
        "language": raw_language,
    }
    if field_errors:
        return render_page(
            request,
            "app/settings.html",
            shell=account_shell(
                request,
                account,
                SETTINGS_TITLE,
                error="Check the highlighted fields.",
            ),
            status_code=422,
            extra=_settings_values(
                account.service,
                account,
                config,
                form=values,
                field_errors=field_errors,
            ),
        )

    try:
        await run_in_threadpool(
            partial(
                account.service.update_profile,
                user_id=str(account.context.user["user_id"]),
                patch={
                    "display_name": display_name,
                    "class_level": class_level,
                    "board": board,
                    "language": language,
                },
            )
        )
    except APIError as exc:
        return render_page(
            request,
            "app/settings.html",
            shell=account_shell(
                request,
                account,
                SETTINGS_TITLE,
                error=(
                    rate_limit_copy(exc)
                    if exc.code == "E-RATE-LIMIT"
                    else validation_copy(_reason(exc))
                ),
            ),
            status_code=429 if exc.code == "E-RATE-LIMIT" else 422,
            extra=_settings_values(account.service, account, config, form=values),
        )
    return RedirectResponse(url=f"{SETTINGS_PATH}?saved=profile", status_code=303)


@router.post(
    "/app/settings/password", response_class=HTMLResponse, include_in_schema=False
)
async def settings_password_submit(request: Request) -> Response:
    """Set (Google-created account) or change the password; rotates the session."""
    account = _require_account(request)
    config = config_for(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)

    payload = account.service.profile_payload_for_user(account.context.user)
    password_set = bool(payload["password_set"])
    current_password = form.get("current_password") or None
    new_password = form.get("new_password") or ""
    confirm = form.get("confirm_password") or ""
    error: str | None = None
    if password_set and not current_password:
        error = "Enter your current password."
    elif not new_password:
        error = "Choose a new password."
    elif len(new_password) < 10:
        error = password_reason_copy("too_short")
    elif confirm != new_password:
        error = "The two passwords do not match."
    if error is not None:
        return render_page(
            request,
            "app/settings.html",
            shell=account_shell(request, account, SETTINGS_TITLE),
            status_code=422,
            extra=_settings_values(
                account.service, account, config, password_error=error
            ),
        )

    try:
        grant = await run_in_threadpool(
            partial(
                account.service.set_or_change_password,
                ctx=account.context,
                current_password=current_password,
                new_password=new_password,
                ip_hash=request_ip_hash_from_request(config, request),
                user_agent_hash=user_agent_hash(
                    config, request.headers.get("User-Agent")
                ),
            )
        )
    except APIError as exc:
        if exc.code == "E-AUTH-INVALID":
            message = "Your current password is wrong. Nothing was changed."
            status = 401
        elif exc.code == "E-VALIDATION":
            message = password_reason_copy(_reason(exc))
            status = 422
        elif exc.code == "E-RATE-LIMIT":
            message = rate_limit_copy(exc)
            status = 429
        else:
            message = "The password could not be changed. Nothing was changed."
            status = 503 if exc.code == "E-SERVICE-UNAVAILABLE" else 400
        response = render_page(
            request,
            "app/settings.html",
            shell=account_shell(request, account, SETTINGS_TITLE),
            status_code=status,
            extra=_settings_values(
                account.service, account, config, password_error=message
            ),
        )
        if exc.code == "E-RATE-LIMIT":
            response.headers["Retry-After"] = str(retry_after_seconds(exc))
        return response
    return redirect_with_session(config, grant, f"{SETTINGS_PATH}?saved=password")


# -- privacy and data -------------------------------------------------------


@router.get(PRIVACY_PATH, response_class=HTMLResponse, include_in_schema=False)
def settings_privacy_page(request: Request) -> Response:
    account = _require_account(request)
    return render_page(
        request,
        "app/settings_privacy.html",
        shell=account_shell(request, account, PRIVACY_TITLE),
        extra=_settings_values(account.service, account, config_for(request)),
    )


@router.post(
    "/app/settings/delete", response_class=HTMLResponse, include_in_schema=False
)
async def settings_delete_submit(request: Request) -> Response:
    """Delete the account and its user-scoped rows after an explicit confirm."""
    account = _require_account(request)
    config = config_for(request)
    form = await _read_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_error(request)

    confirm = (form.get("confirm") or "").strip()
    password = form.get("password") or None
    payload = account.service.profile_payload_for_user(account.context.user)
    error: str | None = None
    if confirm != "DELETE":
        error = "Type DELETE exactly to confirm. Nothing was deleted."
    elif payload["password_set"] and not password:
        error = "Enter your password. Nothing was deleted."
    if error is not None:
        return render_page(
            request,
            "app/settings_privacy.html",
            shell=account_shell(request, account, PRIVACY_TITLE),
            status_code=422,
            extra=_settings_values(
                account.service, account, config, delete_error=error
            ),
        )

    try:
        await run_in_threadpool(
            partial(
                account.service.delete_account,
                ctx=account.context,
                confirm=confirm,
                password=password,
            )
        )
    except APIError as exc:
        message = (
            "Your password is wrong. Nothing was deleted."
            if exc.code == "E-AUTH-INVALID"
            else "The account could not be deleted. Nothing was changed."
        )
        response = render_page(
            request,
            "app/settings_privacy.html",
            shell=account_shell(request, account, PRIVACY_TITLE),
            status_code=401 if exc.code == "E-AUTH-INVALID" else 400,
            extra=_settings_values(
                account.service, account, config, delete_error=message
            ),
        )
        if exc.code == "E-RATE-LIMIT":
            response.headers["Retry-After"] = str(retry_after_seconds(exc))
        return response
    return redirect_and_clear_session(config, "/login?deleted=1")


__all__ = ["router"]
