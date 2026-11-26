"""Service catalog and business settings (PRD A1/A2)."""

import math
from datetime import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from ..auth import require_admin
from ..database import get_session, get_settings
from ..models import Service
from ..web import templates

router = APIRouter(prefix="/app", dependencies=[Depends(require_admin)])


@router.get("/services")
def services(request: Request, session: Session = Depends(get_session)):
    settings = get_settings(session)
    records = session.exec(select(Service).order_by(Service.duration_minutes)).all()
    return templates.TemplateResponse(
        request,
        "admin/services.html",
        {"tab": "more", "settings": settings, "services": records},
    )


@router.post("/services")
def create_service(
    name: str = Form(...),
    duration_minutes: int = Form(...),
    rate: float = Form(...),
    is_flat_rate: bool = Form(False),
    description: str = Form(""),
    session: Session = Depends(get_session),
):
    if not name.strip() or duration_minutes <= 0:
        raise HTTPException(
            status_code=400, detail="Name and positive duration are required"
        )
    if not math.isfinite(rate) or rate < 0:
        raise HTTPException(status_code=400, detail="Rate must be non-negative")
    session.add(
        Service(
            name=name.strip(),
            duration_minutes=duration_minutes,
            rate=rate,
            is_flat_rate=is_flat_rate,
            description=description.strip() or None,
        )
    )
    session.commit()
    return RedirectResponse("/app/services", status_code=303)


@router.post("/services/{service_id}/toggle")
def toggle_service(service_id: int, session: Session = Depends(get_session)):
    service = session.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=404)
    service.active = not service.active
    session.add(service)
    session.commit()
    return RedirectResponse("/app/services", status_code=303)


@router.get("/settings")
def settings_page(request: Request, session: Session = Depends(get_session)):
    settings = get_settings(session)
    return templates.TemplateResponse(
        request, "admin/settings.html", {"tab": "more", "settings": settings}
    )


@router.post("/settings")
def update_settings(
    request: Request,
    work_start: str = Form(...),
    work_end: str = Form(...),
    travel_buffer_minutes: int = Form(...),
    default_hourly_rate: float = Form(...),
    tax_rate: float = Form(...),
    work_day_0: bool = Form(False),
    work_day_1: bool = Form(False),
    work_day_2: bool = Form(False),
    work_day_3: bool = Form(False),
    work_day_4: bool = Form(False),
    work_day_5: bool = Form(False),
    work_day_6: bool = Form(False),
    session: Session = Depends(get_session),
):
    try:
        start_time = time.fromisoformat(work_start)
        end_time = time.fromisoformat(work_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Working hours must be valid times")
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="Day end must be after day start")
    if not 0 <= travel_buffer_minutes <= 1440:
        raise HTTPException(
            status_code=400, detail="Travel buffer must be 0–1440 minutes"
        )
    if not math.isfinite(default_hourly_rate) or default_hourly_rate < 0:
        raise HTTPException(status_code=400, detail="Hourly rate must be non-negative")
    if not math.isfinite(tax_rate) or not 0 <= tax_rate <= 100:
        raise HTTPException(
            status_code=400, detail="Tax rate must be between 0 and 100"
        )
    settings = get_settings(session)
    settings.work_start = start_time.strftime("%H:%M")
    settings.work_end = end_time.strftime("%H:%M")
    settings.travel_buffer_minutes = travel_buffer_minutes
    settings.default_hourly_rate = default_hourly_rate
    settings.tax_rate = tax_rate
    flags = [
        work_day_0,
        work_day_1,
        work_day_2,
        work_day_3,
        work_day_4,
        work_day_5,
        work_day_6,
    ]
    settings.work_days = ",".join(str(i) for i, on in enumerate(flags) if on)
    session.add(settings)
    session.commit()
    return RedirectResponse("/app/settings", status_code=303)
