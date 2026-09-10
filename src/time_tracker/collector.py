"""Serial polling and system notifications, independent of the Windows message pump."""

import logging
import time
from collections import deque
from dataclasses import replace

import psutil

from time_tracker.diagnostics.performance import count, measured
from time_tracker.domain.events import (
    ForegroundChanged,
    Heartbeat,
    IdleObserved,
    ProcessBoundaryRecorded,
    ProcessesObserved,
    ResumeNotified,
    SessionLocked,
    SessionUnlocked,
    SleepPeriodRecorded,
    SystemResumed,
    SystemSleep,
    SystemWake,
)

logger = logging.getLogger(__name__)


class ObservationInterrupted(Exception):
    """A queued lifecycle signal takes precedence over an unfinished observation."""


class CollectionController:
    def __init__(
        self,
        runtime,
        provider,
        clock,
        *,
        monotonic=time.monotonic,
        power_history=None,
        process_events=None,
        shutdown_timeout=20.0,
    ):
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
        self.checkpoint = lambda: None
        self.startup_snapshot_filter = None
        self.process_events = process_events
        self._event_generation = None
        self._event_healthy = False
        self._event_pending = deque()
        if shutdown_timeout <= 0:
            raise ValueError("Positive shutdown timeout required")
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_complete = None
        self.shutdown_at = None
        self.shutdown_events = 0

    def start(self):
        self.shutdown_complete = None
        self.shutdown_at = None
        self.shutdown_events = 0
        self._event_pending.clear()
        self._event_generation = None
        self._event_healthy = False
        if self.process_events is not None:
            self.process_events.start()
        if self.power_history is not None:
            self.power_history.read(
                self.clock.now_ms()
            )  # Fail visibly if System log is inaccessible.
        if self.process_events is None:
            self.runtime.start(snapshot_filter=self.startup_snapshot_filter)
        else:
            # Begin the run before the full process scan; buffered short processes
            # during that scan then belong to a real run and can be recorded later.
            self.runtime.start(
                snapshot_filter=self.startup_snapshot_filter, snapshot=self.provider.user_snapshot()
            )
        self._recorded_power.clear()
        self._pending_resume = None
        self._power_open = self._paused = self._user_resumed = False
        self._next_power = 0
        self._reset_deadlines()
        if self.process_events is not None:
            self._next_process = self._next_fast = 0

    def _process_events(self, *, cutoff=None, deadline=None):
        if self.process_events is None:
            return
        if not self._event_pending:
            generation, coverage, healthy, records = self.process_events.poll()
            if (generation, healthy) != (self._event_generation, self._event_healthy):
                self._next_process = 0
                count("process_events.connected" if healthy else "process_events.fallback")
                logger.info(
                    "Process event source: %s", "connected" if healthy else "polling fallback"
                )
            self._event_generation, self._event_healthy = generation, healthy
            self._event_pending.extend((record, coverage) for record in records)
        while self._event_pending:
            if deadline is not None and time.monotonic() >= deadline:
                return
            record, coverage = self._event_pending[0]
            if cutoff is not None and record["generated_at_ns"] // 1_000_000 > cutoff:
                self._event_pending.popleft()
                continue
            try:
                process = self.provider.event_process(record)
            except (OSError, psutil.Error, ValueError, KeyError):
                self.process_events.invalidate()
                self._event_pending.clear()
                self._event_healthy = False
                self._next_process = 0
                count("process_events.invalid")
                logger.warning("Process event could not be normalized; reverting to polling")
                break
            boundary = record["generated_at_ns"] // 1_000_000
            # Creation is rounded to the domain's ms precision, like psutil snapshots.
            boundary = max(boundary, process.identity.creation_time)
            at = (
                cutoff
                if cutoff is not None
                else max(self.clock.now_ms(), self.runtime.state.last_event_at)
            )
            if cutoff is not None and boundary > cutoff:
                self._event_pending.popleft()
                continue
            if boundary > at or coverage > at:
                self.process_events.invalidate()
                self._event_pending.clear()
                self._event_healthy = False
                self._next_process = 0
                break
            self._handle(
                ProcessBoundaryRecorded(at, process, boundary, record["kind"] == "start", coverage)
            )
            self._event_pending.popleft()
            count("process_events.handled")
            if cutoff is not None:
                self.shutdown_events += 1
                count("process_events.shutdown_handled")

    def _reset_deadlines(self):
        now = self.monotonic()
        self._next_fast = now + 2
        self._next_process = now + 5
        self._next_heartbeat = now + 5

    def notify(self, kind, observed_at=None, *, defer_resume=False):
        if observed_at is not None and observed_at < self.runtime.state.last_event_at:
            count("queue.late_notification")
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
            if defer_resume:
                # A queued wake/unlock is a boundary, not a full process observation.
                # Modern Standby sleep boundaries remain authoritative in the journal.
                if kind != "recheck" and self.power_history is None:
                    self.runtime.handle(ResumeNotified(at, unlocked=kind == "unlock"))
            else:
                self._resume()
        else:
            raise ValueError(f"Unknown system notification: {kind}")

    def _handle(self, event):
        # Timestamp was captured before this check. A notification enqueued afterwards
        # is later than this observation, even if its SQLite commit is still in progress.
        self.checkpoint()
        return self.runtime.handle(event)

    def observation_interrupted(self):
        count("collector.observation_discarded")
        self._next_process = self._next_fast = self._next_heartbeat = 0
        self._user_resumed = False

    def _resume(self):
        self.checkpoint()
        if self.power_history is not None:
            self._sync_power()
            if self._power_open:
                return False
        try:
            if not self._user_resumed and hasattr(self.provider, "user_snapshot"):
                user = self.provider.user_snapshot()
                if self._pending_resume == "unlock" and user.is_locked:
                    return False
                if not self._handle(SystemResumed(user.observed_at, user)):
                    return False
                self._user_resumed = True
            snapshot = self.provider.snapshot()
            self.checkpoint()
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
        if not self._handle(event_type(snapshot.observed_at, snapshot)):
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
        self.checkpoint()
        for start, end in periods:
            if (start, end) not in self._recorded_power:
                at = self.clock.now_ms()
                if end > at:
                    continue
                if not self._handle(SleepPeriodRecorded(at, start, end)):
                    continue
                self._recorded_power.add((start, end))
                latest_sleep_end = max(latest_sleep_end or end, end)
                logger.info("Confirmed Kernel-Power sleep %s..%s (%s ms)", start, end, end - start)
        if self._power_open:
            if not self._paused:
                self._handle(ForegroundChanged(self.clock.now_ms(), None))
            self._paused = True
        return latest_sleep_end

    @measured("collector.tick")
    def tick(self):
        self.checkpoint()
        self._process_events()
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
            self._next_process = now + (60 if self._event_healthy else 5)
            try:
                processes = self.provider.processes.snapshot()
            except (OSError, psutil.Error):
                self._next_process = now + 5
                logger.warning("Process poll failed; retaining the previous process set")
            else:
                self._handle(ProcessesObserved(self.clock.now_ms(), processes))
        if now >= self._next_fast:
            self._next_fast = now + 2
            try:
                locked = self.provider.api.is_locked()
                lock_at = self.clock.now_ms()
                self.checkpoint()
                if locked != self.runtime.state.flags.is_locked:
                    self.notify("lock" if locked else "unlock", lock_at)
                    return
                idle = self.provider.api.idle_ms()
            except OSError:
                # Without a reliable user state, do not claim a fresh heartbeat.
                logger.warning("User state poll failed; stopping collection for recovery")
                raise
            at = self.clock.now_ms()
            self._handle(IdleObserved(at, at - idle))
            if not locked:
                foreground = self.provider.foreground()
                self._handle(ForegroundChanged(self.clock.now_ms(), foreground))
        if now >= self._next_heartbeat:
            self._handle(Heartbeat(self.clock.now_ms()))
            self._next_heartbeat = now + 5

    def stop(self):
        if self.power_history is not None:
            self._sync_power()
        if self.process_events is None:
            self.runtime.stop()
            return
        # Waiting for ETW flush must not extend the user's tracked time.
        self.shutdown_at = max(self.clock.now_ms(), self.runtime.state.last_event_at)
        self.shutdown_complete = False
        deadline = time.monotonic() + self.shutdown_timeout
        self.process_events.begin_finish()
        while time.monotonic() < deadline:
            self._process_events(cutoff=self.shutdown_at, deadline=deadline)
            done, complete, pending = self.process_events.finish_status()
            if done and not pending and not self._event_pending:
                self.shutdown_complete = complete
                break
            if not pending and not self._event_pending:
                time.sleep(0.02)
        reason = "normal" if self.shutdown_complete else "events_incomplete"
        count(
            "process_events.shutdown_complete"
            if self.shutdown_complete
            else "process_events.shutdown_incomplete"
        )
        if not self.shutdown_complete:
            logger.warning("ETW final delivery unconfirmed; closing run as events_incomplete")
        self.runtime.stop(at=self.shutdown_at, reason=reason)

    def close_sources(self):
        if self.process_events is not None:
            self.process_events.close()
