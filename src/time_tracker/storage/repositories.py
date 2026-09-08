"""Typed persistence operations; session orchestration belongs to the domain layer.

Methods compose inside an outer transaction. A failed individual write rolls back
its savepoint, including any change to the run's last-persisted boundary.
"""

import ntpath
import sqlite3
from typing import Any

from time_tracker.domain.identity import normalize_executable_path
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
from time_tracker.storage.transactions import transaction


class RecordNotFound(LookupError):
    """A requested record does not exist or is no longer open."""


class InvalidRunError(ValueError):
    """A session mutation needs a matching, open tracker run."""


class _Records[T]:
    # Identifiers are implementation constants, never caller-supplied SQL values.
    table: str
    model: type[T]

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def _decode(self, row: sqlite3.Row) -> T:
        return self.model(**dict(row))

    def get(self, record_id: int) -> T | None:
        row = self.connection.execute(
            f"SELECT * FROM {self.table} WHERE id = ?", (record_id,)
        ).fetchone()
        return self._decode(row) if row is not None else None

    def _insert(self, **values: Any) -> T:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        row = self.connection.execute(
            f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders}) RETURNING *",
            tuple(values.values()),
        ).fetchone()
        return self._decode(row)


class ApplicationRepository(_Records[Application]):
    table = "applications"
    model = Application

    def _decode(self, row: sqlite3.Row) -> Application:
        values = dict(row)
        values["ignored"] = bool(values["ignored"])
        values["track_titles"] = bool(values["track_titles"])
        return Application(**values)

    def create(self, name: str, *, at: int) -> Application:
        with transaction(self.connection):
            return self._insert(name=name, created_at=at, updated_at=at)

    def list_all(self) -> list[Application]:
        return [
            self._decode(row)
            for row in self.connection.execute("SELECT * FROM applications ORDER BY id")
        ]

    def update_settings(
        self,
        application_id: int,
        *,
        at: int,
        ignored: bool | None = None,
        track_titles: bool | None = None,
    ) -> Application:
        """Persist flags; the future session manager must coordinate RAM/title transitions."""
        if ignored is None and track_titles is None:
            raise ValueError("At least one setting must be supplied")
        for value in (ignored, track_titles):
            if value is not None and type(value) is not bool:
                raise ValueError("Application settings must be booleans")
        with transaction(self.connection):
            row = self.connection.execute(
                """UPDATE applications
                   SET ignored = COALESCE(?, ignored),
                       track_titles = COALESCE(?, track_titles), updated_at = ?
                   WHERE id = ? AND updated_at <= ? RETURNING *""",
                (ignored, track_titles, at, application_id, at),
            ).fetchone()
            if row is None:
                raise RecordNotFound("Application is missing or the settings timestamp is stale")
            return self._decode(row)


class ExecutableRepository(_Records[Executable]):
    table = "executables"
    model = Executable

    def create(self, application_id: int, path: str, *, at: int) -> Executable:
        normalized = normalize_executable_path(path)
        with transaction(self.connection):
            return self._insert(
                application_id=application_id,
                path=normalized,
                exe_name=ntpath.basename(normalized),
                first_seen_at=at,
                last_seen_at=at,
            )

    def find_by_path(self, path: str) -> Executable | None:
        row = self.connection.execute(
            "SELECT * FROM executables WHERE path = ?", (normalize_executable_path(path),)
        ).fetchone()
        return self._decode(row) if row is not None else None

    def touch(self, executable_id: int, *, at: int) -> Executable:
        with transaction(self.connection):
            row = self.connection.execute(
                """UPDATE executables SET last_seen_at = MAX(last_seen_at, ?)
                   WHERE id = ? RETURNING *""",
                (at, executable_id),
            ).fetchone()
            if row is None:
                raise RecordNotFound("Executable does not exist")
            return self._decode(row)


class TrackerRunRepository(_Records[TrackerRun]):
    table = "tracker_runs"
    model = TrackerRun

    def start(self, *, at: int, version: str | None = None) -> TrackerRun:
        with transaction(self.connection):
            return self._insert(
                started_at=at, last_heartbeat_at=at, last_persisted_at=at, version=version
            )

    def get_open(self) -> TrackerRun | None:
        row = self.connection.execute(
            "SELECT * FROM tracker_runs WHERE ended_at IS NULL"
        ).fetchone()
        return self._decode(row) if row is not None else None

    def heartbeat(self, run_id: int, *, at: int) -> TrackerRun:
        with transaction(self.connection):
            row = self.connection.execute(
                """UPDATE tracker_runs SET last_heartbeat_at = MAX(last_heartbeat_at, ?)
                   WHERE id = ? AND ended_at IS NULL AND started_at <= ? RETURNING *""",
                (at, run_id, at),
            ).fetchone()
            if row is None:
                raise InvalidRunError("Heartbeat needs an open run and a valid timestamp")
            return self._decode(row)

    def finish(self, run_id: int, *, at: int, reason: str) -> TrackerRun:
        """Finish only after the caller has closed all sessions in the same transaction."""
        if not reason.strip():
            raise ValueError("Exit reason cannot be empty")
        with transaction(self.connection):
            for table in (
                "process_sessions",
                "application_running_sessions",
                "foreground_sessions",
                "system_state_sessions",
            ):
                if self.connection.execute(
                    f"SELECT 1 FROM {table} WHERE ended_at IS NULL LIMIT 1"
                ).fetchone():
                    raise InvalidRunError("Close all sessions before finishing the run")
            row = self.connection.execute(
                """UPDATE tracker_runs SET ended_at = ?, exit_reason = ?
                   WHERE id = ? AND ended_at IS NULL RETURNING *""",
                (at, reason, run_id),
            ).fetchone()
            if row is None:
                raise InvalidRunError("Tracker run is missing or already closed")
            return self._decode(row)


