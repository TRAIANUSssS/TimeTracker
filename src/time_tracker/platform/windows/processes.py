"""Shared identity resolver for process and foreground observations."""

from collections.abc import Callable
from uuid import uuid4

import psutil

from time_tracker.diagnostics.performance import call, count, measured
from time_tracker.domain.events import ProcessIdentity, ProcessObservation
from time_tracker.domain.identity import normalize_executable_path


class ProcessCollector:
    def __init__(self, metadata: Callable[[str], tuple[str | None, str | None]]):
        self._metadata = metadata
        self._identities: dict[int, ProcessIdentity] = {}

    @measured("process.observe", detailed=True)
    def observe(self, process) -> ProcessObservation | None:
        try:
            try:
                creation = round(
                    call("process.creation", process.create_time, detailed=True) * 1000
                )
            except psutil.AccessDenied:
                count("process.creation_denied", detailed=True)
                creation = None
            previous = self._identities.get(process.pid)
            count("process.known_pid" if previous else "process.new_pid", detailed=True)
            if creation is None:
                # Continuity cannot prove a formerly known creation time after access is lost.
                identity = previous if previous and previous.creation_time is None else None
                identity = identity or ProcessIdentity(process.pid, None, uuid4().hex)
            else:
                identity = ProcessIdentity(process.pid, creation)
            try:
                path = call("process.exe", process.exe, detailed=True) or None
            except psutil.AccessDenied:
                count("process.exe_denied", detailed=True)
                path = None
            if path:
                try:
                    path = normalize_executable_path(path)
                except ValueError:
                    path = None
            # A fresh Process is essential: cached psutil identities can survive PID reuse.
            if creation is not None:
                try:
                    fresh = call("process.construct", psutil.Process, process.pid, detailed=True)
                    if (
                        round(call("process.verify", fresh.create_time, detailed=True) * 1000)
                        != creation
                    ):
                        count("process.reused", detailed=True)
                        return None
                except psutil.AccessDenied:
                    path = None
            description, product = self._metadata(path) if path else (None, None)
            self._identities[process.pid] = identity
            return ProcessObservation(identity, path, description, product)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            count("process.disappeared", detailed=True)
            self._identities.pop(process.pid, None)
            return None

    def by_pid(self, pid: int) -> ProcessObservation | None:
        try:
            return self.observe(psutil.Process(pid))
        except psutil.NoSuchProcess:
            self._identities.pop(pid, None)
            return None

    @measured("process.snapshot")
    def snapshot(self) -> tuple[ProcessObservation, ...]:
        # psutil >=6 does not check reuse in process_iter's own cache.
        psutil.process_iter.cache_clear()
        observed = []
        present = set()
        iterator = iter(psutil.process_iter())
        exhausted = object()
        while True:
            process = call("process.enumerate_next", next, iterator, exhausted, detailed=True)
            if process is exhausted:
                break
            item = self.observe(process)
            if item is not None:
                observed.append(item)
                present.add(item.identity.pid)
        self._identities = {
            pid: identity for pid, identity in self._identities.items() if pid in present
        }
        count("process.observations", len(observed))
        return tuple(observed)
