"""Isolated worker stability and polling/ETW ABBA comparison; no installation or elevation."""

import argparse
import ctypes
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pywintypes
import win32api
import win32process
from benchmark_tracker import current_state, open_history, read_process, save, verify_history
from check_etw_collector import helper_times

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from time_tracker.collector import CollectionController  # noqa: E402
from time_tracker.diagnostics import performance  # noqa: E402
from time_tracker.domain.identity import process_creation_ms  # noqa: E402
from time_tracker.platform.windows.etw_collector import collect  # noqa: E402
from time_tracker.platform.windows.event_pipe import EventPipeServer, pipe_name  # noqa: E402
from time_tracker.platform.windows.event_source import ProcessEventSource  # noqa: E402
from time_tracker.platform.windows.native import WindowsAPI  # noqa: E402
from time_tracker.platform.windows.provider import WindowsProvider  # noqa: E402
from time_tracker.runtime import SystemClock, TrackerRuntime  # noqa: E402
from time_tracker.storage.database import Database  # noqa: E402
from time_tracker.worker import CollectionWorker  # noqa: E402


def plan(scenarios):
    return [
        (f"{scenario}-{index + 1}", mode, scenario)
        for scenario in scenarios
        for index, mode in enumerate(("polling", "etw", "etw", "polling"))
    ]


class CpuHandle:
    """Retain a limited-query handle so process exit/PID reuse cannot change the target."""

    def __init__(self, pid):
        self.handle = win32api.OpenProcess(0x1000, False, pid)
        self.function = ctypes.WinDLL("kernel32", use_last_error=True).GetProcessTimes
        self.function.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_uint64)] * 4
        self.function.restype = ctypes.c_int

    def sample(self):
        values = [ctypes.c_uint64() for _ in range(4)]
        if not self.function(int(self.handle), *(ctypes.byref(value) for value in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        if values[1].value:
            raise RuntimeError("Measured collector exited during the measurement")
        return (values[2].value + values[3].value) / 10000000

    def close(self):
        self.handle.Close()

    def resources(self):
        result = {}
        try:
            result["rss"] = win32process.GetProcessMemoryInfo(self.handle)["WorkingSetSize"]
            count = ctypes.c_uint32()
            function = ctypes.WinDLL("kernel32", use_last_error=True).GetProcessHandleCount
            function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            function.restype = ctypes.c_int
            if not function(int(self.handle), ctypes.byref(count)):
                raise ctypes.WinError(ctypes.get_last_error())
            result["handles"] = count.value
        except (OSError, pywintypes.error) as error:
            result["error"] = str(error)
        return result


def source_digest():
    digest = hashlib.sha256()
    files = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "tools").glob("*.py"))
    for path in files:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def awake_seconds():
    value = ctypes.c_uint64()
    function = ctypes.WinDLL("kernel32", use_last_error=True).QueryUnbiasedInterruptTime
    function.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return value.value / 10000000


def wait_for(worker, predicate, seconds, message):
    deadline = time.monotonic() + seconds
    while not predicate():
        if worker.done.is_set():
            raise RuntimeError(f"Worker exited: {worker.error}")
        if time.monotonic() >= deadline:
            raise TimeoutError(message)
        time.sleep(0.1)


def history_ok(history):
    return bool(
        history["integrity"] == "ok"
        and not history["foreign_key_errors"]
        and not any(history["open_sessions"].values())
        and not any(history["negative_intervals"].values())
        and len(history["runs"]) == 1
        and history["runs"][0]["exit_reason"] == "normal"
    )


def sample_summary(samples, logical_cpus):
    groups = {}
    for first, last in zip(samples, samples[1:], strict=False):
        elapsed = last["elapsed"] - first["elapsed"]
        own = last["cpu"] - first["cpu"]
        helper = last["collector_cpu"] - first["collector_cpu"]
        state = first["state"] if first["state"] == last["state"] else "TRANSITION"
        for key in {"ALL", state}:
            group = groups.setdefault(key, dict(seconds=0, worker_cpu=0, collector_cpu=0))
            group["seconds"] += elapsed
            group["worker_cpu"] += own
            group["collector_cpu"] += helper
    for group in groups.values():
        total = group["worker_cpu"] + group["collector_cpu"]
        group["cpu_seconds_per_minute"] = total * 60 / group["seconds"]
        group["cpu_percent_machine"] = total * 100 / group["seconds"] / logical_cpus
    return groups


