"""Locations for local application data, independent of the working directory."""

import os
import sys
from pathlib import Path


def web_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def tray_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "timetracker.ico"
    return Path(__file__).resolve().parents[2] / "packaging" / "timetracker.ico"


def default_database_path() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    else:
        # Portable storage tests/development; Windows tracking remains the MVP target.
        base = Path.home() / ".local" / "share"
    return base / "TimeTracker" / "tracker.db"
