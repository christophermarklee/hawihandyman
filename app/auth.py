"""Session-cookie authentication for the admin application."""

import secrets
from collections.abc import Mapping

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from . import config
from .cognito import cognito_oauth_client
from .web import templates

router = APIRouter()


class RequiresLogin(Exception):
    """Raised by the admin guard; handled in main.py with a redirect."""


def is_admin(request: Request) -> bool:
    return request.session.get("admin_auth") == "google"


def require_admin(request: Request) -> None:
    """FastAPI dependency protecting all /app routes."""
    if not is_admin(request):
        raise RequiresLogin()


def login_redirect(request: Request) -> Response:
    if request.headers.get("HX-Request"):
        response = Response(status_code=401)
        response.headers["HX-Redirect"] = "/app/login"
        return response
    return RedirectResponse("/app/login", status_code=303)


def _admin_sign_in_available() -> bool:
    settings = config.cognito_settings()
    return bool(
        settings
        and "Google" in settings.providers
        and config.admin_emails()
    )


def _login_page(request: Request, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"error": error, "google_enabled": _admin_sign_in_available()},
        status_code=status_code,
    )


@router.get("/app/login")
def login_form(request: Request):
    if is_admin(request):
        return RedirectResponse("/app", status_code=303)
    if not _admin_sign_in_available():
        return _login_page(
            request, "Google admin sign-in is not configured.", status_code=503
        )
    return _login_page(request)


@router.get("/app/login/google")
async def admin_google_login(request: Request):
    settings = config.cognito_settings()
    if not _admin_sign_in_available() or settings is None:
        return _login_page(
            request, "Google admin sign-in is not configured.", status_code=503
        )
    return await cognito_oauth_client(settings).authorize_redirect(
        request,
        f"{settings.public_base_url}/app/auth/callback",
        identity_provider="Google",
        nonce=secrets.token_urlsafe(32),
    )


@router.get("/app/auth/callback")
async def admin_google_callback(request: Request):
    settings = config.cognito_settings()
    if not _admin_sign_in_available() or settings is None:
        return _login_page(
            request, "Google admin sign-in is not configured.", status_code=503
        )

    try:
        token = await cognito_oauth_client(settings).authorize_access_token(request)
    except OAuthError:
        return _login_page(
            request, "Google sign-in could not be completed. Please try again.", 400
        )

    userinfo = token.get("userinfo")
    email = userinfo.get("email") if isinstance(userinfo, Mapping) else None
    email_verified = (
        userinfo.get("email_verified") if isinstance(userinfo, Mapping) else None
    )
    if (
        not isinstance(userinfo, Mapping)
        or not isinstance(userinfo.get("sub"), str)
        or not userinfo["sub"]
        or not isinstance(email, str)
        or not (
            email_verified is True
            or (
                isinstance(email_verified, str)
                and email_verified.casefold() == "true"
            )
        )
        or email.strip().casefold() not in config.admin_emails()
    ):
        return _login_page(
            request,
            "This verified Google account is not authorized for admin access.",
            403,
        )

    request.session["admin_auth"] = "google"
    request.session["admin_email"] = email.strip().casefold()
    return RedirectResponse("/app", status_code=303)


@router.post("/app/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/app/login", status_code=303)