def compare(results):
    """Keep individual repetitions and state strata; never turn a failed run into a saving."""
    comparisons = {}
    for scenario in {result["scenario"] for result in results}:
        selected = [r for r in results if r["scenario"] == scenario]
        if len(selected) != 4 or not all(r["passed"] for r in selected):
            comparisons[scenario] = {"comparable": False}
            continue
        states = set.intersection(*(set(r["states"]) for r in selected))
        comparison = {"comparable": True, "states": {}, "warnings": []}
        loads = [r.get("system_busy_percent") for r in selected]
        if all(value is not None for value in loads) and max(loads) - min(loads) > 10:
            comparison["warnings"].append("System load differs by more than 10 percentage points")
        active_fractions = [
            r["states"].get("ACTIVE", {}).get("seconds", 0) / r["states"]["ALL"]["seconds"]
            for r in selected
        ]
        if max(active_fractions) - min(active_fractions) > 0.1:
            comparison["warnings"].append("ACTIVE share differs by more than 10 percentage points")
        if comparison["warnings"]:
            comparison["comparable"] = False
        counts = [len(r.get("helpers", [])) for r in selected]
        if len(set(counts)) != 1:
            comparison["warnings"].append("Controlled workload process counts differ")
            comparison["comparable"] = False
        for state in sorted(states):
            rates = {}
            for mode in ("polling", "etw"):
                values = [r["states"][state] for r in selected if r["mode"] == mode]
                rates[mode] = (
                    sum(v["worker_cpu"] + v["collector_cpu"] for v in values)
                    * 60
                    / sum(v["seconds"] for v in values)
                )
            comparison["states"][state] = rates | {
                "reduction_percent": (1 - rates["etw"] / rates["polling"]) * 100
                if rates["polling"]
                else None,
            }
        comparisons[scenario] = comparison
    return comparisons


