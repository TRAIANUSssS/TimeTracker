from dataclasses import dataclass
from types import SimpleNamespace

import pytest

pytest.importorskip("psutil")

from time_tracker.collector import CollectionController
from time_tracker.domain.events import (
    ForegroundObservation,
    ProcessIdentity,
    ProcessObservation,
    TrackerSnapshot,
)
from time_tracker.runtime import TrackerRuntime


@dataclass
class Clock:
    at: int = 1000

    def now_ms(self):
        return self.at

    def monotonic(self):
        return self.at / 1000


class Provider:
    def __init__(self, clock):
        self.clock = clock
        self.api = self
        self.processes = SimpleNamespace(snapshot=self.process_snapshot)
        self.item = ProcessObservation(ProcessIdentity(42, 10), "C:/Apps/editor.exe")
        self.window = ForegroundObservation(self.item, 1, "Document")
        self.locked = False
        self.idle = 0
        self.process_fail = False
        self.snapshot_fail = False
        self.idle_fail = False
        self.process_calls = 0
        self.foreground_calls = 0

    def process_snapshot(self):
        self.process_calls += 1
        if self.process_fail:
            raise OSError("process poll failed")
        return (self.item,)

    def foreground(self):
        self.foreground_calls += 1
        return self.window

    def foreground_for_window(self, hwnd, *, title_required):
        if self.window is None or self.window.hwnd != hwnd:
            return None
        title = self.window.title if title_required(self.item) else None
        return ForegroundObservation(self.item, hwnd, title)

    def idle_ms(self):
        if self.idle_fail:
            raise OSError("idle unavailable")
        return self.idle

    def is_locked(self):
        return self.locked

    def snapshot(self):
        if self.snapshot_fail:
            raise OSError("snapshot failed")
        return TrackerSnapshot(
            self.clock.at,
            self.process_snapshot(),
            None if self.locked else self.foreground(),
            self.clock.at - self.idle,
            is_locked=self.locked,
        )


@pytest.fixture
def controller(database):
    clock = Clock()
    provider = Provider(clock)
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock, monotonic=clock.monotonic)
    controller.start()
    yield controller, provider, clock
    runtime.stop()


def test_poll_deadlines_and_heartbeat_after_observations(controller):
    collector, provider, clock = controller
    clock.at = 2999
    collector.tick()
    assert provider.foreground_calls == 1
    clock.at = 3000
    collector.tick()
    assert provider.foreground_calls == 2
    assert provider.process_calls == 1
    clock.at = 6000
    collector.tick()
    assert provider.process_calls == 2
    assert collector.runtime.state.run.last_heartbeat_at == 6000


def test_failed_process_poll_keeps_existing_running(controller):
    collector, provider, clock = controller
    provider.process_fail = True
    clock.at = 6000
    collector.tick()
    assert len(collector.runtime.state.running_processes) == 1


