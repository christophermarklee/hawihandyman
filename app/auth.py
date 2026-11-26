"""Session-cookie authentication with a single admin password (PRD §4)."""

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from . import config
from .web import templates

router = APIRouter()


class RequiresLogin(Exception):
    """Raised by the admin guard; handled in main.py with a redirect."""


def is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


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


@router.get("/app/login")
def login_form(request: Request):
    if is_admin(request):
        return RedirectResponse("/app", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"error": None})


@router.post("/app/login")
def login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, config.admin_password()):
        request.session["admin"] = True
        return RedirectResponse("/app", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"error": "Wrong password, try again."},
        status_code=401,
    )


@router.post("/app/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/app/login", status_code=303)
