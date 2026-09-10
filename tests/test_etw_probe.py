"""ETW ABI/TDH decoding tests; no elevated session or real user events required."""

import ctypes as C
import importlib.util
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from time_tracker.diagnostics.etw_process_events import (
    GUID,
    KERNEL_PROCESS,
    EtwConsumer,
    EventHeader,
    EventRecord,
    LegacyEvent,
    LegacyHeader,
    LogFile,
    LogHeader,
)
from time_tracker.diagnostics.process_events import FILETIME_UNIX_EPOCH

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows ETW/TDH")


def test_windows_x64_abi_offsets():
    if C.sizeof(C.c_void_p) != 8:
        pytest.skip("x64 ABI check")
    assert C.sizeof(GUID) == 16
    assert C.sizeof(EventHeader) == 80
    assert C.sizeof(EventRecord) == 112
    assert EventRecord.UserData.offset == 96
    assert C.sizeof(LegacyHeader) == 48
    assert C.sizeof(LegacyEvent) == 88
    assert C.sizeof(LogHeader) == 280
    assert C.sizeof(LogFile) == 448
    assert LogFile.LogfileHeader.offset == 120
    assert LogFile.EventRecordCallback.offset == 424


@pytest.mark.parametrize("kind", [1, 2])
def test_tdh_decodes_registered_kernel_manifest_without_starting_a_session(kind):
    # Version zero schema from the registered Kernel-Process provider. TDH itself
    # validates our struct ABI and property extraction against the Windows manifest.
    consumer = EtwConsumer("TimeTracker-Probe-unit", capacity=1)
    creation = FILETIME_UNIX_EPOCH + 10000000
    data = struct.pack("<IQII", 42, creation, 10, 1)
    if kind == 2:
        data += struct.pack("<I", 0)  # ExitCode
    data += "C:\\Test\\helper.exe\0".encode("utf-16-le")
    payload = C.create_string_buffer(data)
    event = EventRecord()
    event.EventHeader.Size = C.sizeof(EventHeader)
    event.EventHeader.ProviderId = GUID.from_buffer_copy(KERNEL_PROCESS)
    event.EventHeader.EventDescriptor.Id = kind
    event.EventHeader.EventDescriptor.Version = 0
    event.EventHeader.EventDescriptor.Opcode = kind
    event.EventHeader.TimeStamp = creation + 10000000
    event.UserData = C.addressof(payload)
    event.UserDataLength = len(data)
    consumer._receive(C.pointer(event))
    assert consumer.error is None
    assert len(consumer.records) == 1
    record = consumer.records[0]
    assert record["pid"] == 42
    assert record["creation_time_ns"] == 1000000000
    assert record["kind"] == ("start" if kind == 1 else "stop")
    assert record["generated_at_ns"] == 2000000000
    assert record["has_image_name"]
    assert "helper.exe" not in str(record)
    consumer._receive(C.pointer(event))
    assert len(consumer.records) == 1
    assert consumer.counts["overflow"] == 1


def test_callback_exceptions_are_reported():
    consumer = EtwConsumer("TimeTracker-Probe-unit")
    event = EventRecord()
    event.EventHeader.ProviderId = GUID.from_buffer_copy(KERNEL_PROCESS)
    event.EventHeader.EventDescriptor.Id = 1

    def failed(*_):
        raise ValueError("bad payload")

    consumer._property = failed
    consumer._receive(C.pointer(event))
    assert consumer.error == "ValueError: bad payload"
    assert consumer.counts["decode_error"] == 1


def test_buffer_loss_is_observable():
    consumer = EtwConsumer("TimeTracker-Probe-unit")
    logfile = LogFile()
    logfile.EventsLost = 3
    logfile.LogfileHeader.BuffersLost = 2
    assert consumer._buffer(C.pointer(logfile)) == 1
    assert consumer.summary([])["events_lost"] == 3
    assert consumer.summary([])["buffers_lost"] == 2


def test_missing_session_reports_failure_and_releases_consumer():
    from uuid import uuid4

    consumer = EtwConsumer("TimeTracker-Probe-absent-" + uuid4().hex)
    try:
        try:
            consumer.start()
        except OSError:
            assert consumer._thread is None
        else:
            # Some Windows versions defer validation until ProcessTrace.
            assert consumer.done.wait(2)
            assert consumer.error is not None
    finally:
        consumer.close()


def probe_module():
    spec = importlib.util.spec_from_file_location(
        "probe_process_events",
        Path(__file__).resolve().parents[1] / "tools/probe_process_events.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_helper_handle_provides_actual_exit_time():
    module = probe_module()
    child = subprocess.Popen(
        [sys._base_executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
    )
    try:
        assert child.wait(timeout=5) == 0
        times = module.helper_times(child)
        assert times["exit_time_ns"] >= times["creation_time_ns"] > 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_full_delivery_delay_includes_provider_generation_delay():
    module = probe_module()
    events = [
        {"pid": 42, "kind": "start", "generated_at_ns": 1300000000, "received_at_ns": 1320000000}
    ]
    module.timing_summary(events, {42: {"creation_time_ns": 0}})
    assert events[0]["delivery_after_event_ms"] == 20
    assert events[0]["delivery_after_process_boundary_ms"] == 1320
    assert events[0]["event_after_process_boundary_ms"] == 1300
