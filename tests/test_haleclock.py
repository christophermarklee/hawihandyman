import os
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("HALECLOCK_SECRET_KEY", "test-secret")
os.environ.setdefault("HALECLOCK_ADMIN_PASSWORD", "test-password")

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import database
from app.main import app
from app.models import Appointment, Client, Invoice, Timecard, compute_invoice_totals


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HALECLOCK_DB", str(tmp_path / "test.db"))
    database.reset_engine()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    database.reset_engine()


@pytest.fixture()
def admin(client):
    response = client.post(
        "/app/login", data={"password": "test-password"}, follow_redirects=False
    )
    assert response.status_code == 303
    return client


def next_weekday(weekday: int) -> date:
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7 + 7)


def book_slot(client, service_id: int, start: str, phone="8085551234", **overrides):
    data = {
        "service_id": service_id,
        "start": start,
        "name": "Test Client",
        "phone": phone,
        "email": "",
        "address": "123 Hawi Rd",
        "notes": "leaky sink",
    }
    data.update(overrides)
    return client.post("/api/book", data=data)


class TestAvailability:
    def test_workday_slots_respect_hours_and_duration(self, client):
        monday = next_weekday(0)
        response = client.get(f"/api/availability?service_id=1&date={monday}")
        slots = response.json()["slots"]
        assert f"{monday}T08:00" in slots
        # 1-hour service: last start fits before the 17:00 close
        assert f"{monday}T16:00" in slots
        assert f"{monday}T16:30" not in slots

    def test_no_slots_on_non_working_day(self, client):
        sunday = next_weekday(6)
        response = client.get(f"/api/availability?service_id=1&date={sunday}")
        assert response.json()["slots"] == []

    def test_booking_blocks_overlap_plus_travel_buffer(self, client):
        monday = next_weekday(0)
        assert book_slot(client, 1, f"{monday}T10:00").status_code == 200
        slots = client.get(f"/api/availability?service_id=1&date={monday}").json()[
            "slots"
        ]
        # 10:00-11:00 booked with a 30-minute travel buffer on each side.
        for taken in ("09:00", "09:30", "10:00", "10:30", "11:00"):
            assert f"{monday}T{taken}" not in slots
        assert f"{monday}T08:00" in slots
        assert f"{monday}T08:30" in slots
        assert f"{monday}T11:30" in slots
        assert f"{monday}T12:00" in slots


class TestBooking:
    def test_double_booking_rejected(self, client):
        monday = next_weekday(0)
        assert book_slot(client, 1, f"{monday}T10:00").status_code == 200
        response = book_slot(client, 1, f"{monday}T10:00", phone="8085559999")
        assert response.status_code == 409

    def test_repeat_phone_reuses_client(self, client):
        monday = next_weekday(0)
        assert book_slot(client, 1, f"{monday}T08:00").status_code == 200
        assert (
            book_slot(client, 1, f"{monday}T14:00", phone="(808) 555-1234").status_code
            == 200
        )
        with Session(database.get_engine()) as session:
            clients = session.exec(select(Client)).all()
        assert len(clients) == 1
        assert clients[0].phone == "8085551234"

    def test_confirmation_includes_ics_link(self, client):
        monday = next_weekday(0)
        response = book_slot(client, 1, f"{monday}T09:00")
        assert "/book/ics/" in response.text
        code = response.text.split("/book/ics/")[1].split('"')[0]
        ics = client.get(f"/book/ics/{code}")
        assert ics.status_code == 200
        assert "BEGIN:VCALENDAR" in ics.text


