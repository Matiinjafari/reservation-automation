"""Process unread reservation emails and reply automatically."""

import email
import imaplib
import json
import logging
import os
import re
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from html import unescape

import psycopg2
from openai import APIError, OpenAI
from pydantic import BaseModel, Field

import mailer
import parsing


log = logging.getLogger("reservations")

IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
FROM_EMAIL = os.getenv("FROM_EMAIL")
DB_URL = os.getenv("DB_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

RESOURCE_LABELS = {
    "grill": "the grill",
    "common_room": "the common room",
}


class EmailReservation(BaseModel):
    date: str = Field(description="Reservation date in YYYY-MM-DD format")
    start_time: str = Field(description="Start time in HH:MM format")
    end_time: str = Field(description="End time in HH:MM format")
    room: str | None = Field(
        default=None,
        description="The resident's apartment or room number",
    )
    phone: str | None = None
    name: str | None = None
    reason: str | None = None
    grill_requested: bool = False
    kitchen_requested: bool = False


TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "extract_reservation",
        "description": "Extract reservation details from an email.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "start_time": {"type": "string", "description": "HH:MM"},
                "end_time": {"type": "string", "description": "HH:MM"},
                "room": {
                    "type": ["string", "null"],
                    "description": "Resident's apartment or room number",
                },
                "phone": {"type": ["string", "null"]},
                "name": {"type": ["string", "null"]},
                "reason": {"type": ["string", "null"]},
                "grill_requested": {"type": "boolean"},
                "kitchen_requested": {"type": "boolean"},
            },
            "required": [
                "date",
                "start_time",
                "end_time",
                "grill_requested",
                "kitchen_requested",
            ],
        },
    },
}

SYSTEM_PROMPT = """
Extract reservation details from the email.

Dates normally use the European day-month-year format. Return dates as
YYYY-MM-DD and times as HH:MM in 24-hour format.

If the email contains only one time, use 23:59 as the end time.
Treat 24:00 as 23:59.

The room field is the sender's apartment or room number, such as 4.2b or
1.7.C. Do not use the name of the facility as the room.

Set grill_requested and kitchen_requested to true only when the sender
explicitly requests them.
""".strip()


def call_with_retry(func, *args, attempts=3, **kwargs):
    for attempt in range(attempts):
        try:
            return func(*args, **kwargs)
        except APIError:
            if attempt + 1 == attempts:
                raise

            wait_seconds = 2**attempt
            log.warning(
                "OpenAI request failed. Retrying in %d second(s).",
                wait_seconds,
            )
            time.sleep(wait_seconds)


def extract_with_llm(body: str) -> dict:
    client = OpenAI()

    response = call_with_retry(
        client.chat.completions.create,
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Extract the reservation from this email:\n\n{body}",
            },
        ],
        tools=[TOOL_DEFINITION],
        tool_choice="required",
    )

    tool_calls = response.choices[0].message.tool_calls or []
    if not tool_calls:
        raise ValueError("The model did not return reservation data")

    arguments = json.loads(tool_calls[0].function.arguments)
    reservation = EmailReservation.model_validate(arguments)
    return reservation.model_dump()


def extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() != "text/plain":
                continue

            payload = part.get_payload(decode=True)
            if payload:
                return unescape(payload.decode(errors="ignore"))

        return ""

    payload = msg.get_payload(decode=True)
    if not payload:
        return ""

    return unescape(payload.decode(errors="ignore"))


def fields_from_llm(body: str, msg) -> dict:
    fields = extract_with_llm(body)
    log.info("Extracted reservation details with the LLM")

    date = parsing.parse_date(fields["date"])
    if not date:
        raise ValueError(f"Invalid date returned by the model: {fields['date']}")

    start_time = parsing.parse_time(fields["start_time"])
    end_text = (fields.get("end_time") or "").strip()
    end_time = (
        parsing.parse_time(end_text)
        if end_text
        else parsing.END_OF_DAY
    )

    room = (fields.get("room") or "").strip()
    if not room or room.lower() in parsing.FACILITY_NAMES:
        room = parsing.extract_room(body) or "Unknown"

    sender_name = parseaddr(msg.get("From"))[0]

    return {
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "name": (fields.get("name") or sender_name or "Unknown").strip(),
        "room": room,
        "phone": (fields.get("phone") or "Not provided").strip(),
        "reason": (fields.get("reason") or "Not specified").strip(),
        "grill_requested": parsing.is_requested(body, "grill"),
        "kitchen_requested": (
            parsing.is_requested(body, "kitchen")
            or bool(fields.get("kitchen_requested"))
        ),
    }


