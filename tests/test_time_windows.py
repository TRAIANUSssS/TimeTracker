from datetime import date, datetime

import pytest

from time_tracker.domain.intervals import Coverage, duration, intersect, union
from time_tracker.domain.time_windows import TimeSelection, timestamp


def selection(day, end=None, start_time="00:00", end_time="24:00", zone="Europe/Berlin"):
    return TimeSelection(
        date.fromisoformat(day), date.fromisoformat(end or day), start_time, end_time, zone
    )


def test_interval_algebra_and_prefix_sums():
    assert union([(3, 8), (1, 5), (8, 10), (15, 15), (20, 30)]) == [(1, 10), (20, 30)]
    assert intersect([(0, 10), (20, 30)], [(5, 25)]) == [(5, 10), (20, 25)]
    coverage = Coverage([(1, 10), (20, 30)])
    assert coverage.measure([(0, 25)]) == 14
    assert not coverage.contains(10)
    assert coverage.contains(20)


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-25", 25), ("2026-09-08", 24)])
def test_full_day_actual_duration(day, hours):
    assert duration(selection(day).windows()) == hours * 3600000


def test_repeated_partial_hour_has_two_separate_occurrences():
    chosen = selection("2026-10-25", start_time="02:15", end_time="02:45")
    expected = [
        (timestamp(datetime.fromisoformat(s)), timestamp(datetime.fromisoformat(e)))
        for s, e in [
            ("2026-10-25T00:15:00+00:00", "2026-10-25T00:45:00+00:00"),
            ("2026-10-25T01:15:00+00:00", "2026-10-25T01:45:00+00:00"),
        ]
    ]
    assert chosen.windows() == expected
    assert chosen.cells()[0].occurrences == 2


def test_missing_hour_is_not_shifted_forward():
    chosen = selection("2026-03-29", start_time="02:15", end_time="02:45")
    assert chosen.windows() == []
    assert chosen.cells()[0].occurrences == 0


@pytest.mark.parametrize(
    "day,start,end,duration_minutes,occurrences",
    [
        ("2026-04-05", "01:00", "02:00", 90, 2),
        ("2026-10-04", "02:00", "03:00", 30, 1),
        ("2026-10-04", "02:00", "02:15", 0, 0),
    ],
)
def test_half_hour_dst(day, start, end, duration_minutes, occurrences):
    chosen = selection(day, start_time=start, end_time=end, zone="Australia/Lord_Howe")
    assert duration(chosen.windows()) == duration_minutes * 60000
    assert chosen.cells()[0].occurrences == occurrences


def test_skipped_calendar_date():
    chosen = selection("2011-12-30", zone="Pacific/Apia")
    assert chosen.windows() == []
    assert all(c.occurrences == 0 for c in chosen.cells())


def test_daily_night_windows_keep_last_next_day_and_exact_minutes():
    chosen = selection("2026-09-08", "2026-09-09", "22:07", "03:02", "Asia/Kathmandu")
    assert len(chosen.windows()) == 2
    assert duration(chosen.windows()) == 2 * (4 * 60 + 55) * 60000
    cells = chosen.cells()
    assert cells[0].minute_from == 22 * 60 + 7
    assert cells[-1].local_date == date(2026, 9, 10)
    assert cells[-1].day_offset == 1
    assert cells[-1].minute_to == 182


def test_2359_is_not_end_of_day():
    assert duration(selection("2026-09-08", end_time="23:59").windows()) == 1439 * 60000


@pytest.mark.parametrize(
    "start,end",
    [
        ("24:00", "01:00"),
        ("12:00", "12:00"),
        ("1:00", "02:00"),
        ("00:00", "24:01"),
        ("01:00:00", "02:00"),
    ],
)
def test_invalid_times(start, end):
    with pytest.raises(ValueError):
        selection("2026-09-08", start_time=start, end_time=end)
