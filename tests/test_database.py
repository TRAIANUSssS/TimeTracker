import sqlite3
from pathlib import Path

import pytest

from time_tracker.storage.database import Database
from time_tracker.storage.migrations import (
    APPLICATION_ID,
    MIGRATIONS,
    SCHEMA_VERSION,
    Migration,
    MigrationError,
    migrate,
)
from time_tracker.storage.repositories import Repositories
from time_tracker.storage.transactions import transaction


def test_initialization_is_idempotent_and_keeps_data(database: Database) -> None:
    with database.transaction() as connection:
        app = Repositories(connection).applications.create("Редактор", at=100)
    assert database.initialize() == SCHEMA_VERSION
    with database.reader() as connection:
        assert Repositories(connection).applications.get(app.id) == app
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == {
            "applications",
            "executables",
            "process_sessions",
            "application_running_sessions",
            "foreground_sessions",
            "system_state_sessions",
            "tracker_runs",
            "application_aliases",
        }
        assert connection.execute("SELECT COUNT(*) FROM application_aliases").fetchone()[0] == 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_connection_pragmas_and_read_only_guard(database: Database) -> None:
    for read_only in (False, True):
        with database.connection(read_only=read_only) as connection:
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
            if read_only:
                with pytest.raises(sqlite3.OperationalError, match="readonly"):
                    connection.execute("DELETE FROM applications")


def test_reader_snapshot_survives_concurrent_writer_commit(database: Database) -> None:
    with database.reader() as reader:
        assert reader.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0
        with database.transaction() as writer:
            Repositories(writer).applications.create("Editor", at=100)
        assert reader.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0
    with database.reader() as reader:
        assert reader.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1


def test_outer_rollback_undoes_successful_repository_operations(database: Database) -> None:
    with pytest.raises(RuntimeError, match="cancel"):
        with database.transaction() as connection:
            repo = Repositories(connection)
            app = repo.applications.create("Editor", at=100)
            repo.executables.create(app.id, "C:/Apps/Editor.exe", at=100)
            raise RuntimeError("cancel")
    with database.reader() as connection:
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM executables").fetchone()[0] == 0


def test_savepoint_failure_does_not_rollback_previous_work(database: Database) -> None:
    with database.transaction() as connection:
        apps = Repositories(connection).applications
        first = apps.create("First", at=100)
        with pytest.raises(sqlite3.IntegrityError):
            with transaction(connection):
                apps.create("Rolled back", at=100)
                apps.create("", at=100)
        last = apps.create("Last", at=100)
    with database.reader() as connection:
        assert Repositories(connection).applications.list_all() == [first, last]


def test_failed_migration_rolls_back_ddl_data_and_version(database: Database) -> None:
    failing = Migration(
        SCHEMA_VERSION + 1,
        "broken",
        (
            "CREATE TABLE migration_probe (id INTEGER)",
            "INSERT INTO applications(name, created_at, updated_at) VALUES ('Lost', 0, 0)",
            "INSERT INTO missing_table VALUES (1)",
        ),
    )
    with database.connection() as connection:
        with pytest.raises(sqlite3.OperationalError):
            migrate(connection, (*MIGRATIONS, failing))
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert (
            connection.execute(
                "SELECT name FROM sqlite_schema WHERE name = 'migration_probe'"
            ).fetchone()
            is None
        )
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0


def test_pending_migration_runs_once(database: Database) -> None:
    second = Migration(
        SCHEMA_VERSION + 1, "add_probe", ("CREATE TABLE migration_probe (id INTEGER)",)
    )
    with database.connection() as connection:
        assert migrate(connection, (*MIGRATIONS, second)) == SCHEMA_VERSION + 1
        assert migrate(connection, (*MIGRATIONS, second)) == SCHEMA_VERSION + 1
        with pytest.raises(MigrationError, match="newer"):
            migrate(connection)
    with pytest.raises(MigrationError):
        database.initialize()


def test_missing_read_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        with Database(path).reader():
            pass
    assert not path.exists()


def test_unversioned_database_is_not_adopted(tmp_path: Path) -> None:
    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (content TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('keep')")
    connection.close()
    with pytest.raises(MigrationError, match="unversioned"):
        Database(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT content FROM unrelated").fetchone()[0] == "keep"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    connection.close()


def test_foreign_database_with_same_version_is_not_adopted(tmp_path: Path) -> None:
    path = tmp_path / "foreign.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 1")
    connection.close()
    with pytest.raises(MigrationError, match="does not belong"):
        Database(path).initialize()


def test_initial_migration_failure_leaves_empty_schema(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "broken.db", isolation_level=None)
    try:
        broken = Migration(1, "broken", ("CREATE TABLE partial (id INTEGER)", "INVALID SQL"))
        with pytest.raises(sqlite3.OperationalError):
            migrate(connection, (broken,))
        assert connection.execute("SELECT name FROM sqlite_schema").fetchall() == []
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("PRAGMA application_id").fetchone()[0] == 0
        assert migrate(connection) == SCHEMA_VERSION
    finally:
        connection.close()


def test_upgrade_v1_preserves_existing_foreground_history(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path, isolation_level=None) as con:
        migrate(con, MIGRATIONS[:1])
        con.execute("INSERT INTO applications(name,created_at,updated_at) VALUES ('Editor',0,0)")
        con.execute(
            "INSERT INTO foreground_sessions(application_id,started_at,ended_at) VALUES (1,100,200)"
        )
    database = Database(path)
    database.initialize()
    with database.reader() as con:
        row = con.execute("SELECT * FROM foreground_sessions").fetchone()
        assert (row["started_at"], row["ended_at"], row["process_session_id"]) == (100, 200, None)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
