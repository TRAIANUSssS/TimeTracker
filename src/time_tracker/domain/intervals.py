"""Half-open UTC millisecond interval algebra. Inputs may overlap or be empty."""

from bisect import bisect_right
from collections.abc import Iterable

type Interval = tuple[int, int]


def union(intervals: Iterable[Interval]) -> list[Interval]:
    result = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersect(left: Iterable[Interval], right: Iterable[Interval]) -> list[Interval]:
    a, b = union(left), union(right)
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return result


def duration(intervals: Iterable[Interval]) -> int:
    return sum(end - start for start, end in union(intervals))


class Coverage:
    """Prefix sums for repeated hour queries without rescanning an entire history."""

    def __init__(self, intervals: Iterable[Interval]):
        self.intervals = union(intervals)
        self.starts = [s for s, _ in self.intervals]
        self.prefix = [0]
        for start, end in self.intervals:
            self.prefix.append(self.prefix[-1] + end - start)

    def before(self, at: int) -> int:
        i = bisect_right(self.starts, at) - 1
        if i < 0:
            return 0
        start, end = self.intervals[i]
        return self.prefix[i] + min(at, end) - start

    def measure(self, intervals: Iterable[Interval]) -> int:
        return sum(self.before(e) - self.before(s) for s, e in union(intervals))

    def contains(self, at: int) -> bool:
        i = bisect_right(self.starts, at) - 1
        return i >= 0 and at < self.intervals[i][1]
