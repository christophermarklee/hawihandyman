"""Timezone helpers: storage is UTC, presentation is the configured local zone."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .models import AppSettings, utcnow

__all__ = ["local_now", "to_local", "to_utc", "tz", "utcnow"]


def tz(settings: AppSettings) -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def to_local(dt: datetime, settings: AppSettings) -> datetime:
    return dt.replace(tzinfo=UTC).astimezone(tz(settings))


def to_utc(local_dt: datetime, settings: AppSettings) -> datetime:
    """Convert a naive local datetime to naive UTC for storage."""
    return local_dt.replace(tzinfo=tz(settings)).astimezone(UTC).replace(tzinfo=None)


def local_now(settings: AppSettings) -> datetime:
    return datetime.now(tz(settings))
