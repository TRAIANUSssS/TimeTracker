from contextlib import contextmanager
from dataclasses import replace
from itertools import product

import pytest

from time_tracker.domain.events import (
    ApplicationSettingsChanged,
    ForegroundChanged,
    ForegroundObservation,
    Heartbeat,
    IdleEnded,
    IdleObserved,
    IdleStarted,
    ProcessesObserved,
    ProcessIdentity,
    ProcessObservation,
    ProcessStarted,
    ProcessStopped,
    SessionLocked,
    SessionUnlocked,
    SystemSleep,
    SystemWake,
    TrackerSnapshot,
    TrackerStopping,
)
from time_tracker.domain.models import SystemState
from time_tracker.domain.session_manager import ClockOrderError, SessionManager
from time_tracker.domain.system_state import SystemFlags
from time_tracker.storage.repositories import Repositories


class InstrumentedStore:
    """Real transactions with write counting and failure before the outer commit."""

    def __init__(self, database):
        self.database = database
        self.changes = 0
        self.fail_commit = False

    @contextmanager
    def transaction(self):
        with self.database.transaction() as connection:
            yield Repositories(connection)
            if self.fail_commit:
                raise RuntimeError("injected commit failure")
            self.changes += connection.total_changes


def process(pid=10, path="C:/Apps/editor.exe", creation=100, token=None):
    return ProcessObservation(ProcessIdentity(pid, creation, token), path)


def snapshot(at=1000, processes=(), foreground=None, last_input=None, **flags):
    return TrackerSnapshot(
        at, tuple(processes), foreground, at if last_input is None else last_input, **flags
    )


def rows(database, table):
    with database.reader() as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


@pytest.fixture
def core(database):
    store = InstrumentedStore(database)
    manager = SessionManager(store)
    manager.start(snapshot())
    return manager, store


def test_process_counts_and_atomic_snapshot_replacement(core, database):
    manager, _ = core
    first, second, third = process(), process(11), process(12)
    manager.handle(ProcessStarted(1100, first))
    manager.handle(ProcessStarted(1200, second))
    assert list(manager.state.application_process_counts.values()) == [2]
    manager.handle(ProcessStopped(1300, first.identity))
    assert list(manager.state.application_process_counts.values()) == [1]
    manager.handle(ProcessesObserved(1400, (third,)))
    assert len(rows(database, "application_running_sessions")) == 1
    manager.handle(ProcessesObserved(1500, ()))
    running = rows(database, "application_running_sessions")
    assert [(r["started_at"], r["ended_at"]) for r in running] == [(1100, 1500)]
    assert manager.state.application_process_counts == {}


def test_foreground_registers_process_before_poll_and_repeats_do_not_write(core, database):
    manager, store = core
    item = process()
    foreground = ForegroundObservation(item, 42, "Document")
    manager.handle(ForegroundChanged(1100, foreground))
    changes = store.changes
    for at in (1200, 1300, 1400):
        manager.handle(ProcessesObserved(at, (item,)))
        manager.handle(ForegroundChanged(at, foreground))
    assert store.changes == changes
    assert rows(database, "process_sessions")[0]["detected_at"] == 1100
    assert rows(database, "application_running_sessions")[0]["started_at"] == 1100
    manager.handle(ProcessStopped(1500, item.identity))
    assert rows(database, "foreground_sessions")[0]["ended_at"] == 1500
    assert manager.state.foreground is None


def test_stale_and_incomplete_snapshots_do_not_remove_new_foreground(core, database):
    manager, store = core
    item = process()
    manager.handle(ForegroundChanged(2000, ForegroundObservation(item, 42)))
    changes = store.changes
    assert not manager.handle(ProcessesObserved(1500, ()))
    manager.handle(ProcessesObserved(2100, (), complete=False))
    assert store.changes == changes
    assert item.identity in manager.state.running_processes
    assert rows(database, "foreground_sessions")[0]["ended_at"] is None


def test_pid_reuse_and_late_stop_keep_the_new_process(core, database):
    manager, _ = core
    old, new = process(), process(creation=1500, path="C:/Apps/browser.exe")
    manager.handle(ForegroundChanged(1100, ForegroundObservation(old, 42)))
    manager.handle(ProcessStarted(1600, new))
    manager.handle(ProcessStopped(1700, old.identity))
    assert set(manager.state.running_processes) == {new.identity}
    assert [(r["detected_at"], r["ended_at"]) for r in rows(database, "process_sessions")] == [
        (1100, 1600),
        (1600, None),
    ]
    assert manager.state.foreground is None


