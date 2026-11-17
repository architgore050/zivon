"""`/onboarding` — class, board, language, optional goal (F2, REQUIREMENTS §10.23).

Three questions on one paper card, skipping allowed, and no write on skip. The
save path calls the same `AuthService.update_profile` method the JSON
`PATCH /v1/me` endpoint uses. The optional goal has no column in the F0 schema,
so it is stored on the device by `frontend/assets/auth.js` and the screen says
so; nothing is collected and silently dropped.
"""

from __future__ import annotations

from functools import partial
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from backend.errors import APIError

from ..context import LoginRequired
from ..flow import (
    BOARD_CHOICES,
    CLASS_CHOICES,
    LANGUAGE_CHOICES,
    account_shell,
    page_account,
    rate_limit_copy,
    render_error_page,
    retry_after_seconds,
    validation_copy,
)
from ..forms import FormBadEncoding, FormTooLarge, read_form
from ..render import render_page

router = APIRouter(tags=["web"])

ONBOARDING_TITLE: Final[str] = "Set up your class"
ONBOARDING_PATH: Final[str] = "/onboarding"


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


def _extra(
    *,
    form: dict[str, str],
    field_errors: dict[str, str] | None = None,
    form_error: str | None = None,
) -> dict[str, object]:
    return {
        "form": form,
        "field_errors": field_errors or {},
        "form_error": form_error,
        "class_choices": CLASS_CHOICES,
        "board_choices": BOARD_CHOICES,
        "language_choices": LANGUAGE_CHOICES,
    }


def _form_from_user(user: dict[str, object]) -> dict[str, str]:
    return {
        "class_level": str(user.get("class_level") or ""),
        "board": str(user.get("board") or "CBSE"),
        "language": str(user.get("language") or "en-IN"),
        "goal": "",
    }


@router.get(ONBOARDING_PATH, response_class=HTMLResponse, include_in_schema=False)
def onboarding_page(request: Request) -> Response:
    """Prefilled from the account row; a returning student can change answers."""
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    return render_page(
        request,
        "auth/onboarding.html",
        shell=account_shell(request, account, ONBOARDING_TITLE),
        extra=_extra(form=_form_from_user(account.context.user)),
    )


@router.post(ONBOARDING_PATH, response_class=HTMLResponse, include_in_schema=False)
async def onboarding_submit(request: Request) -> Response:
    """Save the three answers through the F0 profile service."""
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    try:
        form = await read_form(request)
    except (FormBadEncoding, FormTooLarge):
        return render_error_page(
            request,
            status_code=400,
            title="That form did not arrive",
            message="Go back, reload the page, and submit again.",
        )
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return render_error_page(
            request,
            status_code=403,
            title="This form expired",
            message=(
                "Reload the page and submit again. If it keeps happening, check "
                "that this browser allows cookies for Zivon."
            ),
        )

    class_level = _parse_class(form.get("class_level") or "")
    board = (form.get("board") or "").strip()
    language = _canonical_language(form.get("language") or "")
    field_errors: dict[str, str] = {}
    if class_level is None:
        field_errors["class_level"] = "Choose your class."
    if board not in BOARD_CHOICES:
        field_errors["board"] = "Choose your board."
    if language is None:
        field_errors["language"] = "Choose English, Hindi, or Hinglish."
    values = {
        "class_level": form.get("class_level") or "",
        "board": board,
        "language": form.get("language") or "",
        "goal": form.get("goal") or "",
    }
    if field_errors:
        return render_page(
            request,
            "auth/onboarding.html",
            shell=account_shell(
                request,
                account,
                ONBOARDING_TITLE,
                error="Check the highlighted answers.",
            ),
            status_code=422,
            extra=_extra(form=values, field_errors=field_errors),
        )

    try:
        await run_in_threadpool(
            partial(
                account.service.update_profile,
                user_id=str(account.context.user["user_id"]),
                patch={
                    "class_level": class_level,
                    "board": board,
                    "language": language,
                },
            )
        )
    except APIError as exc:
        message = (
            rate_limit_copy(exc)
            if exc.code == "E-RATE-LIMIT"
            else validation_copy(_reason(exc))
        )
        response = render_page(
            request,
            "auth/onboarding.html",
            shell=account_shell(request, account, ONBOARDING_TITLE, error=message),
            status_code=429 if exc.code == "E-RATE-LIMIT" else 422,
            extra=_extra(form=values),
        )
        if exc.code == "E-RATE-LIMIT":
            response.headers["Retry-After"] = str(retry_after_seconds(exc))
        return response
    return RedirectResponse(url="/app", status_code=303)


@router.post("/onboarding/skip", response_class=HTMLResponse, include_in_schema=False)
async def onboarding_skip(request: Request) -> Response:
    """Skipping never writes; it only leaves the screen."""
    account = page_account(request)
    if account is None:
        raise LoginRequired()
    try:
        form = await read_form(request)
    except (FormBadEncoding, FormTooLarge):
        return render_error_page(
            request,
            status_code=400,
            title="That form did not arrive",
            message="Go back, reload the page, and try again.",
        )
    if not account.service.verify_csrf(account.context, form.get("csrf_token")):
        return render_error_page(
            request,
            status_code=403,
            title="This form expired",
            message="Reload the page and try again.",
        )
    return RedirectResponse(url="/app", status_code=303)


def _reason(exc: APIError) -> str | None:
    value = exc.extra.get("reason")
    return str(value) if value is not None else None


__all__ = ["router"]
