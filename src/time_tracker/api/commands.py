"""Bounded mailbox: HTTP workers submit, the tracker owner applies and acknowledges."""

import logging
from concurrent.futures import Future, TimeoutError
from dataclasses import asdict
from queue import Empty, Full, Queue
from threading import Lock

from time_tracker.domain.events import ApplicationSettingsChanged
from time_tracker.storage.stats import application_json

logger = logging.getLogger(__name__)


class WriterUnavailable(RuntimeError):
    pass


class SettingsMailbox:
    def __init__(self, runtime, *, timeout=10.0):
        self.runtime = runtime
        self.timeout = timeout
        self._queue = Queue(maxsize=128)
        self._lock = Lock()
        self._closed = False

    def change(self, application_id: int, changes: dict):
        future = Future()
        with self._lock:
            if self._closed:
                raise WriterUnavailable("Tracker is stopping")
            try:
                self._queue.put_nowait((application_id, dict(changes), future))
            except Full as error:
                raise WriterUnavailable("Tracker command queue is full") from error
        try:
            return future.result(timeout=self.timeout)
        except TimeoutError:
            if future.cancel():
                raise WriterUnavailable("Tracker did not accept the command in time") from None
            # Once accepted, report the committed result; never report failure then write later.
            return future.result()

    def drain(self):
        for _ in range(64):
            try:
                app_id, changes, future = self._queue.get_nowait()
            except Empty:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                state = self.runtime.state
                if state is None:
                    raise WriterUnavailable("Tracker is not running")
                at = max(self.runtime.clock.now_ms(), state.last_event_at)
                if not self.runtime.handle(ApplicationSettingsChanged(at, app_id, **changes)):
                    raise WriterUnavailable("Tracker rejected the command")
                future.set_result(application_json(asdict(self.runtime.state.applications[app_id])))
            except Exception as error:
                if not isinstance(error, (LookupError, ValueError, WriterUnavailable)):
                    logger.exception("Application settings command failed")
                future.set_exception(error)

    def close(self):
        with self._lock:
            self._closed = True
            while True:
                try:
                    _, _, future = self._queue.get_nowait()
                except Empty:
                    break
                if future.set_running_or_notify_cancel():
                    future.set_exception(WriterUnavailable("Tracker is stopping"))
