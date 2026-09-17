from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from time_tracker.domain.events import (
    ForegroundChanged,
    ForegroundObservation,
    ProcessIdentity,
    ProcessObservation,
    SessionLocked,
    SessionUnlocked,
    SleepPeriodRecorded,
    SystemResumed,
    TrackerSnapshot,
)
from time_tracker.domain.session_manager import SessionManager
from time_tracker.platform.windows.power_history import PowerRecord, completed_periods, parse_record
from time_tracker.storage.repositories import Repositories
from time_tracker.storage.tracker_store import SQLiteTrackerStore


def snapshot(at, locked=False):
    item = ProcessObservation(ProcessIdentity(42, 10), "C:/Apps/editor.exe")
    return TrackerSnapshot(
        at, (item,), ForegroundObservation(item, 1, "Example"), at, is_locked=locked
    )


def states(database):
    with database.reader() as connection:
        return [
            tuple(r)
            for r in connection.execute(
                "SELECT state,started_at,ended_at FROM system_state_sessions ORDER BY started_at,id"
            )
        ]


def test_kernel_timestamp_parser_preserves_milliseconds():
    xml = """<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>
    <Provider Name="Microsoft-Windows-Kernel-Power"/><EventID>507</EventID>
    <TimeCreated SystemTime="2026-09-08T17:04:37.1023160Z"/>
    <EventRecordID>10564</EventRecordID></System></Event>"""
    assert parse_record(xml) == PowerRecord(10564, 507, 1788887077102)


def test_recorded_modern_standby_sequence_includes_intermediate_wake():
    records = (
        PowerRecord(1, 506, 1788887067458),
        PowerRecord(2, 507, 1788887067888),
        PowerRecord(3, 506, 1788887067889),
        PowerRecord(4, 507, 1788887077102),
    )
    periods, opened = completed_periods(records, 1788887003868)
    assert sum(end - start for start, end in periods) == 9643
    assert periods == ((1788887067458, 1788887067888), (1788887067889, 1788887077102))
    assert not opened


def test_pairing_handles_delayed_close_and_ignores_other_runs():
    records = (
        PowerRecord(1, 506, 500),
        PowerRecord(2, 507, 1000),
        PowerRecord(3, 506, 2000),
        PowerRecord(4, 506, 2000),
    )
    assert completed_periods(records, 1000) == ((), True)
    assert completed_periods((*records, PowerRecord(5, 507, 3000)), 1000) == (
        ((2000, 3000),),
        False,
    )


def test_classic_hibernate_pair_does_not_close_modern_interval():
    records = (PowerRecord(1, 506, 1000), PowerRecord(2, 42, 2000), PowerRecord(3, 107, 5000))
    assert completed_periods(records, 1000) == (((2000, 5000),), True)


def test_late_sleep_splits_history_and_clears_stale_foreground(database):
    manager = SessionManager(SQLiteTrackerStore(database))
    manager.start(snapshot(1000))
    manager.handle(SleepPeriodRecorded(5000, 2000, 3000))
    assert states(database) == [
        ("ACTIVE", 1000, 2000),
        ("SLEEP", 2000, 3000),
        ("ACTIVE", 3000, None),
    ]
    assert manager.state.system_session.started_at == 3000
    assert manager.state.foreground is None
    with database.reader() as c:
        assert tuple(
            c.execute("SELECT started_at,ended_at FROM foreground_sessions").fetchone()
        ) == (1000, 2000)
        assert c.execute("SELECT COUNT(*) FROM application_running_sessions").fetchone()[0] == 1
    manager.handle(ForegroundChanged(6000, snapshot(6000).foreground))
    assert manager.state.foreground.session.started_at == 6000
    manager.handle(SessionLocked(7000))
    assert states(database)[-1] == ("LOCKED", 7000, None)


def test_overlay_preserves_lock_state_and_is_idempotent(database):
    manager = SessionManager(SQLiteTrackerStore(database))
    manager.start(snapshot(1000))
    manager.handle(SessionLocked(2000))
    manager.handle(SessionUnlocked(4000, snapshot(4000)))
    manager.handle(SleepPeriodRecorded(6000, 1500, 3500))
    before = states(database)
    manager.handle(SleepPeriodRecorded(7000, 1500, 3500))
    assert states(database) == before
    assert [row for row in before if row[0] != "SLEEP"] == [
        ("ACTIVE", 1000, 1500),
        ("LOCKED", 3500, 4000),
        ("ACTIVE", 4000, None),
    ]
    assert sum(end - start for state, start, end in before if state == "SLEEP") == 2000
    assert manager.state.foreground.session.started_at == 4000


