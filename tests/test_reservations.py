from datetime import datetime, time
from email.message import EmailMessage

import pytest

import parsing
import update_reservations as reservations


def make_email(
    subject: str,
    body: str,
    sender: str = "Test User <test.user@example.com>",
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message.set_content(body)
    return message


def raise_llm_error(_body: str):
    raise RuntimeError("LLM is not available during tests")


# Date and time parsing

def test_parses_iso_date():
    assert parsing.parse_date("2026-03-04") == datetime(2026, 3, 4)


def test_parses_dates_with_day_first():
    assert parsing.parse_date("04/03/2026") == datetime(2026, 3, 4)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("18:30", time(18, 30)),
        ("9:15", time(9, 15)),
        ("21", time(21, 0)),
        ("9pm", time(21, 0)),
        ("9:30 pm", time(21, 30)),
        ("24:00", time(23, 59)),
    ],
)
def test_parses_time(value, expected):
    assert parsing.parse_time(value) == expected


def test_rejects_invalid_time():
    with pytest.raises(ValueError):
        parsing.parse_time("sometime later")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("on 4 March 2026", True),
        ("on 4 March", False),
    ],
)
def test_detects_year(text, expected):
    assert parsing.mentions_year(text) is expected


# Reservation details

@pytest.mark.parametrize(
    "body",
    [
        "We would like the grill.",
        "Please reserve the grill for us",
    ],
)
def test_detects_grill_request(body):
    assert parsing.is_requested(body, "grill")


@pytest.mark.parametrize(
    "body",
    [
        "no grill please",
        "without grill",
        "grill not required",
        "we don't need the grill",
        "just the room",
    ],
)
def test_ignores_negated_grill_request(body):
    assert not parsing.is_requested(body, "grill")


def test_reads_labelled_room_number():
    body = "Your Room Number: 4.2b\nGuests: 10"
    assert parsing.extract_room(body) == "4.2b"


def test_finds_unlabelled_room_number():
    body = "I live in 1.7.C and need the room"
    assert parsing.extract_room(body) == "1.7.C"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Number of guests: 20", 20),
        ("about 15 people", 15),
        ("no count given", None),
    ],
)
def test_reads_attendee_count(body, expected):
    assert parsing.parse_attendees(body) == expected


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Grill reservation", "grill"),
        ("Common room request", "common_room"),
        ("Grill in the common room", "common_room"),
        ("Reservation", None),
    ],
)
def test_detects_resource_from_subject(subject, expected):
    assert parsing.resource_from_subject(subject) == expected


def test_detects_special_request():
    assert parsing.is_special_request("Special request for Saturday")
    assert not parsing.is_special_request("Common room reservation")


@pytest.mark.parametrize(
    ("resource", "kitchen_requested", "expected"),
    [
        ("common_room", False, 50),
        ("common_room", True, 100),
        ("grill", True, 0),
    ],
)
def test_calculates_deposit(resource, kitchen_requested, expected):
    assert (
        parsing.calculate_deposit(resource, kitchen_requested)
        == expected
    )


# Email parsing

def test_uses_labelled_fields_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        reservations,
        "extract_with_llm",
        raise_llm_error,
    )

    message = make_email(
        "Common room reservation",
        "Name: Test User\n"
        "Your Room Number: 4.2b\n"
        "Date: 12.06.2026\n"
        "Time (start and end): 18:00 - 22:00\n"
        "Phone: +49 123 456789\n"
        "Reason: Birthday\n"
        "Guests: 12\n"
        "We would also like to use the kitchen.\n",
    )

    result = reservations.parse_email(message)

    assert result["date"] == "2026-06-12"
    assert result["start_time"] == "18:00:00"
    assert result["end_time"] == "22:00:00"
    assert result["room"] == "4.2b"
    assert result["sender"] == "test.user@example.com"
    assert result["resource_type"] == "common_room"
    assert result["deposit"] == 100
    assert result["attendees_count"] == 12


def test_raises_when_required_fields_are_missing(monkeypatch):
    monkeypatch.setattr(
        reservations,
        "extract_with_llm",
        raise_llm_error,
    )

    message = make_email(
        "Reservation",
        "Hello, can I book something?",
    )

    with pytest.raises(ValueError):
        reservations.parse_email(message)


def test_single_time_uses_end_of_day(monkeypatch):
    monkeypatch.setattr(
        reservations,
        "extract_with_llm",
        raise_llm_error,
    )

    message = make_email(
        "Grill",
        "Date: 2026-07-01\n"
        "Time: 17:00\n"
        "Room: 3.10\n",
    )

    result = reservations.parse_email(message)

    assert result["end_time"] == "23:59:00"
    assert result["resource_type"] == "grill"
    assert result["deposit"] == 0


def test_missing_year_uses_current_year(monkeypatch):
    monkeypatch.setattr(
        reservations,
        "extract_with_llm",
        raise_llm_error,
    )

    message = make_email(
        "Grill",
        "Date: 1 July\n"
        "Time: 17:00 - 21:00\n"
        "Room: 3.10\n",
    )

    result = reservations.parse_email(message)

    current_year = datetime.now().year
    assert result["date"] == f"{current_year}-07-01"


def test_replaces_facility_name_with_room_number(monkeypatch):
    llm_result = {
        "date": "2026-08-15",
        "start_time": "14:00",
        "end_time": "18:00",
        "room": "common room",
        "phone": None,
        "name": "Test User",
        "reason": "Meeting",
        "grill_requested": False,
        "kitchen_requested": False,
    }

    monkeypatch.setattr(
        reservations,
        "extract_with_llm",
        lambda _body: llm_result,
    )

    message = make_email(
        "Meeting room booking",
        "Hi, room 2.4 please. On 15 August 2026, 14-18.",
    )

    result = reservations.parse_email(message)

    assert result["room"] == "2.4"
    assert result["date"] == "2026-08-15"
    assert result["resource_type"] == "common_room"
    assert result["phone"] == "Not provided"
