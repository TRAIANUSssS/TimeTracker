"""Persisted presentation preferences, shared by the API and collection owner."""

import json
from copy import deepcopy

PALETTE = (
    "#F6A6C1",
    "#8CB6EF",
    "#89DCE2",
    "#A6AFE9",
    "#9DD8C4",
    "#F5D879",
    "#98CD98",
    "#C4AFE9",
    "#A2B6C5",
    "#C5A8C9",
    "#F3B184",
    "#EDA39C",
)
DEFAULT_DISPLAY = {
    "time_units": {"days": True, "hours": True, "minutes": True},
    "personal_day_start": "00:00",
    "timezone": None,
}


def read_settings(connection):
    row = connection.execute("SELECT * FROM preferences WHERE id=1").fetchone()
    return {
        "display": deepcopy(DEFAULT_DISPLAY) | json.loads(row["display"]),
        "tracking_paused": bool(row["tracking_paused"]),
        "onboarding_completed": bool(row["onboarding_completed"]),
    }


def save_display(connection, changes):
    display = read_settings(connection)["display"] | changes
    connection.execute("UPDATE preferences SET display=? WHERE id=1", (json.dumps(display),))
    return display


def save_pause(connection, paused):
    connection.execute("UPDATE preferences SET tracking_paused=? WHERE id=1", (int(paused),))


def save_onboarding(connection, completed):
    connection.execute(
        "UPDATE preferences SET onboarding_completed=? WHERE id=1", (int(completed),)
    )
    return {"completed": bool(completed)}
