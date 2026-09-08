from datetime import date, datetime

import pytest

from time_tracker.domain.time_windows import TimeSelection, timestamp
from time_tracker.storage.stats import Statistics

BASE = timestamp(datetime.fromisoformat("2026-09-08T00:00:00+00:00"))
MINUTE = 60000


def at(minute):
    return BASE + minute * MINUTE


def seed(connection, *, states=(), foreground=(), running=(), ignored=()):
    for app_id in (1, 2, 3):
        connection.execute(
            "INSERT INTO applications(id,name,ignored,created_at,updated_at) VALUES(?,?,?,?,?)",
            (app_id, f"App {app_id}", app_id in ignored, BASE, BASE),
        )
    connection.execute(
        "INSERT INTO tracker_runs(started_at,last_heartbeat_at,last_persisted_at,ended_at,"
        "exit_reason) VALUES(?,?,?,?,?)",
        (BASE, at(3000), at(3000), at(3000), "normal"),
    )
    for state, start, end in states:
        connection.execute(
            "INSERT INTO system_state_sessions(state,started_at,ended_at) VALUES(?,?,?)",
            (state, at(start), at(end) if end is not None else None),
        )
    for app_id, start, end in foreground:
        connection.execute(
            "INSERT INTO foreground_sessions(application_id,window_title,started_at,ended_at) "
            "VALUES(?,?,?,?)",
            (app_id, f"Title {app_id}", at(start), at(end) if end is not None else None),
        )
    for app_id, start, end in running:
        connection.execute(
            "INSERT INTO application_running_sessions(application_id,started_at,ended_at) "
            "VALUES(?,?,?)",
            (app_id, at(start), at(end) if end is not None else None),
        )


def chosen(start="00:00", end="24:00", *, days=1):
    return TimeSelection(date(2026, 9, 8), date(2026, 9, 7 + days), start, end, "UTC")


