"""Real owner thread with controlled slow sources; all history is synthetic."""

import threading
import time
from types import SimpleNamespace

import pytest

from time_tracker.api.commands import SettingsMailbox, WriterUnavailable
from time_tracker.collector import CollectionController
from time_tracker.domain.events import (
    ProcessesObserved,
    ProcessIdentity,
    ProcessObservation,
    TrackerSnapshot,
)
from time_tracker.runtime import TrackerRuntime
from time_tracker.worker import CollectionWorker


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Worker did not make progress")
        time.sleep(0.005)


class Provider:
    def __init__(self):
        self.at = 1000
        self.clock = SimpleNamespace(now_ms=lambda: self.at)
        self.api = self
        self.processes = SimpleNamespace(snapshot=self.process_snapshot)
        self.item = ProcessObservation(ProcessIdentity(42, 10), "C:/Apps/editor.exe")
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_poll = self.block_full = False
        self.locked = False
        self.threads = []

    def pause(self):
        self.entered.set()
        assert self.release.wait(5), "Test did not release slow source"

    def process_snapshot(self):
        self.threads.append(threading.get_ident())
        if self.block_poll:
            self.block_poll = False
            self.pause()
            return (ProcessObservation(ProcessIdentity(99, 20), "C:/Apps/stale.exe"),)
        return (self.item,)

    def snapshot(self):
        self.threads.append(threading.get_ident())
        snapshot = TrackerSnapshot(self.at, (self.item,), None, self.at, is_locked=self.locked)
        if self.block_full:
            self.block_full = False
            self.pause()
        return snapshot

    def foreground(self):
        return None

    def is_locked(self):
        return self.locked

    def idle_ms(self):
        return 0


def rows(database, sql):
    with database.reader() as connection:
        return [tuple(row) for row in connection.execute(sql)]


def system(database):
    return rows(database, "SELECT state,started_at,ended_at FROM system_state_sessions ORDER BY id")


@pytest.fixture
def setup_worker(database):
    provider = Provider()
    runtime = TrackerRuntime(database, provider, clock=provider.clock)
    controller = CollectionController(
        runtime, provider, provider.clock, monotonic=lambda: provider.at / 1000
    )
    worker = CollectionWorker(controller)
    yield worker, provider, database
    provider.release.set()
    worker.request_stop()
    worker.join()


def start_poll(worker, provider):
    worker.start()
    assert worker.ready.wait(5)
    provider.block_poll = True
    provider.at = 6000
    assert provider.entered.wait(5)


def test_slow_poll_preserves_queued_boundaries_and_discards_stale_processes(setup_worker):
    worker, provider, database = setup_worker
    start_poll(worker, provider)
    for at, kind in ((6500, "lock"), (7000, "sleep"), (8000, "wake"), (9000, "sleep")):
        provider.at = at
        worker.notify(kind)
    provider.at = 10000
    provider.release.set()
    wait_until(lambda: len(system(database)) == 5)
    provider.at = 11000
    worker.request_stop()
    assert worker.done.wait(5)
    assert worker.error is None
    assert system(database) == [
        ("ACTIVE", 1000, 6500),
        ("LOCKED", 6500, 7000),
        ("SLEEP", 7000, 8000),
        ("LOCKED", 8000, 9000),
        ("SLEEP", 9000, 11000),
    ]
    assert rows(database, "SELECT DISTINCT pid FROM process_sessions") == [(42,)]
    assert set(provider.threads) == {worker._thread.ident}
    assert worker._thread.ident != threading.get_ident()


def test_sleep_during_resume_never_publishes_old_snapshot(setup_worker):
    worker, provider, database = setup_worker
    worker.start()
    assert worker.ready.wait(5)
    provider.at = 2000
    worker.notify("sleep")
    wait_until(lambda: system(database)[-1][0] == "SLEEP")
    provider.block_full = True
    provider.at = 3000
    worker.notify("wake")
    assert provider.entered.wait(5)
    provider.at = 4000
    worker.notify("sleep")
    provider.at = 5000
    provider.release.set()
    wait_until(lambda: system(database)[-1][:2] == ("SLEEP", 4000))
    worker.request_stop()
    assert worker.done.wait(5)
    assert worker.error is None
    assert [row[:2] for row in system(database)] == [
        ("ACTIVE", 1000),
        ("SLEEP", 2000),
        ("ACTIVE", 3000),
        ("SLEEP", 4000),
    ]


