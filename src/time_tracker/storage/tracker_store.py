"""SQLite adapter for the core's transaction port."""

from collections.abc import Iterator
from contextlib import contextmanager

from time_tracker.storage.database import Database
from time_tracker.storage.repositories import Repositories


class SQLiteTrackerStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[Repositories]:
        with self.database.transaction() as connection:
            yield Repositories(connection)
