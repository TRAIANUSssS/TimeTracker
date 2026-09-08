import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from time_tracker.api.app import create_app
from time_tracker.platform.windows.autostart import Autostart, startup_command


def test_dashboard_routes_and_assets_are_same_origin(database, tmp_path, monkeypatch):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text('<html lang="ru"><div id="root"></div></html>')
    (web / "assets/app.js").write_text("console.log('dashboard');")
    (web / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    monkeypatch.setattr("time_tracker.api.app.web_directory", lambda: web)
    with TestClient(create_app(database), base_url="http://127.0.0.1") as client:
        for route in ("/", "/advanced", "/settings"):
            response = client.get(route)
            assert response.status_code == 200
            assert 'id="root"' in response.text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg+xml")
        assert client.get("/not-a-page").status_code == 404
        assert client.get("/assets/../../pyproject.toml").status_code == 404


def test_missing_frontend_does_not_break_statistics(database, tmp_path, monkeypatch):
    monkeypatch.setattr("time_tracker.api.app.web_directory", lambda: tmp_path / "missing")
    with TestClient(create_app(database), base_url="http://127.0.0.1") as client:
        assert client.get("/").status_code == 503
        assert client.get("/applications").json() == []


def test_timeline_exposes_full_dst_axis_even_without_history(database):
    with TestClient(create_app(database), base_url="http://127.0.0.1") as client:
        response = client.get(
            "/stats/timeline",
            params={
                "date_from": "2026-10-25",
                "date_to": "2026-10-25",
                "time_from": "02:15",
                "time_to": "02:45",
                "timezone": "Europe/Berlin",
            },
        )
        import json

        windows = json.loads(response.headers["X-TimeTracker-Windows"])
        assert len(windows) == 2
        assert sum(end - start for start, end in windows) == 3600000


@pytest.mark.skipif(sys.platform != "win32", reason="Windows current-user registry")
def test_autostart_enable_disable_in_isolated_registry_key(tmp_path):
    import winreg

    path = rf"Software\TimeTrackerTest-{uuid4().hex}"
    setting = Autostart(tmp_path / "тест.db", 8766, key=path)
    try:
        assert not setting.enabled()
        setting.set_enabled(True)
        assert setting.enabled()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            command, kind = winreg.QueryValueEx(key, "TimeTracker")
        assert kind == winreg.REG_SZ
        assert "pythonw.exe" in command and "--api-port 8766" in command
        setting.set_enabled(False)
        setting.set_enabled(False)
        assert not setting.enabled()
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def test_frozen_autostart_quotes_paths_and_retains_database(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\My Apps\TimeTracker\TimeTracker.exe")
    command = startup_command(Path(r"C:\My Data\tracker.db"), 8765)
    assert command.startswith('"C:\\My Apps\\TimeTracker\\TimeTracker.exe" --track')
    assert "--database" in command and "--api-port 8765" in command
    monkeypatch.setattr(sys, "executable", "C:\\" + "a" * 270 + "\\TimeTracker.exe")
    with pytest.raises(ValueError, match="260"):
        startup_command(Path("tracker.db"), 8765)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows tray")
def test_tray_dashboard_and_autostart_are_reversible(monkeypatch):
    from types import SimpleNamespace

    from time_tracker.tray.tray_app import TrayApplication

    opened = []
    values = []
    setting = SimpleNamespace(
        enabled=lambda: bool(values and values[-1]), set_enabled=values.append
    )
    monkeypatch.setattr(
        "time_tracker.tray.tray_app.webbrowser.open", lambda url, new: opened.append(url)
    )
    tray = TrayApplication(
        None, None, service=SimpleNamespace(url="http://127.0.0.1:8766"), autostart=setting
    )
    tray._open_dashboard()
    tray._toggle_autostart()
    tray._toggle_autostart()
    assert opened == ["http://127.0.0.1:8766"]
    assert values == [True, False]
    # No native run loop was started; release the optional owned icon.
    if tray._owns_icon:
        import win32gui

        win32gui.DestroyIcon(tray._icon)
