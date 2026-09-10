"""Opt-in bounded timing aggregates. No event payloads or executable paths are recorded."""

from __future__ import annotations

import atexit
import json
import logging
import math
import os
import platform
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from time_tracker import __version__

_active = None
logger = logging.getLogger(__name__)


def environment():
    """Non-sensitive environment information, collected once outside measured stages."""
    import psutil

    result = {
        "version": __version__,
        "python": platform.python_version(),
        "psutil": psutil.__version__,
        "windows": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count() or 1,
        "pid": os.getpid(),
        "build": "frozen" if getattr(sys, "frozen", False) else "python",
        "commit": None,
        "dirty": None,
    }
    if not getattr(sys, "frozen", False):
        root = Path(__file__).resolve().parents[3]
        try:
            options = {
                "cwd": root,
                "capture_output": True,
                "text": True,
                "timeout": 3,
                "check": True,
            }
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            result["commit"] = subprocess.run(
                ["git", "rev-parse", "HEAD"], **options
            ).stdout.strip()
            result["dirty"] = bool(
                subprocess.run(["git", "status", "--porcelain"], **options).stdout.strip()
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return result


class Aggregate:
    def __init__(self, capacity):
        self.count = 0
        self.errors = 0
        self.total = [0, 0, 0, 0]
        self.maximum = [0, 0, 0, 0]
        self.samples = deque(maxlen=capacity)

    def add(self, values, failed):
        self.count += 1
        self.errors += int(failed)
        for index, value in enumerate(values):
            self.total[index] += value
            self.maximum[index] = max(self.maximum[index], value)
        self.samples.append(values)

    def export(self):
        result = {
            "count": self.count,
            "errors": self.errors,
            "sample_count": len(self.samples),
            "quantiles": "most_recent_samples",
        }
        names = ("wall_ms", "thread_cpu_ms", "exclusive_wall_ms", "exclusive_thread_cpu_ms")
        for index, name in enumerate(names):
            values = sorted(item[index] / 1_000_000 for item in self.samples)
            result[name] = {
                "total": self.total[index] / 1_000_000,
                "mean": self.total[index] / self.count / 1_000_000,
                "max": self.maximum[index] / 1_000_000,
                "p50": values[math.ceil(len(values) * 0.50) - 1],
                "p95": values[math.ceil(len(values) * 0.95) - 1],
            }
        return result


class Recorder:
    def __init__(
        self,
        path,
        *,
        detailed=False,
        interval=60,
        capacity=2048,
        wall_clock=time.perf_counter_ns,
        cpu_clock=time.thread_time_ns,
        process_clock=time.process_time_ns,
        metadata=None,
    ):
        if interval <= 0 or capacity < 1:
            raise ValueError("Positive interval and sample capacity are required")
        self.detailed = detailed
        self.interval_ns = int(interval * 1_000_000_000)
        self.capacity = capacity
        self.wall_clock = wall_clock
        self.cpu_clock = cpu_clock
        self.process_clock = process_clock
        self.local = threading.local()
        self.lock = threading.RLock()
        self.stages = {}
        self.latencies = {}
        self.counters = Counter()
        self.closed = False
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("x", encoding="utf-8")
        self.last_wall = wall_clock()
        self.last_process = process_clock()
        self._write(
            {
                "type": "metadata",
                "schema_version": 1,
                "created_at_unix_ms": time.time_ns() // 1_000_000,
                "detailed": detailed,
                "sample_capacity": capacity,
                "environment": metadata if metadata is not None else environment(),
                "intervals_seconds": {
                    "process": 5,
                    "foreground_idle": 2,
                    "power": 2,
                    "heartbeat": 5,
                },
            }
        )

    def _write(self, record):
        try:
            self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.stream.flush()
        except OSError:
            # A full disk must not change tracker state or abort a transaction.
            self.closed = True
            logger.warning("Performance output unavailable; diagnostics disabled", exc_info=True)

    @contextmanager
    def span(self, name):
        if self.closed:
            yield
            return
        stack = getattr(self.local, "stack", None)
        if stack is None:
            stack = self.local.stack = []
        frame = [self.wall_clock(), self.cpu_clock(), 0, 0]
        stack.append(frame)
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            cpu = max(0, self.cpu_clock() - frame[1])
            wall = max(0, self.wall_clock() - frame[0])
            stack.pop()
            if stack:
                stack[-1][2] += wall
                stack[-1][3] += cpu
            with self.lock:
                if name not in self.stages:
                    self.stages[name] = Aggregate(self.capacity)
                self.stages[name].add(
                    (wall, cpu, max(0, wall - frame[2]), max(0, cpu - frame[3])), failed
                )
            if not stack:
                self.flush()

    def count(self, name, value=1):
        with self.lock:
            self.counters[name] += value

    def latency(self, name, seconds):
        with self.lock:
            aggregate = self.latencies.setdefault(name, Aggregate(self.capacity))
            aggregate.add((max(0, int(seconds * 1_000_000_000)), 0, 0, 0), False)

    def flush(self, *, force=False):
        with self.lock:
            if self.closed:
                return
            now = self.wall_clock()
            if not force and now - self.last_wall < self.interval_ns:
                return
            cpu = self.process_clock()
            self._write(
                {
                    "type": "interval",
                    "at_unix_ms": time.time_ns() // 1_000_000,
                    "elapsed_ms": (now - self.last_wall) / 1_000_000,
                    "process_cpu_ms": (cpu - self.last_process) / 1_000_000,
                    "stages": {key: value.export() for key, value in self.stages.items()},
                    "counters": dict(self.counters),
                    "latencies": {
                        key: {
                            "count": value.count,
                            "sample_count": len(value.samples),
                            "quantiles": "most_recent_samples",
                            "wall_ms": value.export()["wall_ms"],
                        }
                        for key, value in self.latencies.items()
                    },
                }
            )
            self.stages.clear()
            self.latencies.clear()
            self.counters.clear()
            self.last_wall = now
            self.last_process = cpu

    def close(self):
        with self.lock:
            try:
                if not self.closed:
                    self.flush(force=True)
            finally:
                self.closed = True
                try:
                    self.stream.close()
                except OSError:
                    logger.warning("Performance output could not be closed", exc_info=True)


def configure(path, *, detailed=False):
    global _active
    if _active is not None:
        raise RuntimeError("Performance recording is already configured")
    _active = Recorder(path, detailed=detailed)
    return _active


def shutdown():
    global _active
    recorder, _active = _active, None
    if recorder is not None:
        recorder.close()


atexit.register(shutdown)


def measured(name, *, detailed=False):
    """For synchronous functions only; generator bodies need explicit span contexts."""

    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            recorder = _active
            if recorder is None or recorder.closed or (detailed and not recorder.detailed):
                return function(*args, **kwargs)
            with recorder.span(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate


@contextmanager
def span(name, *, detailed=False):
    recorder = _active
    if recorder is None or recorder.closed or (detailed and not recorder.detailed):
        yield
    else:
        with recorder.span(name):
            yield


def call(name, function, *args, detailed=False, **kwargs):
    recorder = _active
    if recorder is None or recorder.closed or (detailed and not recorder.detailed):
        return function(*args, **kwargs)
    with recorder.span(name):
        return function(*args, **kwargs)


def count(name, value=1, *, detailed=False):
    recorder = _active
    if recorder is not None and not recorder.closed and (not detailed or recorder.detailed):
        recorder.count(name, value)


def latency(name, seconds):
    """Delivery/scheduling delay, separate from execution and exclusive CPU totals."""
    recorder = _active
    if recorder is not None and not recorder.closed:
        recorder.latency(name, seconds)
