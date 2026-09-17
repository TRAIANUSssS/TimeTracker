"""Authoritative Kernel-Power boundaries, read incrementally from the Windows log."""

from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree import ElementTree

from time_tracker.diagnostics.performance import call, count, measured

NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
EVENT_QUERY = (
    "*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and "
    "(EventID=506 or EventID=507 or EventID=42 or EventID=107)]]"
)


@dataclass(frozen=True)
class PowerRecord:
    record_id: int
    event_id: int
    at: int


@measured("power.parse")
def parse_record(xml: str) -> PowerRecord:
    system = ElementTree.fromstring(xml).find("e:System", NS)
    provider = system.find("e:Provider", NS)
    if provider.attrib["Name"] != "Microsoft-Windows-Kernel-Power":
        raise ValueError("Unexpected power event provider")
    stamp = system.find("e:TimeCreated", NS).attrib["SystemTime"]
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    delta = moment - datetime(1970, 1, 1, tzinfo=UTC)
    at = delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
    return PowerRecord(
        int(system.findtext("e:EventRecordID", namespaces=NS)),
        int(system.findtext("e:EventID", namespaces=NS)),
        at,
    )


def completed_periods(records: tuple[PowerRecord, ...], since: int):
    opened = {}
    periods = []
    for record in sorted(records, key=lambda r: r.record_id):
        if record.at < since:
            continue
        family = "modern" if record.event_id in (506, 507) else "classic"
        if record.event_id in (506, 42):
            opened.setdefault(family, record.at)
        elif record.event_id in (507, 107) and family in opened:
            start = opened.pop(family)
            if record.at > start:
                periods.append((start, record.at))
    return tuple(sorted(set(periods))), bool(opened)


class PowerHistory:
    """Keep an in-memory event-log bookmark for one tracker run.

    A missing/invalid bookmark is not trusted: the current run is reconstructed
    from its beginning. SessionManager deduplicates already accepted intervals.
    """

    def __init__(self):
        self._since = None
        self._bookmark = None
        self._seen_ids = set()
        self._opened = {}
        self._pending = set()

    @staticmethod
    def _timestamp_query(since: int) -> str:
        timestamp = datetime.fromtimestamp(since / 1000, UTC).isoformat(timespec="milliseconds")
        timestamp = timestamp.replace("+00:00", "Z")
        return EVENT_QUERY[:-2] + f" and TimeCreated[@SystemTime >= '{timestamp}']]]"

    def _close_bookmark(self) -> None:
        if self._bookmark is not None:
            self._bookmark.Close()
            self._bookmark = None

    def _reset(self, since: int) -> None:
        self._close_bookmark()
        self._since = since
        self._seen_ids.clear()
        self._opened.clear()

    def close(self) -> None:
        self._close_bookmark()

    def _accept(self, record: PowerRecord) -> None:
        if record.record_id in self._seen_ids or record.at < self._since:
            return
        self._seen_ids.add(record.record_id)
        family = "modern" if record.event_id in (506, 507) else "classic"
        if record.event_id in (506, 42):
            self._opened.setdefault(family, record.at)
        elif record.event_id in (507, 107) and family in self._opened:
            start = self._opened.pop(family)
            if record.at > start:
                self._pending.add((start, record.at))

    def _read_events(self, eventlog, handle, *, seek=False) -> None:
        try:
            if seek:
                call(
                    "power.seek",
                    eventlog.EvtSeek,
                    handle,
                    1,
                    eventlog.EvtSeekRelativeToBookmark | eventlog.EvtSeekStrict,
                    self._bookmark,
                    0,
                )
            while True:
                batch = call("power.next", eventlog.EvtNext, handle, 32)
                if not batch:
                    return
                try:
                    for event in batch:
                        record = parse_record(eventlog.EvtRender(event, eventlog.EvtRenderEventXml))
                        if self._bookmark is None:
                            self._bookmark = call(
                                "power.bookmark.create", eventlog.EvtCreateBookmark, None
                            )
                        call(
                            "power.bookmark.update",
                            eventlog.EvtUpdateBookmark,
                            self._bookmark,
                            event,
                        )
                        self._accept(record)
                finally:
                    for event in batch:
                        event.Close()
        finally:
            handle.Close()

    def _bookmark_latest(self, eventlog) -> None:
        """Anchor an empty initial run after the most recent relevant log event."""
        handle = call(
            "power.query_latest",
            eventlog.EvtQuery,
            "System",
            eventlog.EvtQueryForwardDirection,
            EVENT_QUERY,
        )
        try:
            call(
                "power.seek_latest",
                eventlog.EvtSeek,
                handle,
                -1,
                eventlog.EvtSeekRelativeToLast,
                None,
                0,
            )
            batch = call("power.next", eventlog.EvtNext, handle, 1)
            if not batch:
                return
            try:
                event = batch[0]
                record = parse_record(eventlog.EvtRender(event, eventlog.EvtRenderEventXml))
                self._bookmark = call("power.bookmark.create", eventlog.EvtCreateBookmark, None)
                call("power.bookmark.update", eventlog.EvtUpdateBookmark, self._bookmark, event)
                # Covers a record written between the initial query and this anchor.
                self._accept(record)
            finally:
                for event in batch:
                    event.Close()
        finally:
            handle.Close()

    def _initial_read(self, eventlog) -> None:
        handle = call(
            "power.query",
            eventlog.EvtQuery,
            "System",
            eventlog.EvtQueryForwardDirection,
            self._timestamp_query(self._since),
        )
        self._read_events(eventlog, handle)
        if self._bookmark is None:
            self._bookmark_latest(eventlog)

    @measured("power.read")
    def read(self, since: int) -> tuple[tuple[tuple[int, int], ...], bool]:
        import pywintypes
        import win32evtlog

        if self._since != since:
            self._reset(since)
        try:
            if self._bookmark is None:
                self._initial_read(win32evtlog)
            else:
                handle = call(
                    "power.query",
                    win32evtlog.EvtQuery,
                    "System",
                    win32evtlog.EvtQueryForwardDirection,
                    EVENT_QUERY,
                )
                self._read_events(win32evtlog, handle, seek=True)
        except (OSError, pywintypes.error):
            # Clearing/rotating System invalidates a bookmark. Rebuild only the
            # current run; never extend history across an unobservable gap.
            count("power.bookmark_reset")
            self._reset(since)
            self._initial_read(win32evtlog)
        periods = tuple(sorted(self._pending))
        self._pending.clear()
        count("power.records", len(self._seen_ids))
        return periods, bool(self._opened)
