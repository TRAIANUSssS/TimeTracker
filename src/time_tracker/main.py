"""Development entry point; application services will be wired here later."""

import argparse
import sqlite3
import sys
from pathlib import Path

from time_tracker import __version__
from time_tracker.paths import default_database_path
from time_tracker.platform.instance_lock import AlreadyRunningError, InstanceLock
from time_tracker.storage.database import Database
from time_tracker.storage.migrations import MigrationError


def main() -> int:
    """Initialize storage explicitly; Windows collection will be connected later."""
    parser = argparse.ArgumentParser(
        prog="time-tracker",
        description="TimeTracker storage tools. Windows collection is not implemented yet.",
    )
    parser.add_argument("--version", action="version", version=f"TimeTracker {__version__}")
    parser.add_argument(
        "--init-db", action="store_true", help="create or upgrade the SQLite schema"
    )
    parser.add_argument(
        "--database", type=Path, metavar="PATH", help="database path (used with --init-db)"
    )
    args = parser.parse_args()
    if args.database is not None and not args.init_db:
        parser.error("--database requires --init-db")
    if args.init_db:
        try:
            database = Database(
                args.database if args.database is not None else default_database_path()
            )
            with InstanceLock(database.path):
                version = database.initialize()
        except (OSError, sqlite3.Error, MigrationError, AlreadyRunningError) as error:
            print(f"Database initialization failed: {error}", file=sys.stderr)
            return 1
        print(f"Database ready: {database.path} (schema version {version})")
    else:
        print("Storage and session core are ready. Use --init-db to initialize the database.")
        print("Windows collection and dashboard are not implemented yet.")
    return 0
