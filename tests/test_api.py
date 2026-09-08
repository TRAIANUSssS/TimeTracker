import hashlib
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from time_tracker.api.app import create_app
from time_tracker.api.commands import SettingsMailbox, WriterUnavailable
from time_tracker.api.server import ApiServer
from time_tracker.domain.events import (
    ForegroundChanged,
    ForegroundObservation,
    ProcessIdentity,
    ProcessObservation,
    TrackerSnapshot,
)
from time_tracker.domain.time_windows import timestamp
from time_tracker.runtime import TrackerRuntime

BASE = timestamp(datetime.fromisoformat("2026-09-08T08:00:00+00:00"))
PARAMS = {"date_from": "2026-09-08", "date_to": "2026-09-08", "timezone": "UTC"}


@dataclass
class Clock:
    at: int = BASE

    def now_ms(self):
        return self.at


class Provider:
    def __init__(self, clock):
        self.clock = clock
        self.process = ProcessObservation(ProcessIdentity(42, BASE - 100), "C:/Apps/editor.exe")

    def snapshot(self):
        return TrackerSnapshot(
            self.clock.at,
            (self.process,),
            ForegroundObservation(self.process, 1, "Original title"),
            self.clock.at,
        )


@pytest.fixture
def api(database):
    clock = Clock()
    provider = Provider(clock)
    with TrackerRuntime(database, provider, clock=clock) as runtime:
        mailbox = SettingsMailbox(runtime)
        app = create_app(database, commands=mailbox, clock=clock)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            yield client, runtime, mailbox, clock, provider
        mailbox.close()


def request_with_writer(mailbox, callback):
    with ThreadPoolExecutor(max_workers=1) as executor:
        response = executor.submit(callback)
        deadline = time.monotonic() + 5
        while not response.done() and time.monotonic() < deadline:
            mailbox.drain()
            time.sleep(0.005)
        return response.result(timeout=1)


def test_http_stats_contracts_and_open_session_now(api):
    client, runtime, mailbox, clock, provider = api
    clock.at += 15 * 60000
    response = client.get("/stats/apps", params=PARAMS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "has_tracking_data": True,
        "has_running_data": True,
        "items": [
            {
                "application_id": 1,
                "name": "editor",
                "active_ms": 900000,
                "running_ms": 900000,
                "icon_url": "/applications/1/icon",
            }
        ],
    }
    assert client.get("/stats/system", params=PARAMS).json() == {
        "active_ms": 900000,
        "idle_ms": 0,
        "locked_ms": 0,
        "sleep_ms": 0,
    }
    assert client.get("/stats/context-switches", params=PARAMS).json() == {"context_switches": 0}
    timeline = client.get("/stats/timeline", params=PARAMS).json()
    assert timeline[-1]["type"] == "application"
    assert timeline[-1]["ended_at"] == clock.at
    assert set(timeline[0]) == {"type", "started_at", "ended_at"}
    for end in ("2026-09-09", "2026-09-30"):
        response = client.get("/stats/activity", params=PARAMS | {"date_to": end})
        assert response.status_code == 200, response.text
        assert ("weekday" in response.json()[0]) == (end == "2026-09-30")
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"date_from": "2026-09-10"},
        {"date_from": "09-08-2026"},
        {"date_from": "2026-02-30"},
        {"date_from": "1788854400"},
        {"timezone": "Not/AZone"},
        {"timezone": "../UTC"},
        {"time_from": "24:00"},
        {"time_to": "24:01"},
        {"time_to": "00:00"},
        {"time_from": "8:00"},
        {"time_from": "08:00:00"},
        {"active_only": "perhaps"},
    ],
)
def test_bad_filters_are_422(api, changes):
    response = api[0].get("/stats/apps", params=PARAMS | changes)
    assert response.status_code == 422, response.text


def test_visualization_range_validation(api):
    client = api[0]
    assert (
        client.get("/stats/timeline", params=PARAMS | {"date_to": "2026-09-09"}).status_code == 422
    )
    assert client.get("/stats/activity", params=PARAMS).status_code == 422
    assert client.get("/stats/apps", params={"timezone": "UTC"}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "new"},
        {"ignored": 1},
        {"ignored": "true"},
        {"ignored": None},
        {"track_titles": []},
        {"ignored": True, "track_titles": None},
    ],
)
def test_patch_strict_validation(api, body):
    assert api[0].patch("/applications/1", json=body).status_code == 422
    assert not api[1].state.applications[1].ignored


def test_patch_acknowledges_commit_updates_history_stats_and_title_policy(api):
    client, runtime, mailbox, clock, provider = api
    clock.at += 60000
    response = request_with_writer(
        mailbox,
        lambda: client.patch("/applications/1", json={"ignored": True, "track_titles": False}),
    )
    assert response.status_code == 200, response.text
    assert response.json()["ignored"] is True
    assert runtime.state.applications[1].ignored is True
    assert runtime.state.foreground.session.window_title is None
    assert runtime.state.run.last_persisted_at == clock.at
    clock.at += 60000
    runtime.handle(
        ForegroundChanged(clock.at, ForegroundObservation(provider.process, 1, "Hidden change"))
    )
    with runtime.database.reader() as c:
        rows = c.execute(
            "SELECT window_title,started_at,ended_at FROM foreground_sessions ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("Original title", BASE, BASE + 60000),
            (None, BASE + 60000, None),
        ]
    assert client.get("/stats/apps", params=PARAMS).json() == {
        "has_tracking_data": True,
        "has_running_data": False,
        "items": [],
    }
    assert client.get("/stats/system", params=PARAMS).json()["active_ms"] == 120000
    timeline = client.get("/stats/timeline", params=PARAMS).json()
    assert timeline[-1]["type"] == "other_activity"
    assert "title" not in timeline[-1] and "name" not in timeline[-1]
    response = request_with_writer(
        mailbox, lambda: client.patch("/applications/1", json={"ignored": False})
    )
    assert response.json()["track_titles"] is False
    assert client.get("/stats/apps", params=PARAMS).json()["items"][0]["active_ms"] == 120000