def test_triple_intersection_sleep_gaps_ignored_and_sorting(database):
    with database.transaction() as c:
        seed(
            c,
            states=[
                ("ACTIVE", 0, 20),
                ("IDLE", 20, 40),
                ("SLEEP", 40, 60),
                ("LOCKED", 60, 70),
                ("ACTIVE", 80, 100),
            ],
            foreground=[(1, 0, 10), (2, 10, 40), (3, 80, 100)],
            running=[(1, 0, 20), (2, 0, 100), (3, 0, 100)],
            ignored=[3],
        )
    with database.reader() as c:
        stats = Statistics(c, chosen("00:05", "01:30"), at(100))
        active = stats.apps()
        assert [r["application_id"] for r in active["items"]] == [2, 1]
        assert [(r["active_ms"] // MINUTE, r["running_ms"] // MINUTE) for r in active["items"]] == [
            (10, 55),
            (5, 15),
        ]
        assert active["has_tracking_data"] and active["has_running_data"]
        assert stats.system() == {
            "active_ms": 25 * MINUTE,
            "idle_ms": 20 * MINUTE,
            "locked_ms": 10 * MINUTE,
            "sleep_ms": 20 * MINUTE,
        }
        # Foreground and ACTIVE intersect each other, but outside the selected window.
        assert Statistics(c, chosen("00:25", "00:35"), at(100)).apps()["items"] == []
        assert Statistics(c, chosen("00:45", "00:55"), at(100)).apps(False) == {
            "has_tracking_data": True,
            "has_running_data": False,
            "items": [],
        }
        assert Statistics(c, chosen("01:10", "01:20"), at(100)).apps(False) == {
            "has_tracking_data": False,
            "has_running_data": False,
            "items": [],
        }


def test_active_only_off_includes_background_and_orders_by_running(database):
    with database.transaction() as c:
        seed(
            c,
            states=[("ACTIVE", 0, 60)],
            foreground=[(1, 0, 30), (2, 30, 40)],
            running=[(1, 0, 30), (2, 0, 50), (3, 0, 60)],
        )
    with database.reader() as c:
        stats = Statistics(c, chosen(), at(60))
        assert [r["application_id"] for r in stats.apps()["items"]] == [1, 2]
        assert [r["application_id"] for r in stats.apps(False)["items"]] == [3, 2, 1]


def test_timeline_gaps_unknown_ignored_system_states_and_future(database):
    with database.transaction() as c:
        seed(
            c,
            states=[
                ("ACTIVE", 5, 25),
                ("IDLE", 25, 30),
                ("LOCKED", 30, 35),
                ("SLEEP", 35, 40),
                ("ACTIVE", 45, None),
            ],
            foreground=[(1, 5, 10), (3, 10, 15), (2, 45, None)],
            ignored=[3],
        )
    with database.reader() as c:
        segments = Statistics(c, chosen("00:00", "01:00"), at(50)).timeline()
    assert [
        (s["type"], (s["started_at"] - BASE) // MINUTE, (s["ended_at"] - BASE) // MINUTE)
        for s in segments
    ] == [
        ("no_data", 0, 5),
        ("application", 5, 10),
        ("other_activity", 10, 15),
        ("unknown_activity", 15, 25),
        ("idle", 25, 30),
        ("locked", 30, 35),
        ("sleep", 35, 40),
        ("no_data", 40, 45),
        ("application", 45, 50),
    ]
    assert set(segments[2]) == {"type", "started_at", "ended_at"}
    assert segments[1]["title"] == "Title 1"


def test_open_sessions_use_one_now_and_filter_boundary(database):
    with database.transaction() as c:
        seed(c, states=[("ACTIVE", 0, None)], foreground=[(1, 0, None)], running=[(1, 0, None)])
    with database.reader() as c:
        stats = Statistics(c, chosen("00:30", "01:00"), at(45))
        assert stats.apps()["items"][0]["active_ms"] == 15 * MINUTE
        assert stats.apps()["items"][0]["running_ms"] == 15 * MINUTE
        assert stats.system()["active_ms"] == 15 * MINUTE
        assert stats.timeline()[-1]["ended_at"] == at(45)


def test_context_switches_use_transition_state_previous_app_and_half_open_filter(database):
    with database.transaction() as c:
        seed(
            c,
            states=[("ACTIVE", 0, 20), ("IDLE", 20, 40), ("ACTIVE", 40, 70)],
            foreground=[
                (1, 0, 5),
                (3, 5, 10),
                (1, 10, 15),
                (2, 15, 20),
                (1, 20, 30),
                (2, 30, 45),
                (1, 45, 50),
                (1, 50, 55),
                (2, 55, 65),
            ],
            ignored=[3],
        )
    with database.reader() as c:
        assert Statistics(c, chosen(), at(70)).context_switches() == {"context_switches": 3}
        assert Statistics(c, chosen("00:15", "00:55"), at(70)).context_switches() == {
            "context_switches": 2
        }
        assert Statistics(c, chosen("00:40", "00:45"), at(70)).context_switches() == {
            "context_switches": 0
        }


def test_daily_windows_do_not_fill_overnight_gaps(database):
    with database.transaction() as c:
        seed(c, states=[("ACTIVE", 0, 2880)], foreground=[(1, 0, 2880)], running=[(1, 0, 2880)])
    with database.reader() as c:
        stats = Statistics(c, chosen("08:00", "18:00", days=2), at(2880))
        assert stats.system()["active_ms"] == 20 * 60 * MINUTE
        assert stats.apps()["items"][0]["running_ms"] == 20 * 60 * MINUTE


def test_heatmap_partial_hour_coverage_zero_activity_and_future(database):
    with database.transaction() as c:
        seed(c, states=[("ACTIVE", 8 * 60 + 30, 8 * 60 + 45), ("IDLE", 9 * 60, 10 * 60)])
    with database.reader() as c:
        cells = Statistics(c, chosen("08:30", "11:00", days=2), at(10 * 60 + 30)).activity()
    assert cells[0]["intensity"] == 0.5
    assert cells[0]["window_ms"] == 30 * MINUTE
    assert cells[0]["tracked_ms"] == 15 * MINUTE
    assert cells[1]["status"] == "data" and cells[1]["intensity"] == 0
    assert cells[2]["status"] == "no_data"
    assert all(c["status"] == "future" for c in cells[3:])


def test_heatmap_repeated_hour_and_weighted_weekday_average(database):
    # Berlin Sunday 02:00 occurs twice on Oct 25. Other selected Sundays occur once.
    day = datetime.fromisoformat("2026-10-25T00:00:00+00:00")
    start = timestamp(day)
    with database.transaction() as c:
        c.execute(
            "INSERT INTO system_state_sessions(state,started_at,ended_at) VALUES('ACTIVE',?,?)",
            (start, start + 90 * MINUTE),
        )
    with database.reader() as c:
        short = TimeSelection(
            date(2026, 10, 24), date(2026, 10, 25), "02:00", "03:00", "Europe/Berlin"
        )
        cells = Statistics(c, short, start + 86400000).activity()
        assert cells[-1]["hour_occurrences"] == 2
        assert cells[-1]["intensity"] == 0.75
        long = TimeSelection(
            date(2026, 10, 11), date(2026, 10, 25), "02:00", "03:00", "Europe/Berlin"
        )
        sunday = next(
            x for x in Statistics(c, long, start + 86400000).activity() if x["weekday"] == 7
        )
        assert sunday["sample_days"] == 3
        assert sunday["average_active_ms"] == 30 * MINUTE
        assert sunday["intensity"] == pytest.approx(90 / 240)
        assert sunday["repeated_hour_days"] == 1


def test_heatmap_missing_hour_excluded_from_samples_and_night_anchor(database):
    with database.reader() as c:
        sel = TimeSelection(date(2026, 3, 15), date(2026, 3, 29), "02:00", "03:00", "Europe/Berlin")
        sunday = next(x for x in Statistics(c, sel, at(0)).activity() if x["weekday"] == 7)
        assert sunday["sample_days"] == 2
        assert sunday["missing_hour_days"] == 1
        night = chosen("22:00", "03:00", days=2)
        cells = Statistics(c, night, at(4000)).activity()
        assert [(x["hour"], x["day_offset"]) for x in cells[:5]] == [
            (22, 0),
            (23, 0),
            (0, 1),
            (1, 1),
            (2, 1),
        ]
        assert cells[-1]["date"] == "2026-09-09"
        assert cells[-1]["local_date"] == "2026-09-10"


def test_midnight_is_continuous_and_does_not_add_timeline_duration(database):
    with database.transaction() as c:
        seed(c, states=[("ACTIVE", 1320, 1620)], foreground=[(1, 1320, 1620)])
    with database.reader() as c:
        timeline = Statistics(c, chosen("22:00", "03:00"), at(2000)).timeline()
    assert len(timeline) == 1
    assert timeline[0]["ended_at"] - timeline[0]["started_at"] == 5 * 60 * MINUTE


def test_context_does_not_bridge_tracker_runs_or_count_zero_length_session(database):
    with database.transaction() as c:
        seed(
            c,
            states=[("ACTIVE", 0, 60)],
            foreground=[(1, 0, 10), (2, 15, 15), (1, 20, 25), (2, 40, 50)],
        )
        c.execute(
            "UPDATE tracker_runs SET last_heartbeat_at=?,last_persisted_at=?,ended_at=?",
            (at(30), at(30), at(30)),
        )
        c.execute(
            "INSERT INTO tracker_runs(started_at,last_heartbeat_at,last_persisted_at) "
            "VALUES(?,?,?)",
            (at(40), at(40), at(40)),
        )
    with database.reader() as c:
        assert Statistics(c, chosen(), at(60)).context_switches()["context_switches"] == 0
        assert (
            Statistics(c, chosen("00:20", "00:25"), at(60)).context_switches()["context_switches"]
            == 0
        )


def test_read_snapshot_does_not_mix_settings_updates(database):
    with database.transaction() as c:
        seed(c, states=[("ACTIVE", 0, 60)], foreground=[(1, 0, 60)], running=[(1, 0, 60)])
    with database.reader() as c:
        # Establish this reader's WAL snapshot before the concurrent writer commits.
        c.execute("SELECT ignored FROM applications").fetchall()
        with database.transaction() as writer:
            writer.execute("UPDATE applications SET ignored=1 WHERE id=1")
        assert len(Statistics(c, chosen(), at(60)).apps()["items"]) == 1
    with database.reader() as c:
        assert Statistics(c, chosen(), at(60)).apps()["items"] == []
