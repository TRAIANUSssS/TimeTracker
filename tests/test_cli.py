import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "time_tracker", *args],
        cwd=tmp_path,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )


def test_cli_initializes_requested_database_and_can_run_twice(tmp_path: Path) -> None:
    path = tmp_path / "новая папка" / "tracker.db"
    for _ in range(2):
        result = run_cli(tmp_path, "--init-db", "--database", str(path))
        assert result.returncode == 0, result.stderr
        assert "schema version 1" in result.stdout
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM tracker_runs").fetchone()[0] == 0
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        connection.close()


def test_cli_default_does_not_create_local_data(tmp_path: Path) -> None:
    result = run_cli(tmp_path)
    assert result.returncode == 0
    assert "--init-db" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_implicit_initialization(tmp_path: Path) -> None:
    path = tmp_path / "not-created.db"
    result = run_cli(tmp_path, "--database", str(path))
    assert result.returncode == 2
    assert not path.exists()


def test_cli_reports_invalid_location_without_traceback(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--init-db", "--database", str(tmp_path))
    assert result.returncode == 1
    assert "initialization failed" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_cannot_combine_tracking_and_initialization(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--track", "--init-db")
    assert result.returncode == 2
    assert list(tmp_path.iterdir()) == []


def test_cli_validates_api_port_without_starting_collection(tmp_path: Path) -> None:
    for args in (
        ("--api-port", "8765"),
        ("--track", "--api-port", "0"),
        ("--track", "--api-port", "65536"),
    ):
        result = run_cli(tmp_path, *args)
        assert result.returncode == 2
        assert "--api-port requires" in result.stderr
    assert list(tmp_path.iterdir()) == []
