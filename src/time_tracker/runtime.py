"""Lifecycle coordinator for an injected observation provider; no Windows polling yet."""

from __future__ import annotations

import logging
import time

from time_tracker import __version__
from time_tracker.diagnostics.performance import measured
from time_tracker.domain.events import Heartbeat, TrackerEvent, TrackerStarted, TrackerStopping
from time_tracker.domain.ports import Clock, SnapshotProvider
from time_tracker.domain.session_manager import SessionManager
from time_tracker.domain.tracker_state import TrackerState
from time_tracker.platform.instance_lock import InstanceLock
from time_tracker.storage.database import Database
from time_tracker.storage.tracker_store import SQLiteTrackerStore

logger = logging.getLogger(__name__)


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


class TrackerRuntime:
    def __init__(
        self,
        database: Database,
        provider: SnapshotProvider,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.database = database
        self.provider = provider
        self.clock = clock if clock is not None else SystemClock()
        self._lock = InstanceLock(database.path)
        self._manager: SessionManager | None = None
        self._store = SQLiteTrackerStore(database)
        self.tracking_paused = False

    @property
    def state(self) -> TrackerState | None:
        return self._manager.state if self._manager is not None else None

    @measured("runtime.start")
    def start(self, *, snapshot_filter=None, snapshot=None) -> None:
        if self._manager is not None:
            raise RuntimeError("Runtime is already started")
        self._lock.acquire()
        try:
            self.database.initialize()
            from time_tracker.settings import read_settings

            manager = SessionManager(self._store, version=__version__)
            with self.database.reader() as connection:
                self.tracking_paused = read_settings(connection)["tracking_paused"]
            if self.tracking_paused:
                manager.recover()
                self._manager = manager
                return
            if snapshot is None:
                snapshot = self.provider.snapshot()
            if snapshot_filter is not None:
                snapshot = snapshot_filter(snapshot)
            manager.handle(TrackerStarted(snapshot.observed_at, snapshot))
        except BaseException:
            self._lock.release()
            raise
        self._manager = manager

    @measured("runtime.handle")
    def handle(self, event: TrackerEvent) -> bool:
        if isinstance(event, (TrackerStarted, TrackerStopping)):
            raise ValueError("Use runtime.start() and runtime.stop() for lifecycle commands")
        if self._manager is None:
            raise RuntimeError("Runtime is not started")
        return self._manager.handle(event)

    def set_paused(self, paused: bool, *, snapshot=None):
        if self._manager is None:
            raise RuntimeError("Runtime is not started")
        if paused == self.tracking_paused:
            return
        self._store.pause_transition = paused
        try:
            if paused:
                self._manager.handle(
                    TrackerStopping(max(self.clock.now_ms(), self.state.last_event_at))
                )
            else:
                snapshot = snapshot if snapshot is not None else self.provider.snapshot()
                self._manager.handle(TrackerStarted(snapshot.observed_at, snapshot))
            self.tracking_paused = paused
        finally:
            self._store.pause_transition = None

    def heartbeat(self) -> None:
        state = self.state
        if state is None:
            raise RuntimeError("Runtime is not started")
        self.handle(Heartbeat(max(self.clock.now_ms(), state.last_event_at)))

    @measured("runtime.stop")
    def stop(self, *, at: int | None = None, reason: str = "normal") -> None:
        if self._manager is None:
            return
        state = self.state
        if state is None:
            self._manager = None
            self._lock.release()
            return
        try:
            self._manager.handle(
                TrackerStopping(
                    max(self.clock.now_ms(), state.last_event_at) if at is None else at, reason
                )
            )
        finally:
            # On persistence failure, leave an unfinished run for next startup recovery.
            self._manager = None
            self._lock.release()

    def abort(self) -> None:
        """Release runtime resources without claiming that history was closed normally."""
        if self._manager is not None:
            logger.warning("Runtime aborted; the next startup will recover its open sessions")
        self._manager = None
        self._lock.release()

    def __enter__(self) -> TrackerRuntime:
        self.start()
        return self

    def __exit__(self, exception_type: object, *_: object) -> None:
        if exception_type is None:
            self.stop()
        else:
            self.abort()
