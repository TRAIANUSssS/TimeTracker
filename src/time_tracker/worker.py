"""Single owner for collection and writes; the native window only submits signals."""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, replace

from time_tracker.collector import ObservationInterrupted
from time_tracker.diagnostics.performance import count, latency

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Notification:
    kind: str
    observed_at: int
    queued_at: float


class CollectionWorker:
    def __init__(self, controller, *, service=None, completed=lambda: None, capacity=256):
        if capacity < 1:
            raise ValueError("Positive notification capacity required")
        self.controller = controller
        self.service = service
        self.completed = completed
        self.capacity = capacity
        self.ready = threading.Event()
        self.done = threading.Event()
        self.error = None
        self._condition = threading.Condition()
        self._queue = deque()
        self._stopping = False
        self._abort = False
        self._gap = False
        self._sleeping = False
        self._thread = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError("Collection worker already started")
        self._thread = threading.Thread(target=self._run, name="TimeTracker-Collector")
        self._thread.start()

    def notify(self, kind):
        # Only timestamp + bounded enqueue under this lock. Never hold it for I/O.
        with self._condition:
            if self._stopping:
                return
            item = Notification(kind, self.controller.clock.now_ms(), time.monotonic())
            if kind in ("sleep", "wake", "unlock"):
                self._sleeping = kind == "sleep"
            if len(self._queue) == self.capacity:
                self._gap = True
                count("queue.overflow")
            else:
                self._queue.append(item)
                count("queue.enqueued")
            self._condition.notify()

    def request_stop(self, *, abort=False):
        # Stop cannot be lost even if the data queue is full.
        with self._condition:
            self._stopping = True
            self._abort |= abort
            self._condition.notify()

    def join(self):
        if self._thread is not None:
            self._thread.join()

    def checkpoint(self):
        with self._condition:
            if self._queue or self._gap or self._stopping:
                raise ObservationInterrupted()

    def _command_time(self):
        with self._condition:
            if self._queue or self._gap or self._stopping:
                return None
            return self.controller.clock.now_ms()

    def _startup_snapshot(self, snapshot):
        with self._condition:
            if self._queue or self._gap or self._stopping:
                raise ObservationInterrupted()
            # No history precedes this baseline. A suspend notification is a fact
            # that a process/foreground snapshot alone cannot tell us about.
            if self._sleeping and self.controller.power_history is None:
                return replace(snapshot, is_sleeping=True, foreground=None)
            return snapshot

    def _start_controller(self):
        while True:
            with self._condition:
                if self._stopping:
                    return False
                # Notifications before a run starts invalidate the initial snapshot;
                # they cannot describe intervals in a run which does not exist yet.
                count("queue.before_baseline", len(self._queue))
                self._queue.clear()
                self._gap = False
            try:
                self.controller.start()
                return True
            except ObservationInterrupted:
                count("collector.startup_snapshot_discarded")

    def _run(self):
        started = False
        self.controller.checkpoint = self.checkpoint
        self.controller.startup_snapshot_filter = self._startup_snapshot
        try:
            started = self._start_controller()
            if not started:
                return
            if self.service is not None:
                self.service.start()
            self.ready.set()
            while True:
                with self._condition:
                    gap = self._gap
                    item = self._queue.popleft() if self._queue and not gap else None
                    stopping, abort = self._stopping, self._abort
                if abort:
                    self.controller.runtime.abort()
                    started = False
                    break
                if gap:
                    # A fresh snapshot cannot reconstruct lost boundaries. Close the
                    # untrusted tail through existing crash recovery, then reconcile
                    # in a new run; never extend the old state across an unknown gap.
                    logger.error("Notification queue overflow; recovering from an observation gap")
                    self.controller.runtime.abort()
                    started = False
                    if stopping:
                        break
                    started = self._start_controller()
                    count("queue.recovery")
                    if not started:
                        break
                    continue
                if item is not None:
                    latency("queue.wait", time.monotonic() - item.queued_at)
                    logger.info("Windows notification: %s", item.kind)
                    self.controller.notify(item.kind, item.observed_at, defer_resume=True)
                    count("queue.handled")
                    continue
                if stopping:
                    break
                try:
                    if self.service is not None:
                        self.service.check()
                        self.service.commands.drain(event_time=self._command_time)
                    self.controller.tick()
                except ObservationInterrupted:
                    self.controller.observation_interrupted()
                    continue
                with self._condition:
                    if not (self._queue or self._gap or self._stopping):
                        self._condition.wait(timeout=0.25)
            if started:
                self.controller.checkpoint = lambda: None
                self.controller.stop()
                started = False
        except BaseException as error:
            self.error = error
            logger.exception("Collection worker stopped unexpectedly")
            self.controller.runtime.abort()
        finally:
            try:
                if self.service is not None:
                    self.service.stop()
            except BaseException as error:
                self.error = self.error or error
                logger.exception("Local API shutdown failed")
            self.done.set()
            try:
                self.completed()
            except Exception:
                logger.debug("Native window unavailable at worker completion", exc_info=True)
