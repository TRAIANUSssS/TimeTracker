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

    @property
    def state(self) -> TrackerState | None:
        return self._manager.state if self._manager is not None else None

    @measured("runtime.start")
    def start(self, *, snapshot_filter=None) -> None:
        if self._manager is not None:
            raise RuntimeError("Runtime is already started")
        self._lock.acquire()
        try:
            self.database.initialize()
            manager = SessionManager(SQLiteTrackerStore(self.database), version=__version__)
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

    def heartbeat(self) -> None:
        state = self.state
        if state is None:
            raise RuntimeError("Runtime is not started")
        self.handle(Heartbeat(max(self.clock.now_ms(), state.last_event_at)))

    @measured("runtime.stop")
    def stop(self) -> None:
        if self._manager is None:
            return
        state = self.state
        assert state is not None
        try:
            self._manager.handle(TrackerStopping(max(self.clock.now_ms(), state.last_event_at)))
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
