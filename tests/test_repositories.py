import sqlite3

import pytest

from time_tracker.domain.identity import normalize_executable_path
from time_tracker.domain.models import SystemState
from time_tracker.storage.database import Database
from time_tracker.storage.repositories import InvalidRunError, RecordNotFound, Repositories
from time_tracker.storage.transactions import transaction


def seed(connection: sqlite3.Connection) -> tuple[Repositories, int, int, int]:
    repo = Repositories(connection)
    app = repo.applications.create("Редактор", at=1000)
    exe = repo.executables.create(app.id, "C:/Apps/Editor.exe", at=1000)
    run = repo.runs.start(at=1000, version="test")
    return Repositories(connection, run_id=run.id), app.id, exe.id, run.id


def test_full_session_lifecycle_survives_reopening(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, exe_id, run_id = seed(connection)
        process = repo.processes.start(
            pid=20, process_started_at=50, executable_id=exe_id, detected_at=1000
        )
        running = repo.running.start(app_id, at=1000)
        foreground = repo.foreground.start(
            app_id, at=1000, executable_id=exe_id, hwnd=42, window_title="Файл — Редактор"
        )
        state = repo.system_states.start(SystemState.ACTIVE, at=1000)
        repo.processes.end(process.id, at=1200)
        repo.running.end(running.id, at=1200)
        repo.foreground.end(foreground.id, at=1200)
        repo.system_states.end(state.id, at=1200)
        repo.runs.finish(run_id, at=1200, reason="normal")
    with database.reader() as connection:
        repo = Repositories(connection)
        assert repo.processes.get(process.id).process_started_at == 50
        assert repo.processes.get(process.id).detected_at == 1000
        assert repo.running.get(running.id).ended_at == 1200
        assert repo.foreground.get(foreground.id).window_title == "Файл — Редактор"
        assert repo.system_states.get(state.id).state is SystemState.ACTIVE
        assert repo.runs.get(run_id).recovery_at == 1200
        assert repo.runs.get(run_id).exit_reason == "normal"
        assert repo.runs.get_open() is None
        assert repo.processes.list_open() == []
        assert repo.running.list_open() == []
        assert repo.foreground.list_open() == []
        assert repo.system_states.list_open() == []


def test_session_after_heartbeat_advances_recovery_boundary(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, run_id = seed(connection)
        repo.runs.heartbeat(run_id, at=1100)
        running = repo.running.start(app_id, at=1300)
        run = repo.runs.get(run_id)
        assert run.last_heartbeat_at == 1100
        assert run.last_persisted_at == running.started_at == run.recovery_at == 1300
        repo.runs.heartbeat(run_id, at=1050)
        assert repo.runs.get(run_id).last_heartbeat_at == 1100


def test_failed_session_write_does_not_advance_boundary(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, run_id = seed(connection)
        first = repo.running.start(app_id, at=1100)
        with pytest.raises(sqlite3.IntegrityError):
            repo.running.start(app_id, at=1500)
        assert repo.runs.get(run_id).last_persisted_at == 1100
        assert repo.running.list_open() == [first]


def test_failed_transition_restores_old_session_and_boundary(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, exe_id, run_id = seed(connection)
        previous = repo.foreground.start(app_id, executable_id=exe_id, at=1100)
        other = repo.applications.create("Other", at=1000)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(connection):
                repo.foreground.end(previous.id, at=1200)
                repo.foreground.start(other.id, executable_id=exe_id, at=1200)
        assert repo.foreground.list_open() == [previous]
        assert repo.runs.get(run_id).last_persisted_at == 1100


def test_session_and_boundary_rollback_together(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, run_id = seed(connection)
    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            repo = Repositories(connection, run_id=run_id)
            repo.running.start(app_id, at=1300)
            raise RuntimeError("abort event")
    with database.reader() as connection:
        repo = Repositories(connection)
        assert repo.running.list_open() == []
        assert repo.runs.get(run_id).last_persisted_at == 1000


def test_boundary_write_failure_rolls_back_inserted_session(database: Database) -> None:
    with database.connection() as connection:
        repo, app_id, _, run_id = seed(connection)
        connection.execute(
            """CREATE TEMP TRIGGER fail_boundary BEFORE UPDATE OF last_persisted_at ON tracker_runs
               BEGIN SELECT RAISE(ABORT, 'simulated persistence failure'); END"""
        )
        with pytest.raises(sqlite3.IntegrityError, match="simulated persistence failure"):
            repo.running.start(app_id, at=1300)
    with database.reader() as connection:
        repo = Repositories(connection)
        assert repo.running.list_open() == []
        assert repo.runs.get(run_id).last_persisted_at == 1000


def test_unknown_process_can_only_resolve_with_confirmed_identity(database: Database) -> None:
    with database.transaction() as connection:
        repo, _, exe_id, run_id = seed(connection)
        process = repo.processes.start(pid=42, process_started_at=900, detected_at=1100)
        assert process.executable_id is None
        with pytest.raises(RecordNotFound):
            repo.processes.resolve_executable(
                process.id,
                executable_id=exe_id,
                expected_pid=42,
                expected_creation_time=901,
                at=1200,
            )
        assert repo.runs.get(run_id).last_persisted_at == 1100
        resolved = repo.processes.resolve_executable(
            process.id,
            executable_id=exe_id,
            expected_pid=42,
            expected_creation_time=900,
            at=1200,
        )
        assert resolved.executable_id == exe_id
        assert resolved.detected_at == 1100
        assert repo.running.list_open() == []  # The domain will start running at resolution time.
        assert repo.runs.get(run_id).last_persisted_at == 1200


def test_unknown_creation_time_is_not_inferred_from_pid(database: Database) -> None:
    with database.transaction() as connection:
        repo, _, exe_id, _ = seed(connection)
        process = repo.processes.start(pid=42, detected_at=1100)
        with pytest.raises(RecordNotFound):
            repo.processes.resolve_executable(
                process.id,
                executable_id=exe_id,
                expected_pid=42,
                expected_creation_time=900,
                at=1200,
            )
        assert repo.processes.get(process.id) == process


def test_settings_preserve_history_and_mask_future_titles(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, _ = seed(connection)
        old = repo.foreground.start(app_id, at=1100, window_title="Previous title")
        repo.foreground.end(old.id, at=1200)
        app = repo.applications.update_settings(app_id, at=1200, ignored=True, track_titles=False)
        current = repo.foreground.start(app_id, at=1200, window_title="Must not be persisted")
        assert app.ignored is True and app.track_titles is False
        assert current.window_title is None
        assert repo.foreground.get(old.id).window_title == "Previous title"
        assert len(repo.applications.list_all()) == 1
        with pytest.raises(ValueError):
            repo.applications.update_settings(app_id, at=1300, ignored=1)


@pytest.mark.parametrize(
    "path",
    [
        "c:/apps/EDITOR.exe",
        "C:\\Apps\\Editor.exe",
        "\\\\?\\C:\\Apps\\Editor.exe",
    ],
)
def test_executable_identity_is_normalized(database: Database, path: str) -> None:
    with database.transaction() as connection:
        repo, _, exe_id, _ = seed(connection)
        assert repo.executables.find_by_path(path).id == exe_id
        other = repo.applications.create("Other", at=1000)
        with pytest.raises(sqlite3.IntegrityError):
            repo.executables.create(other.id, path, at=1000)


def test_unc_and_distinct_paths() -> None:
    assert normalize_executable_path("\\\\?\\UNC\\Server\\Apps\\Editor.exe") == (
        "\\\\server\\apps\\editor.exe"
    )
    assert normalize_executable_path("C:/A/editor.exe") != normalize_executable_path(
        "D:/A/editor.exe"
    )


@pytest.mark.parametrize("path", ["", "Editor.exe", "C:Editor.exe", "/Editor.exe", "C:\\"])
def test_missing_and_relative_paths_are_not_executables(path: str) -> None:
    with pytest.raises(ValueError):
        normalize_executable_path(path)


@pytest.mark.parametrize("table", ["processes", "running", "foreground", "system_states"])
def test_negative_session_duration_is_rejected(database: Database, table: str) -> None:
    with database.transaction() as connection:
        repo, app_id, _, run_id = seed(connection)
        sessions = {
            "processes": lambda: repo.processes.start(pid=2, detected_at=1200),
            "running": lambda: repo.running.start(app_id, at=1200),
            "foreground": lambda: repo.foreground.start(app_id, at=1200),
            "system_states": lambda: repo.system_states.start(SystemState.IDLE, at=1200),
        }
        opened = sessions[table]()
        repository = getattr(repo, table)
        with pytest.raises(sqlite3.IntegrityError):
            repository.end(opened.id, at=1100)
        assert repository.get(opened.id).ended_at is None
        assert repo.runs.get(run_id).last_persisted_at == 1200


def test_writes_require_open_run_and_reject_pre_start_time(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, run_id = seed(connection)
        with pytest.raises(InvalidRunError):
            Repositories(connection).running.start(app_id, at=1100)
        with pytest.raises(InvalidRunError):
            repo.running.start(app_id, at=900)
        repo.runs.finish(run_id, at=1000, reason="normal")
        with pytest.raises(InvalidRunError):
            repo.running.start(app_id, at=1100)


def test_finishing_run_requires_closed_sessions(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, run_id = seed(connection)
        repo.running.start(app_id, at=1100)
        with pytest.raises(InvalidRunError, match="Close all"):
            repo.runs.finish(run_id, at=1200, reason="normal")
        assert repo.runs.get_open().id == run_id


def test_duplicate_open_records_are_rejected(database: Database) -> None:
    with database.transaction() as connection:
        repo, app_id, _, _ = seed(connection)
        repo.foreground.start(app_id, at=1000)
        repo.system_states.start(SystemState.ACTIVE, at=1000)
        repo.processes.start(pid=1, process_started_at=50, detected_at=1000)
        for operation in (
            lambda: repo.runs.start(at=1100),
            lambda: repo.foreground.start(app_id, at=1100),
            lambda: repo.system_states.start(SystemState.IDLE, at=1100),
            lambda: repo.processes.start(pid=1, process_started_at=50, detected_at=1100),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                operation()
        repo.processes.start(pid=1, process_started_at=60, detected_at=1100)


def test_alias_schema_blocks_self_links_chains_cycles_and_dangling_ids(database: Database) -> None:
    with database.transaction() as connection:
        apps = Repositories(connection).applications
        a, b, c = (apps.create(name, at=1000).id for name in ("A", "B", "C"))
        connection.execute("INSERT INTO application_aliases VALUES (?, ?, ?)", (b, a, 1000))
        for source, target in ((a, a), (a, b), (c, b), (a, c), (c, 9999)):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO application_aliases VALUES (?, ?, ?)", (source, target, 1000)
                )
        connection.execute("INSERT INTO application_aliases VALUES (?, ?, ?)", (c, a, 1000))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE application_aliases SET canonical_application_id = ? "
                "WHERE application_id = ?",
                (b, c),
            )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO applications(name, ignored, created_at, updated_at) VALUES ('A', 2, 0, 0)",
        "INSERT INTO applications(name, track_titles, created_at, updated_at) "
        "VALUES ('A', -1, 0, 0)",
        "INSERT INTO applications(name, created_at, updated_at) VALUES ('A', 'yesterday', 0)",
        "INSERT INTO system_state_sessions(state, started_at) VALUES ('UNKNOWN', 0)",
        "INSERT INTO process_sessions(executable_id, pid, detected_at) VALUES (9999, 1, 0)",
    ],
)
def test_schema_rejects_invalid_persisted_values(database: Database, statement: str) -> None:
    with database.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement)
