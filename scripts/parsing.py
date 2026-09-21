"""Parsing helpers for reservation emails."""

import re
from datetime import datetime, time

from dateparser import parse as parse_datetime


DATE_SETTINGS = {"DATE_ORDER": "DMY"}
END_OF_DAY = time(23, 59)

COMMON_ROOM_DEPOSIT = 50
KITCHEN_SURCHARGE = 50

FACILITY_NAMES = {
    "common room",
    "the common room",
    "community room",
    "common-room",
    "commonroom",
    "meeting room",
    "conference room",
}

COMMON_ROOM_KEYWORDS = (
    "common room",
    "community room",
    "party room",
    "meeting room",
    "event room",
    "common-room",
    "commonroom",
)

SPECIAL_REQUEST_KEYWORDS = (
    "special",
    "exception",
    "priority",
    "vip",
    "urgent request",
)


def parse_date(value: str) -> datetime | None:
    text = (value or "").strip()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.strptime(text, "%Y-%m-%d")

    return parse_datetime(text, settings=DATE_SETTINGS)


def parse_time(value: str) -> time:
    text = (value or "").strip().replace("24:00", "23:59")

    if re.fullmatch(r"\d{1,2}", text):
        text = f"{int(text):02d}:00"

    if not re.search(r"(?:\b|\d)(am|pm)\b", text.lower()):
        try:
            return datetime.strptime(text, "%H:%M").time()
        except ValueError:
            pass

    parsed = parse_datetime(text, settings=DATE_SETTINGS)
    if not parsed:
        raise ValueError(f"Invalid time: {text}")

    return parsed.time()


def mentions_year(text: str) -> bool:
    return bool(re.search(r"\b(?:19|20)\d{2}\b", text or ""))


def is_requested(body: str, term: str) -> bool:
    text = (body or "").lower()
    term_pattern = re.escape(term)

    if not re.search(rf"\b{term_pattern}\b", text):
        return False

    negated_before = re.search(
        (
            r"(?:\bno\b|\bnot\b|\bwithout\b|don't|do not|"
            r"\bisn't\b|\bis not\b|\bnot required\b)"
            rf"[^\n\r,.;:]{{0,12}}\b{term_pattern}\b"
        ),
        text,
    )

    negated_other = re.search(
        (
            rf"\bno (?:need|need for|use|usage) (?:for )?\b{term_pattern}\b"
            rf"|\b{term_pattern}\b (?:not )?(?:needed|required)"
        ),
        text,
    )

    return not (negated_before or negated_other)


def extract_room(body: str) -> str | None:
    labelled_room = re.search(
        (
            r"(?:Your\s+Room\s+Number|Room(?:\s+Number)?)"
            r"[:\-]?\s*([A-Za-z0-9.\-]{2,10})"
        ),
        body,
        re.IGNORECASE,
    )

    if labelled_room:
        return labelled_room.group(1).strip()

    room_number = re.search(
        r"\b\d{1,2}\.\d{1,2}(?:\.[A-Za-z])?\b",
        body,
    )
    return room_number.group(0).strip() if room_number else None


def parse_attendees(text: str) -> int | None:
    text = text or ""

    labelled_count = re.search(
        (
            r"(?:number of (?:people|guests|attendees|participants)|"
            r"attendees|guests)[:\-]?\s*(\d{1,4})\b"
        ),
        text,
        re.IGNORECASE,
    )

    if labelled_count:
        return int(labelled_count.group(1))

    count_with_label = re.search(
        r"\b(\d{1,4})\s*(?:people|guests|attendees|participants)\b",
        text,
        re.IGNORECASE,
    )

    return int(count_with_label.group(1)) if count_with_label else None


def resource_from_subject(subject: str) -> str | None:
    subject = (subject or "").lower()

    if any(keyword in subject for keyword in COMMON_ROOM_KEYWORDS):
        return "common_room"

    if "grill" in subject:
        return "grill"

    return None


def is_special_request(subject: str | None) -> bool:
    subject = (subject or "").lower()
    return any(
        keyword in subject
        for keyword in SPECIAL_REQUEST_KEYWORDS
    )


def calculate_deposit(
    resource_type: str,
    kitchen_requested: bool,
) -> int:
    if resource_type != "common_room":
        return 0

    deposit = COMMON_ROOM_DEPOSIT
    if kitchen_requested:
        deposit += KITCHEN_SURCHARGE

    return deposit
