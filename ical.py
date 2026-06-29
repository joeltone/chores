"""Shared iCalendar generation utilities."""

from datetime import date, timedelta, datetime, timezone


def build_ics(rows, display_name: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chore Bot//Chore Schedule//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for row in rows:
        due = date.fromisoformat(row["date_due"])
        end = due + timedelta(days=1)
        uid = f"assignment-{row['assignment_id']}@chore-bot"
        desc = _escape(row["description"] or "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(row['chore_name'])}",
            f"DESCRIPTION:Assigned to {display_name}.{' ' + desc if desc else ''}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _escape(s: str) -> str:
    return (s.replace("\\", "\\\\")
             .replace(",", "\\,")
             .replace(";", "\\;")
             .replace("\n", "\\n"))
