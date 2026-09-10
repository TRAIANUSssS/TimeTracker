"""Stage 5 prerequisite probe. No tracker DB, elevated launch or permanent subscription."""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from time_tracker.diagnostics.performance import environment  # noqa: E402
from time_tracker.diagnostics.process_events import (  # noqa: E402
    FILETIME_UNIX_EPOCH,
    TRACE_CLASSES,
    TraceUnavailable,
    WmiProcessTrace,
)


def helper_times(child):
    """Read actual creation/exit time from our retained process handle, even after exit."""
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    api.GetProcessTimes.restype = wintypes.BOOL
    fields = [wintypes.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(int(child._handle), *(ctypes.byref(field) for field in fields)):
        raise ctypes.WinError(ctypes.get_last_error())
    values = [(field.dwHighDateTime << 32) | field.dwLowDateTime for field in fields[:2]]
    return {
        "creation_time_ns": (values[0] - FILETIME_UNIX_EPOCH) * 100,
        "exit_time_ns": (values[1] - FILETIME_UNIX_EPOCH) * 100 if values[1] else None,
    }


def timing_summary(events, helpers):
    """Keep provider/transport delay separate from actual process lifetime."""
    for event in events:
        helper = helpers.get(event["pid"], helpers.get(str(event["pid"])))
        if helper is None:
            continue
        event["delivery_after_event_ms"] = (
            event["received_at_ns"] - event["generated_at_ns"]
        ) / 1e6
        boundary = helper.get("creation_time_ns" if event["kind"] == "start" else "exit_time_ns")
        if boundary is None and event["kind"] == "start":
            boundary = round(helper["creation_time"] * 1e9)
        if boundary is not None:
            event["delivery_after_process_boundary_ms"] = (event["received_at_ns"] - boundary) / 1e6
            event["event_after_process_boundary_ms"] = (event["generated_at_ns"] - boundary) / 1e6


def host_cpu():
    """Readable WmiPrvSE instances only, with explicit missing-coverage accounting."""
    values, denied = {}, []
    for process in psutil.process_iter(["pid", "name"], ad_value=None):
        if (process.info["name"] or "").lower() != "wmiprvse.exe":
            continue
        try:
            creation = process.create_time()
            cpu = process.cpu_times()
            values[f"{process.pid}:{creation}"] = cpu.user + cpu.system
        except psutil.AccessDenied:
            denied.append(process.pid)
        except psutil.NoSuchProcess:
            pass
    return {"seconds": values, "denied_pids": denied}


def cpu_delta(before, after, elapsed):
    shared = before["seconds"].keys() & after["seconds"].keys()
    seconds = sum(after["seconds"][key] - before["seconds"][key] for key in shared)
    complete = (
        not before["denied_pids"]
        and not after["denied_pids"]
        and before["seconds"].keys() == after["seconds"].keys()
    )
    return {
        "readable_stable_instances": len(shared),
        "seconds": seconds,
        "normalized_percent": 100 * seconds / elapsed / (os.cpu_count() or 1),
        "coverage_complete": complete,
        "before": before,
        "after": after,
    }


def wmi_probe(class_name, seconds):
    result = {"class": class_name, "subscribed": False}
    children, expected, captured = [], {}, []
    counts = Counter()
    try:
        with WmiProcessTrace(class_name) as source:
            result["subscribed"] = True
            before = host_cpu()
            began, cpu = time.monotonic(), time.process_time()
            # Subscribe first; record only our own helpers in the report.
            for lifetime in (0.3, 2.0):
                child = subprocess.Popen(
                    [sys._base_executable, "-c", f"import time; time.sleep({lifetime})"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                children.append(child)
                expected[child.pid] = {
                    "creation_time": psutil.Process(child.pid).create_time(),
                    "requested_lifetime_seconds": lifetime,
                }
            while time.monotonic() - began < seconds:
                event = source.next(250)
                if event is not None:
                    counts[event.kind] += 1
                    if event.pid in expected and len(captured) < 256:
                        record = asdict(event)
                        helper = next(child for child in children if child.pid == event.pid)
                        record["helper_alive_at_read"] = helper.poll() is None
                        captured.append(record)
            elapsed = time.monotonic() - began
            result.update(
                elapsed_seconds=elapsed,
                probe_cpu_seconds=time.process_time() - cpu,
                wmiprvse=cpu_delta(before, host_cpu(), elapsed),
                events=dict(counts),
                helpers=expected,
                helper_events=captured,
            )
            required = (
                ("start", "stop")
                if class_name == "Win32_ProcessTrace"
                else ("start" if class_name == "Win32_ProcessStartTrace" else "stop",)
            )
            result["all_helper_events_received"] = all(
                any(event["pid"] == pid and event["kind"] == kind for event in captured)
                for pid in expected
                for kind in required
            )
    except TraceUnavailable as error:
        result.update(error=str(error), hresult=f"0x{error.hresult:08X}")
    finally:
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            expected.setdefault(child.pid, {}).update(helper_times(child))
        timing_summary(captured, expected)
    return result


def command(args, *, timeout=10):
    try:
        reply = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"exit_code": None, "error": str(error)}
    encoding = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    return {
        "exit_code": reply.returncode,
        "stdout": reply.stdout.decode(encoding, errors="replace").strip(),
        "stderr": reply.stderr.decode(encoding, errors="replace").strip(),
    }


def etw_delivery(session, seconds):
    from time_tracker.diagnostics.etw_process_events import EtwConsumer

    consumer = EtwConsumer(session)
    children, expected = [], {}
    result = {}
    try:
        consumer.start()
        began, cpu = time.monotonic(), time.process_time()
        for lifetime in (0.3, 2.0):
            child = subprocess.Popen(
                [sys._base_executable, "-c", f"import time; time.sleep({lifetime})"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            children.append(child)
            expected[child.pid] = {"requested_lifetime_seconds": lifetime}
        time.sleep(seconds)
        result.update(
            elapsed_seconds=time.monotonic() - began, probe_cpu_seconds=time.process_time() - cpu
        )
    finally:
        result["stop"] = command(["logman", "stop", session, "-ets"])
        consumer.close()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            expected[child.pid].update(helper_times(child))
    result.update(consumer.summary(expected))
    result["helpers"] = expected
    timing_summary(result["helper_events"], expected)
    result["all_helper_events_received"] = all(
        any(event["pid"] == pid and event["kind"] == kind for event in result["helper_events"])
        for pid in expected
        for kind in ("start", "stop")
    )
    result["all_helper_identities_matched"] = result["all_helper_events_received"] and all(
        event.get("creation_time_ns") == expected[event["pid"]]["creation_time_ns"]
        for event in result["helper_events"]
    )
    return result


def etw_probe(seconds):
    # -ets addresses an ephemeral ETW session directly, without a saved collector set.
    name = "TimeTracker-Probe-" + uuid4().hex
    result = {
        "session": name,
        "provider": "Microsoft-Windows-Kernel-Process",
        "keyword": "0x10",
        "scope": "real-time event delivery, helper identity and timestamps; no ETL file",
    }
    try:
        result["start"] = command(
            [
                "logman",
                "create",
                "trace",
                name,
                "-p",
                result["provider"],
                "0x10",
                "4",
                "-rt",
                "-ft",
                "00:00:01",
                "-bs",
                "64",
                "-nb",
                "2",
                "4",
                "-ets",
            ]
        )
        if result["start"]["exit_code"] == 0:
            try:
                child = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--etw-child",
                        name,
                        "--seconds",
                        str(seconds),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env={**os.environ, "PYTHONUTF8": "1"},
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=seconds + 20,
                )
                result["delivery"] = (
                    json.loads(child.stdout)
                    if child.returncode == 0
                    else {"error": child.stderr.strip()}
                )
            except subprocess.TimeoutExpired:
                result["delivery"] = {"error": "ETW consumer timeout"}
    finally:
        # The unique name belongs to this invocation; also clean up partial startup.
        result["stop"] = command(["logman", "stop", name, "-ets"])
        result["cleanup_confirmed"] = result["stop"]["exit_code"] in (0, 0x80300002)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "process-events")
    parser.add_argument("--wmi-child", choices=TRACE_CLASSES, help=argparse.SUPPRESS)
    parser.add_argument("--etw-child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows required")
    if not 3 <= args.seconds <= 30:
        parser.error("--seconds must be in 3..30")
    if args.wmi_child:
        print(json.dumps(wmi_probe(args.wmi_child, args.seconds)))
        return 0
    if args.etw_child:
        if not args.etw_child.startswith("TimeTracker-Probe-"):
            parser.error("ETW child requires a probe-owned session")
        print(json.dumps(etw_delivery(args.etw_child, args.seconds)))
        return 0
    folder = args.output.resolve() / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 2,
        "environment": environment(),
        "elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "wmi": [],
    }
    path = folder / "report.json"

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    print(f"Report: {path}", flush=True)
    # Baseline measures just this probe and the readable WMI hosts; it isn't tracker CPU.
    before = host_cpu()
    began = time.monotonic()
    time.sleep(args.seconds)
    report["wmiprvse_without_subscription"] = cpu_delta(
        before, host_cpu(), time.monotonic() - began
    )
    save()
    for name in TRACE_CLASSES:
        try:
            child = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--wmi-child",
                    name,
                    "--seconds",
                    str(args.seconds),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=args.seconds + 20,
            )
            result = (
                json.loads(child.stdout)
                if child.returncode == 0
                else {"class": name, "subscribed": False, "error": child.stderr.strip()}
            )
        except subprocess.TimeoutExpired:
            result = {"class": name, "subscribed": False, "error": "WMI child timeout"}
        report["wmi"].append(result)
        save()
        print(f"{name}: {result.get('error', 'subscribed')}", flush=True)
    report["etw"] = etw_probe(args.seconds)
    save()
    print(f"ETW: {report['etw']['start']}", flush=True)
    if "delivery" in report["etw"]:
        delivery = report["etw"]["delivery"]
        print(
            f"ETW helpers: {delivery.get('all_helper_events_received')}; "
            f"error: {delivery.get('error')}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
