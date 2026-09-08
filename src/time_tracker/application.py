"""Composition root for the Windows application; storage tools stay platform-neutral."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from time_tracker.storage.database import Database


def run_windows(database_path):
    if sys.platform != "win32":
        raise RuntimeError("Windows 10/11 is required for activity collection")
    from time_tracker.collector import CollectionController
    from time_tracker.platform.windows.icons import IconCache
    from time_tracker.platform.windows.native import WindowsAPI
    from time_tracker.platform.windows.power_history import PowerHistory
    from time_tracker.platform.windows.provider import WindowsProvider
    from time_tracker.runtime import SystemClock, TrackerRuntime
    from time_tracker.tray.tray_app import TrayApplication

    database = Database(database_path)
    log_directory = database.path.parent / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_directory / "tracker.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("time_tracker")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        clock = SystemClock()
        api = WindowsAPI()
        provider = WindowsProvider(api, clock, icons=IconCache(database.path.parent / "icons"))
        runtime = TrackerRuntime(database, provider, clock=clock)
        modern = api.modern_standby_supported()
        logger.info(
            "Sleep boundary source: %s", "Kernel-Power" if modern else "Windows notifications"
        )
        controller = CollectionController(
            runtime, provider, clock, power_history=PowerHistory() if modern else None
        )
        TrayApplication(controller, api).run()
    except Exception:
        logger.exception("Application stopped with an error")
        raise
    finally:
        logger.removeHandler(handler)
        handler.close()