def test_patch_not_found_and_storage_failure_rollback(api):
    client, runtime, mailbox, clock, provider = api
    response = request_with_writer(
        mailbox, lambda: client.patch("/applications/99", json={"ignored": True})
    )
    assert response.status_code == 404
    with runtime.database.transaction() as c:
        c.execute(
            "CREATE TRIGGER fail_settings BEFORE UPDATE ON applications "
            "BEGIN SELECT RAISE(ABORT,'test'); END"
        )
    clock.at += 1000
    response = request_with_writer(
        mailbox, lambda: client.patch("/applications/1", json={"track_titles": False})
    )
    assert response.status_code == 503
    assert runtime.state.applications[1].track_titles is True
    assert runtime.state.foreground.session.window_title == "Original title"
    assert client.get("/applications").json()[0]["track_titles"] is True


def test_cancelled_or_closed_mailbox_never_applies_later(api):
    client, runtime, mailbox, clock, provider = api
    mailbox.timeout = 0.01
    response = client.patch("/applications/1", json={"ignored": True})
    assert response.status_code == 503
    mailbox.drain()
    assert runtime.state.applications[1].ignored is False
    mailbox.close()
    assert client.patch("/applications/1", json={"ignored": True}).status_code == 503


def test_icon_reads_cache_and_handles_missing_without_extraction(api):
    client, runtime, *_ = api
    assert client.get("/applications/1/icon").status_code == 404
    with runtime.database.reader() as c:
        path = c.execute("SELECT path FROM executables").fetchone()[0]
    cache = runtime.database.path.parent / "icons"
    cache.mkdir()
    icon = cache / f"{hashlib.sha256(path.encode()).hexdigest()}.png"
    # Endpoint serves cache bytes; Windows extraction is tested separately.
    icon.write_bytes(b"\x89PNG\r\n\x1a\nexample")
    response = client.get("/applications/1/icon")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == icon.read_bytes()
    assert client.get("/applications/999/icon").status_code == 404


def test_local_host_and_same_origin_only(api):
    client = api[0]
    assert client.get("/applications", headers={"host": "attacker.example"}).status_code == 400
    assert (
        client.patch(
            "/applications/1",
            json={"ignored": True},
            headers={"origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert client.get("/applications", headers={"origin": "http://127.0.0.1"}).status_code == 200


def test_api_read_uses_single_clock_read(database):
    class CountingClock:
        calls = 0

        def now_ms(self):
            self.calls += 1
            return BASE

    clock = CountingClock()
    with TestClient(create_app(database, clock=clock), base_url="http://127.0.0.1") as client:
        assert client.get("/stats/apps", params=PARAMS).status_code == 200
        assert clock.calls == 1
        assert client.patch("/applications/1", json={"ignored": True}).status_code == 503


def test_real_loopback_server_reads_writes_and_releases_port(api):
    _, runtime, _, clock, _ = api
    service = ApiServer(runtime, port=0)
    service.start()
    port = service.port
    try:
        with httpx.Client(base_url=service.url, trust_env=False, timeout=5) as client:
            assert client.get("/applications").status_code == 200
            response = request_with_writer(
                service.commands, lambda: client.patch("/applications/1", json={"ignored": True})
            )
            assert response.status_code == 200
        assert runtime.state.applications[1].ignored is True
    finally:
        service.stop()
    with socket.socket() as connection:
        assert connection.connect_ex(("127.0.0.1", port)) != 0
    with pytest.raises(WriterUnavailable):
        service.commands.change(1, {"ignored": False})


def test_occupied_port_fails_without_touching_writer(api):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        service = ApiServer(api[1], port=occupied.getsockname()[1])
        with pytest.raises(OSError):
            service.start()
        assert api[1].state is not None


def test_server_shutdown_rejects_pending_patch_without_late_write(api):
    runtime = api[1]
    service = ApiServer(runtime, port=0)
    service.start()
    try:
        with httpx.Client(base_url=service.url, trust_env=False, timeout=5) as client:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(client.patch, "/applications/1", json={"ignored": True})
                deadline = time.monotonic() + 3
                while service.commands._queue.empty() and time.monotonic() < deadline:
                    time.sleep(0.005)
                service.stop()
                assert future.result(timeout=1).status_code == 503
        assert runtime.state.applications[1].ignored is False
        with runtime.database.reader() as c:
            assert c.execute("SELECT ignored FROM applications WHERE id=1").fetchone()[0] == 0
    finally:
        service.stop()
