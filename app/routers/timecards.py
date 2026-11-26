"""Timecard list, manual entry, and edits (PRD B3)."""

import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from ..auth import require_admin
from ..database import get_session, get_settings
from ..models import Client, Timecard, utcnow
from ..timeutil import to_utc
from ..web import templates

router = APIRouter(prefix="/app/timecards", dependencies=[Depends(require_admin)])


@router.get("")
def timecards(request: Request, session: Session = Depends(get_session)):
    settings = get_settings(session)
    since = utcnow() - timedelta(days=31)
    cards = session.exec(
        select(Timecard)
        .where(Timecard.clock_in_at >= since)
        .order_by(Timecard.clock_in_at.desc())
    ).all()
    rows = [
        {
            "card": card,
            "client": session.get(Client, card.client_id) if card.client_id else None,
        }
        for card in cards
    ]
    total_hours = sum(card.billable_hours() for card in cards if card.clock_out_at)
    total_earnings = sum(card.earnings() for card in cards if card.clock_out_at)
    clients = session.exec(select(Client).order_by(Client.name)).all()
    return templates.TemplateResponse(
        request,
        "admin/timecards.html",
        {
            "tab": "timecards",
            "settings": settings,
            "rows": rows,
            "clients": clients,
            "total_hours": total_hours,
            "total_earnings": round(total_earnings, 2),
        },
    )


def _parse_local(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date/time")


@router.post("")
def create_timecard(
    client_id: str = Form(""),
    start: str = Form(...),  # local YYYY-MM-DDTHH:MM
    end: str = Form(...),
    break_minutes: int = Form(0),
    hourly_rate: float = Form(...),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    start_utc = to_utc(_parse_local(start), settings)
    end_utc = to_utc(_parse_local(end), settings)
    if end_utc <= start_utc:
        raise HTTPException(status_code=400, detail="End must be after start")
    if break_minutes < 0:
        raise HTTPException(
            status_code=400, detail="Break minutes must be non-negative"
        )
    if not math.isfinite(hourly_rate) or hourly_rate < 0:
        raise HTTPException(status_code=400, detail="Hourly rate must be non-negative")
    session.add(
        Timecard(
            client_id=int(client_id) if client_id else None,
            clock_in_at=start_utc,
            clock_out_at=end_utc,
            break_minutes=break_minutes,
            hourly_rate=hourly_rate,
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return RedirectResponse("/app/timecards", status_code=303)


@router.post("/{timecard_id}")
def update_timecard(
    timecard_id: int,
    start: str = Form(...),
    end: str = Form(...),
    break_minutes: int = Form(0),
    hourly_rate: float = Form(...),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    card = session.get(Timecard, timecard_id)
    if card is None:
        raise HTTPException(status_code=404)
    if card.invoice_id is not None:
        raise HTTPException(status_code=409, detail="Timecard already invoiced")
    settings = get_settings(session)
    start_utc = to_utc(_parse_local(start), settings)
    end_utc = to_utc(_parse_local(end), settings)
    if end_utc <= start_utc:
        raise HTTPException(status_code=400, detail="End must be after start")
    if break_minutes < 0:
        raise HTTPException(
            status_code=400, detail="Break minutes must be non-negative"
        )
    if not math.isfinite(hourly_rate) or hourly_rate < 0:
        raise HTTPException(status_code=400, detail="Hourly rate must be non-negative")
    card.clock_in_at = start_utc
    card.clock_out_at = end_utc
    card.break_minutes = break_minutes
    card.hourly_rate = hourly_rate
    card.notes = notes.strip() or None
    session.add(card)
    session.commit()
    return RedirectResponse("/app/timecards", status_code=303)


@router.post("/{timecard_id}/delete")
def delete_timecard(timecard_id: int, session: Session = Depends(get_session)):
    card = session.get(Timecard, timecard_id)
    if card is None:
        raise HTTPException(status_code=404)
    if card.invoice_id is not None:
        raise HTTPException(status_code=409, detail="Timecard already invoiced")
    session.delete(card)
    session.commit()
    return RedirectResponse("/app/timecards", status_code=303)