def test_foreground_started_inside_confirmed_sleep_is_removed(database):
    manager = SessionManager(SQLiteTrackerStore(database))
    manager.start(TrackerSnapshot(1000, (), None, 1000))
    manager.handle(ForegroundChanged(2500, snapshot(2500).foreground))
    manager.handle(SleepPeriodRecorded(4000, 2000, 3000))
    assert manager.state.foreground is None
    with database.reader() as c:
        assert c.execute("SELECT COUNT(*) FROM foreground_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("start,end", [(500, 2000), (2000, 6000), (2000, 2000), (3000, 2000)])
def test_invalid_confirmed_interval_does_not_modify_history(database, start, end):
    manager = SessionManager(SQLiteTrackerStore(database))
    manager.start(snapshot(1000))
    before = manager.state
    with pytest.raises(ValueError):
        manager.handle(SleepPeriodRecorded(5000, start, end))
    assert manager.state == before
    assert states(database) == [("ACTIVE", 1000, None)]


def test_sleep_correction_rolls_back_sql_and_ram(database):
    class Store(SQLiteTrackerStore):
        fail = False

        @contextmanager
        def transaction(self):
            with self.database.transaction() as c:
                yield Repositories(c)
                if self.fail:
                    raise OSError("injected commit failure")

    store = Store(database)
    manager = SessionManager(store)
    manager.start(snapshot(1000))
    before = manager.state
    store.fail = True
    with pytest.raises(OSError):
        manager.handle(SleepPeriodRecorded(5000, 2000, 3000))
    assert manager.state == before
    assert states(database) == [("ACTIVE", 1000, None)]


def test_fast_resume_ends_lock_without_waiting_for_process_metadata(database):
    manager = SessionManager(SQLiteTrackerStore(database))
    manager.start(snapshot(1000))
    manager.handle(SessionLocked(2000))
    manager.handle(SystemResumed(3000, TrackerSnapshot(3000, (), None, 3000)))
    assert manager.state.flags.effective == "ACTIVE"
    assert manager.state.foreground is None
    assert states(database)[-2:] == [("LOCKED", 2000, 3000), ("ACTIVE", 3000, None)]


def test_controller_replays_user_sleep_sequence_with_delayed_log_delivery(database):
    pytest.importorskip("psutil")
    from time_tracker.collector import CollectionController
    from time_tracker.runtime import TrackerRuntime

    clock = SimpleNamespace(at=1788887003868)
    clock.now_ms = lambda: clock.at

    class Source:
        periods = ()
        opened = False

        def read(self, since):
            return self.periods, self.opened

    source = Source()
    provider = SimpleNamespace(
        snapshot=lambda: snapshot(clock.at),
        user_snapshot=lambda: TrackerSnapshot(clock.at, (), None, clock.at),
    )
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock, power_history=source)
    controller.start()
    clock.at = 1788887067758
    controller.notify("sleep")
    source.periods = ((1788887067458, 1788887067888),)
    source.opened = True
    clock.at = 1788887067911
    controller.notify("wake")
    assert runtime.state.foreground is None
    clock.at = 1788887074629
    controller.notify("wake")
    assert controller._paused
    source.periods = (*source.periods, (1788887067889, 1788887077102))
    source.opened = False
    clock.at = 1788887080000
    controller.notify("wake")
    assert not controller._paused
    controller.stop()
    sleep = [(start, end) for state, start, end in states(database) if state == "SLEEP"]
    assert sleep == list(source.periods)
    assert sum(end - start for start, end in sleep) == 9643


def test_real_system_log_query_uses_utc_z_suffix(monkeypatch):
    from time_tracker.platform.windows.power_history import PowerHistory

    event_log = EventLog()
    install_event_log(monkeypatch, event_log)
    PowerHistory().read(int(datetime(2026, 9, 8, 17, tzinfo=UTC).timestamp() * 1000))
    assert "2026-09-08T17:00:00.000Z" in event_log.queries[0][1]


