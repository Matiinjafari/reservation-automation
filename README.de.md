[English](README.md) | **Deutsch**

# Reservation Automation

Eine Python-Anwendung, die Reservierungsanfragen für Gemeinschaftsraum und Grill per E-Mail verarbeitet. Sie liest ungelesene Nachrichten aus einem Postfach, extrahiert die Reservierungsdetails, prüft, ob der gewünschte Zeitraum frei ist, speichert bestätigte Buchungen in PostgreSQL und antwortet dem Absender.

Ich habe sie für ein Wohnhaus entwickelt, in dem die Bewohner den Gemeinschaftsraum und den Grill per E-Mail buchen. Die Anfragen kommen als Freitext in unterschiedlichen Formaten und enthalten oft kein Jahr. Die Hauptaufgabe besteht darin, diese Nachrichten in einheitliche Reservierungsdaten zu überführen.

**Status:** Prototyp. Der Versand echter E-Mails ist standardmäßig deaktiviert. Siehe [E-Mail-Versand](#e-mail-versand).

## Funktionsweise

```text
ungelesene E-Mail (IMAP)
      |
      +-- Sonderanfrage? --> an Admins weiterleiten und beenden
      |
      v
  Nachrichtentext auswerten
      +-- LLM-Extraktion mit Function Calling und Pydantic-Validierung
      +-- Fallback über beschriftete Felder, falls der LLM-Schritt fehlschlägt
      |
      v
  Zeitraum für diese Ressource bereits gebucht?
      +-- nein --> Reservierung speichern, Bestätigung senden, als confirmed protokollieren
      +-- ja   --> Absage senden, als denied protokollieren

  Fehler bei der Auswertung werden als failed protokolliert
```

Sonderanfragen werden direkt an die Admins weitergeleitet und nicht in `reservation_logs` geschrieben.

Bei der Auswertung gibt es einige Besonderheiten:

- **Datum und Uhrzeit:** ISO-Daten werden direkt übernommen. Andere Datumsangaben werden in der Reihenfolge Tag-Monat-Jahr interpretiert. Uhrzeiten wie `9pm`, `9:30 pm`, `21` und `24:00` werden unterstützt. Enthält die E-Mail kein vierstelliges Jahr, wird das aktuelle Jahr verwendet.
- **Verneinungen:** Formulierungen wie „no grill“ dürfen keine Grillreservierung auslösen. Das Grill-Flag wird deshalb durch eine einfache, verneinungsbewusste Textprüfung bestimmt. Die Küche gilt als angefragt, wenn entweder die Textprüfung oder das Modell eine Anfrage erkennt.
- **Zimmernummern:** Das Feld `room` bezeichnet die Wohnungsnummer des Absenders, nicht die angefragte Einrichtung. Liefert das Modell einen Wert wie „common room“, versucht die Anwendung stattdessen, die Wohnungsnummer aus der E-Mail zu lesen.
- **Ressourcenwahl:** Die Betreffzeile entscheidet zwischen Grill und Gemeinschaftsraum. Gibt der Betreff keinen Hinweis, wählt eine ausdrückliche Grillanfrage im Text den Grill, andernfalls wird der Gemeinschaftsraum verwendet.
- **Kaution:** Für den Gemeinschaftsraum beträgt die Kaution 50, bei Küchennutzung kommen weitere 50 hinzu. Für Grillreservierungen fällt keine Kaution an. Die Beträge sind in `scripts/parsing.py` definiert.
- **Verfügbarkeit:** Reservierungen für dieselbe Ressource und dasselbe Datum kollidieren, wenn sich ihre Zeiträume überschneiden. Direkt aufeinanderfolgende Buchungen sind erlaubt: Eine Buchung darf enden, wenn die nächste beginnt.

## Projektstruktur

```text
scripts/
  update_reservations.py   liest E-Mails, verarbeitet Anfragen und sendet Antworten
  export_reservations.py   exportiert Reservierungen als CSV und sendet die Datei an die Admins
  parsing.py               Hilfsfunktionen für Auswertung und Kaution, ohne Netzwerk- oder Datenbankzugriff
  mailer.py                gemeinsamer SMTP-Helfer, E-Mail-Versand standardmäßig deaktiviert
  init_db.sql              Definition der Datenbanktabellen
tests/
  test_reservations.py     Tests für die Auswertung und die Umwandlung von E-Mails in Reservierungen
.gitlab-ci.yml             Test-Job sowie zeitgesteuerte Update- und Export-Jobs
```

## Einrichtung

Voraussetzungen sind Python 3.11, PostgreSQL, ein IMAP/SMTP-Postfach und ein OpenAI-API-Schlüssel.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Eigene Werte in .env eintragen und anschließend laden:
export $(grep -v '^#' .env | xargs)

psql "$DB_URL" -f scripts/init_db.sql
python scripts/update_reservations.py
```

Die Konfiguration wird aus Umgebungsvariablen gelesen. `.env.example` listet die benötigten Werte auf. Eine echte `.env`-Datei darf nicht committet werden.

### Datenbank

`scripts/init_db.sql` legt zwei Tabellen an:

- `reservations` enthält bestätigte Buchungen.
- `reservation_logs` protokolliert reguläre Anfragen mit dem Status `confirmed`, `denied` oder `failed`.

### E-Mail-Versand

Ausgehende E-Mails sind standardmäßig deaktiviert. In diesem Modus werden Nachrichten übersprungen und nur ihre Betreffzeilen ins Log geschrieben.

Mit folgender Variable werden Bestätigungen, Absagen, Weiterleitungen an die Admins und der CSV-Export aktiviert:

```bash
SEND_EMAILS=true
```

Diese Einstellung gilt für beide Skripte, die E-Mails versenden.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Die Tests decken die Hilfsfunktionen zur Auswertung und die Umwandlung einer E-Mail in eine Reservierung ab, einschließlich des Fallbacks über beschriftete Felder und der Verneinungserkennung. Der LLM-Aufruf wird durch einen Stub ersetzt, und die Datenbankabfragen werden von den Tests nicht ausgeführt.

Beispielanfrage, die der Fallback-Parser verarbeitet (sie bleibt englisch, weil der Fallback-Parser englische Feldbezeichnungen wie `Date:` und `Time:` erwartet):

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

Die daraus entstehenden Reservierungsdaten:

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

Das Projekt verwendet GitLab CI/CD.

| Job | Wann | Zweck |
| --- | --- | --- |
| `initialize-db` | manuell in einer nicht zeitgesteuerten Pipeline | legt die Tabellen aus `scripts/init_db.sql` an |
| `test` | jede nicht zeitgesteuerte Pipeline | führt die Tests mit `pytest` aus |
| `update-reservations` | zeitgesteuerte Pipeline | verarbeitet ungelesene Reservierungs-E-Mails |
| `export-reservations` | zeitgesteuerte Pipeline | erstellt `reservations.csv`, speichert sie als Job-Artefakt und sendet sie an die Admins, sofern der E-Mail-Versand aktiviert ist |

Die Werte aus `.env.example` als maskierte CI/CD-Variablen hinterlegen und einen Pipeline-Zeitplan für die Update- und Export-Jobs anlegen. Änderungen an `.gitlab-ci.yml` lassen sich mit dem CI Lint von GitLab prüfen.

## Einschränkungen

- Die Verneinungserkennung ist heuristisch. Gängige Formulierungen wie „no grill“ und „grill not required“ werden erkannt, ungewöhnliche Formulierungen können übersehen werden.
- Der Fallback-Parser erwartet beschriftete Felder wie `Date:` und `Time:`. Er ist nur als Absicherung gedacht, falls die LLM-Extraktion fehlschlägt.
- Das Modell lässt sich über `OPENAI_MODEL` konfigurieren, der Standardwert ist `gpt-3.5-turbo`. Die Qualität der Extraktion kann je nach Modell abweichen.
- Es wird nur der erste `text/plain`-Teil einer Nachricht gelesen. Reine HTML-E-Mails werden nicht unterstützt.
- Die Anwendung verarbeitet ein Postfach und zwei Ressourcen: `common_room` und `grill`. Für weitere Ressourcen müssen die Betreffregeln und die Kautionsberechnung angepasst werden.
- Die Verfügbarkeit wird vor dem Einfügen geprüft, ohne Exclusion Constraint in der Datenbank. Zwei Prozesse, die sich überschneidende Anfragen genau gleichzeitig bearbeiten, könnten daher kollidierende Buchungen erzeugen.

## Datenschutz

Datenbank und CSV-Export enthalten Namen, E-Mail-Adressen, Telefonnummern und Zimmernummern der Bewohner. Die Datenbank und das CI/CD-Projekt sollten privat bleiben. CSV-Exporte, `.env`-Dateien und echte E-Mails dürfen nicht committet werden. Die Tests verwenden ausschließlich fiktive Daten.
