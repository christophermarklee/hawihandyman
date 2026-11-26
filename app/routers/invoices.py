"""Invoices: build from timecards, Hawaii GET, cash payment recording (PRD C)."""

import math

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from .. import config
from ..auth import require_admin
from ..database import get_session, get_settings
from ..email_service import send_invoice_email
from ..models import (
    Client,
    Invoice,
    InvoiceItem,
    Timecard,
    compute_invoice_totals,
    utcnow,
)
from ..timeutil import to_local
from ..web import templates

router = APIRouter(prefix="/app/invoices", dependencies=[Depends(require_admin)])

PAYMENT_METHODS = ["Cash", "Check", "Venmo", "Zelle"]


def _email_redirect(path: str, delivery: bool | None) -> RedirectResponse:
    if delivery is None:
        return RedirectResponse(path, status_code=303)
    status = "sent" if delivery else "failed"
    return RedirectResponse(f"{path}?email={status}", status_code=303)


def _next_invoice_number(session: Session) -> str:
    last = session.exec(select(Invoice).order_by(Invoice.id.desc())).first()
    return f"INV-{(last.id if last else 0) + 1:04d}"


@router.get("")
def invoices(request: Request, session: Session = Depends(get_session)):
    settings = get_settings(session)
    records = session.exec(select(Invoice).order_by(Invoice.created_at.desc())).all()
    rows = [
        {"invoice": invoice, "client": session.get(Client, invoice.client_id)}
        for invoice in records
    ]
    clients = session.exec(select(Client).order_by(Client.name)).all()
    return templates.TemplateResponse(
        request,
        "admin/invoices.html",
        {"tab": "invoices", "settings": settings, "rows": rows, "clients": clients},
    )


@router.get("/new")
def new_invoice(
    request: Request, client_id: int, session: Session = Depends(get_session)
):
    settings = get_settings(session)
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404)
    unbilled = session.exec(
        select(Timecard)
        .where(
            Timecard.client_id == client_id,
            Timecard.invoice_id == None,
            Timecard.clock_out_at != None,
        )
        .order_by(Timecard.clock_in_at)
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/invoice_new.html",
        {
            "tab": "invoices",
            "settings": settings,
            "client": client,
            "timecards": unbilled,
        },
    )


