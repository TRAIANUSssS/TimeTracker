"""Opt-in complete packaged application smoke; all collected data stays in tmp_path."""

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from time_tracker.storage.database import Database


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("TIME_TRACKER_PACKAGED_SMOKE") != "1",
    reason="Set TIME_TRACKER_PACKAGED_SMOKE=1 after building the executable",
)
def test_packaged_tracker_dashboard_collection_and_shutdown(tmp_path):
    import win32con
    import win32gui
    import win32process

    executable = Path(__file__).resolve().parents[1] / "dist/TimeTracker/TimeTracker.exe"
    assert executable.is_file()
    database = Database(tmp_path / "История с пробелами" / "tracker.db")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [str(executable), "--database", str(database.path), "--api-port", str(port)],
        cwd=tmp_path,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    def close_window():
        def visit(hwnd, _):
            if win32process.GetWindowThreadProcessId(hwnd)[
                1
            ] == process.pid and win32gui.GetClassName(hwnd).startswith("TimeTracker."):
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

        win32gui.EnumWindows(visit, None)

    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2
        ) as client:
            deadline = time.monotonic() + 30
            while True:
                assert process.poll() is None, "Packaged application exited during startup"
                try:
                    response = client.get("/")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, "Packaged HTTP server did not start"
                time.sleep(0.2)
            assert '<div id="root">' in response.text
            assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', response.text)
            assert len(assets) >= 2
            for asset in assets:
                assert client.get(asset).status_code == 200
            assert client.get("/settings").status_code == 200
            assert client.get("/favicon.svg").status_code == 200
            # Includes real native polling and heartbeat, without sleep/lock manipulation.
            time.sleep(6)
            apps = client.get("/applications").json()
            assert apps
            reply = client.patch(
                f"/applications/{apps[0]['id']}", json={"track_titles": False}, timeout=15
            )
            assert reply.status_code == 200
            params = {
                "date_from": "2026-03-29",
                "date_to": "2026-03-30",
                "timezone": "Europe/Berlin",
            }
            cells = client.get("/stats/activity", params=params).json()
            assert any(cell["status"] == "missing_hour" for cell in cells)
            frontend = executable.parents[2] / "frontend"
            browser = subprocess.run(
                ["node", "tests/packaged-browser.mjs", f"http://127.0.0.1:{port}"],
                cwd=frontend,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assert browser.returncode == 0, browser.stdout + browser.stderr
        close_window()
        assert process.wait(timeout=15) == 0
        with database.reader() as connection:
            run = connection.execute("SELECT * FROM tracker_runs").fetchone()
            assert run["exit_reason"] == "normal"
            assert run["last_heartbeat_at"] > run["started_at"]
            for table in (
                "process_sessions",
                "application_running_sessions",
                "foreground_sessions",
                "system_state_sessions",
            ):
                assert (
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE ended_at IS NULL"
                    ).fetchone()[0]
                    == 0
                )
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with socket.socket() as connection:
            assert connection.connect_ex(("127.0.0.1", port)) != 0
    finally:
        if process.poll() is None:
            close_window()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
