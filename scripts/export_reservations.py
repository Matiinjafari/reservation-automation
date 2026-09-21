"""Export reservations to CSV and send the file to the admins."""

import csv
import logging
import os
from email.message import EmailMessage

import psycopg2

import mailer


log = logging.getLogger("export")

DB_URL = os.getenv("DB_URL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
CSV_FILENAME = "reservations.csv"


def export_reservations(path: str = CSV_FILENAME) -> bool:
    conn = psycopg2.connect(DB_URL)

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM reservations ORDER BY date, start_time"
            )
            rows = cur.fetchall()

            if not rows:
                log.info("There are no reservations to export")
                return False

            columns = [column[0] for column in cur.description]

        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            writer.writerows(rows)

        log.info("Exported %d reservation(s) to %s", len(rows), path)
        return True
    finally:
        conn.close()


def email_export(path: str = CSV_FILENAME) -> None:
    recipients = mailer.admin_recipients()
    if not recipients:
        log.warning("No admin email addresses are configured")
        return

    message = EmailMessage()
    message["Subject"] = "Current reservations list"
    message["From"] = FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message.set_content(
        "Hello,\n\nAttached is the latest list of reservations."
    )

    with open(path, "rb") as file:
        message.add_attachment(
            file.read(),
            maintype="text",
            subtype="csv",
            filename=os.path.basename(path),
        )

    if mailer.send(message):
        log.info("Sent the reservation export to the admins")


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if export_reservations():
        email_export()


if __name__ == "__main__":
    main()