@pytest.mark.parametrize("creation,token,expected_count", [(100, None, 1), (None, "gap-1", 2)])
def test_unknown_path_resolution_never_backdates_running(
    core, database, creation, token, expected_count
):
    manager, _ = core
    unknown = process(path=None, creation=creation, token=token)
    manager.handle(ProcessStarted(1100, unknown))
    assert not rows(database, "applications")
    assert not rows(database, "application_running_sessions")
    manager.handle(ProcessStarted(2000, replace(unknown, executable_path="C:/Apps/editor.exe")))
    sessions = rows(database, "process_sessions")
    assert len(sessions) == expected_count
    assert sessions[-1]["executable_id"] is not None
    if creation is None:
        assert sessions[0]["executable_id"] is None
        assert sessions[0]["ended_at"] == 2000
    assert rows(database, "application_running_sessions")[0]["started_at"] == 2000


def test_access_denied_does_not_erase_known_process(core, database):
    manager, store = core
    item = process()
    manager.handle(ProcessStarted(1100, item))
    changes = store.changes
    manager.handle(ProcessesObserved(1200, (replace(item, executable_path=None),)))
    assert store.changes == changes
    assert manager.state.running_processes[item.identity].executable is not None
    assert len(rows(database, "applications")) == 1


@pytest.mark.parametrize(
    "description,product_name,expected",
    [(" Editor ", "Product", "Editor"), (" ", "Product", "Product"), (None, None, "editor")],
)
def test_registry_metadata_and_path_normalization(
    core, database, description, product_name, expected
):
    manager, _ = core
    item = replace(process(), file_description=description, product_name=product_name)
    manager.handle(ProcessStarted(1100, item))
    manager.handle(ProcessStarted(1200, process(11, path="c:\\APPS\\EDITOR.exe")))
    assert [row["name"] for row in rows(database, "applications")] == [expected]
    assert len(rows(database, "executables")) == 1


def test_foreground_title_hwnd_and_unknown_transitions(core, database):
    manager, _ = core
    first = ForegroundObservation(process(), 42, "First")
    manager.handle(ForegroundChanged(1100, first))
    manager.handle(ForegroundChanged(1200, replace(first, title="Second")))
    manager.handle(ForegroundChanged(1300, replace(first, hwnd=43, title="Second")))
    manager.handle(ForegroundChanged(1400, None))
    manager.handle(ForegroundChanged(1500, first))
    assert [(r["started_at"], r["ended_at"]) for r in rows(database, "foreground_sessions")] == [
        (1100, 1200),
        (1200, 1300),
        (1300, 1400),
        (1500, None),
    ]


def test_settings_split_titles_atomically_and_preserve_raw_history(core, database):
    manager, store = core
    fg = ForegroundObservation(process(), 42, "Old title")
    manager.handle(ForegroundChanged(1100, fg))
    app_id = manager.state.foreground.session.application_id
    manager.handle(ApplicationSettingsChanged(1200, app_id, ignored=True, track_titles=False))
    changes = store.changes
    manager.handle(ForegroundChanged(1300, replace(fg, title="Private title")))
    manager.handle(ApplicationSettingsChanged(1400, app_id, ignored=True, track_titles=False))
    assert store.changes == changes
    assert [r["window_title"] for r in rows(database, "foreground_sessions")] == ["Old title", None]
    assert len(rows(database, "application_running_sessions")) == 1
    assert manager.state.flags.effective == SystemState.ACTIVE
    manager.handle(ApplicationSettingsChanged(1500, app_id, track_titles=True))
    assert manager.state.foreground.session.window_title is None
    manager.handle(ForegroundChanged(1600, replace(fg, title="Fresh title")))
    assert manager.state.foreground.session.window_title == "Fresh title"


@pytest.mark.parametrize("sleeping,locked,idle", list(product((False, True), repeat=3)))
def test_system_priority(sleeping, locked, idle):
    expected = "SLEEP" if sleeping else "LOCKED" if locked else "IDLE" if idle else "ACTIVE"
    assert SystemFlags(sleeping, locked, idle).effective == expected


def test_idle_exact_boundary_and_foreground_continuity(core, database):
    manager, _ = core
    manager.handle(ForegroundChanged(1100, ForegroundObservation(process(), 42)))
    manager.handle(IdleObserved(300999, 1000))
    assert manager.state.flags.effective == SystemState.ACTIVE
    manager.handle(IdleStarted(302999, 1000))
    assert manager.state.system_session.started_at == 301000
    assert manager.state.foreground is not None
    manager.handle(IdleEnded(303000, 302500))
    assert [
        (r["state"], r["started_at"], r["ended_at"])
        for r in rows(database, "system_state_sessions")
    ] == [("ACTIVE", 1000, 301000), ("IDLE", 301000, 303000), ("ACTIVE", 303000, None)]
    assert len(rows(database, "foreground_sessions")) == 1
    assert len(rows(database, "application_running_sessions")) == 1


