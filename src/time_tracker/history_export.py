"""Stable user-facing exports of interval history."""

import csv
import io
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

CSV_FIELDS = (
    "started_at",
    "ended_at",
    "duration_ms",
    "type",
    "application_id",
    "application_name",
    "window_title",
    "timezone",
)


def _local_time(value, timezone):
    return (
        datetime.fromtimestamp(value / 1000, UTC)
        .astimezone(ZoneInfo(timezone))
        .isoformat(timespec="milliseconds")
    )


def export_records(segments, timezone):
    return [
        {
            "started_at": _local_time(segment["started_at"], timezone),
            "ended_at": _local_time(segment["ended_at"], timezone),
            "duration_ms": segment["ended_at"] - segment["started_at"],
            "type": segment["type"],
            "application_id": segment.get("application_id"),
            "application_name": segment.get("name"),
            "window_title": segment.get("title"),
            "timezone": timezone,
        }
        for segment in segments
    ]


def json_export(records, selection, *, include_titles, exported_at):
    payload = {
        "schema_version": 1,
        "exported_at": datetime.fromtimestamp(exported_at / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "timezone": selection.timezone,
        "personal_day_start": selection.personal_day_start,
        "period": {
            "date_from": selection.date_from.isoformat(),
            "date_to": selection.date_to.isoformat(),
            "time_from": selection.time_from,
            "time_to": selection.time_to,
            "full_day": selection.full_day,
        },
        "include_titles": include_titles,
        "records": records,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _excel_safe(value):
    if not isinstance(value, str):
        return value
    return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value


def csv_export(records):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, delimiter=";", lineterminator="\r\n")
    writer.writeheader()
    for record in records:
        writer.writerow({key: _excel_safe(record.get(key)) for key in CSV_FIELDS})
    return output.getvalue().encode("utf-8-sig")
