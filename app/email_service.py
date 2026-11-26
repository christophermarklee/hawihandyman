"""Customer email delivery through Amazon SES."""

import logging
from functools import lru_cache

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from . import config
from .models import AppSettings, Appointment, Client, Invoice, Service
from .timeutil import to_local

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _ses_client(region: str):
    return boto3.client("sesv2", region_name=region)


def send_customer_email(
    recipient: str | None,
    subject: str,
    body: str,
    notification: str,
) -> bool | None:
    if not recipient:
        return None

    settings = config.ses_settings()
    if settings is None:
        logger.error("SES is not configured; %s email was not sent", notification)
        return False

    params: dict[str, object] = {
        "FromEmailAddress": settings.from_address,
        "Destination": {"ToAddresses": [recipient]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            }
        },
    }
    if settings.reply_to_address:
        params["ReplyToAddresses"] = [settings.reply_to_address]

    try:
        _ses_client(settings.region).send_email(**params)
    except (BotoCoreError, ClientError) as error:
        error_code = (
            error.response.get("Error", {}).get("Code", type(error).__name__)
            if isinstance(error, ClientError)
            else type(error).__name__
        )
        logger.error(
            "SES delivery failed for %s (error %s)", notification, error_code
        )
        return False
    return True


def send_appointment_email(
    client: Client,
    appointment: Appointment,
    service: Service,
    settings: AppSettings,
    event: str,
) -> bool | None:
    local_start = to_local(appointment.start_at, settings)
    when = local_start.strftime("%A, %B %-d at %-I:%M %p")
    messages = {
        "booked": (
            "Your Hawi Handyman appointment is confirmed",
            f"Your {service.name} appointment is booked for {when} Hawaii time.\n"
            f"Confirmation code: {appointment.confirmation_code}\n"
            f"Add it to your calendar: {config.public_base_url()}/book/ics/"
            f"{appointment.confirmation_code}",
        ),
        "rescheduled": (
            "Your Hawi Handyman appointment was rescheduled",
            f"Your {service.name} appointment is now scheduled for {when} "
            "Hawaii time.",
        ),
        "cancelled": (
            "Your Hawi Handyman appointment was cancelled",
            f"Your {service.name} appointment scheduled for {when} Hawaii time "
            "has been cancelled.",
        ),
        "completed": (
            "Your Hawi Handyman appointment is complete",
            f"Your {service.name} appointment on {when} Hawaii time is complete.",
        ),
    }
    subject, details = messages[event]
    body = f"Aloha {client.name},\n\n{details}\n\nMahalo,\nHawi Handyman"
    return send_customer_email(
        client.email, subject, body, f"appointment_{event}"
    )


def send_invoice_email(
    client: Client,
    invoice: Invoice,
    event: str,
) -> bool | None:
    messages = {
        "issued": (
            f"Your Hawi Handyman invoice {invoice.invoice_number}",
            f"Your invoice {invoice.invoice_number} for ${invoice.total:,.2f} "
            f"is ready to view and pay:\n{config.public_base_url()}/i/"
            f"{invoice.public_token}",
        ),
        "paid": (
            f"Payment received for invoice {invoice.invoice_number}",
            f"We received your payment of ${invoice.total:,.2f} for invoice "
            f"{invoice.invoice_number}. Mahalo!",
        ),
        "void": (
            f"Invoice {invoice.invoice_number} was cancelled",
            f"Invoice {invoice.invoice_number} for ${invoice.total:,.2f} "
            "has been cancelled. Please contact us if you have questions.",
        ),
    }
    subject, details = messages[event]
    body = f"Aloha {client.name},\n\n{details}\n\nMahalo,\nHawi Handyman"
    return send_customer_email(client.email, subject, body, f"invoice_{event}")
