"""Ordered, atomic schema upgrades using SQLite user_version."""

import sqlite3
from dataclasses import dataclass

from time_tracker.storage.schema import INITIAL_SCHEMA
from time_tracker.storage.transactions import transaction


class MigrationError(RuntimeError):
    """The database cannot safely be upgraded by this application version."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (Migration(1, "initial_schema", INITIAL_SCHEMA),)
SCHEMA_VERSION = MIGRATIONS[-1].version
APPLICATION_ID = 0x5454524B  # "TTRK": distinguish tracker files from unrelated SQLite databases.


def schema_version(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def validate_database(connection: sqlite3.Connection, latest: int = SCHEMA_VERSION) -> int:
    """Check ownership/version before changing either schema or journal settings."""
    current = schema_version(connection)
    if current > latest:
        raise MigrationError(f"Database schema {current} is newer than supported {latest}")
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    if application_id not in (0, APPLICATION_ID) or (
        current > 0 and application_id != APPLICATION_ID
    ):
        raise MigrationError("This SQLite database does not belong to TimeTracker")
    if current == 0:
        existing = connection.execute(
            "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        if existing:
            raise MigrationError("Refusing to migrate a nonempty, unversioned database")
    return current


def migrate(connection: sqlite3.Connection, migrations: tuple[Migration, ...] = MIGRATIONS) -> int:
    """Apply all pending DDL and its version stamp in one transaction."""
    if tuple(item.version for item in migrations) != tuple(range(1, len(migrations) + 1)):
        raise MigrationError("Migration versions must be consecutive, starting at 1")
    latest = len(migrations)
    with transaction(connection):
        current = validate_database(connection, latest)
        for migration in migrations[current:]:
            # executescript() can implicitly commit: execute each statement explicitly instead.
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    return latest