def test_user_pause_ignores_hooks_and_lifecycle_until_fresh_resume(controller, database):
    collector, provider, clock = controller
    clock.at = 2000
    collector.set_paused(True)
    clock.at = 10_000
    calls = provider.process_calls
    collector.notify("lock")
    collector.notify("sleep")
    collector.notify("wake")
    collector.foreground_changed(1, False, clock.at)
    collector.tick()
    assert provider.process_calls == calls
    assert collector.runtime.state is None
    provider.snapshot_fail = True
    with pytest.raises(OSError):
        collector.set_paused(False)
    assert collector.runtime.tracking_paused
    provider.snapshot_fail = False
    provider.locked = True
    collector.set_paused(False)
    assert collector.runtime.state.flags.is_locked
    assert collector.runtime.state.run.started_at == 10_000
    with database.reader() as connection:
        rows = connection.execute(
            "SELECT started_at,ended_at FROM system_state_sessions ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [(1000, 2000), (10_000, None)]


def test_resume_accepts_snapshot_while_newer_native_event_is_queued(controller):
    collector, provider, clock = controller
    clock.at = 2000
    collector.set_paused(True)
    clock.at = 3000
    collector.startup_snapshot_filter = lambda _: (_ for _ in ()).throw(
        AssertionError("startup-only filter must not reject an explicit resume")
    )
    collector.set_paused(False)
    assert collector.runtime.state.run.started_at == 3000


def test_foreground_hook_resolves_only_its_window_and_splits_title(controller, database):
    collector, provider, clock = controller
    clock.at = 1100
    collector.foreground_changed(1, False, clock.at)
    # Repeated foreground notifications for the same HWND are harmless.
    clock.at = 1200
    collector.foreground_changed(1, False, clock.at)
    provider.window = ForegroundObservation(provider.item, 1, "Renamed document")
    clock.at = 1300
    collector.foreground_changed(1, True, clock.at)
    # A stale name-change for another HWND cannot close the current foreground.
    clock.at = 1400
    collector.foreground_changed(2, True, clock.at)
    with database.reader() as connection:
        rows = connection.execute(
            "SELECT window_title,started_at,ended_at FROM foreground_sessions ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("Document", 1000, 1300),
        ("Renamed document", 1300, None),
    ]
    assert provider.foreground_calls == 1  # Only the startup snapshot used global polling.


def test_hook_queue_loss_forces_immediate_foreground_reconciliation(controller):
    collector, provider, clock = controller
    collector.set_foreground_hooks_active(True)
    clock.at = 3000
    collector.foreground_events_lost()
    collector.tick()
    assert provider.foreground_calls == 2


def test_sleep_stops_polling_and_heartbeat_until_fresh_resume(controller):
    collector, provider, clock = controller
    clock.at = 2000
    collector.notify("sleep")
    provider.snapshot_fail = True
    clock.at = 10000
    collector.notify("wake")
    collector.tick()
    assert collector.runtime.state.flags.is_sleeping
    assert collector.runtime.state.run.last_heartbeat_at == 1000
    assert provider.foreground_calls == 1
    provider.snapshot_fail = False
    provider.locked = True
    collector.tick()
    assert collector.runtime.state.flags.effective == "LOCKED"
    assert collector.runtime.state.foreground is None


def test_unlock_retries_until_wts_confirms_unlock(controller):
    collector, provider, clock = controller
    provider.locked = True
    clock.at = 2000
    collector.notify("lock")
    clock.at = 3000
    collector.notify("unlock")
    assert collector.runtime.state.flags.is_locked
    provider.locked = False
    provider.idle = 300001
    clock.at = 400000
    collector.tick()
    assert collector.runtime.state.flags.effective == "IDLE"
    assert collector.runtime.state.foreground is not None


def test_poll_reconciles_missed_lock_notification(controller):
    collector, provider, clock = controller
    provider.locked = True
    clock.at = 3000
    collector.tick()
    assert collector.runtime.state.flags.effective == "LOCKED"
    assert collector.runtime.state.foreground is None
    provider.locked = False
    clock.at = 5000
    collector.tick()
    assert collector.runtime.state.flags.effective == "ACTIVE"


def test_duplicate_wake_does_not_split_running_or_foreground(controller, database):
    collector, _, clock = controller
    clock.at = 2000
    collector.notify("sleep")
    clock.at = 10000
    collector.notify("wake")
    clock.at = 10010
    collector.notify("wake")
    with database.reader() as connection:
        assert connection.execute("SELECT COUNT(*) FROM foreground_sessions").fetchone()[0] == 2
        assert (
            connection.execute("SELECT COUNT(*) FROM application_running_sessions").fetchone()[0]
            == 1
        )


def test_idle_failure_cannot_advance_heartbeat(controller):
    collector, provider, clock = controller
    provider.idle_fail = True
    clock.at = 6000
    with pytest.raises(OSError, match="idle unavailable"):
        collector.tick()
    assert collector.runtime.state.run.last_heartbeat_at == 1000


def test_backward_wall_clock_does_not_write_poll_data(controller):
    collector, provider, clock = controller
    clock.at = 500
    collector.tick()
    assert provider.process_calls == 1
    assert collector.runtime.state.last_event_at == 1000


def test_slow_process_collection_does_not_backdate_idle_or_heartbeat(controller, monkeypatch):
    collector, provider, clock = controller

    def slow_snapshot():
        clock.at = 8000
        return (provider.item,)

    monkeypatch.setattr(provider.processes, "snapshot", slow_snapshot)
    provider.idle = 100
    clock.at = 6000
    collector.tick()
    assert collector.runtime.state.last_input_at == 7900
    assert collector.runtime.state.run.last_heartbeat_at == 8000


def test_lock_during_failed_resume_does_not_strand_runtime_in_sleep(controller):
    collector, provider, clock = controller
    clock.at = 2000
    collector.notify("sleep")
    provider.snapshot_fail = True
    clock.at = 10000
    collector.notify("wake")
    provider.locked = True
    collector.notify("lock")
    provider.snapshot_fail = False
    clock.at = 11000
    collector.tick()
    assert collector.runtime.state.flags.effective == "LOCKED"
    assert not collector.runtime.state.flags.is_sleeping
