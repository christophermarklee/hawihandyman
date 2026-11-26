"""Public, unauthenticated endpoints: booking flow and invoice links."""

import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from ..availability import available_slots, slot_is_available
from ..database import get_session, get_settings
from ..models import Appointment, Client, Invoice, InvoiceItem, Service
from ..timeutil import local_now, to_utc
from ..web import templates

router = APIRouter()


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def active_services(session: Session) -> list[Service]:
    return list(session.exec(select(Service).where(Service.active == True)).all())


@router.get("/book")
def book_page(request: Request, session: Session = Depends(get_session)):
    settings = get_settings(session)
    return templates.TemplateResponse(
        request,
        "public/book.html",
        {
            "services": active_services(session),
            "settings": settings,
            "today": local_now(settings).date().isoformat(),
        },
    )


@router.get("/api/availability/month")
def availability_month(
    service_id: int,
    month: date,
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    service = session.get(Service, service_id)
    if service is None or not service.active:
        raise HTTPException(status_code=404, detail="Unknown service")

    first_day = month.replace(day=1)
    available_dates = []
    day = first_day
    while day.month == first_day.month:
        if available_slots(session, service, day, settings):
            available_dates.append(day.isoformat())
        day += timedelta(days=1)
    return {"month": first_day.strftime("%Y-%m"), "available_dates": available_dates}


@router.get("/api/availability")
def availability(
    request: Request,
    service_id: int,
    date: date,
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    service = session.get(Service, service_id)
    if service is None or not service.active:
        raise HTTPException(status_code=404, detail="Unknown service")
    slots = available_slots(session, service, date, settings)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "public/_slots.html",
            {"slots": slots, "service": service, "date": date},
        )
    return {"slots": [slot.strftime("%Y-%m-%dT%H:%M") for slot in slots]}


@router.post("/api/book")
def book(
    request: Request,
    service_id: int = Form(...),
    start: str = Form(...),  # local time, YYYY-MM-DDTHH:MM
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(""),
    address: str = Form(...),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    service = session.get(Service, service_id)
    if service is None or not service.active:
        raise HTTPException(status_code=404, detail="Unknown service")
    try:
        start_local = datetime.strptime(start, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start time")
    start_utc = to_utc(start_local, settings)

    # The session transaction is BEGIN IMMEDIATE (see database.py), so this
    # availability re-check and the insert are atomic against double-booking.
    if not slot_is_available(session, service, start_utc, settings):
        return templates.TemplateResponse(
            request,
            "public/_slot_taken.html",
            {"service": service, "date": start_local.date()},
            status_code=409,
        )

    digits = normalize_phone(phone)
    if not digits or not name.strip():
        raise HTTPException(status_code=400, detail="Name and phone are required")
    client = session.exec(select(Client).where(Client.phone == digits)).first()
    if client is None:
        client = Client(name=name.strip(), phone=digits)
        session.add(client)
    client.email = email.strip() or client.email
    client.address = address.strip() or client.address
    session.flush()

    appointment = Appointment(
        client_id=client.id,
        service_id=service.id,
        start_at=start_utc,
        end_at=start_utc + timedelta(minutes=service.duration_minutes),
        buffer_minutes=settings.travel_buffer_minutes,
        notes=notes.strip() or None,
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)

    return templates.TemplateResponse(
        request,
        "public/_confirmation.html",
        {
            "appointment": appointment,
            "service": service,
            "client": client,
            "settings": settings,
            "start_local": start_local,
        },
    )


@router.get("/book/ics/{code}")
def booking_ics(code: str, session: Session = Depends(get_session)):
    appointment = session.exec(
        select(Appointment).where(Appointment.confirmation_code == code)
    ).first()
    if appointment is None:
        raise HTTPException(status_code=404)
    service = session.get(Service, appointment.service_id)
    stamp = "%Y%m%dT%H%M%SZ"
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//HaleClock//Booking//EN",
            "BEGIN:VEVENT",
            f"UID:{appointment.confirmation_code}@hawihandyman.com",
            f"DTSTAMP:{appointment.created_at.strftime(stamp)}",
            f"DTSTART:{appointment.start_at.strftime(stamp)}",
            f"DTEND:{appointment.end_at.strftime(stamp)}",
            f"SUMMARY:Hawi Handyman — {service.name}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    return PlainTextResponse(
        ics,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="booking-{code}.ics"'},
    )


@router.get("/i/{public_token}")
def public_invoice(
    request: Request, public_token: str, session: Session = Depends(get_session)
):
    invoice = session.exec(
        select(Invoice).where(Invoice.public_token == public_token)
    ).first()
    if invoice is None or invoice.status == "void":
        raise HTTPException(status_code=404)
    settings = get_settings(session)
    client = session.get(Client, invoice.client_id)
    items = session.exec(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
    ).all()
    return templates.TemplateResponse(
        request,
        "public/invoice.html",
        {"invoice": invoice, "client": client, "items": items, "settings": settings},
    )