class EventLog:
    class Handle:
        def __init__(self, events):
            self.events = events
            self.index = 0
            self.closed = False

        def Close(self):
            self.closed = True

    class Bookmark:
        def __init__(self):
            self.event = None
            self.closed = False

        def Close(self):
            self.closed = True

    class Event:
        def __init__(self, record_id, event_id, at):
            self.record_id = record_id
            self.event_id = event_id
            self.at = at
            self.closed = False

        def Close(self):
            self.closed = True

    EvtQueryForwardDirection = 1
    EvtQueryReverseDirection = 2
    EvtSeekRelativeToLast = 3
    EvtSeekRelativeToBookmark = 4
    EvtSeekStrict = 8
    EvtRenderEventXml = 1

    def __init__(self, events=()):
        self.events = list(events)
        self.queries = []
        self.seeks = []
        self.fail_seek = False
        self.seek_error = None

    @staticmethod
    def _xml(event):
        stamp = datetime.fromtimestamp(event.at / 1000, UTC).isoformat(timespec="milliseconds")
        return f"""<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>
        <Provider Name="Microsoft-Windows-Kernel-Power"/><EventID>{event.event_id}</EventID>
        <TimeCreated SystemTime="{stamp.replace("+00:00", "Z")}"/>
        <EventRecordID>{event.record_id}</EventRecordID></System></Event>"""

    def EvtQuery(self, _channel, flags, xpath):
        self.queries.append((flags, xpath))
        events = (
            list(reversed(self.events))
            if flags == self.EvtQueryReverseDirection
            else list(self.events)
        )
        return self.Handle(events)

    def EvtNext(self, handle, count):
        result = handle.events[handle.index : handle.index + count]
        handle.index += len(result)
        return result

    def EvtCreateBookmark(self, _xml):
        return self.Bookmark()

    @staticmethod
    def EvtUpdateBookmark(bookmark, event):
        bookmark.event = event

    def EvtSeek(self, handle, position, flags, bookmark, _timeout):
        if flags == self.EvtSeekRelativeToLast:
            handle.index = len(handle.events) + position
            return
        self.seeks.append((position, bookmark.event.record_id if bookmark.event else None, flags))
        if self.seek_error is not None:
            error, self.seek_error = self.seek_error, None
            raise error
        if self.fail_seek:
            self.fail_seek = False
            raise OSError("bookmark invalid after log rotation")
        index = next(
            index
            for index, event in enumerate(handle.events)
            if event.record_id == bookmark.event.record_id
        )
        handle.index = index + position

    @staticmethod
    def EvtRender(event, _flag):
        return EventLog._xml(event)


def install_event_log(monkeypatch, event_log):
    import sys

    monkeypatch.setitem(sys.modules, "win32evtlog", event_log)


def test_power_history_uses_bookmark_and_retains_open_pair(monkeypatch):
    from time_tracker.platform.windows.power_history import EVENT_QUERY, PowerHistory

    event_log = EventLog((EventLog.Event(1, 506, 1000),))
    install_event_log(monkeypatch, event_log)
    history = PowerHistory()
    assert history.read(1000) == ((), True)
    event_log.events.append(EventLog.Event(2, 507, 2000))
    assert history.read(1000) == (((1000, 2000),), False)
    assert event_log.queries[0][0] == event_log.EvtQueryForwardDirection
    assert "TimeCreated" in event_log.queries[0][1]
    assert event_log.queries[1] == (event_log.EvtQueryForwardDirection, EVENT_QUERY)
    assert event_log.seeks == [
        (1, 1, event_log.EvtSeekRelativeToBookmark | event_log.EvtSeekStrict)
    ]


def test_invalid_power_bookmark_rebuilds_current_run_after_log_rotation(monkeypatch):
    from time_tracker.platform.windows.power_history import PowerHistory

    event_log = EventLog((EventLog.Event(1, 506, 1000),))
    install_event_log(monkeypatch, event_log)
    history = PowerHistory()
    assert history.read(1000) == ((), True)
    # The record ID was reused after rotation, so seek must fail and only the
    # current run is replayed from its timestamp filter.
    event_log.events = [EventLog.Event(1, 506, 1100), EventLog.Event(2, 507, 2100)]
    event_log.fail_seek = True
    assert history.read(1000) == (((1100, 2100),), False)
    assert sum("TimeCreated" in query for _, query in event_log.queries) == 2


