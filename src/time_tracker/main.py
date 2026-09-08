"""Command-line and console-free entry points."""

import argparse
import sqlite3
import sys
from pathlib import Path

from time_tracker import __version__
from time_tracker.paths import default_database_path
from time_tracker.platform.instance_lock import AlreadyRunningError, InstanceLock
from time_tracker.storage.database import Database
from time_tracker.storage.migrations import MigrationError


def main(argv=None) -> int:
    """Explicit storage initialization or Windows tray collection."""
    parser = argparse.ArgumentParser(
        prog="time-tracker",
        description="TimeTracker storage tools and Windows activity collection.",
    )
    parser.add_argument("--version", action="version", version=f"TimeTracker {__version__}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--track", action="store_true", help="start Windows collection in the tray")
    mode.add_argument("--init-db", action="store_true", help="create or upgrade the SQLite schema")
    parser.add_argument(
        "--database", type=Path, metavar="PATH", help="database path (with --init-db or --track)"
    )
    parser.add_argument("--api-port", type=int, help="local API port with --track (default: 8765)")
    args = parser.parse_args(argv)
    if args.database is not None and not (args.init_db or args.track):
        parser.error("--database requires --init-db or --track")
    if args.api_port is not None and (not args.track or not 1 <= args.api_port <= 65535):
        parser.error("--api-port requires --track and a port in 1..65535")
    if args.track:
        from time_tracker.application import run_windows

        try:
            run_windows(
                args.database if args.database is not None else default_database_path(),
                api_port=args.api_port if args.api_port is not None else 8765,
            )
        except Exception as error:
            print(f"Tracking failed: {error}", file=sys.stderr)
            return 1
        return 0
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
        print("Use --track to start Windows collection and the dashboard in the tray.")
        print("Dashboard: http://127.0.0.1:8765/ ; API documentation: /docs.")
    return 0


def tray_main() -> int:
    """GUI entry point for pythonw: show failures even without a console."""
    result = main(["--track", *sys.argv[1:]])
    if result and sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "Не удалось запустить TimeTracker. Проверьте журнал logs/tracker.log рядом с базой."
            " Возможно, другой экземпляр уже работает.",
            "TimeTracker",
            0x10,
        )
    return result
