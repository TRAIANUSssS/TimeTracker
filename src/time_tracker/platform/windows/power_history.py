"""Authoritative Kernel-Power boundaries; no desktop-message or polling timestamps."""

from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree import ElementTree

from time_tracker.diagnostics.performance import call, count, measured

NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}


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
    @measured("power.read")
    def read(self, since: int) -> tuple[tuple[tuple[int, int], ...], bool]:
        import win32evtlog

        timestamp = datetime.fromtimestamp(since / 1000, UTC).isoformat(timespec="milliseconds")
        timestamp = timestamp.replace("+00:00", "Z")
        query = (
            "*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and "
            "(EventID=506 or EventID=507 or EventID=42 or EventID=107) and "
            f"TimeCreated[@SystemTime >= '{timestamp}']]]"
        )
        handle = call(
            "power.query",
            win32evtlog.EvtQuery,
            "System",
            win32evtlog.EvtQueryForwardDirection,
            query,
        )
        records = []
        try:
            while True:
                batch = call("power.next", win32evtlog.EvtNext, handle, 32)
                if not batch:
                    break
                try:
                    for event in batch:
                        records.append(
                            parse_record(
                                win32evtlog.EvtRender(event, win32evtlog.EvtRenderEventXml)
                            )
                        )
                finally:
                    for event in batch:
                        event.Close()
        finally:
            handle.Close()
        count("power.records", len(records))
        return completed_periods(tuple(records), since)