def test_native_invalid_bookmark_error_rebuilds_current_run(monkeypatch):
    import pywintypes

    from time_tracker.platform.windows.power_history import PowerHistory

    event_log = EventLog((EventLog.Event(1, 506, 1000),))
    install_event_log(monkeypatch, event_log)
    history = PowerHistory()
    history.read(1000)
    event_log.events.append(EventLog.Event(2, 507, 2000))
    event_log.seek_error = pywintypes.error(1168, "EvtSeek", "Element not found")
    assert history.read(1000) == (((1000, 2000),), False)


def test_unlock_user_boundary_precedes_slow_full_snapshot(database):
    pytest.importorskip("psutil")
    from time_tracker.collector import CollectionController
    from time_tracker.runtime import TrackerRuntime

    clock = SimpleNamespace(at=1000)
    clock.now_ms = lambda: clock.at
    provider = SimpleNamespace(
        snapshot=lambda: snapshot(clock.at),
        user_snapshot=lambda: TrackerSnapshot(clock.at, (), None, clock.at),
    )
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock)
    controller.start()
    clock.at = 2000
    controller.notify("lock")

    def slow_snapshot():
        clock.at = 8000
        return snapshot(clock.at)

    provider.snapshot = slow_snapshot
    clock.at = 3000
    controller.notify("unlock")
    assert ("LOCKED", 2000, 3000) in states(database)
    assert runtime.state.foreground.session.started_at == 8000
    controller.stop()


def test_duplicate_fast_resume_does_not_fragment_foreground(database):
    manager = SessionManager(SQLiteTrackerStore(database))
    manager.start(snapshot(1000))
    original = manager.state.foreground
    manager.handle(SystemResumed(2000, TrackerSnapshot(2000, (), None, 2000)))
    assert manager.state.foreground == original


def test_resume_rejects_snapshot_captured_before_another_sleep(database):
    pytest.importorskip("psutil")
    from time_tracker.collector import CollectionController
    from time_tracker.runtime import TrackerRuntime

    clock = SimpleNamespace(at=1000)
    clock.now_ms = lambda: clock.at

    class Source:
        periods = ()

        def read(self, since):
            return self.periods, False

    source = Source()
    provider = SimpleNamespace(snapshot=lambda: snapshot(clock.at))
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock, power_history=source)
    controller.start()
    try:
        clock.at = 2000
        controller.notify("sleep")

        def interrupted_snapshot():
            result = snapshot(3000)
            source.periods = ((2000, 2500), (3500, 4500))
            clock.at = 5000
            return result

        provider.snapshot = interrupted_snapshot
        clock.at = 3000
        controller.notify("wake")
        assert runtime.state.foreground is None
        assert controller._paused
        provider.snapshot = lambda: snapshot(clock.at)
        clock.at = 6000
        controller.notify("wake")
        assert runtime.state.foreground.session.started_at == 6000
    finally:
        controller.stop()


def test_pending_modern_resume_survives_lock_after_log_failure(database):
    pytest.importorskip("psutil")
    from time_tracker.collector import CollectionController
    from time_tracker.runtime import TrackerRuntime

    clock = SimpleNamespace(at=1000)
    clock.now_ms = lambda: clock.at
    source = SimpleNamespace(read=lambda since: ((), False))
    provider = SimpleNamespace(snapshot=lambda: snapshot(clock.at))
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock, power_history=source)
    controller.start()
    try:
        clock.at = 2000
        controller.notify("sleep")

        def failed_snapshot():
            raise OSError("Temporary snapshot failure")

        provider.snapshot = failed_snapshot
        clock.at = 3000
        controller.notify("wake")
        controller.notify("lock")
        assert controller._pending_resume == "wake"
        provider.snapshot = lambda: snapshot(clock.at, locked=True)
        clock.at = 4000
        controller.tick()
        assert not controller._paused
        assert runtime.state.flags.effective == "LOCKED"
    finally:
        controller.stop()
