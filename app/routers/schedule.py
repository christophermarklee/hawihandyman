"""Admin schedule: calendar view plus fast manual booking (PRD A4)."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from ..auth import require_admin
from ..database import get_session, get_settings
from ..models import Appointment, Client, Service
from ..routers.public import normalize_phone
from ..timeutil import local_now, to_local, to_utc
from ..web import templates

router = APIRouter(prefix="/app/schedule", dependencies=[Depends(require_admin)])


def _conflicts(
    session: Session,
    start_utc: datetime,
    end_utc: datetime,
    *,
    exclude_id: int | None = None,
) -> bool:
    appointments = session.exec(
        select(Appointment).where(
            Appointment.status == "booked",
            Appointment.start_at < end_utc + timedelta(days=1),
            Appointment.end_at > start_utc - timedelta(days=1),
        )
    ).all()
    return any(
        appointment.id != exclude_id
        and start_utc
        < appointment.end_at + timedelta(minutes=appointment.buffer_minutes)
        and end_utc
        > appointment.start_at - timedelta(minutes=appointment.buffer_minutes)
        for appointment in appointments
    )


@router.get("")
def schedule(
    request: Request,
    start: date | None = None,
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    first_day = start or local_now(settings).date()
    first_day -= timedelta(days=first_day.weekday())
    start_utc = to_utc(datetime.combine(first_day, datetime.min.time()), settings)
    last_day = first_day + timedelta(days=6)
    end_utc = to_utc(
        datetime.combine(last_day + timedelta(days=1), datetime.min.time()), settings
    )
    appointments = session.exec(
        select(Appointment)
        .where(
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
            "local_start": to_local(appointment.start_at, settings),
        }
        for appointment in appointments
    ]
    week_days = [
        {
            "date": first_day + timedelta(days=offset),
            "rows": [
                row
                for row in rows
                if row["local_start"].date() == first_day + timedelta(days=offset)
            ],
        }
        for offset in range(7)
    ]
    services = session.exec(select(Service).where(Service.active == True)).all()
    clients = session.exec(select(Client).order_by(Client.name)).all()
    return templates.TemplateResponse(
        request,
        "admin/schedule.html",
        {
            "tab": "schedule",
            "settings": settings,
            "rows": rows,
            "services": services,
            "clients": clients,
            "first_day": first_day,
            "last_day": last_day,
            "today": local_now(settings).date(),
            "week_days": week_days,
            "prev_start": first_day - timedelta(days=7),
            "next_start": first_day + timedelta(days=7),
        },
    )


@router.post("")
def create_appointment(
    service_id: int = Form(...),
    start: str = Form(...),  # local YYYY-MM-DDTHH:MM
    client_id: str = Form(""),
    new_client_name: str = Form(""),
    new_client_phone: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    service = session.get(Service, service_id)
    if service is None or not service.active:
        raise HTTPException(status_code=404)
    try:
        start_local = datetime.strptime(start, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start time")

    if client_id:
        client = session.get(Client, int(client_id))
        if client is None:
            raise HTTPException(status_code=404, detail="Client not found")
    else:
        if not new_client_name.strip():
            raise HTTPException(status_code=400, detail="Client name required")
        client = Client(
            name=new_client_name.strip(), phone=normalize_phone(new_client_phone)
        )
        session.add(client)
        session.flush()

    start_utc = to_utc(start_local, settings)
    end_utc = start_utc + timedelta(minutes=service.duration_minutes)
    if _conflicts(session, start_utc, end_utc):
        raise HTTPException(status_code=409, detail="Appointment overlaps a booked job")
    session.add(
        Appointment(
            client_id=client.id,
            service_id=service.id,
            start_at=start_utc,
            end_at=end_utc,
            buffer_minutes=settings.travel_buffer_minutes,
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return RedirectResponse("/app/schedule", status_code=303)


@router.post("/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: int,
    start: str = Form(...),
    session: Session = Depends(get_session),
):
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404)
    if appointment.status != "booked":
        raise HTTPException(
            status_code=409, detail="Only booked appointments can be rescheduled"
        )
    try:
        start_local = datetime.strptime(start, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start time")
    settings = get_settings(session)
    service = session.get(Service, appointment.service_id)
    start_utc = to_utc(start_local, settings)
    end_utc = start_utc + timedelta(minutes=service.duration_minutes)
    if _conflicts(session, start_utc, end_utc, exclude_id=appointment.id):
        raise HTTPException(status_code=409, detail="Appointment overlaps a booked job")
    appointment.start_at = start_utc
    appointment.end_at = end_utc
    appointment.buffer_minutes = settings.travel_buffer_minutes
    session.add(appointment)
    session.commit()
    return RedirectResponse("/app/schedule", status_code=303)


@router.post("/{appointment_id}/cancel")
def cancel_appointment(appointment_id: int, session: Session = Depends(get_session)):
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404)
    appointment.status = "cancelled"
    session.add(appointment)
    session.commit()
    return RedirectResponse("/app/schedule", status_code=303)


@router.post("/{appointment_id}/done")
def complete_appointment(appointment_id: int, session: Session = Depends(get_session)):
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404)
    appointment.status = "done"
    session.add(appointment)
    session.commit()
    return RedirectResponse("/app/schedule", status_code=303)
