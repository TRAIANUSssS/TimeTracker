"""Ordinary-user pipe reader; never touches the tracker or SQLite from its thread."""

import logging
import threading
import time
from collections import deque

import pywintypes

from time_tracker.platform.windows.event_pipe import EventPipeClient
from time_tracker.platform.windows.event_stream import EventStream

logger = logging.getLogger(__name__)


class ProcessEventSource:
    def __init__(self, channel="default", *, capacity=4096, client_factory=EventPipeClient):
        if capacity < 1:
            raise ValueError("Positive event queue capacity required")
        self.channel = channel
        self.capacity = capacity
        self.client_factory = client_factory
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._queue = deque()
        self._generation = None
        self._coverage = 0
        self._healthy = False
        self._invalid = False
        self._last_packet = 0.0
        self._finishing = threading.Event()
        self._active = False
        self._finish_done = False
        self._complete = False
        self._collector_pid = None
        self._generations = 0
        self._faults = 0
        self._peak_pending = 0
        self._received = 0
        self.finish_requested = False
        self.connected = threading.Event()
        self.finished = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="TimeTracker-ProcessEvents", daemon=True
        )
        self._thread.start()

    def invalidate(self):
        with self._lock:
            if not self._invalid:
                self._faults += 1
            self._healthy = False
            self._invalid = True
            self._queue.clear()

    def status(self):
        """Read-only bounded telemetry; contains no executable paths or window titles."""
        with self._lock:
            return {
                "generation": self._generation,
                "collector_pid": self._collector_pid,
                "generations": self._generations,
                "healthy": self._healthy and time.monotonic() - self._last_packet < 5,
                "invalid": self._invalid,
                "faults": self._faults,
                "pending": len(self._queue),
                "peak_pending": self._peak_pending,
                "received": self._received,
            }

    def poll(self, limit=64):
        with self._lock:
            healthy = self._healthy and time.monotonic() - self._last_packet < 5
            return (
                self._generation,
                self._coverage,
                healthy,
                tuple(self._queue.popleft() for _ in range(min(limit, len(self._queue)))),
            )

    def begin_finish(self):
        """Freeze the generation and ask the reader to finish its owned stream."""
        with self._lock:
            self._finishing.set()
            if not self._active:
                self._finish_done = True
                if self._generation is None:
                    self._complete = True  # no ETW coverage: ordinary polling run

    def finish_status(self):
        with self._lock:
            return self._finish_done, self._complete and not self._invalid, len(self._queue)

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                if self._finishing.is_set():
                    return
                self._active = True
            try:
                with self.client_factory(self.channel, control=True) as client:
                    stream = EventStream()
                    last_packet = time.monotonic()
                    can_finish = sent_finish = False
                    while not self._stop.is_set():
                        if self._finishing.is_set() and stream.stream_id and not sent_finish:
                            if not can_finish:
                                raise RuntimeError("Collector does not support finish control")
                            client.request_finish(stream.stream_id)
                            sent_finish = True
                        try:
                            message = client.receive(500)
                        except TimeoutError:
                            if client.handle is None or (
                                not self._finishing.is_set() and time.monotonic() - last_packet >= 5
                            ):
                                raise
                            continue
                        records = stream.accept(message)
                        last_packet = time.monotonic()
                        with self._lock:
                            if message["type"] == "ready":
                                self._collector_pid = message.get("collector_pid")
                                self._generations += 1
                                self._generation = stream.stream_id
                                self._coverage = message["started_at_ns"] // 1_000_000
                                self._queue.clear()
                                self._invalid = False
                                self._complete = False
                                self.finish_requested = False
                                self.finished.clear()
                                can_finish = "finish" in message.get("capabilities", [])
                            self._last_packet = last_packet
                            if stream.gap or len(self._queue) + len(records) > self.capacity:
                                if not self._invalid:
                                    self._faults += 1
                                self._invalid = True
                                self._queue.clear()
                            if not self._invalid:
                                self._queue.extend(records)
                            self._received += len(records)
                            self._peak_pending = max(self._peak_pending, len(self._queue))
                            self._healthy = stream.healthy and not self._invalid
                            if self._healthy:
                                self.connected.set()
                            if stream.stopped:
                                self._complete = stream.complete and not self._invalid
                                self.finish_requested = message.get("finish_requested") is True
                                self.finished.set()
                        if stream.stopped:
                            break
            except (OSError, pywintypes.error, ValueError, RuntimeError, KeyError, TypeError):
                logger.debug("Process event source unavailable", exc_info=True)
            finally:
                with self._lock:
                    self._healthy = False
                    self._active = False
                    if self._finishing.is_set():
                        self._finish_done = True
                        if self._generation is None:
                            self._complete = True
            self._finishing.wait(5)

    def close(self):
        self._stop.set()
        self._finishing.set()
        if self._thread is not None:
            self._thread.join(2)
            if self._thread.is_alive():
                raise RuntimeError("Process event reader did not stop")
