"""Polling adapter that shares process identity across all observation sources."""

import logging
import time

import psutil

from time_tracker.diagnostics.performance import count, measured
from time_tracker.domain.events import ForegroundObservation, TrackerSnapshot
from time_tracker.platform.windows.processes import ProcessCollector

logger = logging.getLogger(__name__)


class WindowsProvider:
    def __init__(self, api, clock, *, icons=None, monotonic=time.monotonic):
        self.api = api
        self.clock = clock
        self.icons = icons
        self._metadata = {}
        self._metadata_retry_at = {}
        self._monotonic = monotonic
        self.processes = ProcessCollector(self.metadata, monotonic=monotonic)

    @measured("metadata.resolve", detailed=True)
    def metadata(self, path):
        if path not in self._metadata or (
            path in self._metadata_retry_at and self._monotonic() >= self._metadata_retry_at[path]
        ):
            count("metadata.miss", detailed=True)
            if self.icons is not None and path not in self._metadata:
                self.icons.ensure(path)
            try:
                description, product = self.api.file_metadata(path)
                previous = self._metadata.get(path, (None, None))
                self._metadata[path] = (description or previous[0], product or previous[1])
            except OSError:
                logger.warning("Executable metadata unavailable", exc_info=True)
                self._metadata.setdefault(path, (None, None))
            if all(self._metadata[path]):
                self._metadata_retry_at.pop(path, None)
            else:
                self._metadata_retry_at[path] = self._monotonic() + 60
        else:
            count("metadata.hit", detailed=True)
        return self._metadata[path]

    @measured("foreground.resolve")
    def foreground(self):
        try:
            window = self.api.foreground()
            if window is None:
                return None
            hwnd, pid, title = window
            process = self.processes.by_pid(pid)
            if process is None:
                return None
            # Resolve metadata can take time; recheck the handle's owner and foreground.
            current = self.api.foreground()
            if current is None or current[:2] != (hwnd, pid):
                return None
            return ForegroundObservation(process, hwnd, current[2])
        except (OSError, psutil.Error):
            logger.warning("Foreground observation unavailable")
            return None

    @measured("provider.snapshot")
    def snapshot(self):
        processes = self.processes.snapshot()
        locked = self.api.is_locked()
        foreground = None if locked else self.foreground()
        idle = self.api.idle_ms()
        at = self.clock.now_ms()
        return TrackerSnapshot(at, processes, foreground, at - idle, is_locked=locked)

    def user_snapshot(self):
        locked = self.api.is_locked()
        idle = self.api.idle_ms()
        at = self.clock.now_ms()
        return TrackerSnapshot(at, (), None, at - idle, is_locked=locked)
