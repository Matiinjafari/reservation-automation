# Reservation Automation

A Python application that handles room and grill reservation requests sent by email. It reads unread messages from a mailbox, extracts the reservation details, checks whether the requested time is available, stores confirmed bookings in PostgreSQL, and replies to the sender.

I built it for a residential building where residents book the common room and grill by email. Requests arrive as free text, use different formats, and often omit the year. The main challenge is turning those messages into consistent reservation data.

**Status:** Prototype. Sending real emails is disabled by default. See [Sending emails](#sending-emails).

## How it works

```text
unread email (IMAP)
      |
      +-- special request? --> forward to admins and stop
      |
      v
  parse the body
      +-- LLM extraction using function calling and Pydantic validation
      +-- labelled-field fallback if the LLM step fails
      |
      v
  slot already booked for this resource?
      +-- no  --> save reservation, send confirmation, log as confirmed
      +-- yes --> send rejection, log as denied

  parsing errors are logged as failed
```

Special requests are forwarded directly to the admins and are not written to `reservation_logs`.

Some parts of the parsing require a little extra handling:

- **Dates and times:** ISO dates are accepted directly. Other dates are interpreted in day-month-year order. Times such as `9pm`, `9:30 pm`, `21`, and `24:00` are supported. If the email does not contain a four-digit year, the current year is used.
- **Negations:** Phrases such as "no grill" must not create a grill reservation. The grill flag is therefore determined by a small negation-aware text check. The kitchen is considered requested if either the text check or the model detects a request.
- **Room numbers:** The `room` field refers to the sender's apartment number, not the requested facility. If the model returns a value such as "common room", the application tries to read the apartment number from the email instead.
- **Resource selection:** The subject line is used to choose between the grill and common room. If the subject gives no indication, an explicit grill request in the body selects the grill; otherwise the common room is used.
- **Deposit:** The common-room deposit is 50, with another 50 added when the kitchen is requested. Grill reservations do not require a deposit. These amounts are defined in `scripts/parsing.py`.
- **Availability:** Reservations for the same resource and date conflict when their time ranges overlap. Back-to-back bookings are allowed, so one booking may end when the next begins.

## Project layout

```text
scripts/
  update_reservations.py   reads emails, processes requests and sends replies
  export_reservations.py   exports reservations to CSV and emails the file to admins
  parsing.py               parsing and deposit helpers without network or database access
  mailer.py                shared SMTP helper with email sending disabled by default
  init_db.sql              database table definitions
tests/
  test_reservations.py     tests for parsing and email-to-reservation conversion
.gitlab-ci.yml             test, scheduled update and export jobs
```

## Setup

The application requires Python 3.11, PostgreSQL, an IMAP/SMTP mailbox, and an OpenAI API key.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your own values to .env, then load them:
export $(grep -v '^#' .env | xargs)

psql "$DB_URL" -f scripts/init_db.sql
python scripts/update_reservations.py
```

Configuration is read from environment variables. `.env.example` lists the required values. Do not commit a real `.env` file.

### Database

`scripts/init_db.sql` creates two tables:

- `reservations` contains confirmed bookings.
- `reservation_logs` records regular requests with the status `confirmed`, `denied`, or `failed`.

### Sending emails

Outgoing email is disabled by default. In this mode, messages are skipped and their subjects are written to the log.

Set the following variable to enable confirmation emails, rejection emails, admin forwards, and CSV exports:

```bash
SEND_EMAILS=true
```

This setting is shared by both email-processing scripts.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover the parsing helpers and the conversion from an email to a reservation, including the labelled-field fallback and negation handling. The LLM call is replaced with a stub, and the database queries are not executed by the test suite.

Example request handled by the fallback parser:

```text
Subject: Common room reservation
Name: Test User
Your Room Number: 4.2b
Date: 12.06.2026
Time (start and end): 18:00 - 22:00
Phone: +49 123 456789
Reason: Birthday
Guests: 12
We would also like to use the kitchen.
```

The resulting reservation data is:

```json
{
  "date": "2026-06-12",
  "start_time": "18:00:00",
  "end_time": "22:00:00",
  "name": "Test User",
  "sender": "test.user@example.com",
  "phone": "+49 123 456789",
  "reason": "Birthday",
  "room": "4.2b",
  "deposit": 100,
  "attendees_count": 12,
  "resource_type": "common_room"
}
```

## CI/CD

The project uses GitLab CI/CD.

| Job | When | Purpose |
| --- | --- | --- |
| `initialize-db` | manually in a non-scheduled pipeline | creates the tables from `scripts/init_db.sql` |
| `test` | every non-scheduled pipeline | runs the test suite with `pytest` |
| `update-reservations` | scheduled pipeline | processes unread reservation emails |
| `export-reservations` | scheduled pipeline | creates `reservations.csv`, stores it as a job artifact, and emails it to the admins when email sending is enabled |

Add the values from `.env.example` as masked CI/CD variables and create a pipeline schedule for the update and export jobs. GitLab's CI lint can be used to validate changes to `.gitlab-ci.yml`.

## Limitations

- Negation handling is heuristic. Common expressions such as "no grill" and "grill not required" are recognised, but unusual phrasing may be missed.
- The fallback parser expects labelled fields such as `Date:` and `Time:`. It is intended only as a backup when LLM extraction fails.
- The model can be configured with `OPENAI_MODEL`; its default is `gpt-3.5-turbo`. Extraction quality may differ between models.
- Only the first `text/plain` part of a message is read. HTML-only emails are not supported.
- The application handles one mailbox and two resources: `common_room` and `grill`. Supporting another resource requires changes to the subject rules and deposit calculation.
- Availability is checked before insertion without a database-level exclusion constraint. Two processes handling overlapping requests at exactly the same time could therefore create conflicting bookings.

## Privacy

The database and CSV export contain residents' names, email addresses, phone numbers, and room numbers. Keep the database and CI/CD project private. Do not commit CSV exports, `.env` files, or real emails. The test suite uses fictional data only.
