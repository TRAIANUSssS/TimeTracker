"""Exercise real ETW -> pipe -> worker -> SessionManager -> isolated SQLite."""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from check_etw_collector import helper_times

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from time_tracker.collector import CollectionController  # noqa: E402
from time_tracker.diagnostics import performance  # noqa: E402
from time_tracker.domain.identity import process_creation_ms  # noqa: E402
from time_tracker.platform.windows.event_source import ProcessEventSource  # noqa: E402
from time_tracker.platform.windows.native import WindowsAPI  # noqa: E402
from time_tracker.platform.windows.provider import WindowsProvider  # noqa: E402
from time_tracker.runtime import SystemClock, TrackerRuntime  # noqa: E402
from time_tracker.storage.database import Database  # noqa: E402
from time_tracker.worker import CollectionWorker  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="default")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--stop-early",
        action="store_true",
        help="Stop the worker immediately after helpers exit, requesting the final ETW buffer",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "etw-integration")
    args = parser.parse_args()
    if not 10 <= args.timeout <= 300:
        parser.error("--timeout must be in 10..300")
    folder = args.output / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    database = Database(folder / "tracker.db")
    clock = SystemClock()
    provider = WindowsProvider(WindowsAPI(), clock)
    source = ProcessEventSource(args.channel)
    runtime = TrackerRuntime(database, provider, clock=clock)
    controller = CollectionController(runtime, provider, clock, process_events=source)
    worker = CollectionWorker(controller)
    children = []
    report = {"schema_version": 1, "database": str(database.path), "stop_early": args.stop_early}
    started, cpu_started = time.monotonic(), time.process_time()
    performance.configure(folder / "performance.jsonl")
    try:
        worker.start()
        deadline = started + args.timeout
        while not (worker.ready.is_set() and source.connected.is_set()):
            if worker.done.is_set():
                raise RuntimeError(f"Worker failed: {worker.error}")
            if time.monotonic() >= deadline:
                raise TimeoutError("ETW source did not connect")
            time.sleep(0.1)
        for seconds in (0.3, 2):
            children.append(
                subprocess.Popen(
                    [sys._base_executable, "-c", f"import time; time.sleep({seconds})"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            )
        if args.stop_early:
            for child in children:
                child.wait(timeout=5)
            if source.finished.is_set():
                raise RuntimeError("Collector finished before the shutdown test; use --seconds 60")
        else:
            while not source.finished.wait(0.1):
                if worker.done.is_set():
                    raise RuntimeError(f"Worker failed: {worker.error}")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Collector did not finish within the test timeout")
            # Let the owner consume the last batch and observe the polling fallback.
            remaining = time.monotonic() + 5
            while time.monotonic() < remaining:
                with database.reader() as con:
                    closed = con.execute(
                        "SELECT COUNT(*) FROM process_sessions "
                        "WHERE pid IN (?,?) AND ended_at IS NOT NULL",
                        tuple(child.pid for child in children),
                    ).fetchone()[0]
                if closed >= 2 and not controller._event_healthy:
                    break
                time.sleep(0.1)
    except Exception as error:
        report["error"] = str(error)
    finally:
        worker.request_stop()
        worker.join()
        performance.shutdown()
        report["worker_error"] = str(worker.error) if worker.error else None
        report["collector_finished"] = source.finished.is_set()
        report["finish_requested"] = source.finish_requested
        report["shutdown_complete"] = controller.shutdown_complete
        report["shutdown_at"] = controller.shutdown_at
        report["shutdown_events"] = controller.shutdown_events
        report["source_incomplete"] = source._invalid
        report["fallback_observed"] = source.connected.is_set() and not controller._event_healthy
        report["elapsed_seconds"] = time.monotonic() - started
        report["reader_and_worker_cpu_seconds"] = time.process_time() - cpu_started
        helpers = []
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            helpers.append({"pid": child.pid, **helper_times(child)})
        report["helpers"] = helpers
    with database.reader() as con:
        report["runs"] = [
            dict(row)
            for row in con.execute("SELECT started_at, ended_at, exit_reason FROM tracker_runs")
        ]
        report["integrity_check"] = con.execute("PRAGMA integrity_check").fetchone()[0]
        report["foreign_key_errors"] = [
            tuple(row) for row in con.execute("PRAGMA foreign_key_check")
        ]
        for helper in helpers:
            sessions = [
                dict(row)
                for row in con.execute(
                    "SELECT * FROM process_sessions WHERE pid=? AND process_started_at=?",
                    (helper["pid"], process_creation_ms(helper["creation_time_ns"])),
                )
            ]
            helper["sessions"] = sessions
            expected = (helper["exit_time_ns"] - helper["creation_time_ns"]) / 1_000_000
            helper["actual_lifetime_ms"] = expected
            helper["passed"] = bool(
                len(sessions) == 1
                and sessions[0]["executable_id"] is not None
                and sessions[0]["ended_at"] is not None
                and abs(sessions[0]["ended_at"] - sessions[0]["detected_at"] - expected) <= 2
            )
    report["passed"] = bool(
        len(helpers) == 2
        and all(helper["passed"] for helper in helpers)
        and report["integrity_check"] == "ok"
        and not report["foreign_key_errors"]
        and not report.get("error")
        and not report["worker_error"]
        and report["collector_finished"]
        and not report["source_incomplete"]
        and report["shutdown_complete"]
        and report["runs"]
        and all(run["exit_reason"] == "normal" for run in report["runs"])
        and (report["finish_requested"] if args.stop_early else report["fallback_observed"])
    )
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {path}")
    print(f"Passed: {report['passed']}; error: {report.get('error') or report['worker_error']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
