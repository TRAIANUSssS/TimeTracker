"""Persistence and snapshot interfaces consumed by the core, without SQLite imports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from time_tracker.domain.events import TrackerSnapshot
from time_tracker.domain.models import (
    Application,
    ApplicationRunningSession,
    Executable,
    ForegroundSession,
    ProcessSession,
    SystemState,
    SystemStateSession,
    TrackerRun,
)


class Applications(Protocol):
    def get(self, record_id: int) -> Application | None: ...
    def list_all(self) -> list[Application]: ...
    def create(self, name: str, *, at: int) -> Application: ...
    def update_settings(
        self,
        application_id: int,
        *,
        at: int,
        ignored: bool | None = None,
        track_titles: bool | None = None,
    ) -> Application: ...


class Executables(Protocol):
    def get(self, record_id: int) -> Executable | None: ...
    def find_by_path(self, path: str) -> Executable | None: ...
    def create(self, application_id: int, path: str, *, at: int) -> Executable: ...
    def touch(self, executable_id: int, *, at: int) -> Executable: ...


class Runs(Protocol):
    def start(self, *, at: int, version: str | None = None) -> TrackerRun: ...
    def get(self, record_id: int) -> TrackerRun | None: ...
    def get_open(self) -> TrackerRun | None: ...
    def get_latest(self) -> TrackerRun | None: ...
    def heartbeat(self, run_id: int, *, at: int) -> TrackerRun: ...
    def finish(self, run_id: int, *, at: int, reason: str) -> TrackerRun: ...


class Sessions[T](Protocol):
    def end(self, session_id: int, *, at: int) -> T: ...
    def list_open(self) -> list[T]: ...


class Processes(Sessions[ProcessSession], Protocol):
    def record_boundary(
        self,
        *,
        pid: int,
        creation: int,
        boundary: int,
        started: bool,
        coverage: int,
        at: int,
        executable_id: int | None,
        absent_at: int | None,
    ) -> ProcessSession | None: ...
    def start(
        self,
        *,
        pid: int,
        detected_at: int,
        executable_id: int | None = None,
        process_started_at: int | None = None,
    ) -> ProcessSession: ...
    def resolve_executable(
        self,
        session_id: int,
        *,
        executable_id: int,
        expected_pid: int,
        expected_creation_time: int,
        at: int,
    ) -> ProcessSession: ...


class Running(Sessions[ApplicationRunningSession], Protocol):
    def start(self, application_id: int, *, at: int) -> ApplicationRunningSession: ...
    def rebuild(
        self, application_id: int, *, since: int, at: int
    ) -> ApplicationRunningSession | None: ...


class Foreground(Sessions[ForegroundSession], Protocol):
    def clip_process(self, process_session_id: int, *, ended_at: int, at: int) -> None: ...
    def start(
        self,
        application_id: int,
        *,
        at: int,
        executable_id: int | None = None,
        hwnd: int | None = None,
        window_title: str | None = None,
        process_session_id: int | None = None,
    ) -> ForegroundSession: ...


class SystemSessions(Sessions[SystemStateSession], Protocol):
    def start(self, state: SystemState, *, at: int) -> SystemStateSession: ...
    def record_sleep(self, started_at: int, ended_at: int, *, at: int) -> None: ...


class TrackerRepositories(Protocol):
    applications: Applications
    executables: Executables
    runs: Runs
    processes: Processes
    running: Running
    foreground: Foreground
    system_states: SystemSessions

    def for_run(self, run_id: int) -> TrackerRepositories: ...


class TrackerStore(Protocol):
    def transaction(self) -> AbstractContextManager[TrackerRepositories]: ...


class SnapshotProvider(Protocol):
    def snapshot(self) -> TrackerSnapshot: ...


class Clock(Protocol):
    def now_ms(self) -> int: ...
