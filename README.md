# Reservation Automation

A Python tool that handles room and grill reservation requests sent by email. It reads the unread mails in a mailbox, works out what was requested, checks whether the slot is free, stores the booking in PostgreSQL and replies to the sender.

I built it for a residential building where residents book the common room and the grill by email. Requests arrive as free text, in different formats and often without a year, so the interesting part is turning those mails into clean data.

**Status:** prototype. Sending real emails is switched off by default (see [Sending emails](#sending-emails)).

## How it works

```
unread email (IMAP)
      │
      ├─ subject looks like a "special request"? ──► forward to admins, stop
      │
      ▼
  parse the body
      ├─ 1. LLM extraction (OpenAI function calling, validated with Pydantic)
      └─ 2. regex fallback on labelled lines ("Date:", "Time:", ...) if step 1 fails
      │
      ▼
  slot already booked for this resource?
      ├─ no  ─► save reservation, send confirmation
      └─ yes ─► send rejection
      │
      ▼
  every attempt is written to reservation_logs (confirmed / denied / failed)
```

Some details that took a bit of care:

- **Dates and times.** ISO dates are trusted as they are, everything else is read day-first. `9pm`, `9:30 pm`, `21` and `24:00` all work. If the email contains no four-digit year, the current year is used.
- **Negations.** "No grill" must not book the grill, so the grill and kitchen flags come from a small negation-aware check instead of trusting the model alone.
- **Room numbers.** The model is told that `room` is the sender's own apartment number, not the facility. If it returns "common room" anyway, the number is read from the text instead.
- **Resource.** The subject line decides between grill and common room. Without a hint in the subject, a grill request in the body means grill, everything else means common room.
- **Deposit.** Common room: 50, plus 50 if the kitchen is requested. Grill: none. The amounts are constants in `scripts/parsing.py`.
- **Availability.** Two bookings of the same resource on the same day conflict if their time ranges overlap; back-to-back bookings (one ends at 18:00, the next starts at 18:00) do not.

## Project layout

```
scripts/
  update_reservations.py   main job: read mail, parse, book, reply
  export_reservations.py   export all reservations to CSV and email it to the admins
  parsing.py               date, time, room, negation and deposit helpers (no I/O)
  mailer.py                SMTP helper with a dry-run default
  init_db.sql              table definitions
tests/
  test_reservations.py     unit tests for the parsing and email-to-reservation logic
.gitlab-ci.yml             test job plus the scheduled update and export jobs
```

## Setup

You need Python 3.11, a PostgreSQL database, an IMAP/SMTP mailbox and an OpenAI API key.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in your own values
export $(grep -v '^#' .env | xargs)

psql "$DB_URL" -f scripts/init_db.sql
python scripts/update_reservations.py
```

Configuration is read from environment variables only. `.env.example` lists all of them. Never commit your real `.env`.

### Database

`scripts/init_db.sql` creates two tables:

- `reservations`: the confirmed bookings
- `reservation_logs`: one row per processed request, with its status

The file was reconstructed from the queries in the scripts, so check the column types against your own database before you rely on it.

### Sending emails

By default the scripts only log what they would send. Set `SEND_EMAILS=true` to send real confirmations, rejections, admin forwards and the CSV export. This applies to both scripts.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover the parsing helpers and the email-to-reservation step, including the regex fallback and the negation handling. The LLM call and the database are not part of the tests: the LLM is replaced by a stub, and the SQL queries have to be tried against a real database.

Example of what the fallback parser returns for a labelled request:

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

The pipeline is written for GitLab CI/CD and does not run on GitHub.

| Job | When | What it does |
| --- | --- | --- |
| `initialize-db` | manual | creates the tables from `scripts/init_db.sql` |
| `test` | pushes and merge requests | runs `pytest` |
| `update-reservations` | scheduled pipeline | processes the unread mails |
| `export-reservations` | scheduled pipeline | writes `reservations.csv`, keeps it as a job artifact and emails it to the admins |

Set the variables from `.env.example` as masked CI/CD variables and create a pipeline schedule for the two scheduled jobs. After editing `.gitlab-ci.yml`, check it with the CI lint in GitLab's pipeline editor.

## Limitations

- Negation handling is heuristic. "No grill" and "grill not required" are recognised, but unusual phrasings may not be.
- The regex fallback needs labelled lines (`Date:`, `Time:`). It is only a safety net for when the LLM call fails.
- The model name is configurable (`OPENAI_MODEL`, default `gpt-3.5-turbo`). Results depend on the model, so a stricter model is worth trying if extraction is unreliable.
- Only the first `text/plain` part of an email is read; HTML-only mails are not handled.
- One mailbox, two resources (`common_room`, `grill`). Adding another resource means extending the subject rules and the deposit logic.

## Privacy

The database and the CSV export contain names, email addresses, phone numbers and room numbers of residents. Keep the database and the CI/CD project private, and do not commit exports, `.env` files or real emails. The tests only use made-up data.
