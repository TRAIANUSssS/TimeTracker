"""Standalone ETW helper. No database, HTTP server, elevation or installation."""

import argparse
import os
import subprocess
import sys
import time
from uuid import uuid4

import pywintypes
import win32api

from time_tracker.platform.windows.etw import EtwConsumer
from time_tracker.platform.windows.event_pipe import EventPipeServer


class EtwSession:
    """Own one uniquely named, ephemeral session; never attach to another owner."""

    def __init__(self):
        self.name = "TimeTracker-Collector-" + uuid4().hex
        self._attempted = False

    def _command(self, *arguments):
        # Resolve the OS utility explicitly instead of searching an elevated PATH.
        result = subprocess.run(
            [win32api.GetSystemDirectory() + "\\logman.exe", *arguments, "-ets"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        return result.returncode & 0xFFFFFFFF

    def start(self):
        if self._attempted:
            raise RuntimeError("ETW session already started")
        self._attempted = True
        code = self._command(
            "create",
            "trace",
            self.name,
            "-p",
            "Microsoft-Windows-Kernel-Process",
            "0x10",
            "4",
            "-rt",
            "-ft",
            "00:00:01",
            "-bs",
            "64",
            "-nb",
            "2",
            "16",
        )
        if code:
            raise OSError(code, f"ETW start failed: 0x{code:08X}")

    def close(self):
        if self._attempted:
            code = self._command("stop", self.name)
            if code not in (0, 0x80300002):
                raise OSError(code, f"ETW cleanup failed for {self.name}: 0x{code:08X}")
            self._attempted = False


def unhealthy(batch):
    counts = batch["events"]
    return bool(
        batch["error"]
        or batch["events_lost"]
        or batch["buffers_lost"]
        or counts.get("overflow")
        or counts.get("decode_error")
        or counts.get("missing_CreateTime")
        or counts.get("missing_start_image")
    )


def collect(sink, seconds, *, session_factory=EtwSession, consumer_factory=EtwConsumer):
    """Stream a single generation. Any gap remains unhealthy until a new generation."""
    session = session_factory()
    consumer = consumer_factory(session.name, include_image_names=True)
    sequence = 0
    began = time.monotonic()
    cpu_began = time.process_time()
    started_at = time.time_ns()

    def send(kind, **fields):
        nonlocal sequence
        sequence += 1
        sink.send(
            {
                "schema_version": 1,
                "stream_id": session.name,
                "message_sequence": sequence,
                "type": kind,
                "sent_at_ns": time.time_ns(),
                **fields,
            }
        )

    def drain(kind="batch"):
        batch = consumer.drain(8)
        send(
            kind,
            healthy=not unhealthy(batch) and not batch["source_done"],
            data_complete=not unhealthy(batch),
            **batch,
        )
        return batch

    try:
        session.start()
        consumer.start()
        # Ready means the consumer was opened, not a guarantee of loss-free history.
        send("ready", started_at_ns=started_at, collector_pid=os.getpid())
        deadline = began + seconds
        while time.monotonic() < deadline:
            batch = drain()
            if batch["source_done"]:
                raise RuntimeError(batch["error"] or "ETW source stopped unexpectedly")
            if not batch["pending"]:
                consumer.done.wait(min(0.25, max(0, deadline - time.monotonic())))
    finally:
        # A failed transport must still stop the owned session and release the reader.
        try:
            session.close()
        finally:
            consumer.close()
    while True:
        batch = drain("draining")
        if not batch["pending"]:
            break
    send(
        "stopped",
        healthy=False,
        elapsed_seconds=time.monotonic() - began,
        collector_cpu_seconds=time.process_time() - cpu_began,
        cleanup_confirmed=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="default")
    parser.add_argument(
        "--seconds", type=int, default=60, help="Session lifetime, 3..86400 seconds"
    )
    args = parser.parse_args(argv)
    if not 3 <= args.seconds <= 86400:
        parser.error("--seconds must be in 3..86400")
    try:
        with EventPipeServer(args.channel) as pipe:
            print(f"Waiting for local reader on channel {args.channel} (30 seconds)", flush=True)
            pipe.accept()
            try:
                collect(pipe, args.seconds)
            except Exception as error:
                try:
                    pipe.send({"schema_version": 1, "type": "error", "error": str(error)})
                except (OSError, pywintypes.error):
                    pass
                raise
        return 0
    except (
        OSError,
        pywintypes.error,
        ValueError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"ETW collector: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