def fields_from_labels(body: str, msg) -> dict:
    def find(pattern: str) -> str | None:
        match = re.search(pattern, body, re.IGNORECASE)
        return match.group(1).strip() if match else None

    date_text = find(r"(?:Date)[:\-]?\s*(.+)")
    time_text = find(r"(?:Time(?: \(start and end\))?)[:\-]?\s*(.+)")

    if not date_text or not time_text:
        raise ValueError("Date or time is missing")

    date = parsing.parse_date(date_text)
    if not date:
        raise ValueError(f"Invalid date: {date_text}")

    time_range = re.search(
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
        r"\s*(?:-|/|to)\s*"
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        time_text,
        re.IGNORECASE,
    )

    if time_range:
        start_time = parsing.parse_time(time_range.group(1))
        end_time = parsing.parse_time(time_range.group(2))
    else:
        start_time = parsing.parse_time(time_text)
        end_time = parsing.END_OF_DAY

    sender_name = parseaddr(msg.get("From"))[0]

    return {
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "name": (
            find(r"(?:Name|Full Name)[:\-]?\s*(.+)")
            or sender_name
            or "Unknown"
        ),
        "room": (
            find(
                r"(?:Room(?: Number)?|Your Room Number)"
                r"[:\-]?\s*([A-Za-z0-9.\-]{2,10})"
            )
            or parsing.extract_room(body)
            or "Unknown"
        ),
        "phone": (
            find(
                r"(?:Phone|phn|phn no|phone number|Your Phone Number)"
                r"[:\-]?\s*([\+\d][\d\s\-().]+)"
            )
            or "Not provided"
        ),
        "reason": (
            find(r"(?:Reason(?: for reservation)?)[:\-]?\s*(.+)")
            or "Not specified"
        ),
        "grill_requested": parsing.is_requested(body, "grill"),
        "kitchen_requested": parsing.is_requested(body, "kitchen"),
    }


def parse_email(msg) -> dict:
    subject = msg.get("Subject") or ""
    body = extract_body(msg)

    log.info("Parsing email: %s", subject)
    log.debug("Email body:\n%s", body)

    try:
        fields = fields_from_llm(body, msg)
    except Exception as error:
        log.warning("LLM extraction failed: %s", error)
        fields = fields_from_labels(body, msg)

    date = fields["date"]
    if not parsing.mentions_year(body):
        date = date.replace(year=datetime.now().year)

    start = datetime.combine(date.date(), fields["start_time"])
    end = datetime.combine(date.date(), fields["end_time"])

    if end <= start:
        end = datetime.combine(date.date(), parsing.END_OF_DAY)

    resource_type = parsing.resource_from_subject(subject)
    if not resource_type:
        resource_type = (
            "grill"
            if fields["grill_requested"]
            else "common_room"
        )

    return {
        "date": date.date().isoformat(),
        "start_time": start.strftime("%H:%M:%S"),
        "end_time": end.strftime("%H:%M:%S"),
        "name": fields["name"],
        "sender": parseaddr(msg.get("From"))[1],
        "phone": fields["phone"],
        "reason": fields["reason"],
        "room": fields["room"],
        "deposit": parsing.calculate_deposit(
            resource_type,
            fields["kitchen_requested"],
        ),
        "attendees_count": parsing.parse_attendees(body),
        "resource_type": resource_type,
    }


