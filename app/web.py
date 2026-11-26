"""Shared Jinja2 template environment."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .models import AppSettings
from .timeutil import to_local

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def money(value: float) -> str:
    return f"${value:,.2f}"


def epoch(dt: datetime) -> int:
    """Naive-UTC datetime -> Unix seconds (for the client-side ticker)."""
    return int(dt.replace(tzinfo=UTC).timestamp())


def fmt_local(
    dt: datetime, settings: AppSettings, fmt: str = "%a %b %-d, %-I:%M %p"
) -> str:
    return to_local(dt, settings).strftime(fmt)


def fmt_hours(hours: float) -> str:
    whole = int(hours)
    minutes = round((hours - whole) * 60)
    return f"{whole}h {minutes:02d}m"


templates.env.filters["money"] = money
templates.env.filters["hours"] = fmt_hours
templates.env.filters["epoch"] = epoch
templates.env.globals["fmt_local"] = fmt_local
