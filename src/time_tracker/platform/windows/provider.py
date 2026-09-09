"""Polling adapter that shares process identity across all observation sources."""

import logging

import psutil

from time_tracker.diagnostics.performance import count, measured
from time_tracker.domain.events import ForegroundObservation, TrackerSnapshot
from time_tracker.platform.windows.processes import ProcessCollector

logger = logging.getLogger(__name__)


class WindowsProvider:
    def __init__(self, api, clock, *, icons=None):
        self.api = api
        self.clock = clock
        self.icons = icons
        self._metadata = {}
        self.processes = ProcessCollector(self.metadata)

    @measured("metadata.resolve", detailed=True)
    def metadata(self, path):
        if path not in self._metadata:
            count("metadata.miss", detailed=True)
            if self.icons is not None:
                self.icons.ensure(path)
            try:
                self._metadata[path] = self.api.file_metadata(path)
            except OSError:
                logger.warning("Executable metadata unavailable", exc_info=True)
                self._metadata[path] = (None, None)
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
