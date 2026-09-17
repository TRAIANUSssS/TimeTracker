"""Composition root for the Windows application; storage tools stay platform-neutral."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from time_tracker.storage.database import Database


def run_windows(database_path, *, api_port=6969, process_events=None, started_from_autostart=False):
    if sys.platform != "win32":
        raise RuntimeError("Windows 10/11 is required for activity collection")
    from time_tracker.api.server import ApiServer
    from time_tracker.collection_mode import CollectionMode
    from time_tracker.collector import CollectionController
    from time_tracker.platform.windows.autostart import Autostart
    from time_tracker.platform.windows.event_source import ProcessEventSource
    from time_tracker.platform.windows.icons import IconCache
    from time_tracker.platform.windows.managed_etw import CHANNEL, ManagedEtw
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
    collection_mode = None
    try:
        managed = ManagedEtw()
        collection_mode = CollectionMode(
            database.path, managed, external=process_events is not None
        )
        source = None
        if process_events is not None:
            source = ProcessEventSource(process_events)
        elif collection_mode.active_mode == "etw":
            source = ProcessEventSource(CHANNEL, client_factory=managed.client)
        collection_mode.source = source
        clock = SystemClock()
        api = WindowsAPI()
        provider = WindowsProvider(api, clock, icons=IconCache(database.path.parent / "icons"))
        runtime = TrackerRuntime(database, provider, clock=clock)
        modern = api.modern_standby_supported()
        logger.info(
            "Sleep boundary source: %s", "Kernel-Power" if modern else "Windows notifications"
        )
        controller = CollectionController(
            runtime,
            provider,
            clock,
            power_history=PowerHistory() if modern else None,
            process_events=source,
        )
        TrayApplication(
            controller,
            api,
            service=ApiServer(runtime, port=api_port, collection_mode=collection_mode),
            autostart=Autostart(database.path, api_port),
            notify_on_start=not started_from_autostart,
        ).run()
    except Exception:
        logger.exception("Application stopped with an error")
        raise
    finally:
        if collection_mode is not None:
            collection_mode.close()
        logger.removeHandler(handler)
        handler.close()