@router.post("/from-timecards")
async def create_from_timecards(
    request: Request, session: Session = Depends(get_session)
):
    form = await request.form()
    settings = get_settings(session)
    try:
        client_id = int(form["client_id"])
        tax_rate = float(form.get("tax_rate") or settings.tax_rate)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid invoice details")
    client = session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404)
    tax_mode = form.get("tax_mode", "add")
    if tax_mode not in {"add", "included", "none"}:
        raise HTTPException(status_code=400, detail="Invalid tax mode")
    if not math.isfinite(tax_rate) or not 0 <= tax_rate <= 100:
        raise HTTPException(
            status_code=400, detail="Tax rate must be between 0 and 100"
        )
    if tax_mode == "none":
        tax_rate = 0.0

    try:
        timecard_ids = [int(value) for value in form.getlist("timecard_ids")]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid timecard selection")
    if len(timecard_ids) != len(set(timecard_ids)):
        raise HTTPException(status_code=400, detail="Duplicate timecard selection")
    cards = []
    for timecard_id in timecard_ids:
        card = session.get(Timecard, timecard_id)
        if (
            card is None
            or card.client_id != client_id
            or card.invoice_id is not None
            or card.clock_out_at is None
        ):
            raise HTTPException(status_code=409, detail="Timecard unavailable")
        cards.append(card)

    extra_descriptions = form.getlist("item_description")
    extra_amounts = form.getlist("item_amount")

    items: list[InvoiceItem] = []
    subtotal = 0.0
    for card in cards:
        hours = round(card.billable_hours(), 2)
        amount = card.earnings()
        label = to_local(card.clock_in_at, settings).strftime("%Y-%m-%d")
        items.append(
            InvoiceItem(
                invoice_id=0,
                description=f"Labor {label} — {hours:g} hrs @ ${card.hourly_rate:g}/hr",
                quantity=hours,
                unit_amount=card.hourly_rate,
                amount=amount,
            )
        )
        subtotal += amount
    for description, amount_raw in zip(extra_descriptions, extra_amounts):
        if not description.strip() or not amount_raw.strip():
            continue
        try:
            amount = float(amount_raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid material amount")
        if not math.isfinite(amount) or amount < 0:
            raise HTTPException(
                status_code=400, detail="Material amounts must be non-negative"
            )
        amount = round(amount, 2)
        items.append(
            InvoiceItem(
                invoice_id=0,
                description=description.strip(),
                quantity=1,
                unit_amount=amount,
                amount=amount,
            )
        )
        subtotal += amount

    if not items:
        raise HTTPException(status_code=400, detail="Nothing to invoice")

    tax_amount, total = compute_invoice_totals(subtotal, tax_mode, tax_rate)
    invoice = Invoice(
        invoice_number=_next_invoice_number(session),
        client_id=client_id,
        subtotal=round(subtotal, 2),
        tax_mode=tax_mode,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
        status="sent",
    )
    session.add(invoice)
    session.flush()
    for item in items:
        item.invoice_id = invoice.id
        session.add(item)
    for card in cards:
        card.invoice_id = invoice.id
        session.add(card)
    session.commit()
    delivery = send_invoice_email(client, invoice, "issued")
    return _email_redirect(f"/app/invoices/{invoice.id}", delivery)


@router.get("/{invoice_id}")
def invoice_detail(
    request: Request, invoice_id: int, session: Session = Depends(get_session)
):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404)
    settings = get_settings(session)
    client = session.get(Client, invoice.client_id)
    items = session.exec(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
    ).all()
    public_url = f"{config.public_base_url()}/i/{invoice.public_token}"
    email_notice = {
        "sent": "Customer email sent.",
        "failed": (
            "The invoice was saved, but its email could not be sent. "
            "Please contact the customer directly."
        ),
    }.get(request.query_params.get("email"))
    email_notice_class = (
        "bg-emerald-50 text-emerald-800"
        if request.query_params.get("email") == "sent"
        else "bg-amber-50 text-amber-800"
    )
    sms_text = (
        f"Aloha {client.name.split()[0] if client.name else ''}! Here's your invoice "
        f"{invoice.invoice_number} from Hawi Handyman for ${invoice.total:,.2f}: {public_url}"
    )
    return templates.TemplateResponse(
        request,
        "admin/invoice_detail.html",
        {
            "tab": "invoices",
            "settings": settings,
            "invoice": invoice,
            "client": client,
            "items": items,
            "public_url": public_url,
            "sms_text": sms_text,
            "payment_methods": PAYMENT_METHODS,
            "email_notice": email_notice,
            "email_notice_class": email_notice_class,
        },
    )


@router.post("/{invoice_id}/mark-paid")
def mark_paid(
    invoice_id: int,
    payment_method: str = Form("Cash"),
    session: Session = Depends(get_session),
):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404)
    if invoice.status not in {"draft", "sent"}:
        raise HTTPException(status_code=409, detail="Invoice is already closed")
    if payment_method not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Invalid payment method")
    invoice.status = "paid"
    invoice.payment_method = payment_method
    invoice.paid_at = utcnow()
    client = session.get(Client, invoice.client_id)
    session.add(invoice)
    session.commit()
    delivery = send_invoice_email(client, invoice, "paid")
    return _email_redirect(f"/app/invoices/{invoice_id}", delivery)


@router.post("/{invoice_id}/void")
def void_invoice(
    invoice_id: int,
    session: Session = Depends(get_session),
):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404)
    if invoice.status not in {"draft", "sent"}:
        raise HTTPException(
            status_code=409, detail="Only unpaid invoices can be voided"
        )
    invoice.status = "void"
    client = session.get(Client, invoice.client_id)
    cards = session.exec(
        select(Timecard).where(Timecard.invoice_id == invoice.id)
    ).all()
    for card in cards:
        card.invoice_id = None
        session.add(card)
    session.add(invoice)
    session.commit()
    delivery = send_invoice_email(client, invoice, "void")
    return _email_redirect(f"/app/invoices/{invoice_id}", delivery)
