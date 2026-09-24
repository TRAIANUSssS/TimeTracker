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
    def __init__(self, runtime, *, timeout=10.0, controller=None, autostart=None):
        self.runtime = runtime
        self.controller = controller
        self.autostart = autostart
        self.timeout = timeout
        self._queue = Queue(maxsize=128)
        self._lock = Lock()
        self._closed = False

    def change(self, application_id: int | str, changes: dict):
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

    def drain(self, *, event_time=None):
        for _ in range(64):
            # Reserve a timestamp before accepting a command. Native lifecycle
            # notifications take precedence; HTTP arrival time is not history time.
            reserved_at = event_time() if event_time is not None else None
            if event_time is not None and reserved_at is None:
                break
            try:
                app_id, changes, future = self._queue.get_nowait()
            except Empty:
                break
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(self._apply(app_id, changes, reserved_at))
            except Exception as error:
                if not isinstance(error, (LookupError, ValueError, WriterUnavailable)):
                    logger.exception("Application settings command failed")
                future.set_exception(error)

    def _apply(self, target, changes, reserved_at):
        from time_tracker.settings import save_display
        from time_tracker.storage.repositories import ApplicationRepository

        if target == "display":
            with self.runtime.database.transaction() as connection:
                return save_display(connection, changes)
        if target == "recording":
            if "autostart" in changes:
                if self.autostart is None:
                    raise WriterUnavailable("Autostart is unavailable")
                self.autostart.set_enabled(changes["autostart"])
            if "tracking_paused" in changes:
                owner = self.controller if self.controller is not None else self.runtime
                from time_tracker.collector import ObservationInterrupted

                try:
                    owner.set_paused(changes["tracking_paused"])
                except ObservationInterrupted as error:
                    raise WriterUnavailable("System state changed; retry the command") from error
            return {
                "tracking_paused": self.runtime.tracking_paused,
                "autostart": self.autostart.enabled() if self.autostart is not None else None,
            }
        state = self.runtime.state
        at = self.runtime.clock.now_ms() if reserved_at is None else reserved_at
        if state is None:
            if not self.runtime.tracking_paused:
                raise WriterUnavailable("Tracker is not running")
            with self.runtime.database.transaction() as connection:
                app = ApplicationRepository(connection).update_settings(target, at=at, **changes)
        else:
            at = max(at, state.last_event_at)
            if not self.runtime.handle(ApplicationSettingsChanged(at, target, **changes)):
                raise WriterUnavailable("Tracker rejected the command")
            app = self.runtime.state.applications[target]
        return application_json(asdict(app))

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
