"""Guest auth screens: `/login`, `/signup`, `/verify-email`, `/forgot-password`,
`/reset-password` (F2, REQUIREMENTS §6/§10.22).

Every route is a thin HTML translation of the F0 account service: the same
`AuthService` methods the JSON endpoints under `/v1/auth/*` call. This module
never hashes a password, mints a token, resolves a session, or talks to Google
on its own; it parses a browser form, calls the service, and renders a page.

CSRF contract (also recorded in `docs/specs/frontend/identity-settings.md`):

- guest forms that create a session or start an email (`/login`, `/signup`,
  `/forgot-password`) carry the signed double-submit token from `web/forms.py`;
- the verify/reset forms are opened from a one-time emailed link, which is
  itself the anti-forgery credential (nobody can guess another browser's
  token), so they do not add a second token;
- signed-in forms live in `onboarding.py` / `settings.py` and verify the F0C
  session-derived CSRF token with `AuthService.verify_csrf`.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from typing import Final
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from backend.auth.service import normalize_email, safe_next_path
from backend.auth.tokens import request_ip_hash_from_request, user_agent_hash
from backend.config import BackendConfig
from backend.errors import APIError

from ..context import FlashMessage, resolve_account
from ..flow import (
    config_for,
    notice,
    page_account,
    password_reason_copy,
    rate_limit_copy,
    redirect_and_clear_session,
    redirect_with_session,
    render_error_page,
    render_public_page,
    retry_after_seconds,
    service_for,
    validation_copy,
)
from ..forms import (
    FormBadEncoding,
    FormTooLarge,
    attach_guest_cookie,
    guest_token_valid,
    new_guest_token,
    read_form,
)

router = APIRouter(tags=["web"])

LOGIN_TITLE: Final[str] = "Sign in"
SIGNUP_TITLE: Final[str] = "Create your account"
VERIFY_TITLE: Final[str] = "Verify your email"
FORGOT_TITLE: Final[str] = "Reset your password"
RESET_TITLE: Final[str] = "Choose a new password"

_FORM_EXPIRED_TITLE: Final[str] = "This form expired"
_FORM_EXPIRED_TEXT: Final[str] = (
    "Reload the page and submit again. If it keeps happening, check that this "
    "browser allows cookies for Zivon."
)
_GOOGLE_ERROR_COPY: Final[dict[str, str]] = {
    "E-AUTH-INVALID": "Google sign-in did not complete. Please try again.",
    "E-EMAIL-UNVERIFIED": (
        "Google did not confirm that email address, so nothing was linked."
    ),
    "E-CONFLICT": (
        "That Google account is already linked to a different Zivon account."
    ),
    "E-RATE-LIMIT": "Too many Google sign-in attempts. Wait a minute and try again.",
    "E-SERVICE-UNAVAILABLE": (
        "Google sign-in is unavailable right now. Email and password still work."
    ),
}


# -- shared helpers ---------------------------------------------------------


def _google_available(config: BackendConfig) -> bool:
    return bool(config.google_client_id and config.google_client_secret)


def _guest_values(
    form_token: str,
    *,
    next_path: str = "/app",
    email: str = "",
    field_errors: dict[str, str] | None = None,
    form_error: str | None = None,
    google_available: bool = False,
    sent: bool = False,
) -> dict[str, object]:
    """Template values every guest auth form expects."""
    return {
        "form_token": form_token,
        "next_path": next_path,
        "email": email,
        "field_errors": field_errors or {},
        "form_error": form_error,
        "google_available": google_available,
        "google_intent": "login",
        "google_next": quote(next_path, safe="/"),
        "sent": sent,
    }


def _render_form(
    request: Request,
    template: str,
    title: str,
    *,
    status_code: int = 200,
    values: dict[str, object],
    flash: Sequence[FlashMessage] = (),
    error: str | None = None,
) -> HTMLResponse:
    return render_public_page(
        request,
        template,
        title,
        status_code=status_code,
        extra=values,
        flash=flash,
        error=error,
    )


def _render_fresh(
    request: Request,
    template: str,
    title: str,
    *,
    values: dict[str, object] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render a guest form and issue its double-submit nonce cookie."""
    config = config_for(request)
    form_token, cookie_value = new_guest_token(config)
    merged = _guest_values(form_token, google_available=_google_available(config))
    if values:
        merged.update(values)
    response = _render_form(
        request, template, title, status_code=status_code, values=merged
    )
    attach_guest_cookie(response, config, cookie_value)
    return response