def trial(args):
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    clock = SystemClock()
    provider = WindowsProvider(WindowsAPI(), clock)
    source = ProcessEventSource(args.channel) if args.mode != "polling" else None
    database = Database(directory / "tracker.db")
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock, process_events=source)
    snapshots = []
    original_snapshot = provider.processes.snapshot

    def snapshot():
        began = time.perf_counter()
        result = original_snapshot()
        snapshots.append(
            {
                "at": time.monotonic(),
                "wall_ms": (time.perf_counter() - began) * 1000,
                "processes": len(result),
            }
        )
        return result

    provider.processes.snapshot = snapshot
    worker = CollectionWorker(controller)
    report = {
        "mode": args.mode,
        "scenario": args.scenario,
        "passed": False,
        "source_sha256": source_digest(),
        "reader_elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),
    }
    if report["reader_elevated"]:
        raise RuntimeError("Run trial in an ordinary terminal")
    helpers, completed_helpers, samples = [], [], []
    launched = 0
    collector_cpu = None
    own_process = psutil.Process()
    performance.configure(directory / "performance.jsonl")
    try:
        worker.start()
        wait_for(worker, worker.ready.is_set, 90, "Worker did not start")
        if source:
            wait_for(worker, lambda: source.status()["healthy"], 90, "Collector did not connect")
        if args.mode == "resilience":
            generation = source.status()["generation"]
            wait_for(worker, lambda: not source.status()["healthy"], 40, "No collector stop")
            before = len(snapshots)
            wait_for(worker, lambda: len(snapshots) > before, 15, "No fallback snapshot")
            report["fallback_snapshot"] = True
            wait_for(
                worker,
                lambda: source.status()["healthy"] and source.status()["generation"] != generation,
                90,
                "No new generation",
            )
            report["reconnected"] = True
        else:
            warmup_end = time.monotonic() + args.warmup
            wait_for(
                worker,
                lambda: time.monotonic() >= warmup_end,
                args.warmup + 5,
                "Warmup did not finish",
            )
        if source:
            status = source.status()
            if not status["healthy"]:
                raise RuntimeError("ETW unhealthy after warmup")
            collector_cpu = CpuHandle(status["collector_pid"])
            generation = status["generation"]
        duration = 20 if args.mode == "resilience" else args.duration
        started = time.monotonic()
        next_launch = 0
        next_progress = 30
        with (
            closing(open_history(database.path)) as con,
            (directory / "samples.jsonl").open("x", encoding="utf-8") as output,
        ):
            while True:
                if worker.done.is_set():
                    raise RuntimeError(f"Worker exited: {worker.error}")
                elapsed = time.monotonic() - started
                for child in helpers[:]:
                    if child.poll() is not None:
                        completed_helpers.append({"pid": child.pid, **helper_times(child)})
                        child._handle.Close()
                        helpers.remove(child)
                own = read_process(own_process.pid, own_process.create_time())
                status = source.status() if source else None
                if status and (
                    not status["healthy"] or status["generation"] != generation or status["faults"]
                ):
                    raise RuntimeError("ETW lost coverage during measured window")
                system = psutil.cpu_times()
                sample = dict(
                    elapsed=elapsed,
                    wall=time.time(),
                    awake=awake_seconds(),
                    cpu=own["cpu_seconds"],
                    collector_cpu=collector_cpu.sample() if collector_cpu else 0,
                    rss=own["rss_bytes"],
                    handles=own["handles"],
                    state=current_state(con),
                    source=status,
                    collector_resources=collector_cpu.resources() if collector_cpu else None,
                    system_busy=system.user + system.system,
                    system_idle=system.idle,
                )
                samples.append(sample)
                output.write(json.dumps(sample) + "\n")
                output.flush()
                if elapsed >= duration:
                    break
                if (
                    (args.scenario == "churn" or args.mode == "resilience")
                    and elapsed >= next_launch
                    and elapsed < duration - 8
                ):
                    lifetime = 0.3 if launched % 2 == 0 else 2
                    child = subprocess.Popen(
                        [sys._base_executable, "-c", f"import time; time.sleep({lifetime})"],
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    helpers.append(child)
                    launched += 1
                    next_launch += 1 if args.mode == "resilience" else 10
                if elapsed >= next_progress:
                    print(f"{args.mode}/{args.scenario}: {elapsed:.0f}/{duration:.0f}s", flush=True)
                    next_progress += 30
                time.sleep(min(1, max(0, started + duration - time.monotonic())))
        report["states"] = sample_summary(samples, os.cpu_count() or 1)
        first, last = samples[0], samples[-1]
        report["sleep_or_clock_gap_seconds"] = abs(
            last["wall"] - first["wall"] - (last["awake"] - first["awake"])
        )
        report["max_sample_gap_seconds"] = max(
            b["elapsed"] - a["elapsed"] for a, b in zip(samples, samples[1:], strict=False)
        )
        report["resources"] = {
            "rss_first": first["rss"],
            "rss_last": last["rss"],
            "rss_peak": max(s["rss"] for s in samples),
            "handles_first": first["handles"],
            "handles_last": last["handles"],
            "handles_peak": max(s["handles"] for s in samples),
        }
        report["collector_resources"] = {
            "first": first["collector_resources"],
            "last": last["collector_resources"],
        }
        busy = last["system_busy"] - first["system_busy"]
        idle = last["system_idle"] - first["system_idle"]
        report["system_busy_percent"] = 100 * busy / (busy + idle) if busy + idle else None
        report["snapshots"] = [s for s in snapshots if s["at"] >= started]
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        worker.request_stop()
        worker.join()
        if collector_cpu:
            collector_cpu.close()
        performance.shutdown()
        report["worker_error"] = str(worker.error) if worker.error else None
        report["source"] = source.status() if source else None
        report["shutdown_complete"] = controller.shutdown_complete
        report["helpers"] = completed_helpers
        for child in helpers:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
                report["error"] = "Workload helper exceeded its lifetime"
            report["helpers"].append({"pid": child.pid, **helper_times(child)})
            child._handle.Close()
    try:
        report["history"] = verify_history(database.path)
        with closing(open_history(database.path)) as con:
            for helper in report["helpers"]:
                found = con.execute(
                    "SELECT detected_at, ended_at, executable_id FROM process_sessions "
                    "WHERE pid=? AND process_started_at=?",
                    (helper["pid"], process_creation_ms(helper["creation_time_ns"])),
                ).fetchall()
                helper["sessions"] = [dict(row) for row in found]
                expected = (helper["exit_time_ns"] - helper["creation_time_ns"]) / 1000000
                helper["exact"] = bool(
                    len(found) == 1
                    and found[0]["ended_at"] is not None
                    and found[0]["executable_id"] is not None
                    and abs(found[0]["ended_at"] - found[0]["detected_at"] - expected) <= 2
                )
        report["passed"] = bool(
            not report.get("error")
            and not report["worker_error"]
            and history_ok(report["history"])
            and report["sleep_or_clock_gap_seconds"] < 2
            and report["max_sample_gap_seconds"] < 5
            and (
                not source
                or (
                    report["shutdown_complete"]
                    and not report["source"]["faults"]
                    and all(h["exact"] for h in report["helpers"])
                )
            )
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    save(directory / "report.json", report)
    print(f"Report: {directory / 'report.json'}; Passed: {report['passed']}", flush=True)
    return 0 if report["passed"] else 1


def collector_host(args):
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Run only --collector-host in an elevated terminal of the same user")
    sessions = [("resilience", 10), ("resilience", 180)] + [
        (name, args.duration + args.warmup + 180)
        for name, mode, _ in plan(args.scenarios)
        if mode == "etw"
    ]
    for index, (name, seconds) in enumerate(sessions):
        channel = f"{args.channel}-{name}"
        print(f"Collector {index + 1}/{len(sessions)}: waiting on {channel}", flush=True)
        with EventPipeServer(channel) as server:
            deadline = time.monotonic() + args.duration * 2 + args.warmup * 2 + 300
            while True:
                try:
                    server.accept(60000)
                    break
                except TimeoutError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Benchmark did not connect") from None
            collect(server, seconds)
        if index == 0:
            # Leave enough time for the reader to observe disconnect and polling fallback.
            time.sleep(12)
    print("All collector sessions stopped normally", flush=True)


def suite(args):
    if ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Run the benchmark in an ordinary terminal; elevate only collector-host")
    directory = args.output.resolve() / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "environment.json", performance.environment())
    configuration = dict(
        duration=args.duration,
        warmup=args.warmup,
        scenarios=args.scenarios,
        order="ABBA",
        source_sha256=source_digest(),
        scope="worker + observer harness + collector; no UI/API/icons",
        excluded="startup, warmup, shutdown, workload helpers, parent launcher; "
        "system ETW overhead not attributed separately",
    )
    save(directory / "configuration.json", configuration)
    print(f"Suite: {directory}", flush=True)
    results = []
    try:
        for name, mode, scenario in [("resilience", "resilience", "churn"), *plan(args.scenarios)]:
            if source_digest() != configuration["source_sha256"]:
                raise RuntimeError("Source changed during the suite; comparison invalid")
            target = directory / name
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--trial",
                "--mode",
                mode,
                "--scenario",
                scenario,
                "--channel",
                f"{args.channel}-{name}",
                "--duration",
                str(args.duration),
                "--warmup",
                str(args.warmup),
                "--output",
                str(target),
            ]
            print(f"Starting {name}: {mode}", flush=True)
            child = subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                returncode = child.wait(timeout=args.duration + args.warmup + 300)
            except BaseException:
                # The venv executable can be a launcher. Terminate only our own tree.
                if child.poll() is None:
                    owned = psutil.Process(child.pid)
                    descendants = owned.children(recursive=True)
                    for process in reversed(descendants):
                        try:
                            process.kill()
                        except psutil.NoSuchProcess:
                            pass
                    try:
                        owned.kill()
                    except psutil.NoSuchProcess:
                        pass
                    child.wait(timeout=10)
                raise
            report = json.loads((target / "report.json").read_text(encoding="utf-8"))
            if (
                report["source_sha256"] != configuration["source_sha256"]
                or source_digest() != configuration["source_sha256"]
            ):
                report["passed"] = False
                report["error"] = "Source changed during the suite"
            results.append({"directory": name, **report})
            save(
                directory / "report.json",
                {
                    "passed": all(r["passed"] for r in results),
                    "complete": False,
                    "runs": results,
                    "comparisons": compare([r for r in results if r["mode"] != "resilience"]),
                },
            )
            if returncode or not report["passed"]:
                raise RuntimeError(f"Run failed: {target / 'report.json'}")
        save(
            directory / "report.json",
            {
                "passed": True,
                "complete": True,
                "runs": results,
                "comparisons": compare([r for r in results if r["mode"] != "resilience"]),
            },
        )
    except BaseException as error:
        save(directory / "failure.json", {"error": str(error)})
        raise
    print(f"Report: {directory / 'report.json'}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--collector-host", action="store_true")
    target.add_argument("--trial", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--channel", default="cpu-stability")
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--warmup", type=float, default=30)
    parser.add_argument(
        "--scenarios", nargs="+", choices=("quiet", "churn"), default=["quiet", "churn"]
    )
    parser.add_argument(
        "--mode",
        choices=("polling", "etw", "resilience"),
        default="polling",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--scenario", choices=("quiet", "churn"), default="quiet", help=argparse.SUPPRESS
    )
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "process-events-benchmark")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or not 10 <= args.duration <= 3600:
        parser.error("duration must be 10..3600 seconds")
    if not math.isfinite(args.warmup) or not 0 <= args.warmup <= 120:
        parser.error("warmup must be 0..120 seconds")
    if len(set(args.scenarios)) != len(args.scenarios):
        parser.error("duplicate scenarios")
    pipe_name(args.channel + "-resilience" if not args.trial else args.channel)
    if args.collector_host:
        collector_host(args)
    elif args.trial:
        return trial(args)
    else:
        suite(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