def test_startup_idle_begins_at_startup_not_before(database):
    manager = SessionManager(InstrumentedStore(database))
    manager.start(snapshot(500000, last_input=1000))
    assert manager.state.system_session.started_at == 500000
    assert manager.state.flags.effective == SystemState.IDLE


@pytest.mark.parametrize(
    "locked,last_input,expected",
    [(True, 400000, "LOCKED"), (False, 1000, "IDLE"), (False, 400000, "ACTIVE")],
)
def test_wake_uses_fresh_state_and_does_not_resume_old_foreground(
    core, database, locked, last_input, expected
):
    manager, _ = core
    old = process()
    fresh = process(20, "C:/Apps/browser.exe")
    manager.handle(ForegroundChanged(1100, ForegroundObservation(old, 42)))
    manager.handle(SystemSleep(2000))
    manager.handle(ProcessesObserved(3000, ()))
    assert old.identity in manager.state.running_processes
    wake = snapshot(
        400000, (fresh,), ForegroundObservation(fresh, 50), last_input, is_locked=locked
    )
    manager.handle(SystemWake(400000, wake))
    assert manager.state.flags.effective == expected
    assert set(manager.state.running_processes) == {fresh.identity}
    assert rows(database, "foreground_sessions")[0]["ended_at"] == 2000
    assert rows(database, "system_state_sessions")[1]["state"] == "SLEEP"
    assert (manager.state.foreground is None) == locked


def test_lock_sleep_unlock_priority_and_idle_boundary_clamping(core, database):
    manager, _ = core
    manager.handle(SessionLocked(2000))
    manager.handle(SystemSleep(3000))
    manager.handle(IdleObserved(350000, 1000))
    assert manager.state.flags.effective == SystemState.SLEEP
    manager.handle(SystemWake(400000, snapshot(400000, last_input=1000, is_locked=True)))
    assert manager.state.flags.effective == SystemState.LOCKED
    manager.handle(SessionUnlocked(410000, snapshot(410000, last_input=410000)))
    manager.handle(IdleStarted(420000, 1000))
    # A late last-input sample must not extend IDLE into the preceding locked interval.
    assert manager.state.system_session.started_at == 410000
    assert all(
        r["ended_at"] is None or r["ended_at"] >= r["started_at"]
        for r in rows(database, "system_state_sessions")
    )


def test_failed_transition_rolls_back_database_caches_and_watermark(core, database):
    manager, store = core
    previous = manager.state
    store.fail_commit = True
    event = ForegroundChanged(2000, ForegroundObservation(process(), 42, "Example"))
    with pytest.raises(RuntimeError, match="injected"):
        manager.handle(event)
    assert manager.state == previous
    assert not rows(database, "applications")
    assert not rows(database, "process_sessions")
    store.fail_commit = False
    manager.handle(event)
    assert manager.state.run.last_persisted_at == 2000
    assert len(rows(database, "applications")) == 1


def test_failed_settings_leave_policy_and_foreground_unchanged(core, database):
    manager, store = core
    manager.handle(ForegroundChanged(1100, ForegroundObservation(process(), 42, "Title")))
    previous = manager.state
    app_id = previous.foreground.session.application_id
    store.fail_commit = True
    with pytest.raises(RuntimeError, match="injected"):
        manager.handle(ApplicationSettingsChanged(1200, app_id, track_titles=False))
    assert manager.state == previous
    assert rows(database, "applications")[0]["track_titles"] == 1
    assert len(rows(database, "foreground_sessions")) == 1


def test_state_snapshot_cannot_modify_live_maps(core):
    manager, _ = core
    manager.handle(ProcessStarted(1100, process()))
    state = manager.state
    state.running_processes.clear()
    state.applications.clear()
    assert len(manager.state.running_processes) == 1
    assert len(manager.state.applications) == 1


@pytest.mark.parametrize("heartbeat,change,boundary", [(2000, 3000, 3000), (3000, 2000, 3000)])
def test_crash_recovery_uses_maximum_confirmed_boundary(
    core, database, heartbeat, change, boundary
):
    manager, store = core
    for event in sorted(
        [Heartbeat(heartbeat), ForegroundChanged(change, ForegroundObservation(process(), 42))],
        key=lambda e: e.observed_at,
    ):
        manager.handle(event)
    restarted = SessionManager(store)
    restarted.start(snapshot(5000))
    run = rows(database, "tracker_runs")[0]
    assert (run["ended_at"], run["exit_reason"]) == (boundary, "crash")
    for table in (
        "process_sessions",
        "application_running_sessions",
        "foreground_sessions",
        "system_state_sessions",
    ):
        assert rows(database, table)[0]["ended_at"] == boundary
    assert restarted.state.system_session.started_at == 5000


