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


MIGRATIONS = (
    Migration(1, "initial_schema", INITIAL_SCHEMA),
    Migration(
        2,
        "process_event_boundaries",
        (
            "ALTER TABLE foreground_sessions ADD COLUMN process_session_id INTEGER "
            "REFERENCES process_sessions(id)",
            "CREATE INDEX idx_foreground_process ON foreground_sessions(process_session_id)",
            "CREATE INDEX idx_process_identity_history "
            "ON process_sessions(pid, process_started_at, detected_at)",
        ),
    ),
    Migration(
        3,
        "settings",
        (
            "ALTER TABLE applications ADD COLUMN color TEXT",
            "CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), "
            "display TEXT NOT NULL DEFAULT '{}', tracking_paused INTEGER NOT NULL DEFAULT 0 "
            "CHECK(tracking_paused IN (0,1))) STRICT",
            "INSERT INTO preferences(id) VALUES(1)",
        ),
    ),
    Migration(
        4,
        "onboarding",
        (
            "ALTER TABLE preferences ADD COLUMN onboarding_completed INTEGER NOT NULL "
            "DEFAULT 1 CHECK(onboarding_completed IN (0,1))",
        ),
    ),
    Migration(
        5,
        "process_catalog",
        (
            "ALTER TABLE applications ADD COLUMN category TEXT NOT NULL DEFAULT 'unknown' "
            "CHECK(category IN ('system','user','unknown'))",
            "ALTER TABLE applications ADD COLUMN catalog_version INTEGER NOT NULL DEFAULT 0 "
            "CHECK(catalog_version >= 0)",
        ),
    ),
)
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
        initial_version = current
        for migration in migrations[current:]:
            # executescript() can implicitly commit: execute each statement explicitly instead.
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        # Existing installations must not be interrupted after an upgrade. Only a
        # database created all the way to the onboarding schema in this call is new.
        if initial_version == 0 and latest >= 4:
            connection.execute("UPDATE preferences SET onboarding_completed=0 WHERE id=1")
    return latest