def test_notification_during_accepted_write_keeps_original_boundary(setup_worker):
    worker, provider, database = setup_worker
    runtime = worker.controller.runtime
    original = runtime.handle

    def handle(event):
        if isinstance(event, ProcessesObserved):
            # The collector already reserved this event's timestamp and checked
            # its queue; a subsequent enqueue must not wait for persistence.
            provider.pause()
        return original(event)

    runtime.handle = handle
    worker.start()
    assert worker.ready.wait(5)
    provider.at = 6000
    assert provider.entered.wait(5)
    provider.at = 6500
    worker.notify("lock")
    worker.request_stop()
    assert not worker.done.is_set()
    provider.at = 7000
    provider.release.set()
    assert worker.done.wait(5)
    assert worker.error is None
    assert system(database) == [("ACTIVE", 1000, 6500), ("LOCKED", 6500, 7000)]


def test_startup_signal_retries_baseline_without_backdating_history(setup_worker):
    worker, provider, database = setup_worker
    provider.block_full = True
    worker.start()
    assert provider.entered.wait(5)
    provider.at = 2000
    provider.locked = True
    worker.notify("lock")
    provider.at = 3000
    provider.release.set()
    assert worker.ready.wait(5)
    assert system(database) == [("LOCKED", 3000, None)]
    assert worker.error is None


def test_stop_during_startup_leaves_no_run_and_releases_database(setup_worker):
    worker, provider, database = setup_worker
    provider.block_full = True
    worker.start()
    assert provider.entered.wait(5)
    worker.request_stop()
    provider.release.set()
    assert worker.done.wait(5)
    assert worker.error is None
    assert rows(database, "SELECT id FROM tracker_runs") == []
    from time_tracker.platform.instance_lock import InstanceLock

    with InstanceLock(database.path):
        pass


def test_overflow_recovers_unknown_tail_then_reconciles(setup_worker):
    worker, provider, database = setup_worker
    worker.capacity = 2
    start_poll(worker, provider)
    for at, kind in ((6500, "lock"), (7000, "sleep"), (8000, "wake")):
        provider.at = at
        worker.notify(kind)
    assert len(worker._queue) == 2
    provider.at = 9000
    provider.release.set()
    wait_until(lambda: len(rows(database, "SELECT id FROM tracker_runs")) == 2)
    worker.request_stop()
    assert worker.done.wait(5)
    assert worker.error is None
    assert rows(database, "SELECT started_at,ended_at,exit_reason FROM tracker_runs") == [
        (1000, 1000, "crash"),
        (9000, 9000, "normal"),
    ]
    assert rows(database, "SELECT DISTINCT pid FROM process_sessions") == [(42,)]


def test_stop_after_overflow_aborts_without_claiming_normal_history(setup_worker):
    worker, provider, database = setup_worker
    worker.capacity = 1
    start_poll(worker, provider)
    worker.notify("sleep")
    worker.notify("wake")
    worker.request_stop()
    provider.release.set()
    assert worker.done.wait(5)
    assert rows(database, "SELECT ended_at,exit_reason FROM tracker_runs") == [(None, None)]


def test_settings_wait_for_lifecycle_and_execute_on_owner(setup_worker):
    worker, provider, database = setup_worker
    commands = SettingsMailbox(worker.controller.runtime)
    worker.service = SimpleNamespace(
        start=lambda: None, check=lambda: None, commands=commands, stop=commands.close
    )
    start_poll(worker, provider)
    answers = []
    caller = threading.Thread(target=lambda: answers.append(commands.change(1, {"ignored": True})))
    caller.start()
    try:
        wait_until(lambda: commands._queue.qsize() == 1)
        provider.at = 6500
        provider.locked = True
        worker.notify("lock")
        provider.at = 7000
        provider.release.set()
        caller.join(5)
        assert not caller.is_alive()
        assert answers[0]["ignored"] is True
        assert system(database)[:2] == [("ACTIVE", 1000, 6500), ("LOCKED", 6500, None)]
        assert worker.error is None
    finally:
        provider.release.set()
        commands.close()
        caller.join(5)


def test_worker_failure_aborts_and_closes_pending_commands(setup_worker):
    worker, provider, database = setup_worker
    commands = SettingsMailbox(worker.controller.runtime)
    worker.service = SimpleNamespace(
        start=lambda: None, check=lambda: None, commands=commands, stop=commands.close
    )
    worker.start()
    assert worker.ready.wait(5)

    def fail():
        raise OSError("disk unavailable")

    worker.controller.tick = fail
    assert worker.done.wait(5)
    assert isinstance(worker.error, OSError)
    assert rows(database, "SELECT ended_at,exit_reason FROM tracker_runs") == [(None, None)]
    with pytest.raises(WriterUnavailable, match="stopping"):
        commands.change(1, {"ignored": True})
