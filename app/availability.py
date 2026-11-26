"""Open-slot calculation for the public booking page (PRD A2/A3)."""

from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from .models import Appointment, AppSettings, Service
from .timeutil import local_now, to_local, to_utc, utcnow


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def busy_windows(session: Session, day_start_utc: datetime, day_end_utc: datetime):
    """Booked appointment windows (expanded by their travel buffers) that touch
    the given UTC range."""
    appointments = session.exec(
        select(Appointment).where(
            Appointment.status == "booked",
            Appointment.start_at < day_end_utc + timedelta(hours=24),
            Appointment.end_at > day_start_utc - timedelta(hours=24),
        )
    ).all()
    windows = []
    for appointment in appointments:
        buffer = timedelta(minutes=appointment.buffer_minutes)
        windows.append((appointment.start_at - buffer, appointment.end_at + buffer))
    return windows


def available_slots(
    session: Session, service: Service, day: date, settings: AppSettings
) -> list[datetime]:
    """Open local start times for a service on a given local date."""
    work_days = {int(d) for d in settings.work_days.split(",") if d.strip() != ""}
    if day.weekday() not in work_days:
        return []

    duration = timedelta(minutes=service.duration_minutes)
    interval = timedelta(minutes=settings.slot_interval_minutes)

    first = datetime.combine(day, _parse_hhmm(settings.work_start))
    last_end = datetime.combine(day, _parse_hhmm(settings.work_end))

    day_start_utc = to_utc(first, settings)
    day_end_utc = to_utc(last_end, settings)
    windows = busy_windows(session, day_start_utc, day_end_utc)
    now_local = local_now(settings).replace(tzinfo=None)

    slots = []
    cursor = first
    while cursor + duration <= last_end:
        if cursor > now_local:
            start_utc = to_utc(cursor, settings)
            end_utc = start_utc + duration
            if not any(
                start_utc < busy_end and end_utc > busy_start
                for busy_start, busy_end in windows
            ):
                slots.append(cursor)
        cursor += interval
    return slots


def slot_is_available(
    session: Session, service: Service, start_utc: datetime, settings: AppSettings
) -> bool:
    """Re-check a specific slot (used inside the booking transaction)."""
    start_local = to_local(start_utc, settings).replace(tzinfo=None)
    if start_local not in available_slots(
        session, service, start_local.date(), settings
    ):
        return False
    return start_utc > utcnow()
