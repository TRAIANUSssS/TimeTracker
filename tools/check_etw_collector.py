"""Read the standalone collector as an ordinary user; verify two own helpers."""

import argparse
import ctypes
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pywintypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from time_tracker.platform.windows.event_pipe import EventPipeClient  # noqa: E402
from time_tracker.platform.windows.event_stream import EventStream  # noqa: E402


def helper_times(child):
    # Retained process handle remains valid after exit; no PID lookup or reuse race.
    values = [ctypes.c_uint64() for _ in range(4)]
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetProcessTimes
    function.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_uint64)] * 4
    function.restype = ctypes.c_int
    if not function(int(child._handle), *(ctypes.byref(value) for value in values)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "creation_time_ns": (values[0].value - 116444736000000000) * 100,
        "exit_time_ns": (values[1].value - 116444736000000000) * 100,
    }


def check(channel):
    report = {"schema_version": 1, "reader_elevated": bool(ctypes.windll.shell32.IsUserAnAdmin())}
    children, events = [], []
    counts = Counter()
    stream = EventStream()
    reader_cpu = time.process_time()
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                client = EventPipeClient(channel)
                break
            except pywintypes.error as error:
                if error.winerror not in (2, 231) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        with client:
            while not stream.stopped:
                message = client.receive(30000)  # includes source start/stop with logman
                records = stream.accept(message)
                if message["type"] == "ready":
                    report["stream_id"] = stream.stream_id
                    for seconds in (0.3, 2):
                        children.append(
                            subprocess.Popen(
                                [sys._base_executable, "-c", f"import time; time.sleep({seconds})"],
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                        )
                pids = {child.pid for child in children}
                for record in records:
                    counts[record["kind"]] += 1
                    if record["pid"] in pids:
                        # Report no executable paths from user processes.
                        events.append(
                            {key: value for key, value in record.items() if key != "image_name"}
                            | {"image_name_present": bool(record.get("image_name"))}
                        )
                if message["type"] in ("batch", "draining"):
                    report["source_health"] = {
                        key: message[key]
                        for key in (
                            "events",
                            "error",
                            "events_lost",
                            "buffers_lost",
                            "last_sequence",
                        )
                    }
                if message["type"] == "stopped":
                    report["collector"] = message
    except (OSError, pywintypes.error, ValueError, RuntimeError) as error:
        report["error"] = str(error)
    finally:
        helpers = {}
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            helpers[child.pid] = helper_times(child)
        report["helpers"] = helpers
        report["helper_events"] = events
        report["events_received"] = dict(counts)
        report["reader_cpu_seconds"] = time.process_time() - reader_cpu
    complete = len(helpers) == 2 and all(
        sum(event["pid"] == pid and event["kind"] == kind for event in events) == 1
        for pid in helpers
        for kind in ("start", "stop")
    )
    health = report.get("source_health", {})
    # Draining is no longer live, but that alone is not a data loss.
    no_losses = not any(health.get(key, 0) for key in ("events_lost", "buffers_lost")) and not any(
        health.get("events", {}).get(key, 0)
        for key in ("overflow", "decode_error", "missing_CreateTime", "missing_start_image")
    )
    report["passed"] = bool(
        complete
        and no_losses
        and not stream.gap
        and not report.get("error")
        and not health.get("error")
        and report.get("collector", {}).get("cleanup_confirmed")
        and all(e.get("creation_time_ns") == helpers[e["pid"]]["creation_time_ns"] for e in events)
        and all(e["image_name_present"] for e in events if e["kind"] == "start")
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="default")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "etw-collector")
    args = parser.parse_args()
    report = check(args.channel)
    folder = args.output / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {path}")
    print(f"Passed: {report['passed']}; error: {report.get('error')}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
