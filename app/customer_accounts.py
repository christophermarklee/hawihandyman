"""Customer identity links for Cognito-authenticated accounts."""

from fastapi import Request
from sqlmodel import Session, select

from .models import Client, CustomerAccount, CustomerClientLink


def customer_account_from_request(
    request: Request, session: Session
) -> CustomerAccount | None:
    account_id = request.session.get("customer_account_id")
    if not isinstance(account_id, int):
        return None
    return session.get(CustomerAccount, account_id)


def ensure_customer_account(
    session: Session, cognito_sub: str, email: str | None
) -> CustomerAccount:
    account = session.exec(
        select(CustomerAccount).where(CustomerAccount.cognito_sub == cognito_sub)
    ).first()
    if account is None:
        account = CustomerAccount(cognito_sub=cognito_sub, email=email)
        session.add(account)
        session.flush()
    elif email and account.email != email:
        account.email = email
        session.add(account)
    return account


def linked_clients(session: Session, account_id: int) -> list[Client]:
    links = session.exec(
        select(CustomerClientLink)
        .where(CustomerClientLink.account_id == account_id)
        .order_by(CustomerClientLink.id)
    ).all()
    return [
        client
        for link in links
        if (client := session.get(Client, link.client_id)) is not None
    ]


def link_client_to_account(
    session: Session, account_id: int, client_id: int
) -> bool:
    existing = session.exec(
        select(CustomerClientLink).where(CustomerClientLink.client_id == client_id)
    ).first()
    if existing is not None:
        return existing.account_id == account_id
    session.add(CustomerClientLink(account_id=account_id, client_id=client_id))
    return True
