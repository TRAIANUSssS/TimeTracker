"""Serial polling and system notifications, independent of the Windows message pump."""

import logging
import time
from dataclasses import replace

import psutil

from time_tracker.diagnostics.performance import measured
from time_tracker.domain.events import (
    ForegroundChanged,
    Heartbeat,
    IdleObserved,
    ProcessesObserved,
    SessionLocked,
    SessionUnlocked,
    SleepPeriodRecorded,
    SystemResumed,
    SystemSleep,
    SystemWake,
)

logger = logging.getLogger(__name__)


class CollectionController:
    def __init__(self, runtime, provider, clock, *, monotonic=time.monotonic, power_history=None):
        self.runtime = runtime
        self.provider = provider
        self.clock = clock
        self.monotonic = monotonic
        self._next_fast = 0.0
        self._next_process = 0.0
        self._next_heartbeat = 0.0
        self._pending_resume = None
        self.power_history = power_history
        self._recorded_power = set()
        self._power_open = False
        self._paused = False
        self._next_power = 0.0
        self._user_resumed = False

    def start(self):
        if self.power_history is not None:
            self.power_history.read(
                self.clock.now_ms()
            )  # Fail visibly if System log is inaccessible.
        self.runtime.start()
        self._reset_deadlines()

    def _reset_deadlines(self):
        now = self.monotonic()
        self._next_fast = now + 2
        self._next_process = now + 5
        self._next_heartbeat = now + 5

    def notify(self, kind, observed_at=None):
        at = max(
            self.clock.now_ms() if observed_at is None else observed_at,
            self.runtime.state.last_event_at,
        )
        if kind == "sleep":
            self._pending_resume = None
            self._user_resumed = False
            if self.power_history is not None:
                self._paused = True
                self.runtime.handle(ForegroundChanged(at, None))
                return
            self.runtime.handle(SystemSleep(at))
        elif kind == "lock":
            # Lock can arrive while a wake snapshot is still failing. Keep retrying wake:
            # clearing it here would leave the core in SLEEP indefinitely.
            if not self.runtime.state.flags.is_sleeping and not self._paused:
                self._pending_resume = None
            self.runtime.handle(SessionLocked(at))
        elif kind in ("wake", "unlock", "recheck"):
            self._pending_resume = kind
            self._user_resumed = False
            self._resume()
        else:
            raise ValueError(f"Unknown system notification: {kind}")

    def _resume(self):
        if self.power_history is not None:
            self._sync_power()
            if self._power_open:
                return False
        try:
            if not self._user_resumed and hasattr(self.provider, "user_snapshot"):
                user = self.provider.user_snapshot()
                if self._pending_resume == "unlock" and user.is_locked:
                    return False
                if not self.runtime.handle(SystemResumed(user.observed_at, user)):
                    return False
                self._user_resumed = True
            snapshot = self.provider.snapshot()
        except (OSError, psutil.Error):
            logger.warning("Fresh system snapshot unavailable; retrying before collection resumes")
            return False
        # A notification can precede the WTS query's state update. Retry unlock until confirmed.
        if self._pending_resume == "unlock" and snapshot.is_locked:
            return False
        if snapshot.observed_at < self.runtime.state.last_event_at:
            return False
        if self.power_history is not None:
            latest_sleep_end = self._sync_power()
            if self._power_open:
                return False
            if latest_sleep_end is not None and latest_sleep_end > snapshot.observed_at:
                # A whole sleep/wake cycle occurred after this observation was captured.
                # Retry instead of assigning a new timestamp to an obsolete foreground.
                self._user_resumed = False
                return False
            # Synchronization may have advanced the event watermark after the slow snapshot.
            snapshot = replace(snapshot, observed_at=self.clock.now_ms())
        event_type = SessionUnlocked if self._pending_resume == "unlock" else SystemWake
        if not self.runtime.handle(event_type(snapshot.observed_at, snapshot)):
            return False
        self._pending_resume = None
        self._paused = False
        self._reset_deadlines()
        return True

    def _sync_power(self) -> int | None:
        if self.clock.now_ms() < self.runtime.state.last_event_at:
            return None
        latest_sleep_end = None
        periods, self._power_open = self.power_history.read(self.runtime.state.run.started_at)
        for start, end in periods:
            if (start, end) not in self._recorded_power:
                at = self.clock.now_ms()
                if end > at:
                    continue
                if not self.runtime.handle(SleepPeriodRecorded(at, start, end)):
                    continue
                self._recorded_power.add((start, end))
                latest_sleep_end = max(latest_sleep_end or end, end)
                logger.info("Confirmed Kernel-Power sleep %s..%s (%s ms)", start, end, end - start)
        if self._power_open:
            if not self._paused:
                self.runtime.handle(ForegroundChanged(self.clock.now_ms(), None))
            self._paused = True
        return latest_sleep_end

    @measured("collector.tick")
    def tick(self):
        if self.power_history is not None and self.monotonic() >= self._next_power:
            self._next_power = self.monotonic() + 2
            self._sync_power()
            if self._paused and not self._power_open and self._recorded_power:
                self._pending_resume = self._pending_resume or "wake"
        if self._pending_resume:
            self._resume()
            return
        if self._paused:
            return
        if self.runtime.state.flags.is_sleeping:
            return
        now = self.monotonic()
        # Capture timestamps after reading each source; slow metadata must not backdate input.
        at = self.clock.now_ms()
        if at < self.runtime.state.last_event_at:
            return
        if now >= self._next_process:
            self._next_process = now + 5
            try:
                processes = self.provider.processes.snapshot()
            except (OSError, psutil.Error):
                logger.warning("Process poll failed; retaining the previous process set")
            else:
                self.runtime.handle(ProcessesObserved(self.clock.now_ms(), processes))
        if now >= self._next_fast:
            self._next_fast = now + 2
            try:
                locked = self.provider.api.is_locked()
                if locked != self.runtime.state.flags.is_locked:
                    self.notify("lock" if locked else "unlock")
                    return
                idle = self.provider.api.idle_ms()
            except OSError:
                # Without a reliable user state, do not claim a fresh heartbeat.
                logger.warning("User state poll failed; stopping collection for recovery")
                raise
            at = self.clock.now_ms()
            self.runtime.handle(IdleObserved(at, at - idle))
            if not locked:
                foreground = self.provider.foreground()
                self.runtime.handle(ForegroundChanged(self.clock.now_ms(), foreground))
        if now >= self._next_heartbeat:
            self.runtime.handle(Heartbeat(self.clock.now_ms()))
            self._next_heartbeat = now + 5

    def stop(self):
        if self.power_history is not None:
            self._sync_power()
        self.runtime.stop()
