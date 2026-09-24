from datetime import date, datetime

import pytest
from tests.test_api import BASE, PARAMS, Clock, Provider, request_with_writer
from tests.test_api import api as api_fixture

from time_tracker.domain.intervals import duration
from time_tracker.domain.time_windows import TimeSelection, timestamp
from time_tracker.runtime import TrackerRuntime
from time_tracker.settings import read_settings

api = api_fixture


def change(api, path, values):
    client, _, mailbox, _, _ = api
    return request_with_writer(mailbox, lambda: client.patch(path, json=values))


def test_pause_closes_intervals_and_keeps_gap_after_fresh_resume(api):
    client, runtime, _, clock, provider = api
    clock.at += 60_000
    assert change(api, "/settings/recording", {"tracking_paused": True}).status_code == 200
    assert runtime.state is None
    clock.at += 10 * 60_000
    assert client.get("/stats/system", params=PARAMS).json()["active_ms"] == 60_000
    assert client.get("/settings/preferences").json()["recording"]["tracking_paused"]
    assert (
        change(api, "/applications/1", {"track_titles": False, "color": "#F6A6C1"}).status_code
        == 200
    )
    assert change(api, "/settings/recording", {"tracking_paused": False}).status_code == 200
    assert runtime.state.foreground.session.window_title is None
    clock.at += 60_000
    assert client.get("/stats/system", params=PARAMS).json()["active_ms"] == 120_000
    segments = client.get("/stats/timeline", params=PARAMS).json()
    assert any(
        s["type"] == "no_data"
        and s["started_at"] == BASE + 60_000
        and s["ended_at"] == BASE + 660_000
        for s in segments
    )
    assert segments[-1]["color"] == "#F6A6C1"


def test_pause_survives_restart_without_starting_sessions(database):
    clock = Clock()
    provider = Provider(clock)
    with TrackerRuntime(database, provider, clock=clock) as runtime:
        clock.at += 1000
        runtime.set_paused(True)
    clock.at += 100_000
    with TrackerRuntime(database, provider, clock=clock) as runtime:
        assert runtime.state is None
        assert runtime.tracking_paused
        with database.reader() as connection:
            assert connection.execute("SELECT count(*) FROM tracker_runs").fetchone()[0] == 1
            assert (
                connection.execute(
                    "SELECT count(*) FROM process_sessions WHERE ended_at IS NULL"
                ).fetchone()[0]
                == 0
            )
        runtime.set_paused(False)
        assert runtime.state.run.started_at == clock.at


def test_failed_pause_rolls_back_history_and_preference(database, monkeypatch):
    clock = Clock()
    with TrackerRuntime(database, Provider(clock), clock=clock) as runtime:
        clock.at += 1000

        def fail(*args):
            raise OSError("disk failure")

        monkeypatch.setattr("time_tracker.settings.save_pause", fail)
        with pytest.raises(OSError):
            runtime.set_paused(True)
        assert runtime.state is not None
        assert not runtime.tracking_paused
        with database.reader() as connection:
            assert not read_settings(connection)["tracking_paused"]
            assert connection.execute("SELECT ended_at FROM tracker_runs").fetchone()[0] is None


def test_color_palette_validation_and_auto(api):
    client, _, _, _, _ = api
    assert change(api, "/applications/1", {"color": "#f6a6c1"}).json()["color"] == "#F6A6C1"
    assert client.patch("/applications/1", json={"color": "#00FF00"}).status_code == 422
    assert change(api, "/applications/1", {"color": None}).json()["color"] is None
    assert client.get("/applications").json()[0]["color"] is None


def test_display_validation_and_persisted_personal_day(api):
    client, _, _, clock, _ = api
    assert (
        client.patch(
            "/settings/display",
            json={"time_units": {"days": False, "hours": False, "minutes": False}},
        ).status_code
        == 422
    )
    for invalid in ("24:00", "02:70", "2:00"):
        assert (
            client.patch("/settings/display", json={"personal_day_start": invalid}).status_code
            == 422
        )
    assert client.patch("/settings/display", json={"timezone": "unknown"}).status_code == 422
    assert (
        change(
            api, "/settings/display", {"personal_day_start": "02:00", "timezone": "UTC"}
        ).status_code
        == 200
    )
    clock.at = timestamp(datetime.fromisoformat("2026-09-09T03:00:00+00:00"))
    result = client.get("/stats/timeline", params=PARAMS)
    assert result.status_code == 200
    assert result.json()[0]["started_at"] == timestamp(
        datetime.fromisoformat("2026-09-08T02:00:00+00:00")
    )
    assert result.json()[-1]["ended_at"] == timestamp(
        datetime.fromisoformat("2026-09-09T02:00:00+00:00")
    )
    partial = client.get(
        "/stats/timeline", params=PARAMS | {"time_from": "00:00", "time_to": "01:00"}
    )
    assert partial.json()[0]["started_at"] == timestamp(
        datetime.fromisoformat("2026-09-09T00:00:00+00:00")
    )


@pytest.mark.parametrize(("day", "hours"), [(date(2026, 3, 28), 23), (date(2026, 10, 24), 25)])
def test_personal_day_handles_dst_and_partial_hours(day, hours):
    selection = TimeSelection(day, day, "03:30", "03:30", "Europe/Berlin", "03:30", True)
    assert duration(selection.windows()) == hours * 3_600_000
    assert selection.cells()[0].minute_from == 210
    assert selection.cells()[-1].minute_to == 210
    assert selection.cells()[-1].day_offset == 1


def test_autostart_reads_real_state_and_reports_failure(api):
    client, _, mailbox, _, _ = api

    class Autostart:
        value = False

        def enabled(self):
            return self.value

        def set_enabled(self, value):
            if not value:
                raise OSError("registry denied")
            self.value = value

    mailbox.autostart = Autostart()
    assert change(api, "/settings/recording", {"autostart": True}).json()["autostart"]
    assert change(api, "/settings/recording", {"autostart": False}).status_code == 503
    assert client.get("/settings/preferences").json()["recording"]["autostart"]
