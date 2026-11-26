"""Today dashboard: one-tap clock in / break / out (PRD B1-B2)."""

import math
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, select

from ..auth import require_admin
from ..database import get_session, get_settings
from ..models import Appointment, Client, Service, Timecard, utcnow
from ..timeutil import local_now, to_utc
from ..web import templates

router = APIRouter(prefix="/app", dependencies=[Depends(require_admin)])


def active_timecard(session: Session) -> Timecard | None:
    return session.exec(select(Timecard).where(Timecard.clock_out_at == None)).first()


def clients_sorted(session: Session) -> list[Client]:
    return list(session.exec(select(Client).order_by(Client.name)).all())


def _widget_context(session: Session) -> dict:
    settings = get_settings(session)
    card = active_timecard(session)
    client = session.get(Client, card.client_id) if card and card.client_id else None
    return {
        "settings": settings,
        "card": card,
        "card_client": client,
        "now": utcnow(),
        "clients": clients_sorted(session),
    }


@router.get("")
def today(request: Request, session: Session = Depends(get_session)):
    settings = get_settings(session)
    day_start_local = local_now(settings).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_utc = to_utc(day_start_local.replace(tzinfo=None), settings)
    end_utc = start_utc + timedelta(days=1)
    appointments = session.exec(
        select(Appointment)
        .where(
            Appointment.status == "booked",
            Appointment.start_at >= start_utc,
            Appointment.start_at < end_utc,
        )
        .order_by(Appointment.start_at)
    ).all()
    rows = [
        {
            "appointment": appointment,
            "client": session.get(Client, appointment.client_id),
            "service": session.get(Service, appointment.service_id),
        }
        for appointment in appointments
    ]
    context = _widget_context(session)
    context.update({"tab": "today", "appointment_rows": rows})
    return templates.TemplateResponse(request, "admin/today.html", context)


def _clock_widget(request: Request, session: Session, **extra):
    context = _widget_context(session)
    context.update(extra)
    return templates.TemplateResponse(request, "admin/_clock_widget.html", context)


@router.post("/clock/in")
def clock_in(
    request: Request,
    client_id: str = Form(""),
    new_client_name: str = Form(""),
    hourly_rate: float = Form(...),
    appointment_id: str = Form(""),
    session: Session = Depends(get_session),
):
    if active_timecard(session) is not None:
        raise HTTPException(status_code=409, detail="Already clocked in")
    if not math.isfinite(hourly_rate) or hourly_rate < 0:
        raise HTTPException(status_code=400, detail="Hourly rate must be non-negative")
    client_pk: int | None = int(client_id) if client_id else None
    if client_pk is None and new_client_name.strip():
        client = Client(name=new_client_name.strip(), phone="")
        session.add(client)
        session.flush()
        client_pk = client.id
    card = Timecard(
        client_id=client_pk,
        appointment_id=int(appointment_id) if appointment_id else None,
        clock_in_at=utcnow(),
        hourly_rate=hourly_rate,
    )
    session.add(card)
    session.commit()
    return _clock_widget(request, session)


@router.post("/clock/break")
def toggle_break(request: Request, session: Session = Depends(get_session)):
    card = active_timecard(session)
    if card is None:
        raise HTTPException(status_code=409, detail="Not clocked in")
    now = utcnow()
    if card.active_break_start is None:
        card.active_break_start = now
    else:
        card.break_minutes += max(
            int((now - card.active_break_start).total_seconds() // 60), 0
        )
        card.active_break_start = None
    session.add(card)
    session.commit()
    return _clock_widget(request, session)


@router.post("/clock/out")
def clock_out(request: Request, session: Session = Depends(get_session)):
    card = active_timecard(session)
    if card is None:
        raise HTTPException(status_code=409, detail="Not clocked in")
    now = utcnow()
    if card.active_break_start is not None:
        card.break_minutes += max(
            int((now - card.active_break_start).total_seconds() // 60), 0
        )
        card.active_break_start = None
    card.clock_out_at = now
    session.add(card)
    session.commit()
    session.refresh(card)
    return _clock_widget(request, session, finished_card=card)


@router.post("/appointments/{appointment_id}/start")
def start_job(
    request: Request, appointment_id: int, session: Session = Depends(get_session)
):
    """One-tap 'Start Job' from a scheduled appointment (PRD A4)."""
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404)
    if active_timecard(session) is not None:
        raise HTTPException(status_code=409, detail="Already clocked in")
    service = session.get(Service, appointment.service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not found")
    rate = (
        service.rate * 60 / service.duration_minutes
        if service.is_flat_rate
        else service.rate
    )
    card = Timecard(
        client_id=appointment.client_id,
        appointment_id=appointment.id,
        clock_in_at=utcnow(),
        hourly_rate=rate,
    )
    session.add(card)
    session.commit()
    response = _clock_widget(request, session)
    response.headers["HX-Retarget"] = "#clock-widget"
    return response