def _csrf_rejected(request: Request) -> HTMLResponse:
    return render_error_page(
        request,
        status_code=403,
        title=_FORM_EXPIRED_TITLE,
        message=_FORM_EXPIRED_TEXT,
    )


def _bad_form(request: Request) -> HTMLResponse:
    return render_error_page(
        request,
        status_code=400,
        title="That form did not arrive",
        message=(
            "The browser sent something other than a normal form submission. "
            "Go back, reload the page, and try again."
        ),
    )


async def _form_or_error(request: Request) -> dict[str, str] | HTMLResponse:
    """Parse the body, or return the branded 400 page for a malformed post."""
    try:
        return await read_form(request)
    except (FormBadEncoding, FormTooLarge):
        return _bad_form(request)


def _email_shape_ok(email: str) -> bool:
    try:
        normalize_email(email)
    except APIError:
        return False
    return True


def _html_status(exc: APIError) -> int:
    if exc.code == "E-RATE-LIMIT":
        return 429
    if exc.code in ("E-AUTH-INVALID", "E-AUTH-REQUIRED"):
        return 401
    if exc.code == "E-EMAIL-UNVERIFIED":
        return 403
    if exc.code == "E-CONFLICT":
        return 409
    if exc.code == "E-SERVICE-UNAVAILABLE":
        return 503
    if exc.code == "E-VALIDATION":
        return 422
    return 400


# -- sign in ----------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> Response:
    """The guard's redirect target. A signed-in visitor goes straight on."""
    next_path = safe_next_path(request.query_params.get("next"))
    if resolve_account(request) is not None:
        return RedirectResponse(url=next_path, status_code=303)

    error_code = (request.query_params.get("error") or "").strip()
    error = None
    flash: tuple[FlashMessage, ...] = ()
    if error_code:
        error = _GOOGLE_ERROR_COPY.get(
            error_code, "Google sign-in could not be completed. Please try again."
        )
    else:
        notices = {
            "reset": "Password updated. Sign in with your new password.",
            "verified": "Email verified. You can sign in now.",
            "signed_out": (
                "You are signed out. Reading still works without an account."
            ),
            "deleted": (
                "Your account and the data attached to it were deleted. You can "
                "still read every chapter as a guest."
            ),
        }
        for key, text in notices.items():
            if request.query_params.get(key):
                flash = (notice(text),)
                break

    config = config_for(request)
    form_token, cookie_value = new_guest_token(config)
    values = _guest_values(
        form_token,
        next_path=next_path,
        google_available=_google_available(config),
    )
    response = _render_form(
        request,
        "auth/login.html",
        LOGIN_TITLE,
        values=values,
        flash=flash,
        error=error,
    )
    attach_guest_cookie(response, config, cookie_value)
    return response


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_submit(request: Request) -> Response:
    """Email + password through `AuthService.login`; no account enumeration."""
    service = service_for(request)
    config = config_for(request)
    form = await _form_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    token = form.get("csrf_token") or ""
    if not guest_token_valid(request, token):
        return _csrf_rejected(request)

    next_path = safe_next_path(form.get("next"))
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""
    field_errors: dict[str, str] = {}
    if not email:
        field_errors["email"] = "Enter your email address."
    elif not _email_shape_ok(email):
        field_errors["email"] = "Enter a valid email address."
    if not password:
        field_errors["password"] = "Enter your password."
    values = _guest_values(
        token,
        next_path=next_path,
        email=email,
        field_errors=field_errors,
        form_error="Check the highlighted fields." if field_errors else None,
        google_available=_google_available(config),
    )
    if field_errors:
        return _render_form(
            request,
            "auth/login.html",
            LOGIN_TITLE,
            status_code=422,
            values=values,
        )

    ip_hash = request_ip_hash_from_request(config, request)
    try:
        await run_in_threadpool(service.check_rate_limit, "login", ip_hash)
        grant = await run_in_threadpool(
            partial(
                service.login,
                email=email,
                password=password,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash(
                    config, request.headers.get("User-Agent")
                ),
            )
        )
    except APIError as exc:
        values["form_error"] = _login_error_copy(exc)
        response = _render_form(
            request,
            "auth/login.html",
            LOGIN_TITLE,
            status_code=_html_status(exc),
            values=values,
        )
        if exc.code == "E-RATE-LIMIT":
            response.headers["Retry-After"] = str(retry_after_seconds(exc))
        return response
    return redirect_with_session(config, grant, next_path)


