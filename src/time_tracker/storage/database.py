"""File-backed SQLite connections, migrations and transaction boundaries."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from time_tracker.storage.migrations import (
    SCHEMA_VERSION,
    MigrationError,
    migrate,
    validate_database,
)
from time_tracker.storage.transactions import transaction


class Database:
    """Connection factory; connections remain confined to the calling thread."""

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout = timeout

    @contextmanager
    def _connection(self, mode: str) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode={mode}",
            uri=True,
            timeout=self.timeout,
            isolation_level=None,
            autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            if mode == "ro":
                connection.execute("PRAGMA query_only = ON")
            yield connection
        finally:
            connection.close()

    def initialize(self) -> int:
        """Create/upgrade the schema, without starting a run or performing recovery."""
        if sqlite3.sqlite_version_info < (3, 37, 0):
            raise MigrationError("SQLite 3.37 or newer is required for STRICT tables")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection("rwc") as connection:
            validate_database(connection)
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise MigrationError("This database location does not support WAL")
            connection.execute("PRAGMA synchronous = FULL")
            return migrate(connection)

    @contextmanager
    def connection(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        """Open an initialized database; this never creates a missing file."""
        with self._connection("ro" if read_only else "rw") as connection:
            if validate_database(connection) != SCHEMA_VERSION:
                raise MigrationError(
                    "Unsupported schema; initialize with the matching version first"
                )
            if not read_only:
                connection.execute("PRAGMA synchronous = FULL")
            yield connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection, transaction(connection):
            yield connection

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        """A read-only snapshot for a complete statistics request."""
        with self.connection(read_only=True) as connection:
            connection.execute("BEGIN")
            try:
                yield connection
            finally:
                connection.rollback()
