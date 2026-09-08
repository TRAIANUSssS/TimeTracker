"""Invert local calendar selections into all their real UTC occurrences."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from time_tracker.domain.intervals import Interval, union

DAY = 86_400_000
HOUR = 3_600_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def timestamp(moment: datetime) -> int:
    delta = moment - EPOCH
    return delta.days * DAY + delta.seconds * 1000 + delta.microseconds // 1000


def minutes(value: str, *, end: bool = False) -> int:
    if end and value == "24:00":
        return 1440
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("Time must be HH:MM; 24:00 is allowed only for time_to")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def time_label(value: int) -> str:
    return f"{value // 60:02}:{value % 60:02}"


@lru_cache(maxsize=512)
def offset_spans(day: date, timezone: str) -> tuple[tuple[int, int, int], ...]:
    """Partition a padded UTC day by offset, locating transitions to the millisecond.

    Hourly probes cover IANA transitions (including non-hour and date-line changes).
    Wall boundaries are then intersected with each constant-offset span; attaching
    tzinfo to the two endpoints alone would wrongly fill gaps between DST folds.
    """
    zone = ZoneInfo(timezone)
    midnight = timestamp(datetime.combine(day, datetime.min.time(), UTC))
    start, end = midnight - 2 * DAY, midnight + 3 * DAY

    def offset(at):
        return int(
            (EPOCH + timedelta(milliseconds=at)).astimezone(zone).utcoffset().total_seconds() * 1000
        )

    spans = []
    cursor = boundary = start
    current = offset(start)
    while cursor < end:
        probe = min(cursor + HOUR, end)
        following = offset(probe)
        if following != current:
            low, high = cursor, probe
            while high - low > 1:
                middle = (low + high) // 2
                if offset(middle) == current:
                    low = middle
                else:
                    high = middle
            spans.append((boundary, high, current))
            boundary = high
            current = following
        cursor = probe
    spans.append((boundary, end, current))
    return tuple(spans)


@dataclass(frozen=True)
class HourCell:
    date: date
    day_offset: int
    hour: int
    minute_from: int
    minute_to: int
    windows: tuple[Interval, ...]
    occurrences: int

    @property
    def local_date(self) -> date:
        return self.date + timedelta(days=self.day_offset)


@dataclass(frozen=True)
class TimeSelection:
    date_from: date
    date_to: date
    time_from: str
    time_to: str
    timezone: str

    def __post_init__(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must not follow date_to")
        if self.date_from.year < 2 or self.date_to.year > 9998:
            raise ValueError("Supported date years: 2..9998")
        if minutes(self.time_from) == minutes(self.time_to, end=True):
            raise ValueError("Time range must not be empty")
        ZoneInfo(self.timezone)

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def cells(self) -> list[HourCell]:
        result = []
        lower, upper = minutes(self.time_from), minutes(self.time_to, end=True)
        if upper < lower:
            upper += 1440
        for index in range(self.days):
            anchor = self.date_from + timedelta(days=index)
            midnight = timestamp(datetime.combine(anchor, datetime.min.time(), UTC))
            spans = offset_spans(anchor, self.timezone)
            for hour_index in range(lower // 60, (upper + 59) // 60):
                low, high = max(lower, hour_index * 60), min(upper, (hour_index + 1) * 60)
                wall_start, wall_end = midnight + low * 60000, midnight + high * 60000
                pieces = []
                wall_events = []
                for start, end, offset in spans:
                    s, e = max(start, wall_start - offset), min(end, wall_end - offset)
                    if s < e:
                        pieces.append((s, e))
                        wall_events.extend(((s + offset, 1), (e + offset, -1)))
                # Count simultaneous wall-time occurrences, not offset changes: a forward
                # change inside a selected hour may leave two disjoint pieces, not a fold.
                occurrences = current = 0
                for _, change in sorted(wall_events):
                    current += change
                    occurrences = max(occurrences, current)
                result.append(
                    HourCell(
                        anchor,
                        hour_index // 24,
                        hour_index % 24,
                        low - (hour_index // 24) * 1440,
                        high - (hour_index // 24) * 1440,
                        tuple(union(pieces)),
                        occurrences,
                    )
                )
        return result

    def windows(self) -> list[Interval]:
        return union(w for cell in self.cells() for w in cell.windows)