class _SessionRecords[T](_Records[T]):
    start_column = "started_at"

    def __init__(self, connection: sqlite3.Connection, run_id: int | None = None) -> None:
        super().__init__(connection)
        self.run_id = run_id

    def _run_start(self, at: int) -> int:
        row = self.connection.execute(
            """SELECT started_at FROM tracker_runs
               WHERE id = ? AND ended_at IS NULL AND started_at <= ?""",
            (self.run_id, at),
        ).fetchone()
        if row is None:
            raise InvalidRunError("Session writes need an open run and a timestamp within that run")
        return row[0]

    def _record_boundary(self, at: int) -> None:
        self.connection.execute(
            "UPDATE tracker_runs SET last_persisted_at = MAX(last_persisted_at, ?) WHERE id = ?",
            (at, self.run_id),
        )

    def _start(self, at: int, **values: Any) -> T:
        with transaction(self.connection):
            self._run_start(at)
            record = self._insert(**values, **{self.start_column: at})
            self._record_boundary(at)
            return record

    def end(self, session_id: int, *, at: int) -> T:
        with transaction(self.connection):
            run_start = self._run_start(at)
            row = self.connection.execute(
                f"""UPDATE {self.table} SET ended_at = ?
                    WHERE id = ? AND ended_at IS NULL AND {self.start_column} >= ?
                    RETURNING *""",
                (at, session_id, run_start),
            ).fetchone()
            if row is None:
                raise RecordNotFound("Session is missing or is not open in this run")
            self._record_boundary(at)
            return self._decode(row)

    def list_open(self) -> list[T]:
        return [
            self._decode(row)
            for row in self.connection.execute(
                f"SELECT * FROM {self.table} WHERE ended_at IS NULL ORDER BY id"
            )
        ]


class ProcessSessionRepository(_SessionRecords[ProcessSession]):
    table = "process_sessions"
    model = ProcessSession
    start_column = "detected_at"

    def start(
        self,
        *,
        pid: int,
        detected_at: int,
        executable_id: int | None = None,
        process_started_at: int | None = None,
    ) -> ProcessSession:
        return self._start(
            detected_at, executable_id=executable_id, pid=pid, process_started_at=process_started_at
        )

    def resolve_executable(
        self,
        session_id: int,
        *,
        executable_id: int,
        expected_pid: int,
        expected_creation_time: int,
        at: int,
    ) -> ProcessSession:
        """Attach metadata only when the previously recorded process identity matches."""
        with transaction(self.connection):
            run_start = self._run_start(at)
            row = self.connection.execute(
                """UPDATE process_sessions SET executable_id = ?
                   WHERE id = ? AND executable_id IS NULL AND ended_at IS NULL
                     AND pid = ? AND process_started_at = ? AND detected_at BETWEEN ? AND ?
                   RETURNING *""",
                (executable_id, session_id, expected_pid, expected_creation_time, run_start, at),
            ).fetchone()
            if row is None:
                raise RecordNotFound("Unresolved process identity does not match")
            self._record_boundary(at)
            return self._decode(row)


class RunningSessionRepository(_SessionRecords[ApplicationRunningSession]):
    table = "application_running_sessions"
    model = ApplicationRunningSession

    def start(self, application_id: int, *, at: int) -> ApplicationRunningSession:
        return self._start(at, application_id=application_id)


class ForegroundSessionRepository(_SessionRecords[ForegroundSession]):
    table = "foreground_sessions"
    model = ForegroundSession

    def start(
        self,
        application_id: int,
        *,
        at: int,
        executable_id: int | None = None,
        hwnd: int | None = None,
        window_title: str | None = None,
    ) -> ForegroundSession:
        with transaction(self.connection):
            application = ApplicationRepository(self.connection).get(application_id)
            if application is None:
                raise RecordNotFound("Foreground application does not exist")
            return self._start(
                at,
                application_id=application_id,
                executable_id=executable_id,
                hwnd=hwnd,
                window_title=window_title if application.track_titles else None,
            )


class SystemStateSessionRepository(_SessionRecords[SystemStateSession]):
    table = "system_state_sessions"
    model = SystemStateSession

    def _decode(self, row: sqlite3.Row) -> SystemStateSession:
        values = dict(row)
        values["state"] = SystemState(values["state"])
        return SystemStateSession(**values)

    def start(self, state: SystemState, *, at: int) -> SystemStateSession:
        return self._start(at, state=SystemState(state).value)


class Repositories:
    """Repositories sharing one connection and, optionally, the current tracker run."""

    def __init__(self, connection: sqlite3.Connection, *, run_id: int | None = None) -> None:
        self.applications = ApplicationRepository(connection)
        self.executables = ExecutableRepository(connection)
        self.runs = TrackerRunRepository(connection)
        self.processes = ProcessSessionRepository(connection, run_id)
        self.running = RunningSessionRepository(connection, run_id)
        self.foreground = ForegroundSessionRepository(connection, run_id)
        self.system_states = SystemStateSessionRepository(connection, run_id)