def _login_error_copy(exc: APIError) -> str:
    if exc.code == "E-AUTH-INVALID":
        # Unknown address and wrong password are deliberately indistinguishable.
        return "Email or password is wrong. Check both and try again."
    if exc.code == "E-RATE-LIMIT":
        return rate_limit_copy(exc)
    if exc.code == "E-VALIDATION":
        return validation_copy(_reason(exc))
    if exc.code == "E-SERVICE-UNAVAILABLE":
        return "Sign-in is unavailable right now. Try again in a minute."
    return "Sign-in did not work. Try again."


def _reason(exc: APIError) -> str | None:
    value = exc.extra.get("reason")
    return str(value) if value is not None else None


# -- sign up ----------------------------------------------------------------


@router.get("/signup", response_class=HTMLResponse, include_in_schema=False)
def signup_page(request: Request) -> Response:
    if resolve_account(request) is not None:
        return RedirectResponse(url="/app", status_code=303)
    return _render_fresh(request, "auth/signup.html", SIGNUP_TITLE)


@router.post("/signup", response_class=HTMLResponse, include_in_schema=False)
async def signup_submit(request: Request) -> Response:
    """Create the one account for this email through `AuthService.register`."""
    service = service_for(request)
    config = config_for(request)
    form = await _form_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    token = form.get("csrf_token") or ""
    if not guest_token_valid(request, token):
        return _csrf_rejected(request)

    email = (form.get("email") or "").strip()
    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""
    agreed = (form.get("agree") or "").strip() == "yes"
    field_errors: dict[str, str] = {}
    if not email:
        field_errors["email"] = "Enter your email address."
    elif not _email_shape_ok(email):
        field_errors["email"] = "Enter a valid email address."
    if not password:
        field_errors["password"] = "Choose a password."
    elif len(password) < 10:
        field_errors["password"] = password_reason_copy("too_short")
    if password and confirm != password:
        field_errors["confirm_password"] = "The two passwords do not match."
    if not agreed:
        field_errors["agree"] = "Tick the box to agree to the Terms and Privacy Policy."
    values = _guest_values(
        token,
        next_path="/onboarding",
        email=email,
        field_errors=field_errors,
        form_error="Check the highlighted fields." if field_errors else None,
        google_available=_google_available(config),
    )
    if field_errors:
        return _render_form(
            request,
            "auth/signup.html",
            SIGNUP_TITLE,
            status_code=422,
            values=values,
        )

    ip_hash = request_ip_hash_from_request(config, request)
    try:
        await run_in_threadpool(service.check_rate_limit, "register", ip_hash)
        grant = await run_in_threadpool(
            partial(
                service.register,
                email=email,
                password=password,
                ip_hash=ip_hash,
                user_agent_hash=user_agent_hash(
                    config, request.headers.get("User-Agent")
                ),
            )
        )
    except APIError as exc:
        values["form_error"] = _signup_error_copy(exc)
        response = _render_form(
            request,
            "auth/signup.html",
            SIGNUP_TITLE,
            status_code=_html_status(exc),
            values=values,
        )
        if exc.code == "E-RATE-LIMIT":
            response.headers["Retry-After"] = str(retry_after_seconds(exc))
        return response
    return redirect_with_session(config, grant, "/onboarding")


