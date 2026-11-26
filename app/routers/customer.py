"""Customer sign-in and project dashboard."""

import secrets
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from .. import config
from ..customer_accounts import (
    customer_account_from_request,
    ensure_customer_account,
    link_client_to_account,
    linked_clients,
)
from ..database import get_session, get_settings
from ..models import Appointment, Client, CustomerAccount, Invoice, Service
from ..web import templates

router = APIRouter()

PROVIDER_LABELS = {
    "Google": "Google",
    "SignInWithApple": "Apple",
    "Facebook": "Facebook",
}


def _cognito_client(settings: config.CognitoSettings):
    oauth = OAuth()
    return oauth.register(
        name="cognito",
        client_id=settings.client_id,
        client_secret=None,
        server_metadata_url=(
            f"{settings.issuer_url}/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        },
    )


def _account_page(request: Request, message: str | None = None, status_code: int = 200):
    settings = config.cognito_settings()
    return templates.TemplateResponse(
        request,
        "public/account.html",
        {
            "account": None,
            "auth_enabled": settings is not None,
            "providers": (
                [
                    {"name": name, "label": PROVIDER_LABELS[name]}
                    for name in settings.providers
                ]
                if settings
                else []
            ),
            "message": message,
        },
        status_code=status_code,
    )


@router.get("/account")
def customer_account(request: Request, session: Session = Depends(get_session)):
    account = customer_account_from_request(request, session)
    if account is None:
        return _account_page(request)
    if account.id is None:
        raise HTTPException(status_code=500, detail="Invalid customer account")

    clients = linked_clients(session, account.id)
    client_ids = [client.id for client in clients]
    appointments = []
    invoices = []
    if client_ids:
        appointments = session.exec(
            select(Appointment)
            .where(Appointment.client_id.in_(client_ids))
            .order_by(Appointment.start_at.desc())
        ).all()
        invoices = session.exec(
            select(Invoice)
            .where(
                Invoice.client_id.in_(client_ids),
                Invoice.status != "void",
            )
            .order_by(Invoice.created_at.desc())
        ).all()

    rows = [
        {
            "appointment": appointment,
            "client": session.get(Client, appointment.client_id),
            "service": session.get(Service, appointment.service_id),
        }
        for appointment in appointments
    ]
    return templates.TemplateResponse(
        request,
        "public/account.html",
        {
            "account": account,
            "auth_enabled": config.cognito_settings() is not None,
            "providers": [],
            "message": request.session.pop("customer_message", None),
            "settings": get_settings(session),
            "rows": rows,
            "clients": clients,
            "invoices": invoices,
        },
    )


@router.get("/account/login")
async def customer_login(request: Request, provider: str | None = None):
    settings = config.cognito_settings()
    if settings is None:
        return _account_page(
            request, "Customer sign-in is not configured yet.", status_code=503
        )
    if provider is not None and provider not in settings.providers:
        raise HTTPException(status_code=400, detail="Unsupported sign-in provider")

    client = _cognito_client(settings)
    callback_url = f"{settings.public_base_url}/account/callback"
    extra_params = {"nonce": secrets.token_urlsafe(32)}
    if provider:
        extra_params["identity_provider"] = provider
    return await client.authorize_redirect(request, callback_url, **extra_params)


@router.get("/account/callback")
async def customer_callback(
    request: Request, session: Session = Depends(get_session)
):
    settings = config.cognito_settings()
    if settings is None:
        return _account_page(
            request, "Customer sign-in is not configured yet.", status_code=503
        )
    try:
        token = await _cognito_client(settings).authorize_access_token(request)
    except OAuthError:
        return _account_page(
            request, "Sign-in could not be completed. Please try again.", 400
        )

    userinfo = token.get("userinfo")
    if (
        not userinfo
        or not isinstance(userinfo.get("sub"), str)
        or not userinfo["sub"]
    ):
        return _account_page(
            request, "Sign-in did not return a valid customer identity.", 401
        )

    account = ensure_customer_account(
        session, userinfo["sub"], userinfo.get("email")
    )
    session.commit()
    if account.id is None:
        raise HTTPException(status_code=500, detail="Customer account was not saved")
    request.session["customer_account_id"] = account.id
    return RedirectResponse("/account", status_code=303)


@router.post("/account/claim")
def claim_project(
    request: Request,
    confirmation_code: str = Form(...),
    session: Session = Depends(get_session),
):
    account = customer_account_from_request(request, session)
    if account is None:
        return RedirectResponse("/account", status_code=303)

    appointment = session.exec(
        select(Appointment).where(
            Appointment.confirmation_code == confirmation_code.strip().upper()
        )
    ).first()
    if appointment is None or not link_client_to_account(
        session, account.id, appointment.client_id
    ):
        request.session["customer_message"] = (
            "We couldn't verify that project. Check the confirmation code or contact us."
        )
    else:
        session.commit()
        request.session["customer_message"] = "Project added to your account."
    return RedirectResponse("/account", status_code=303)


@router.post("/account/logout")
def customer_logout(request: Request):
    request.session.pop("customer_account_id", None)
    settings = config.cognito_settings()
    if settings is None:
        return RedirectResponse("/book", status_code=303)
    params = urlencode(
        {
            "client_id": settings.client_id,
            "logout_uri": f"{settings.public_base_url}/book",
        }
    )
    return RedirectResponse(
        f"{settings.domain}/logout?{params}", status_code=303
    )
