"""Late ETW boundaries with the real SQLite owner, plus controller fallback."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from time_tracker.collector import CollectionController, ObservationInterrupted
from time_tracker.domain.events import (
    ForegroundChanged,
    ForegroundObservation,
    Heartbeat,
    ProcessBoundaryRecorded,
    ProcessesObserved,
    ProcessIdentity,
    ProcessObservation,
    SessionLocked,
    SystemSleep,
    TrackerSnapshot,
)
from time_tracker.domain.session_manager import SessionManager
from time_tracker.runtime import TrackerRuntime
from time_tracker.storage.tracker_store import SQLiteTrackerStore
from time_tracker.worker import CollectionWorker


def item(pid=42, creation=1100, path="C:/Apps/one.exe"):
    return ProcessObservation(ProcessIdentity(pid, creation), path)


def boundary(process, start=True, when=None, received=5000, coverage=1000):
    return ProcessBoundaryRecorded(
        received, process, when or process.identity.creation_time, start, coverage
    )


def rows(db, table):
    with db.reader() as con:
        return [
            dict(row)
            for row in con.execute(
                f"SELECT * FROM {table} ORDER BY started_at"
                if table == "application_running_sessions"
                else f"SELECT * FROM {table} ORDER BY id"
            )
        ]


@pytest.fixture
def manager(database):
    value = SessionManager(SQLiteTrackerStore(database))
    value.start(TrackerSnapshot(1000, (), None, 1000))
    return value


@pytest.mark.parametrize("reverse", [False, True])
def test_delayed_short_process_preserves_lifetime_and_deduplicates(manager, database, reverse):
    manager.handle(Heartbeat(4000))
    start, stop = boundary(item()), boundary(replace(item(), executable_path=None), False, 1450)
    for event in [stop, start] if reverse else [start, stop]:
        assert manager.handle(event)
    manager.handle(start)
    manager.handle(stop)
    sessions = rows(database, "process_sessions")
    assert len(sessions) == 1
    assert (sessions[0]["detected_at"], sessions[0]["ended_at"]) == (1100, 1450)
    running = rows(database, "application_running_sessions")
    assert [(r["started_at"], r["ended_at"]) for r in running] == [(1100, 1450)]
    assert manager.state.last_event_at == 5000
    assert not manager.state.running_processes


def test_late_start_does_not_revive_identity_absent_from_newer_snapshot(manager, database):
    manager.handle(ProcessesObserved(3000, ()))
    manager.handle(boundary(item()))
    assert not manager.state.running_processes
    manager.handle(boundary(item(), False, 1450))
    assert rows(database, "process_sessions")[0]["ended_at"] == 1450


def test_stop_before_start_corrects_process_seen_during_slow_snapshot(manager, database):
    manager.handle(ProcessesObserved(3000, (item(),)))
    manager.handle(boundary(replace(item(), executable_path=None), False, 1450))
    manager.handle(boundary(item()))
    assert not manager.state.running_processes
    assert [
        (r["started_at"], r["ended_at"]) for r in rows(database, "application_running_sessions")
    ] == [(1100, 1450)]


def test_late_old_pid_stop_does_not_close_new_owner(manager, database):
    old, new = item(), item(42, 2000, "C:/Apps/two.exe")
    manager.handle(ProcessesObserved(3000, (new,)))
    manager.handle(boundary(old))
    manager.handle(boundary(old, False, 1500))
    assert list(manager.state.running_processes) == [new.identity]
    assert manager.state.running_processes[new.identity].session.ended_at is None


def test_running_is_union_not_sum_for_overlapping_instances(manager, database):
    a, b = item(), item(43, 1200)
    for event in [boundary(a), boundary(b), boundary(a, False, 1400), boundary(b, False, 1600)]:
        manager.handle(event)
    assert [
        (r["started_at"], r["ended_at"]) for r in rows(database, "application_running_sessions")
    ] == [(1100, 1600)]


def test_late_stop_trims_closed_foreground_without_trimming_other_process(manager, database):
    a, b = item(), item(43, 1200)
    manager.handle(ForegroundChanged(1300, ForegroundObservation(a, 1, "a")))
    manager.handle(ForegroundChanged(2000, ForegroundObservation(b, 2, "b")))
    manager.handle(boundary(a, False, 1500))
    fg = rows(database, "foreground_sessions")
    assert fg[0]["ended_at"] == 1500
    assert fg[1]["ended_at"] is None
    assert manager.state.foreground.identity == b.identity


@pytest.mark.parametrize("event", [SessionLocked(2000), SystemSleep(2000)])
def test_authoritative_events_work_during_lock_and_sleep(manager, database, event):
    manager.handle(event)
    manager.handle(boundary(item()))
    manager.handle(boundary(item(), False, 1450))
    assert rows(database, "process_sessions")[0]["ended_at"] == 1450
    assert manager.state.flags.is_locked or manager.state.flags.is_sleeping


def test_coverage_does_not_extend_before_run(manager, database):
    process = item(creation=100)
    manager.handle(boundary(process, False, 1400, coverage=500))
    assert rows(database, "process_sessions")[0]["detected_at"] == 1000


class Source:
    def __init__(self):
        self.healthy = True
        self.generation = "one"
        self.records = []
        self.closed = False

    def start(self):
        pass

    def poll(self):
        records, self.records = self.records, []
        return self.generation, 1000, self.healthy, records

    def invalidate(self):
        self.healthy = False

    def close(self):
        self.closed = True

    def begin_finish(self):
        pass

    def finish_status(self):
        return True, self.healthy, len(self.records)


class Provider:
    def __init__(self):
        self.at = 1000
        self.calls = 0
        self.api = self
        self.processes = SimpleNamespace(snapshot=self.process_snapshot)

    def now_ms(self):
        return self.at

    def user_snapshot(self):
        return TrackerSnapshot(self.at, (), None, self.at)

    def process_snapshot(self):
        self.calls += 1
        return ()

    def snapshot(self):
        return replace(self.user_snapshot(), processes=self.process_snapshot())

    def foreground(self):
        return None

    def is_locked(self):
        return False

    def idle_ms(self):
        return 0

    def event_process(self, record):
        return item()


def setup(database):
    provider, source = Provider(), Source()
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(
        runtime, provider, provider, process_events=source, monotonic=lambda: provider.at / 1000
    )
    controller.start()
    return controller, provider, source


def test_healthy_source_reconciles_60s_and_disconnect_immediately_falls_back(database):
    controller, provider, source = setup(database)
    try:
        controller.tick()
        assert provider.calls == 1
        provider.at = 6000
        controller.tick()
        assert provider.calls == 1
        provider.at = 61000
        controller.tick()
        assert provider.calls == 2
        source.healthy = False
        provider.at = 62000
        controller.tick()
        assert provider.calls == 3
        provider.at = 67000
        controller.tick()
        assert provider.calls == 4
    finally:
        controller.stop()
        controller.close_sources()
    assert source.closed


def test_worker_checkpoint_does_not_drop_drained_event(database):
    controller, provider, source = setup(database)
    source.records = [{"kind": "start", "generated_at_ns": 1100000000}]
    provider.at = 3000
    checks = 0

    def checkpoint():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ObservationInterrupted()

    try:
        controller.checkpoint = checkpoint
        with pytest.raises(ObservationInterrupted):
            controller.tick()
        assert len(controller._event_pending) == 1
        controller.checkpoint = lambda: None
        controller.tick()
        assert not controller._event_pending
        assert len(rows(database, "process_sessions")) == 1
    finally:
        controller.stop()
        controller.close_sources()


def test_real_pipe_to_worker_to_sqlite_preserves_short_interval(database):
    import time
    from uuid import uuid4

    from time_tracker.platform.windows.event_pipe import EventPipeServer
    from time_tracker.platform.windows.event_source import ProcessEventSource

    channel = uuid4().hex
    provider = Provider()
    source = ProcessEventSource(channel)
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(runtime, provider, provider, process_events=source)
    worker = CollectionWorker(controller)
    with EventPipeServer(channel) as server:
        worker.start()
        try:
            server.accept(3000)
            assert worker.ready.wait(3)
            provider.at = 5000
            envelope = {"schema_version": 1, "stream_id": "test-worker"}
            server.send(
                envelope | {"type": "ready", "message_sequence": 1, "started_at_ns": 1000000000}
            )
            common = {"pid": 42, "creation_time_ns": 1100000000, "received_at_ns": 5000000000}
            server.send(
                envelope
                | {
                    "type": "batch",
                    "message_sequence": 2,
                    "healthy": True,
                    "data_complete": True,
                    "records": [
                        common
                        | {
                            "kind": "start",
                            "sequence": 1,
                            "generated_at_ns": 1100000000,
                            "image_name": "C:/Apps/one.exe",
                        },
                        common | {"kind": "stop", "sequence": 2, "generated_at_ns": 1450000000},
                    ],
                }
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                sessions = rows(database, "process_sessions")
                if sessions and sessions[0]["ended_at"] == 1450:
                    break
                time.sleep(0.02)
            assert (sessions[0]["detected_at"], sessions[0]["ended_at"]) == (1100, 1450)
            assert [
                (r["started_at"], r["ended_at"])
                for r in rows(database, "application_running_sessions")
            ] == [(1100, 1450)]
        finally:
            worker.request_stop()
            worker.join()
        assert worker.error is None
        assert not source._thread.is_alive()


def test_process_boundary_rolls_back_both_history_and_ram(database):
    from tests.test_session_manager import InstrumentedStore

    store = InstrumentedStore(database)
    manager = SessionManager(store)
    manager.start(TrackerSnapshot(1000, (), None, 1000))
    before = manager.state
    store.fail_commit = True
    with pytest.raises(RuntimeError, match="commit"):
        manager.handle(boundary(item()))
    assert manager.state == before
    assert rows(database, "process_sessions") == []
    assert rows(database, "application_running_sessions") == []


def test_reconnect_forces_snapshot_even_inside_60s_interval(database):
    controller, provider, source = setup(database)
    try:
        controller.tick()
        source.generation = "two"
        provider.at = 3000
        controller.tick()
        assert provider.calls == 2
    finally:
        controller.stop()
        controller.close_sources()


def test_creation_rounding_matches_windows_psutil_for_real_helper():
    import ctypes as C
    import subprocess
    import sys

    import psutil

    from time_tracker.domain.identity import process_creation_ms

    child = subprocess.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(2)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        values = [C.c_uint64() for _ in range(4)]
        function = C.WinDLL("kernel32", use_last_error=True).GetProcessTimes
        function.argtypes = [C.c_void_p] + [C.POINTER(C.c_uint64)] * 4
        function.restype = C.c_int
        assert function(int(child._handle), *(C.byref(value) for value in values))
        raw_ns = (values[0].value - 116444736000000000) * 100
        assert process_creation_ms(raw_ns) == round(psutil.Process(child.pid).create_time() * 1000)
    finally:
        child.kill()
        child.wait(timeout=5)


def test_reader_queue_overflow_forces_incomplete_source():
    import time
    from uuid import uuid4

    from time_tracker.platform.windows.event_pipe import EventPipeServer
    from time_tracker.platform.windows.event_source import ProcessEventSource

    channel = uuid4().hex
    source = ProcessEventSource(channel, capacity=1)
    with EventPipeServer(channel) as server:
        source.start()
        try:
            server.accept(3000)
            envelope = {"schema_version": 1, "stream_id": "overflow"}
            server.send(
                envelope | {"type": "ready", "message_sequence": 1, "started_at_ns": 1000000000}
            )
            record = {
                "kind": "stop",
                "pid": 42,
                "creation_time_ns": 1100000000,
                "generated_at_ns": 1450000000,
                "received_at_ns": 5000000000,
            }
            server.send(
                envelope
                | {
                    "type": "batch",
                    "message_sequence": 2,
                    "healthy": True,
                    "data_complete": True,
                    "records": [record | {"sequence": 1}, record | {"sequence": 2}],
                }
            )
            deadline = time.monotonic() + 3
            while not source._invalid and time.monotonic() < deadline:
                time.sleep(0.01)
            assert source._invalid
            _, _, healthy, records = source.poll()
            assert not healthy and not records
        finally:
            source.close()


def test_submillisecond_pid_identity_collision_falls_back_instead_of_merging():
    from time_tracker.platform.windows.event_stream import EventStream

    stream = EventStream()
    envelope = {"schema_version": 1, "stream_id": "collision"}
    stream.accept(envelope | {"type": "ready", "message_sequence": 1})
    record = {
        "kind": "stop",
        "pid": 42,
        "generated_at_ns": 1450000000,
        "received_at_ns": 5000000000,
    }
    stream.accept(
        envelope
        | {
            "type": "batch",
            "message_sequence": 2,
            "healthy": True,
            "data_complete": True,
            "records": [
                record | {"creation_time_ns": 1100000100, "sequence": 1},
                record | {"creation_time_ns": 1100000200, "sequence": 2},
            ],
        }
    )
    assert stream.gap and not stream.healthy