def _signup_error_copy(exc: APIError) -> str:
    if exc.code == "E-CONFLICT":
        return (
            "That email already has a Zivon account. Sign in instead, or use "
            "another address."
        )
    if exc.code == "E-RATE-LIMIT":
        return rate_limit_copy(exc)
    if exc.code == "E-VALIDATION":
        return validation_copy(_reason(exc))
    if exc.code == "E-SERVICE-UNAVAILABLE":
        return "Account creation is unavailable right now. Try again in a minute."
    return "The account could not be created. Try again."


# -- email verification -----------------------------------------------------


@router.get("/verify-email", response_class=HTMLResponse, include_in_schema=False)
def verify_email_page(request: Request) -> Response:
    """Token state, or the honest "check your inbox" state without a token."""
    token = (request.query_params.get("token") or "").strip()
    return render_public_page(
        request,
        "auth/verify_email.html",
        VERIFY_TITLE,
        extra={
            "token": token,
            "signed_in": resolve_account(request) is not None,
            "has_token": bool(token),
        },
    )


@router.post("/verify-email", response_class=HTMLResponse, include_in_schema=False)
async def verify_email_submit(request: Request) -> Response:
    """Consume the emailed token; the token itself is the anti-forgery credential."""
    service = service_for(request)
    form = await _form_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    token = (form.get("token") or "").strip()
    if not token:
        return render_error_page(
            request,
            status_code=400,
            title="This verification link is incomplete",
            message=(
                "Open the link from the verification email again. A resend "
                "action is not available yet."
            ),
        )
    config = config_for(request)
    ip_hash = request_ip_hash_from_request(config, request)
    try:
        await run_in_threadpool(service.check_rate_limit, "verify", ip_hash)
        await run_in_threadpool(service.verify_email, token)
    except APIError as exc:
        if exc.code == "E-RATE-LIMIT":
            return render_error_page(
                request,
                status_code=429,
                title="Too many attempts",
                message=rate_limit_copy(exc),
                retry_after=retry_after_seconds(exc),
            )
        return render_error_page(
            request,
            status_code=400,
            title="This link is no longer valid",
            message=(
                "Verification links work once and expire. The link may already "
                "have been used. Sign in and open Settings to check the state."
            ),
        )
    account = page_account(request)
    target = "/app/settings?verified=1" if account is not None else "/login?verified=1"
    return RedirectResponse(url=target, status_code=303)


# -- password reset ---------------------------------------------------------


@router.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
def forgot_password_page(request: Request) -> Response:
    return _render_fresh(request, "auth/forgot_password.html", FORGOT_TITLE)


@router.post("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def forgot_password_submit(
    request: Request, background: BackgroundTasks
) -> Response:
    """Always shows the same "if that address exists" state (no enumeration)."""
    service = service_for(request)
    config = config_for(request)
    form = await _form_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    token = form.get("csrf_token") or ""
    if not guest_token_valid(request, token):
        return _csrf_rejected(request)
    email = (form.get("email") or "").strip()
    field_errors: dict[str, str] = {}
    if not email:
        field_errors["email"] = "Enter your email address."
    elif not _email_shape_ok(email):
        field_errors["email"] = "Enter a valid email address."
    values = _guest_values(
        token,
        email=email,
        field_errors=field_errors,
        form_error="Check the highlighted fields." if field_errors else None,
    )
    if field_errors:
        return _render_form(
            request,
            "auth/forgot_password.html",
            FORGOT_TITLE,
            status_code=422,
            values=values,
        )

    ip_hash = request_ip_hash_from_request(config, request)
    try:
        await run_in_threadpool(service.check_rate_limit, "reset", ip_hash)
    except APIError as exc:
        values["form_error"] = rate_limit_copy(exc)
        response = _render_form(
            request,
            "auth/forgot_password.html",
            FORGOT_TITLE,
            status_code=429,
            values=values,
        )
        response.headers["Retry-After"] = str(retry_after_seconds(exc))
        return response
    # Same work and same response whether or not the address exists; the send
    # happens after the response, like the JSON endpoint's background task.
    background.add_task(service.request_password_reset, email)
    values["sent"] = True
    return _render_form(
        request,
        "auth/forgot_password.html",
        FORGOT_TITLE,
        values=values,
    )


