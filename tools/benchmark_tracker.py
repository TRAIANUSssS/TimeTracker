"""Reproducible Windows baseline. Always launch into a new, isolated data directory."""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from time_tracker.diagnostics import performance  # noqa: E402


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_process(pid, creation):
    """Fresh identity check on every read; never silently attach to a reused PID."""
    process = psutil.Process(pid)
    if process.create_time() != creation:
        raise RuntimeError("Observed PID was reused")
    with process.oneshot():
        cpu = process.cpu_times()
        result = {
            "cpu_seconds": cpu.user + cpu.system,
            "rss_bytes": process.memory_info().rss,
            "threads": process.num_threads(),
            "handles": process.num_handles(),
        }
        try:
            result["io"] = process.io_counters()._asdict()
        except psutil.AccessDenied:
            result["io"] = None
    return result


def open_history(path):
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=0.1)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def current_state(connection):
    if connection is None:
        return "UNOBSERVED"
    try:
        row = connection.execute(
            "SELECT state FROM system_state_sessions WHERE ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else "UNOBSERVED"
    except sqlite3.Error:
        return "UNOBSERVED"


def summarize(samples, logical_cpus):
    groups = defaultdict(lambda: {"elapsed_seconds": 0.0, "cpu_seconds": 0.0, "cpu_samples": []})
    for before, after in zip(samples, samples[1:], strict=False):
        elapsed = after["elapsed_seconds"] - before["elapsed_seconds"]
        cpu = after["cpu_seconds"] - before["cpu_seconds"]
        state = after["state"] if before["state"] == after["state"] else "TRANSITION"
        for key in ("ALL", state):
            group = groups[key]
            group["elapsed_seconds"] += elapsed
            group["cpu_seconds"] += cpu
            group["cpu_samples"].append(100 * cpu / elapsed / logical_cpus)
    for group in groups.values():
        values = sorted(group.pop("cpu_samples"))
        group["sample_intervals"] = len(values)
        group["cpu_percent_mean"] = (
            100 * group["cpu_seconds"] / group["elapsed_seconds"] / logical_cpus
        )
        group["cpu_seconds_per_minute"] = 60 * group["cpu_seconds"] / group["elapsed_seconds"]
        group["cpu_percent_p95_1s"] = values[math.ceil(len(values) * 0.95) - 1]
        group["cpu_percent_max_1s"] = max(values)
    return dict(groups)


def close_owned_process(child):
    """Graceful shutdown only for the child we launched, using its own tracker window."""
    import win32con
    import win32gui
    import win32process

    if child.poll() is not None:
        return child.returncode
    try:
        descendants = psutil.Process(child.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        return child.wait(timeout=2)
    owned = {child.pid, *(item.pid for item in descendants)}

    def visit(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] in owned and win32gui.GetClassName(
            hwnd
        ).startswith("TimeTracker."):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    win32gui.EnumWindows(visit, None)
    try:
        return child.wait(timeout=30)
    except subprocess.TimeoutExpired:
        for process in reversed(descendants):
            try:
                process.kill()  # psutil checks identity; only descendants of our own child.
            except psutil.NoSuchProcess:
                pass
        child.kill()
        child.wait(timeout=10)
        raise RuntimeError(
            "Benchmark child did not shut down normally; test history is incomplete"
        ) from None


def tracker_process(child):
    """Windows venv python.exe can be a launcher: find the process owning the tray window."""
    import win32gui
    import win32process

    candidates = [psutil.Process(child.pid), *psutil.Process(child.pid).children(recursive=True)]
    identities = {item.pid: item for item in candidates}
    matches = []

    def visit(hwnd, _):
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if pid in identities and win32gui.GetClassName(hwnd).startswith("TimeTracker."):
            matches.append(identities[pid])

    win32gui.EnumWindows(visit, None)
    if len(matches) != 1:
        raise RuntimeError("Cannot identify exactly one benchmark tracker window")
    return matches[0]


def verify_history(path):
    with closing(open_history(path)) as connection:
        result = {
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_errors": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
            "runs": [
                dict(row)
                for row in connection.execute(
                    "SELECT id, exit_reason, started_at, ended_at FROM tracker_runs"
                )
            ],
        }
        tables = (
            "process_sessions",
            "application_running_sessions",
            "foreground_sessions",
            "system_state_sessions",
        )
        result["open_sessions"] = {
            table: connection.execute(
                f"SELECT count(*) FROM {table} WHERE ended_at IS NULL"
            ).fetchone()[0]
            for table in tables
        }
        result["negative_intervals"] = {}
        for table in tables:
            start = "detected_at" if table == "process_sessions" else "started_at"
            result["negative_intervals"][table] = connection.execute(
                f"SELECT count(*) FROM {table} WHERE ended_at < {start}"
            ).fetchone()[0]
    return result


def measure(pid, creation, duration, directory, *, database=None, churn=False):
    connection = open_history(database) if database is not None else None
    samples, helpers, launches = [], [], []
    started = time.perf_counter()
    next_launch = 0.0
    next_progress = 30.0
    try:
        with (directory / "samples.jsonl").open("x", encoding="utf-8") as stream:
            while True:
                now = time.perf_counter()
                sample = read_process(pid, creation)
                sample.update(
                    elapsed_seconds=now - started,
                    at_unix_ms=time.time_ns() // 1_000_000,
                    state=current_state(connection),
                )
                samples.append(sample)
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                if now - started >= duration:
                    break
                if churn and now - started >= next_launch and started + duration - now >= 10:
                    lifetime = 0.3 if len(launches) % 2 == 0 else 7.0
                    helper = subprocess.Popen(
                        [sys._base_executable, "-c", f"import time; time.sleep({lifetime})"],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    helpers.append(helper)
                    launches.append(
                        {
                            "pid": helper.pid,
                            "creation_time": psutil.Process(helper.pid).create_time(),
                            "started_at_unix_ms": time.time_ns() // 1_000_000,
                            "requested_lifetime_seconds": lifetime,
                        }
                    )
                    next_launch = now - started + 10
                if now - started >= next_progress:
                    print(
                        f"  {now - started:.0f}/{duration:g}s, state={sample['state']}", flush=True
                    )
                    next_progress += 30
                time.sleep(min(1.0, max(0.0, started + duration - time.perf_counter())))
    finally:
        for helper in helpers:
            if helper.poll() is None:
                helper.wait(timeout=15)
        if connection is not None:
            connection.close()
    result = {
        "pid": pid,
        "creation_time": creation,
        "logical_cpus": os.cpu_count() or 1,
        "duration_seconds": duration,
        "states": summarize(samples, os.cpu_count() or 1),
        "rss_first_bytes": samples[0]["rss_bytes"],
        "rss_last_bytes": samples[-1]["rss_bytes"],
        "handles_first": samples[0]["handles"],
        "handles_last": samples[-1]["handles"],
        "helpers": launches,
        "scenario": "churn" if churn else "quiet",
    }
    if samples[0]["io"] and samples[-1]["io"]:
        result["io_delta"] = {
            key: samples[-1]["io"][key] - value for key, value in samples[0]["io"].items()
        }
    return result


def launched_run(args, directory, mode):
    database = directory / "tracker.db"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = (
        [str(args.executable)]
        if args.executable
        else [sys.executable, "-m", "time_tracker", "--track"]
    )
    command += ["--database", str(database), "--api-port", str(port)]
    if mode != "off":
        command += ["--perf", str(directory / "performance.jsonl")]
        if mode == "detail":
            command += ["--perf-detail"]
    result = {"mode": mode, "build": "frozen" if args.executable else "python"}
    with (directory / "console.log").open("w", encoding="utf-8") as console:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=console,
            stderr=console,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            began = time.perf_counter()
            while True:
                if child.poll() is not None:
                    raise RuntimeError(f"Benchmark child exited: see {directory / 'console.log'}")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.perf_counter() - began > 90:
                        raise TimeoutError("Benchmark application startup exceeded 90 s") from None
                    time.sleep(0.25)
            process = tracker_process(child)
            creation = process.create_time()
            result["launcher_pid"] = child.pid
            result["startup_wall_seconds"] = time.perf_counter() - began
            result["startup_cpu_seconds"] = read_process(process.pid, creation)["cpu_seconds"]
            # Warmup is kept separate; no synthetic input is sent to the desktop.
            time.sleep(args.warmup)
            result.update(
                measure(
                    process.pid,
                    creation,
                    args.duration,
                    directory,
                    database=database,
                    churn=args.scenario == "churn",
                )
            )
        finally:
            result["exit_code"] = close_owned_process(child)
    result["history"] = verify_history(database)
    if result.get("helpers"):
        with closing(open_history(database)) as connection:
            for helper in result["helpers"]:
                helper["observed_sessions"] = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT detected_at, ended_at FROM process_sessions "
                        "WHERE pid=? AND process_started_at=?",
                        (helper["pid"], round(helper["creation_time"] * 1000)),
                    )
                ]
    history = result["history"]
    result["validation_passed"] = (
        result["exit_code"] == 0
        and history["integrity"] == "ok"
        and history["foreign_key_errors"] == 0
        and not any(history["open_sessions"].values())
        and not any(history["negative_intervals"].values())
        and len(history["runs"]) == 1
        and history["runs"][0]["exit_reason"] == "normal"
    )
    return result


def micro_run(args, directory):
    from time_tracker.platform.windows.native import WindowsAPI
    from time_tracker.platform.windows.provider import WindowsProvider
    from time_tracker.runtime import SystemClock

    performance.configure(directory / "performance.jsonl", detailed=True)
    provider = WindowsProvider(WindowsAPI(), SystemClock())
    results = []
    try:
        for index in range(args.snapshots):
            wall, cpu = time.perf_counter(), time.process_time()
            processes = provider.processes.snapshot()
            results.append(
                {
                    "index": index,
                    "phase": "cold" if index == 0 else "warm",
                    "processes": len(processes),
                    "wall_seconds": time.perf_counter() - wall,
                    "cpu_seconds": time.process_time() - cpu,
                }
            )
            print(f"snapshot {index + 1}: {results[-1]}", flush=True)
    finally:
        performance.shutdown()
    return {"snapshots": results, "scope": "collector only; no database or icons"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--pid", type=int, help="observe an existing process; never stop it")
    target.add_argument("--micro", action="store_true", help="profile process snapshots without DB")
    target.add_argument("--executable", type=Path, help="launch a portable exe with isolated DB")
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--warmup", type=float, default=30)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--modes", nargs="+", choices=("off", "light", "detail"), default=["off", "light"]
    )
    parser.add_argument("--snapshots", type=int, default=5)
    parser.add_argument("--scenario", choices=("quiet", "churn"), default="quiet")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "benchmarks")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows is required")
    if (
        not math.isfinite(args.duration)
        or args.duration < 1
        or not math.isfinite(args.warmup)
        or not 0 <= args.warmup <= 60
        or args.repeats < 1
        or args.snapshots < 1
    ):
        parser.error("duration >=1, warmup 0..60, repeats/snapshots >=1 are required")
    if args.pid is not None and args.scenario != "quiet":
        parser.error("--pid is read-only observation; churn requires an isolated launch")
    if args.executable is not None:
        args.executable = args.executable.resolve(strict=True)
    root = args.output.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    root.mkdir(parents=True, exist_ok=False)
    save(root / "environment.json", performance.environment())
    save(
        root / "configuration.json",
        {
            "duration_seconds": args.duration,
            "warmup_seconds": args.warmup,
            "repeats": args.repeats,
            "modes": args.modes,
            "scenario": args.scenario,
            "target": "observe"
            if args.pid
            else "micro"
            if args.micro
            else "frozen"
            if args.executable
            else "python",
        },
    )
    print(f"Report: {root}", flush=True)
    try:
        if args.micro:
            save(root / "summary.json", micro_run(args, root))
        elif args.pid is not None:
            creation = psutil.Process(args.pid).create_time()
            save(root / "summary.json", measure(args.pid, creation, args.duration, root))
        else:
            results = []
            for repeat in range(args.repeats):
                modes = args.modes if repeat % 2 == 0 else list(reversed(args.modes))
                for mode in modes:
                    directory = root / f"{repeat + 1:02d}-{mode}"
                    directory.mkdir()
                    print(f"Starting {directory.name}", flush=True)
                    result = launched_run(args, directory, mode)
                    save(directory / "summary.json", result)
                    results.append({"directory": directory.name, **result})
                    save(root / "summary.json", results)
                    if not result["validation_passed"]:
                        raise RuntimeError("Benchmark history validation failed; see summary.json")
                    print(json.dumps(result["states"], ensure_ascii=False), flush=True)
    except BaseException as error:
        save(root / "failure.json", {"type": type(error).__name__, "message": str(error)})
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
