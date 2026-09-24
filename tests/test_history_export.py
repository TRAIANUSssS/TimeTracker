import csv
import io
import json
from datetime import date

from time_tracker.domain.time_windows import TimeSelection
from time_tracker.history_export import csv_export, export_records, json_export


def test_export_serializers_preserve_unicode_and_protect_excel_formulas():
    selection = TimeSelection(date(2026, 9, 8), date(2026, 9, 8), "00:00", "24:00", "UTC")
    segments = [
        {
            "type": "application",
            "started_at": 0,
            "ended_at": 1500,
            "application_id": 7,
            "name": "Редактор",
            "title": "=2+2",
        }
    ]
    records = export_records(segments, "UTC")
    payload = json.loads(
        json_export(records, selection, include_titles=True, exported_at=2000).decode("utf-8")
    )
    assert payload["records"][0]["application_name"] == "Редактор"
    assert payload["records"][0]["window_title"] == "=2+2"
    assert payload["exported_at"] == "1970-01-01T00:00:02.000Z"

    encoded = csv_export(records)
    assert encoded.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(encoded.decode("utf-8-sig")), delimiter=";"))
    assert rows[0]["application_name"] == "Редактор"
    assert rows[0]["window_title"] == "'=2+2"
    assert rows[0]["duration_ms"] == "1500"


def test_export_timestamps_keep_both_offsets_of_repeated_dst_hour():
    # Europe/Berlin 02:30 occurs twice on the 2026 autumn clock change.
    first = 1792888200000
    second = first + 3600000
    records = export_records(
        [{"type": "idle", "started_at": first, "ended_at": second + 1000}],
        "Europe/Berlin",
    )
    assert records[0]["started_at"].endswith("+02:00")
    assert records[0]["ended_at"].endswith("+01:00")
