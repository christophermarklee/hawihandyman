"""Database models for HaleClock."""

import math
import secrets
from datetime import UTC, datetime

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp; everything in the database is UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class AppSettings(SQLModel, table=True):
    __tablename__ = "settings"

    id: int = Field(default=1, primary_key=True)
    business_name: str = "Hawi Handyman"
    timezone: str = "Pacific/Honolulu"
    work_days: str = "0,1,2,3,4"  # weekday numbers, Monday=0
    work_start: str = "08:00"
    work_end: str = "17:00"
    travel_buffer_minutes: int = 30
    slot_interval_minutes: int = 30
    default_hourly_rate: float = 85.0
    tax_rate: float = 4.712  # Hawaii GET pass-on rate (Oahu)


class Client(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(index=True)
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class CustomerAccount(SQLModel, table=True):
    __tablename__ = "customer_accounts"

    id: int | None = Field(default=None, primary_key=True)
    cognito_sub: str = Field(unique=True, index=True)
    email: str | None = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class CustomerClientLink(SQLModel, table=True):
    __tablename__ = "customer_client_links"

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="customer_accounts.id", index=True)
    client_id: int = Field(foreign_key="client.id", unique=True, index=True)
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Service(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str | None = None
    duration_minutes: int
    rate: float  # flat price when is_flat_rate, otherwise hourly rate
    is_flat_rate: bool = True
    active: bool = True


class Appointment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id")
    service_id: int = Field(foreign_key="service.id")
    start_at: NaiveDatetime = Field(index=True)  # UTC
    end_at: NaiveDatetime  # UTC
    buffer_minutes: int = 0
    status: str = "booked"  # booked | done | cancelled
    notes: str | None = None
    confirmation_code: str = Field(
        default_factory=lambda: secrets.token_hex(12).upper(), index=True, unique=True
    )
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class Timecard(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    client_id: int | None = Field(default=None, foreign_key="client.id")
    appointment_id: int | None = Field(default=None, foreign_key="appointment.id")
    invoice_id: int | None = Field(default=None, foreign_key="invoice.id")
    clock_in_at: NaiveDatetime  # UTC
    clock_out_at: NaiveDatetime | None = None  # UTC; NULL while clocked in
    break_minutes: int = 0
    active_break_start: NaiveDatetime | None = None  # UTC; set while on break
    hourly_rate: float = 0.0
    notes: str | None = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)

    def billable_hours(self, as_of: datetime | None = None) -> float:
        end = self.clock_out_at or as_of or utcnow()
        seconds = max((end - self.clock_in_at).total_seconds(), 0)
        break_seconds = self.break_minutes * 60
        if self.active_break_start and self.clock_out_at is None:
            break_seconds += max((end - self.active_break_start).total_seconds(), 0)
        return max(seconds - break_seconds, 0) / 3600

    def earnings(self, as_of: datetime | None = None) -> float:
        return round(self.billable_hours(as_of) * self.hourly_rate, 2)


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    public_token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(16), index=True, unique=True
    )
    invoice_number: str = ""
    client_id: int = Field(foreign_key="client.id")
    subtotal: float = 0.0
    tax_mode: str = "add"  # add | included | none
    tax_rate: float = 0.0  # percent, e.g. 4.712
    tax_amount: float = 0.0
    total: float = 0.0
    status: str = "draft"  # draft | sent | paid | void
    payment_method: str | None = None  # Cash | Check | Venmo | Zelle
    paid_at: NaiveDatetime | None = None
    notes: str | None = None
    created_at: NaiveDatetime = Field(default_factory=utcnow)


class InvoiceItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id")
    description: str
    quantity: float = 1.0
    unit_amount: float = 0.0
    amount: float = 0.0


def compute_invoice_totals(
    subtotal: float, tax_mode: str, tax_rate: float
) -> tuple[float, float]:
    """Return (tax_amount, total) for a subtotal under the given GET mode."""
    if tax_mode not in {"add", "included", "none"}:
        raise ValueError("tax_mode must be add, included, or none")
    if not math.isfinite(subtotal) or not math.isfinite(tax_rate):
        raise ValueError("subtotal and tax_rate must be finite numbers")
    if subtotal < 0 or tax_rate < 0:
        raise ValueError("subtotal and tax_rate must not be negative")
    subtotal = round(subtotal, 2)
    rate = tax_rate / 100
    if tax_mode == "add":
        tax = round(subtotal * rate, 2)
        return tax, round(subtotal + tax, 2)
    if tax_mode == "included":
        tax = round(subtotal - subtotal / (1 + rate), 2)
        return tax, subtotal
    return 0.0, subtotal
