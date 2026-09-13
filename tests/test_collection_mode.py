import threading

import pytest
from fastapi.testclient import TestClient

from time_tracker.api.app import create_app
from time_tracker.collection_mode import CollectionMode


class Backend:
    def __init__(self, installed=False):
        self.present = installed
        self.error = None
        self.called = threading.Event()
        self.release = threading.Event()

    def installed(self):
        return self.present

    def available(self):
        return True

    def configure(self, action):
        self.called.set()
        assert self.release.wait(3)
        if self.error:
            raise self.error
        self.present = action == "install"


def wait_setup(mode):
    import time

    deadline = time.monotonic() + 3
    while mode.status()["busy"]:
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_preference_applies_on_next_launch_and_keeps_current_run(tmp_path):
    backend = Backend(installed=True)
    mode = CollectionMode(tmp_path / "tracker.db", backend)
    assert mode.status()["mode"] == "polling"
    mode.request("etw")
    assert mode.status()["restart_required"]
    assert mode.active_mode == "polling"
    restarted = CollectionMode(tmp_path / "tracker.db", backend)
    assert restarted.active_mode == "etw"
    assert not restarted.status()["restart_required"]
    restarted.request("polling")
    with pytest.raises(RuntimeError, match="перезапустите"):
        restarted.request("remove")
    assert CollectionMode(tmp_path / "tracker.db", backend).active_mode == "polling"


@pytest.mark.parametrize("cancel", [False, True])
def test_setup_is_async_serialized_and_cancellation_does_not_enable(tmp_path, cancel):
    backend = Backend()
    if cancel:
        backend.error = PermissionError("UAC cancelled")
    mode = CollectionMode(tmp_path / "tracker.db", backend)
    mode.request("install")
    assert backend.called.wait(1)
    assert mode.status()["busy"]
    assert mode.status()["mode"] == "polling"
    with pytest.raises(RuntimeError):
        mode.request("install")
    backend.release.set()
    wait_setup(mode)
    assert mode.status()["mode"] == ("polling" if cancel else "etw")
    assert bool(mode.status()["error"]) == cancel


def test_remove_preserves_history_and_missing_component_falls_back(tmp_path):
    backend = Backend(installed=True)
    backend.release.set()
    database = tmp_path / "tracker.db"
    database.write_bytes(b"history sentinel")
    mode = CollectionMode(database, backend)
    mode.request("remove")
    wait_setup(mode)
    assert database.read_bytes() == b"history sentinel"
    assert mode.status()["mode"] == "polling"
    with pytest.raises(RuntimeError, match="установите"):
        mode.request("etw")


def test_bad_settings_and_external_channel_never_install(tmp_path):
    (tmp_path / "collection-settings.json").write_text("[]")
    backend = Backend()
    mode = CollectionMode(tmp_path / "tracker.db", backend)
    assert mode.active_mode == "polling"
    assert mode.status()["error"]
    external = CollectionMode(tmp_path / "tracker.db", backend, external=True)
    with pytest.raises(RuntimeError):
        external.request("install")
    assert not backend.called.is_set()


def test_save_failure_does_not_change_preference(tmp_path, monkeypatch):
    mode = CollectionMode(tmp_path / "tracker.db", Backend(installed=True))

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr("time_tracker.collection_mode.os.replace", fail)
    with pytest.raises(OSError):
        mode.request("etw")
    assert mode.status()["mode"] == "polling"
    assert not list(tmp_path.glob("*.tmp"))


def test_settings_api_requires_token_and_same_origin(database):
    backend = Backend(installed=True)
    mode = CollectionMode(database.path, backend)
    with TestClient(create_app(database, collection_mode=mode)) as client:
        state = client.get("http://localhost/settings/collection").json()
        url = "http://localhost/settings/collection"
        assert client.post(url, json={"action": "etw"}).status_code == 403
        headers = {"X-TimeTracker-Token": state["token"]}
        assert (
            client.post(
                url, json={"action": "etw"}, headers={**headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.post(url, json={"action": "etw", "path": "bad"}, headers=headers).status_code
            == 422
        )
        response = client.post(url, json={"action": "etw"}, headers=headers)
        assert response.status_code == 202
        assert response.json()["restart_required"]
        mode.close()
        assert client.post(url, json={"action": "polling"}, headers=headers).status_code == 409


def test_missing_task_keeps_requested_mode_but_reports_actual_polling(tmp_path):
    backend = Backend(installed=True)
    mode = CollectionMode(tmp_path / "tracker.db", backend)
    mode.request("etw")
    backend.present = False
    restarted = CollectionMode(tmp_path / "tracker.db", backend)
    assert restarted.status()["mode"] == "etw"
    assert restarted.status()["effective_mode"] == "polling"
    assert not restarted.status()["installed"]
