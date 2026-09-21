"""Shared SMTP utilities."""

import logging
import os
import smtplib
from email.message import EmailMessage


log = logging.getLogger(__name__)


def admin_recipients() -> list[str]:
    addresses = os.getenv("ADMIN_EMAILS", "")
    return [
        address.strip()
        for address in addresses.split(",")
        if address.strip()
    ]


def send(message: EmailMessage) -> bool:
    emails_enabled = os.getenv("SEND_EMAILS", "false").lower() == "true"

    if not emails_enabled:
        log.info("Email sending is disabled: %s", message["Subject"])
        return False

    server = os.getenv("SMTP_SERVER")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    with smtplib.SMTP(server, port) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)

    return True
