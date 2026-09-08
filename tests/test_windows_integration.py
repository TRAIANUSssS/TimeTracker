"""Native message dispatch with synthetic observations; no desktop activity is recorded."""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows message loop")


def test_native_window_system_messages_and_exit(tmp_path):
    script = r"""
import sys
import threading
import win32con
import win32gui
from time_tracker.collector import CollectionController
from time_tracker.domain.events import (
    TrackerSnapshot, ProcessIdentity, ProcessObservation, ForegroundObservation
)
from time_tracker.platform.windows.native import WindowsAPI
from time_tracker.runtime import TrackerRuntime
from time_tracker.storage.database import Database
from time_tracker.tray.tray_app import TrayApplication, EXIT_COMMAND, WM_TRAY

class Clock:
    at = 1000
    def now_ms(self): return self.at
class Provider:
    def __init__(self, clock):
        self.clock = clock
        self.locked = False
    def snapshot(self):
        process = ProcessObservation(ProcessIdentity(42, 10), 'C:/Apps/editor.exe')
        return TrackerSnapshot(self.clock.at, (process,), ForegroundObservation(process, 1, 'Test'),
                               self.clock.at, is_locked=self.locked)
clock = Clock()
provider = Provider(clock)
database = Database(sys.argv[1])
runtime = TrackerRuntime(database, provider, clock=clock)
ready = threading.Event()
class Controller(CollectionController):
    def start(self):
        super().start()
        ready.set()
    def tick(self): pass
controller = Controller(runtime, provider, clock)
class CheckedAPI(WindowsAPI):
    registered = False
    unregistered = False
    def register_power_notifications(self, hwnd):
        result = super().register_power_notifications(hwnd)
        self.registered = True
        return result
    def unregister_power_notifications(self, handle):
        super().unregister_power_notifications(handle)
        self.unregistered = True
api = CheckedAPI()
app = TrayApplication(controller, api, show_icon=False)
failures = []
def send():
    try:
        assert ready.wait(10), 'Startup timeout'
        provider.locked = True
        clock.at = 2000
        win32gui.SendMessage(app.hwnd, 0x02B1, 7, 0)
        clock.at = 3000
        win32gui.SendMessage(app.hwnd, win32con.WM_POWERBROADCAST, 4, 0)
        clock.at = 10000
        win32gui.SendMessage(app.hwnd, win32con.WM_POWERBROADCAST, 18, 0)
        provider.locked = False
        clock.at = 11000
        win32gui.SendMessage(app.hwnd, 0x02B1, 8, 0)
        clock.at = 12000
        # Exercise the actual Exit branch of the native tray menu without user interaction.
        win32gui.TrackPopupMenu = lambda *args: EXIT_COMMAND
        win32gui.SendMessage(app.hwnd, WM_TRAY, 0, win32con.WM_RBUTTONUP)
    except BaseException as error:
        failures.append(error)
        if app.hwnd:
            win32gui.PostMessage(app.hwnd, win32con.WM_CLOSE, 0, 0)
worker = threading.Thread(target=send, daemon=True)
worker.start()
app.run()
worker.join(5)
assert not worker.is_alive()
assert not failures, failures
assert app.hwnd is None
assert api.registered and api.unregistered
with database.reader() as connection:
    query = 'SELECT state,started_at,ended_at FROM system_state_sessions ORDER BY id'
    states = [tuple(row) for row in connection.execute(query)]
    assert states == [
        ('ACTIVE',1000,2000),('LOCKED',2000,3000),('SLEEP',3000,10000),
        ('LOCKED',10000,11000),('ACTIVE',11000,12000)
    ], states
    run = connection.execute('SELECT ended_at,exit_reason FROM tracker_runs').fetchone()
    assert tuple(run) == (12000,'normal')
print('Native messages and tray Exit passed')
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "native.db")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=25,
        env={**os.environ, "PYTHONUTF8": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "tray Exit passed" in child.stdout


def test_cli_track_refuses_a_database_with_an_existing_owner(tmp_path):
    from time_tracker.platform.instance_lock import InstanceLock

    database_path = tmp_path / "locked.db"
    with InstanceLock(database_path):
        child = subprocess.run(
            [sys.executable, "-m", "time_tracker", "--track", "--database", str(database_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    assert child.returncode == 1
    assert "already using this database" in child.stderr
    assert not database_path.exists()


def test_window_callback_failure_aborts_instead_of_silently_continuing(monkeypatch):
    from types import SimpleNamespace

    import win32con
    import win32gui

    from time_tracker.tray.tray_app import TrayApplication

    aborted = []
    quit_codes = []

    def failed():
        raise OSError("disk unavailable")

    controller = SimpleNamespace(
        tick=failed, runtime=SimpleNamespace(abort=lambda: aborted.append(True))
    )
    app = TrayApplication(controller, None, show_icon=False)
    app._started = True
    monkeypatch.setattr(win32gui, "PostQuitMessage", quit_codes.append)
    app._window_proc(0, win32con.WM_TIMER, 1, 0)
    assert isinstance(app.error, OSError)
    assert aborted == [True]
    assert quit_codes == [1]
    assert not app._started


def test_exit_during_collection_waits_for_current_transaction(monkeypatch):
    from types import SimpleNamespace

    import win32gui

    from time_tracker.tray.tray_app import TrayApplication

    stopped = []
    controller = SimpleNamespace(stop=lambda: stopped.append(True))
    app = TrayApplication(controller, None, show_icon=False)
    app._started = True
    app._busy = True
    monkeypatch.setattr(win32gui, "PostQuitMessage", lambda _: None)
    app._close()
    assert not stopped
    app._busy = False
    app._drain()
    assert stopped == [True]
    assert not app._started


def test_native_tray_services_http_settings_and_closes_api(tmp_path):
    script = r"""