def send_email(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = FROM_EMAIL
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        mailer.send(message)
    except Exception:
        log.exception("Could not send email '%s'", subject)


def forward_to_admins(raw_email: bytes, subject: str | None) -> None:
    recipients = mailer.admin_recipients()
    if not recipients:
        log.warning("No admin email addresses are configured")
        return

    message = EmailMessage()
    message["From"] = FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"FWD: {subject or '(no subject)'}"
    message.set_content(
        "This email was forwarded automatically because it appears to be "
        "a special request. The original message is attached."
    )
    message.add_attachment(
        raw_email,
        maintype="message",
        subtype="rfc822",
        filename="original.eml",
    )

    try:
        mailer.send(message)
    except Exception:
        log.exception("Could not forward the request to the admins")


def has_conflict(cur, date, start_time, end_time, resource_type) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM reservations
        WHERE date = %s
          AND resource_type = %s
          AND start_time < %s
          AND end_time > %s
        LIMIT 1
        """,
        (date, resource_type, end_time, start_time),
    )
    return cur.fetchone() is not None


def save_reservation(cur, reservation: dict) -> None:
    cur.execute(
        """
        INSERT INTO reservations (
            date,
            start_time,
            end_time,
            name,
            email,
            phone,
            reason,
            room,
            deposit,
            resource_type,
            attendees_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            reservation["date"],
            reservation["start_time"],
            reservation["end_time"],
            reservation["name"],
            reservation["sender"],
            reservation["phone"],
            reservation["reason"],
            reservation["room"],
            reservation["deposit"],
            reservation["resource_type"],
            reservation["attendees_count"],
        ),
    )


def log_attempt(cur, data: dict, status: str, reason: str = "") -> None:
    cur.execute(
        """
        INSERT INTO reservation_logs (
            email,
            name,
            phone,
            request_date,
            request_time,
            status,
            reason,
            room,
            resource_type,
            attendees_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            data.get("sender", "unknown"),
            data.get("name", "unknown"),
            data.get("phone", "unknown"),
            data.get("date"),
            data.get("start_time"),
            status,
            reason,
            data.get("room", "unknown"),
            data.get("resource_type"),
            data.get("attendees_count"),
        ),
    )


def process_message(cur, conn, raw_email: bytes) -> None:
    msg = email.message_from_bytes(raw_email)
    subject = msg.get("Subject")

    if parsing.is_special_request(subject):
        log.info("Forwarding special request to the admins")
        forward_to_admins(raw_email, subject)
        return

    try:
        reservation = parse_email(msg)
    except Exception as error:
        log.error("Could not parse reservation email: %s", error)

        try:
            log_attempt(
                cur,
                {"sender": parseaddr(msg.get("From"))[1]},
                "failed",
                str(error),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            log.exception("Could not log the failed reservation attempt")

        return

    label = RESOURCE_LABELS[reservation["resource_type"]]
    slot = (
        f"on {reservation['date']} "
        f"from {reservation['start_time'][:5]} "
        f"to {reservation['end_time'][:5]}"
    )

    if has_conflict(
        cur,
        reservation["date"],
        reservation["start_time"],
        reservation["end_time"],
        reservation["resource_type"],
    ):
        send_email(
            reservation["sender"],
            "Reservation denied",
            f"Hello,\n\nSorry, {label} is already taken {slot}.",
        )
        log_attempt(cur, reservation, "denied", "Time conflict")
        conn.commit()
        return

    save_reservation(cur, reservation)
    log_attempt(cur, reservation, "confirmed")
    conn.commit()

    send_email(
        reservation["sender"],
        "Reservation confirmed",
        (
            f"Hello,\n\nYour reservation for {label} {slot} is confirmed.\n"
            "You will receive a separate email about the key pickup."
        ),
    )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    mailbox = imaplib.IMAP4_SSL(IMAP_SERVER)
    conn = None
    cur = None

    try:
        mailbox.login(IMAP_USER, IMAP_PASSWORD)
        mailbox.select("inbox")

        _, messages = mailbox.search(None, "(UNSEEN)")
        message_ids = messages[0].split()
        log.info("Found %d unread email(s)", len(message_ids))

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        for message_id in message_ids:
            _, message_data = mailbox.fetch(message_id, "(RFC822)")
            process_message(cur, conn, message_data[0][1])
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

        try:
            mailbox.logout()
        except Exception:
            log.exception("Could not close the mailbox connection")


if __name__ == "__main__":
    main()