def test_failed_recovery_and_startup_are_one_transaction(core, database):
    manager, store = core
    manager.handle(ForegroundChanged(2000, ForegroundObservation(process(), 42)))
    restarted = SessionManager(store)
    store.fail_commit = True
    with pytest.raises(RuntimeError, match="injected"):
        restarted.start(snapshot(5000))
    assert restarted.state is None
    assert len(rows(database, "tracker_runs")) == 1
    assert rows(database, "foreground_sessions")[0]["ended_at"] is None
    store.fail_commit = False
    restarted.start(snapshot(5000))
    assert rows(database, "tracker_runs")[0]["ended_at"] == 2000


def test_shutdown_is_atomic_and_clean_restart_has_no_recovery(core, database):
    manager, store = core
    manager.handle(ForegroundChanged(2000, ForegroundObservation(process(), 42)))
    previous = manager.state
    store.fail_commit = True
    with pytest.raises(RuntimeError, match="injected"):
        manager.handle(TrackerStopping(3000))
    assert manager.state == previous
    assert rows(database, "foreground_sessions")[0]["ended_at"] is None
    store.fail_commit = False
    manager.handle(TrackerStopping(3000))
    assert manager.state is None
    for table in (
        "process_sessions",
        "application_running_sessions",
        "foreground_sessions",
        "system_state_sessions",
        "tracker_runs",
    ):
        assert rows(database, table)[0]["ended_at"] == 3000
    restarted = SessionManager(store)
    with pytest.raises(ClockOrderError):
        restarted.start(snapshot(2500))
    restarted.start(snapshot(4000))
    assert rows(database, "tracker_runs")[0]["exit_reason"] == "normal"


@pytest.mark.parametrize(
    "event",
    [
        IdleStarted(1100, 1000),
        IdleEnded(400000, 1000),
        IdleObserved(1100, 1200),
        SystemWake(1100, snapshot(1200)),
        SessionUnlocked(1100, snapshot(1100, is_locked=True)),
        ProcessesObserved(1100, (process(), process())),
    ],
)
def test_invalid_observations_leave_state_unchanged(core, event):
    manager, _ = core
    previous = manager.state
    with pytest.raises(ValueError):
        manager.handle(event)
    assert manager.state == previous


def test_unknown_creation_requires_continuity_token_and_restarts_after_gap(core, database):
    with pytest.raises(ValueError, match="token"):
        ProcessIdentity(10, None)
    manager, _ = core
    first = process(creation=None, token="observation-1")
    second = process(creation=None, token="observation-2")
    manager.handle(ProcessStarted(1100, first))
    manager.handle(ProcessesObserved(1200, ()))
    manager.handle(ProcessStarted(1300, second))
    manager.handle(ProcessStopped(1400, first.identity))
    assert set(manager.state.running_processes) == {second.identity}
    assert len(rows(database, "process_sessions")) == 2


def test_same_foreground_fields_split_at_process_owner_change(core, database):
    manager, _ = core
    old, new = process(), process(11)
    manager.handle(ForegroundChanged(1100, ForegroundObservation(old, 42, "Same")))
    manager.handle(ForegroundChanged(1200, ForegroundObservation(new, 42, "Same")))
    manager.handle(ProcessStopped(1300, old.identity))
    assert manager.state.foreground.identity == new.identity
    sessions = rows(database, "foreground_sessions")
    assert len(sessions) == 2
    assert sessions[0]["ended_at"] == sessions[1]["started_at"] == 1200
    assert sessions[0]["process_session_id"] != sessions[1]["process_session_id"]
    manager.handle(ProcessStopped(1400, new.identity))
    assert manager.state.foreground is None


def test_sleep_preserves_raw_running_but_splits_system_and_foreground(core, database):
    manager, _ = core
    item = process()
    foreground = ForegroundObservation(item, 42)
    manager.handle(ForegroundChanged(1100, foreground))
    manager.handle(SystemSleep(2000))
    manager.handle(SystemWake(5000, snapshot(5000, (item,), foreground)))
    assert len(rows(database, "process_sessions")) == 1
    assert len(rows(database, "application_running_sessions")) == 1
    assert [(r["started_at"], r["ended_at"]) for r in rows(database, "foreground_sessions")] == [
        (1100, 2000),
        (5000, None),
    ]
    assert [r["state"] for r in rows(database, "system_state_sessions")] == [
        "ACTIVE",
        "SLEEP",
        "ACTIVE",
    ]


def test_backdated_idle_does_not_move_recovery_boundary_backwards(core, database):
    manager, store = core
    manager.handle(ForegroundChanged(302000, ForegroundObservation(process(), 42)))
    manager.handle(IdleStarted(303000, 1000))
    assert manager.state.system_session.started_at == 301000
    assert manager.state.run.last_persisted_at == 302000
    restarted = SessionManager(store)
    restarted.start(snapshot(400000))
    assert rows(database, "foreground_sessions")[0]["ended_at"] == 302000
    assert rows(database, "system_state_sessions")[1]["ended_at"] == 302000