class TestClock:
    def test_admin_pages_render(self, admin):
        for path in (
            "/app",
            "/app/schedule",
            "/app/timecards",
            "/app/invoices",
            "/app/services",
            "/app/settings",
        ):
            assert admin.get(path).status_code == 200

    def test_clock_in_break_out_flow(self, admin):
        response = admin.post(
            "/app/clock/in",
            data={
                "new_client_name": "Walk Up",
                "hourly_rate": "90",
                "client_id": "",
                "appointment_id": "",
            },
        )
        assert response.status_code == 200
        assert "CLOCKED IN" in response.text

        assert (
            admin.post("/app/clock/in", data={"hourly_rate": "90"}).status_code == 409
        )

        response = admin.post("/app/clock/break")
        assert "ON BREAK" in response.text
        response = admin.post("/app/clock/break")
        assert "CLOCKED IN" in response.text

        response = admin.post("/app/clock/out")
        assert response.status_code == 200
        assert "Shift saved" in response.text
        with Session(database.get_engine()) as session:
            card = session.exec(select(Timecard)).one()
        assert card.clock_out_at is not None
        assert card.hourly_rate == 90
        assert card.active_break_start is None

    def test_clock_requires_login(self, client):
        response = client.post(
            "/app/clock/in", data={"hourly_rate": "90"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/app/login"


class TestSchedule:
    def test_calendar_shows_weekly_appointments_and_their_statuses(self, admin):
        monday = next_weekday(0)
        assert (
            book_slot(
                admin,
                1,
                f"{monday}T10:00",
                name="Completed Client",
            ).status_code
            == 200
        )
        assert (
            book_slot(
                admin,
                1,
                f"{monday}T14:00",
                phone="8085552222",
                name="Cancelled Client",
            ).status_code
            == 200
        )

        with Session(database.get_engine()) as session:
            appointments = session.exec(
                select(Appointment).order_by(Appointment.start_at)
            ).all()
            appointment_ids = [appointment.id for appointment in appointments]

        assert (
            admin.post(
                f"/app/schedule/{appointment_ids[0]}/done", follow_redirects=False
            ).status_code
            == 303
        )
        assert (
            admin.post(
                f"/app/schedule/{appointment_ids[1]}/cancel", follow_redirects=False
            ).status_code
            == 303
        )

        response = admin.get(f"/app/schedule?start={monday + timedelta(days=3)}")
        assert response.status_code == 200
        assert response.text.count('href="#appointment-') == 2
        assert "Completed Client" in response.text
        assert "Cancelled Client" in response.text
        assert "10:00 AM" in response.text
        assert "2:00 PM" in response.text
        assert "done" in response.text
        assert "cancelled" in response.text

    def test_manual_appointments_reject_conflicts_and_can_reschedule(self, admin):
        monday = next_weekday(0)
        assert book_slot(admin, 1, f"{monday}T10:00").status_code == 200
        assert (
            book_slot(admin, 1, f"{monday}T14:00", phone="8085552222").status_code
            == 200
        )

        with Session(database.get_engine()) as session:
            clients = session.exec(select(Client)).all()
            appointments = session.exec(
                select(Appointment).order_by(Appointment.start_at)
            ).all()
        client_id = clients[0].id
        appointment_id = appointments[0].id

        conflict = admin.post(
            "/app/schedule",
            data={
                "service_id": 1,
                "start": f"{monday}T10:00",
                "client_id": client_id,
            },
        )
        assert conflict.status_code == 409

        conflict = admin.post(
            f"/app/schedule/{appointment_id}/reschedule",
            data={"start": f"{monday}T13:30"},
        )
        assert conflict.status_code == 409

        moved = admin.post(
            f"/app/schedule/{appointment_id}/reschedule",
            data={"start": f"{monday}T08:00"},
            follow_redirects=False,
        )
        assert moved.status_code == 303


class TestInvoices:
    def _add_timecard(self, hours: float, rate: float, client_name="Inv Client") -> int:
        with Session(database.get_engine()) as session:
            record = session.exec(
                select(Client).where(Client.name == client_name)
            ).first()
            if record is None:
                record = Client(name=client_name, phone="8085550000")
                session.add(record)
                session.flush()
            start = datetime(2026, 1, 5, 18, 0)
            session.add(
                Timecard(
                    client_id=record.id,
                    clock_in_at=start,
                    clock_out_at=start + timedelta(hours=hours),
                    hourly_rate=rate,
                )
            )
            session.commit()
            return record.id

    def test_invoice_from_timecards_with_get_added(self, admin):
        client_id = self._add_timecard(2, 85)
        response = admin.post(
            "/app/invoices/from-timecards",
            data={
                "client_id": client_id,
                "tax_mode": "add",
                "tax_rate": "4.712",
                "timecard_ids": "1",
                "item_description": "Hardware",
                "item_amount": "42.50",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        with Session(database.get_engine()) as session:
            invoice = session.exec(select(Invoice)).one()
            card = session.exec(select(Timecard)).one()
        assert invoice.subtotal == 212.50  # 2h × $85 + $42.50
        assert invoice.tax_amount == 10.01  # 212.50 × 4.712%
        assert invoice.total == 222.51
        assert invoice.invoice_number == "INV-0001"
        assert card.invoice_id == invoice.id

        public = admin.get(f"/i/{invoice.public_token}")
        assert public.status_code == 200
        assert "222.51" in public.text

    def test_invalid_tax_and_negative_material_are_rejected(self, admin):
        client_id = self._add_timecard(1, 100)
        response = admin.post(
            "/app/invoices/from-timecards",
            data={
                "client_id": client_id,
                "tax_mode": "unexpected",
                "timecard_ids": "1",
            },
        )
        assert response.status_code == 400
        response = admin.post(
            "/app/invoices/from-timecards",
            data={
                "client_id": client_id,
                "tax_mode": "add",
                "tax_rate": "4.712",
                "timecard_ids": "1",
                "item_description": "Hardware",
                "item_amount": "-5",
            },
        )
        assert response.status_code == 400

    def test_invoice_tax_included_and_none(self, admin):
        tax, total = compute_invoice_totals(104.71, "included", 4.712)
        assert total == 104.71
        assert tax == 4.71
        assert compute_invoice_totals(100, "none", 4.712) == (0.0, 100)

    def test_mark_paid_shows_paid_on_public_link(self, admin):
        client_id = self._add_timecard(1, 100)
        admin.post(
            "/app/invoices/from-timecards",
            data={"client_id": client_id, "tax_mode": "none", "timecard_ids": "1"},
            follow_redirects=False,
        )
        with Session(database.get_engine()) as session:
            invoice = session.exec(select(Invoice)).one()
        response = admin.post(
            f"/app/invoices/{invoice.id}/mark-paid",
            data={"payment_method": "Venmo"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        public = admin.get(f"/i/{invoice.public_token}")
        assert "PAID" in public.text
        assert "Venmo" in public.text
        assert admin.post(f"/app/invoices/{invoice.id}/void").status_code == 409
        assert (
            admin.post(
                f"/app/invoices/{invoice.id}/mark-paid",
                data={"payment_method": "Cash"},
            ).status_code
            == 409
        )

    def test_invoiced_timecard_cannot_be_rebilled_until_void(self, admin):
        client_id = self._add_timecard(1, 100)
        admin.post(
            "/app/invoices/from-timecards",
            data={"client_id": client_id, "tax_mode": "none", "timecard_ids": "1"},
            follow_redirects=False,
        )
        response = admin.post(
            "/app/invoices/from-timecards",
            data={"client_id": client_id, "tax_mode": "none", "timecard_ids": "1"},
        )
        assert response.status_code == 409

        admin.post("/app/invoices/1/void", follow_redirects=False)
        with Session(database.get_engine()) as session:
            card = session.exec(select(Timecard)).one()
        assert card.invoice_id is None
