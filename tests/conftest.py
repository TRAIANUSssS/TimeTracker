from pathlib import Path

import pytest

from time_tracker.storage.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "данные трекера" / "tracker.db")
    database.initialize()
    return database