import socket
import sys
import threading
import time
import httpx
import win32con
import win32gui
from time_tracker.api.server import ApiServer
from time_tracker.collector import CollectionController
from time_tracker.domain.events import (
    TrackerSnapshot, ProcessIdentity, ProcessObservation, ForegroundObservation
)
from time_tracker.platform.windows.native import WindowsAPI
from time_tracker.runtime import TrackerRuntime
from time_tracker.storage.database import Database
from time_tracker.tray.tray_app import TrayApplication

class Clock:
    at = 1788854400000
    def now_ms(self): return self.at
class Provider:
    def snapshot(self):
        process = ProcessObservation(ProcessIdentity(42, 10), 'C:/Apps/editor.exe')
        return TrackerSnapshot(clock.at, (process,),
            ForegroundObservation(process, 1, 'Original'), clock.at)
clock = Clock()
provider = Provider()
database = Database(sys.argv[1])
runtime = TrackerRuntime(database, provider, clock=clock)
controller = CollectionController(runtime, provider, clock)
service = ApiServer(runtime, port=0)
tray = TrayApplication(controller, WindowsAPI(), show_icon=False, service=service)
errors = []

def drive():
    try:
        deadline = time.monotonic() + 8
        while not service._server.started:
            if time.monotonic() > deadline: raise TimeoutError('API startup')
            time.sleep(0.01)
        clock.at += 1000
        with httpx.Client(base_url=service.url, timeout=5, trust_env=False) as client:
            assert client.get('/applications').json()[0]['track_titles'] is True
            response = client.patch('/applications/1', json={'track_titles': False})
            assert response.status_code == 200, response.text
            assert response.json()['track_titles'] is False
        clock.at += 1000
    except BaseException as error:
        errors.append(error)
    finally:
        if tray.hwnd:
            win32gui.PostMessage(tray.hwnd, win32con.WM_CLOSE, 0, 0)

driver = threading.Thread(target=drive, daemon=True)
driver.start()
tray.run()
driver.join(2)
assert not driver.is_alive()
assert not errors, errors
with database.reader() as connection:
    titles = [tuple(r) for r in connection.execute(
        'SELECT window_title,started_at,ended_at FROM foreground_sessions ORDER BY id')]
    assert titles == [('Original',1788854400000,1788854401000),
                      (None,1788854401000,1788854402000)], titles
    assert connection.execute('SELECT exit_reason FROM tracker_runs').fetchone()[0] == 'normal'
with socket.socket() as connection:
    assert connection.connect_ex(('127.0.0.1',service.port)) != 0
print('Native tray API passed')
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "native-api.db")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=25,
        env={**os.environ, "PYTHONUTF8": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "Native tray API passed" in child.stdout