@router.get("/reset-password", response_class=HTMLResponse, include_in_schema=False)
def reset_password_page(request: Request) -> Response:
    token = (request.query_params.get("token") or "").strip()
    return render_public_page(
        request,
        "auth/reset_password.html",
        RESET_TITLE,
        extra={"token": token, "has_token": bool(token), "field_errors": {}},
    )


@router.post("/reset-password", response_class=HTMLResponse, include_in_schema=False)
async def reset_password_submit(request: Request) -> Response:
    """Consume the emailed reset token; then send the student to sign in."""
    service = service_for(request)
    config = config_for(request)
    form = await _form_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    token = (form.get("token") or "").strip()
    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""
    extra: dict[str, object] = {
        "token": token,
        "has_token": bool(token),
        "field_errors": {},
    }
    if not token:
        return render_public_page(
            request,
            "auth/reset_password.html",
            RESET_TITLE,
            status_code=400,
            extra={**extra, "form_error": "This reset link is incomplete."},
        )
    field_errors: dict[str, str] = {}
    if not password:
        field_errors["password"] = "Choose a new password."
    elif len(password) < 10:
        field_errors["password"] = password_reason_copy("too_short")
    if password and confirm != password:
        field_errors["confirm_password"] = "The two passwords do not match."
    if field_errors:
        return render_public_page(
            request,
            "auth/reset_password.html",
            RESET_TITLE,
            status_code=422,
            extra={**extra, "field_errors": field_errors},
        )

    ip_hash = request_ip_hash_from_request(config, request)
    try:
        await run_in_threadpool(service.check_rate_limit, "reset", ip_hash)
        await run_in_threadpool(
            partial(service.reset_password, token=token, new_password=password)
        )
    except APIError as exc:
        if exc.code == "E-RATE-LIMIT":
            response = render_public_page(
                request,
                "auth/reset_password.html",
                RESET_TITLE,
                status_code=429,
                extra={**extra, "form_error": rate_limit_copy(exc)},
            )
            response.headers["Retry-After"] = str(retry_after_seconds(exc))
            return response
        if exc.code == "E-VALIDATION":
            return render_public_page(
                request,
                "auth/reset_password.html",
                RESET_TITLE,
                status_code=422,
                extra={
                    **extra,
                    "field_errors": {
                        "password": password_reason_copy(_reason(exc)),
                    },
                },
            )
        return render_error_page(
            request,
            status_code=400,
            title="This reset link is no longer valid",
            message=(
                "Reset links work once and expire after an hour. Request a new "
                "one from the sign-in screen."
            ),
        )
    return RedirectResponse(url="/login?reset=1", status_code=303)


# -- sign out ---------------------------------------------------------------


@router.post("/logout", response_class=HTMLResponse, include_in_schema=False)
async def logout_submit(request: Request) -> Response:
    """Revoke this session and clear the cookie; idempotent for a stale tab."""
    config = config_for(request)
    account = page_account(request)
    if account is None:
        return redirect_and_clear_session(config, "/login?signed_out=1")
    form = await _form_or_error(request)
    if isinstance(form, HTMLResponse):
        return form
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return _csrf_rejected(request)
    await run_in_threadpool(
        account.service.revoke_session, str(account.context.session["session_id"])
    )
    return redirect_and_clear_session(config, "/login?signed_out=1")


__all__ = ["router"]
