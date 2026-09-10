"""Opt-in smoke: actual desktop observation, temporary DB, automatic tray shutdown."""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("TIME_TRACKER_WINDOWS_SMOKE") != "1",
    reason="Set TIME_TRACKER_WINDOWS_SMOKE=1 for a brief live Windows collection test",
)


def test_live_collectors_native_tray_and_icon(tmp_path):
    script = r"""
import sys
import threading
import win32con
import win32gui
from pathlib import Path
from time_tracker.collector import CollectionController
from time_tracker.platform.windows.native import WindowsAPI
from time_tracker.platform.windows.provider import WindowsProvider
from time_tracker.platform.windows.icons import IconCache
from time_tracker.platform.windows.power_history import PowerHistory
from time_tracker.runtime import SystemClock, TrackerRuntime
from time_tracker.storage.database import Database
from time_tracker.tray.tray_app import TrayApplication
clock = SystemClock()
api = WindowsAPI()
database = Database(sys.argv[1])
icons = IconCache(database.path.parent / 'icons')
assert icons.ensure(sys.executable) is not None, 'Python executable icon could not be extracted'
provider = WindowsProvider(api, clock)
runtime = TrackerRuntime(database, provider, clock=clock)
ready = threading.Event()
class Controller(CollectionController):
    def start(self):
        super().start()
        ready.set()
    def tick(self):
        super().tick()
        state = self.runtime.state
        if state.run.last_heartbeat_at > state.run.started_at:
            heartbeat.set()
controller = Controller(runtime, provider, clock,
    power_history=PowerHistory() if api.modern_standby_supported() else None)
app = TrayApplication(controller, api)
heartbeat = threading.Event()
def finish():
    if ready.wait(25):
        # Exit now cancels an in-flight poll: wait for an actual committed heartbeat,
        # rather than assuming that a five-second schedule finishes within six seconds.
        heartbeat.wait(12)
        win32gui.PostMessage(app.hwnd, win32con.WM_CLOSE, 0, 0)
threading.Thread(target=finish, daemon=True).start()
app.run()
with database.reader() as connection:
    run = connection.execute('SELECT * FROM tracker_runs').fetchone()
    assert run['exit_reason'] == 'normal'
    assert run['last_heartbeat_at'] > run['started_at']
    count = connection.execute('SELECT COUNT(*) FROM process_sessions').fetchone()[0]
    assert count > 0
    for table in (
        'process_sessions','foreground_sessions','application_running_sessions','system_state_sessions'
    ):
        query = f'SELECT COUNT(*) FROM {table} WHERE ended_at IS NULL'
        assert connection.execute(query).fetchone()[0] == 0
    assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
print('Live collection, heartbeat, icon, tray and shutdown passed')
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "live.db")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=40,
        env={**os.environ, "PYTHONUTF8": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "shutdown passed" in child.stdout
