import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from time_tracker.domain.events import (
    ForegroundChanged,
    ForegroundObservation,
    Heartbeat,
    ProcessIdentity,
    ProcessObservation,
    TrackerSnapshot,
    TrackerStopping,
)
from time_tracker.platform.instance_lock import AlreadyRunningError, InstanceLock
from time_tracker.runtime import TrackerRuntime
from time_tracker.storage.database import Database


@dataclass
class FakeClock:
    at: int = 1000

    def now_ms(self):
        return self.at


class FakeProvider:
    def __init__(self, clock):
        self.clock = clock
        self.fail = False
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("snapshot unavailable")
        process = ProcessObservation(ProcessIdentity(42, 100), "C:/Apps/editor.exe")
        return TrackerSnapshot(
            self.clock.at, (process,), ForegroundObservation(process, 50, "Example"), self.clock.at
        )


@pytest.fixture
def setup(tmp_path):
    clock = FakeClock()
    provider = FakeProvider(clock)
    database = Database(tmp_path / "история" / "tracker.db")
    return database, clock, provider


def test_runtime_fake_provider_and_clock_lifecycle(setup):
    database, clock, provider = setup
    with TrackerRuntime(database, provider, clock=clock) as runtime:
        assert runtime.state.run.started_at == 1000
        assert runtime.state.foreground.session.window_title == "Example"
        clock.at = 2000
        runtime.heartbeat()
        assert runtime.state.run.last_heartbeat_at == 2000
        clock.at = 3000
    assert runtime.state is None
    assert provider.calls == 1
    with database.reader() as connection:
        assert tuple(
            connection.execute("SELECT ended_at, exit_reason FROM tracker_runs").fetchone()
        ) == (3000, "normal")


def test_second_runtime_is_rejected_before_database_or_provider_access(setup, monkeypatch):
    database, clock, provider = setup
    first = TrackerRuntime(database, provider, clock=clock)
    first.start()
    try:

        def forbidden():
            pytest.fail("Second runtime must not reach database initialization or recovery")

        monkeypatch.setattr(database, "initialize", forbidden)
        second = TrackerRuntime(database, provider, clock=clock)
        with pytest.raises(AlreadyRunningError):
            second.start()
        assert provider.calls == 1
        assert first.state.run.ended_at is None
        clock.at = 2000
    finally:
        first.stop()


def test_failed_snapshot_releases_lock_and_creates_no_run(setup):
    database, clock, provider = setup
    provider.fail = True
    runtime = TrackerRuntime(database, provider, clock=clock)
    with pytest.raises(RuntimeError, match="snapshot unavailable"):
        runtime.start()
    with database.reader() as connection:
        assert connection.execute("SELECT COUNT(*) FROM tracker_runs").fetchone()[0] == 0
    provider.fail = False
    with runtime:
        assert runtime.state is not None


def test_abort_leaves_crash_boundary_for_next_start(setup):
    database, clock, provider = setup
    with pytest.raises(RuntimeError, match="simulated crash"):
        with TrackerRuntime(database, provider, clock=clock) as runtime:
            clock.at = 2000
            runtime.heartbeat()
            raise RuntimeError("simulated crash")
    clock.at = 5000
    with TrackerRuntime(database, provider, clock=clock) as restarted:
        assert restarted.state.run.started_at == 5000
        with database.reader() as connection:
            assert tuple(
                connection.execute(
                    "SELECT ended_at, exit_reason FROM tracker_runs WHERE id=1"
                ).fetchone()
            ) == (2000, "crash")


def test_shutdown_write_failure_releases_lock_for_recovery(setup):
    database, clock, provider = setup
    runtime = TrackerRuntime(database, provider, clock=clock)
    runtime.start()
    with database.transaction() as connection:
        connection.execute("""CREATE TRIGGER fail_close
            BEFORE UPDATE OF ended_at ON foreground_sessions
            BEGIN SELECT RAISE(ABORT, 'injected disk failure'); END""")
    clock.at = 2000
    with pytest.raises(sqlite3.IntegrityError, match="injected disk failure"):
        runtime.stop()
    assert runtime.state is None
    with InstanceLock(database.path), database.transaction() as connection:
        assert connection.execute("SELECT ended_at FROM tracker_runs").fetchone()[0] is None
        connection.execute("DROP TRIGGER fail_close")
    clock.at = 3000
    with TrackerRuntime(database, provider, clock=clock):
        with database.reader() as connection:
            assert tuple(
                connection.execute(
                    "SELECT ended_at, exit_reason FROM tracker_runs WHERE id=1"
                ).fetchone()
            ) == (1000, "crash")


def test_runtime_rejects_raw_lifecycle_and_foreign_thread_mutation(setup):
    database, clock, provider = setup
    with TrackerRuntime(database, provider, clock=clock) as runtime:
        with pytest.raises(ValueError, match="lifecycle"):
            runtime.handle(TrackerStopping(2000))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runtime.handle, Heartbeat(2000))
            with pytest.raises(RuntimeError, match="owner thread"):
                future.result()
        assert runtime.state.run.last_heartbeat_at == 1000


def test_backward_clock_clamps_heartbeat_and_shutdown_to_accepted_observation(setup):
    database, clock, provider = setup
    with TrackerRuntime(database, provider, clock=clock) as runtime:
        runtime.handle(ForegroundChanged(3000, None))
        clock.at = 500
        runtime.heartbeat()
        assert runtime.state.run.last_heartbeat_at == 3000
    with database.reader() as connection:
        assert connection.execute("SELECT ended_at FROM tracker_runs").fetchone()[0] == 3000


def test_os_lock_is_released_by_abrupt_child_exit(setup):
    database, clock, provider = setup
    # os._exit bypasses finally/context managers: only the OS can release this lock.
    script = """
import os
import sys
from time_tracker.domain.events import (
    TrackerSnapshot, ProcessIdentity, ProcessObservation, ForegroundObservation, Heartbeat
)
from time_tracker.runtime import TrackerRuntime
from time_tracker.storage.database import Database
class Provider:
    def snapshot(self):
        process = ProcessObservation(ProcessIdentity(42, 100), 'C:/Apps/editor.exe')
        return TrackerSnapshot(1000, (process,), ForegroundObservation(process, 50), 1000)
runtime = TrackerRuntime(Database(sys.argv[1]), Provider())
runtime.start()
runtime.handle(Heartbeat(2000))
os._exit(0)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(database.path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        env={**os.environ, "PYTHONUTF8": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    clock.at = 5000
    with TrackerRuntime(database, provider, clock=clock):
        with database.reader() as connection:
            runs = connection.execute(
                "SELECT started_at, ended_at, exit_reason FROM tracker_runs ORDER BY id"
            ).fetchall()
            assert tuple(runs[0]) == (1000, 2000, "crash")
            assert tuple(runs[1]) == (5000, None, None)
            for table in (
                "process_sessions",
                "application_running_sessions",
                "foreground_sessions",
                "system_state_sessions",
            ):
                assert (
                    connection.execute(f"SELECT ended_at FROM {table} WHERE id=1").fetchone()[0]
                    == 2000
                )


def test_cli_cannot_initialize_database_owned_by_another_process(setup, tmp_path):
    database, clock, provider = setup
    with TrackerRuntime(database, provider, clock=clock):
        child = subprocess.run(
            [sys.executable, "-m", "time_tracker", "--init-db", "--database", str(database.path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
        assert child.returncode == 1
        assert "already using this database" in child.stderr
        assert "Traceback" not in child.stderr
