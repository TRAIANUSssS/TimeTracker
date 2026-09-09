"""External CPU accounting and isolated-history validation."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("psutil")

from time_tracker.storage.database import Database

spec = importlib.util.spec_from_file_location(
    "benchmark_tracker", Path(__file__).resolve().parents[1] / "tools/benchmark_tracker.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_cpu_is_time_weighted_and_normalized_by_logical_cpus():
    result = runner.summarize(
        [
            {"elapsed_seconds": 0, "cpu_seconds": 0, "state": "ACTIVE"},
            {"elapsed_seconds": 1, "cpu_seconds": 1, "state": "ACTIVE"},
            {"elapsed_seconds": 4, "cpu_seconds": 2, "state": "IDLE"},
            {"elapsed_seconds": 6, "cpu_seconds": 2, "state": "IDLE"},
        ],
        4,
    )
    assert result["ALL"]["cpu_percent_mean"] == pytest.approx(100 * 2 / 6 / 4)
    assert result["ALL"]["cpu_seconds_per_minute"] == 20
    assert result["ACTIVE"]["cpu_percent_mean"] == 25
    assert result["TRANSITION"]["elapsed_seconds"] == 3
    assert result["IDLE"]["cpu_percent_mean"] == 0


def test_external_observer_rejects_reused_pid_before_reading_counters(monkeypatch):
    monkeypatch.setattr(runner.psutil, "Process", lambda _: SimpleNamespace(create_time=lambda: 2))
    with pytest.raises(RuntimeError, match="reused"):
        runner.read_process(42, 1)


def test_history_validation_uses_process_detected_time(tmp_path):
    database = Database(tmp_path / "history.db")
    database.initialize()
    result = runner.verify_history(database.path)
    assert result["integrity"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert set(result["negative_intervals"]) == {
        "process_sessions",
        "application_running_sessions",
        "foreground_sessions",
        "system_state_sessions",
    }
    assert not any(result["negative_intervals"].values())
    assert not any(result["open_sessions"].values())


def test_observer_does_not_create_missing_database(tmp_path):
    import sqlite3

    path = tmp_path / "absent.db"
    with pytest.raises(sqlite3.OperationalError):
        runner.open_history(path)
    assert not path.exists()
