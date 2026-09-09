"""Shared identity resolver for process and foreground observations."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

import psutil

from time_tracker.diagnostics.performance import call, count, measured
from time_tracker.domain.events import ProcessIdentity, ProcessObservation
from time_tracker.domain.identity import normalize_executable_path


@dataclass(frozen=True, slots=True)
class CachedProcess:
    observation: ProcessObservation
    retry_at: float


class ProcessCollector:
    def __init__(
        self,
        metadata: Callable[[str], tuple[str | None, str | None]],
        *,
        monotonic=time.monotonic,
        retry_seconds=60,
    ):
        if retry_seconds <= 0:
            raise ValueError("Process metadata retry interval must be positive")
        self._metadata = metadata
        self._monotonic = monotonic
        self._retry_seconds = retry_seconds
        self._identities: dict[int, ProcessIdentity] = {}
        self._cache: dict[int, CachedProcess] = {}

    def _forget(self, pid):
        self._identities.pop(pid, None)
        self._cache.pop(pid, None)

    @measured("process.observe", detailed=True)
    def observe(self, process) -> ProcessObservation | None:
        """Resolve the current owner of a PID; never trust the supplied object's cached time."""
        pid = process.pid
        try:
            process = call("process.construct", psutil.Process, pid, detailed=True)
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
            cached = self._cache.get(pid)
            # A continuity token is not proof of identity for reusing executable metadata.
            if creation is None or (cached and cached.observation.identity != identity):
                self._cache.pop(pid, None)
                cached = None
            if cached:
                item = cached.observation
                complete = item.executable_path and item.file_description and item.product_name
                if complete or self._monotonic() < cached.retry_at:
                    count("process.cache_hit", detailed=True)
                    self._identities[pid] = identity
                    return item
            count("process.cache_refresh" if cached else "process.cache_miss", detailed=True)
            path = cached.observation.executable_path if cached else None
            if not path:
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
            description, product = self._metadata(path) if path else (None, None)
            if cached and path:
                description = description or cached.observation.file_description
                product = product or cached.observation.product_name
            # New/refreshed data may take time: verify AFTER path and metadata resolution.
            # Cache hits have already had one fresh identity check and do not read new data.
            if creation is not None:
                try:
                    fresh = call("process.construct", psutil.Process, process.pid, detailed=True)
                    if (
                        round(call("process.verify", fresh.create_time, detailed=True) * 1000)
                        != creation
                    ):
                        count("process.reused", detailed=True)
                        self._forget(pid)
                        return None
                except psutil.AccessDenied:
                    path, description, product = None, None, None
            self._identities[pid] = identity
            item = ProcessObservation(identity, path, description, product)
            if creation is not None:
                self._cache[pid] = CachedProcess(item, self._monotonic() + self._retry_seconds)
            return item
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            count("process.disappeared", detailed=True)
            self._forget(pid)
            return None

    def by_pid(self, pid: int) -> ProcessObservation | None:
        try:
            return self.observe(psutil.Process(pid))
        except psutil.NoSuchProcess:
            self._forget(pid)
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
        self._cache = {pid: item for pid, item in self._cache.items() if pid in present}
        count("process.observations", len(observed))
        return tuple(observed)
