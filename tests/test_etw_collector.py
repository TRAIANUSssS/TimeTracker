"""Collector lifecycle and real local IPC; ETW rights are not needed."""

import concurrent.futures
import threading
from uuid import uuid4

import pytest
import pywintypes

from time_tracker.platform.windows import etw_collector as collector
from time_tracker.platform.windows.etw import GUID, KERNEL_PROCESS, EtwConsumer, EventRecord
from time_tracker.platform.windows.event_pipe import (
    EventPipeClient,
    EventPipeServer,
    decode_frame,
    encode_frame,
    pipe_name,
    user_sid,
)
from time_tracker.platform.windows.event_stream import EventStream


def test_pipe_delivers_json_and_cancels_idle_read():
    channel = uuid4().hex
    frame = {"schema_version": 1, "records": [{"image_name": "C:\\Тест\\app.exe"}]}
    with EventPipeServer(channel) as server, EventPipeClient(channel) as client:
        server.accept(500)  # connection completed before accept
        server.send(frame)
        assert client.receive() == frame
        with pytest.raises(TimeoutError):
            client.receive(20)
        server.send(frame)  # cancellation did not poison the next operation
        assert client.receive() == frame


def test_pipe_pending_accept_and_disconnect():
    channel = uuid4().hex
    with EventPipeServer(channel) as server, concurrent.futures.ThreadPoolExecutor() as pool:
        accepting = pool.submit(server.accept, 2000)
        with EventPipeClient(channel):
            accepting.result(timeout=3)
        with pytest.raises(pywintypes.error):
            server.send({"schema_version": 1})


def test_pipe_accept_timeout_and_exclusive_ownership():
    channel = uuid4().hex
    with EventPipeServer(channel) as server:
        with pytest.raises(pywintypes.error):
            EventPipeServer(channel)
        with pytest.raises(TimeoutError):
            server.accept(20)
    with EventPipeServer(channel):
        pass


def test_slow_reader_cannot_block_collector_forever():
    channel = uuid4().hex
    with EventPipeServer(channel) as server, EventPipeClient(channel):
        server.accept(500)
        with pytest.raises(TimeoutError):
            server.send({"schema_version": 1, "padding": "x" * 1000000}, timeout_ms=20)


@pytest.mark.parametrize("channel", ["", "../outside", "a\\b", "x" * 65])
def test_channel_validation(channel):
    with pytest.raises(ValueError):
        pipe_name(channel)


@pytest.mark.parametrize("data", [b"[]", b'{"schema_version":2}', b"not json"])
def test_protocol_rejects_invalid_frames(data):
    with pytest.raises(ValueError):
        decode_frame(data)


def test_protocol_size_bound():
    with pytest.raises(ValueError):
        encode_frame({"data": "x" * (2 * 1024 * 1024)})


class FakeSession:
    name = "TimeTracker-Collector-test"

    def __init__(self, calls, fail=False):
        self.calls = calls
        self.fail = fail

    def start(self):
        self.calls.append("start")
        if self.fail:
            raise PermissionError("denied")

    def close(self):
        self.calls.append("stop")


class FakeConsumer:
    def __init__(self, calls):
        self.calls = calls
        self.done = threading.Event()

    def start(self):
        self.calls.append("open")

    def close(self):
        self.calls.append("close")
        self.done.set()

    def drain(self, _):
        return {
            "events": {},
            "error": None,
            "records": [],
            "pending": 0,
            "events_lost": 0,
            "buffers_lost": 0,
            "source_done": self.done.is_set(),
        }


@pytest.mark.parametrize("failure", [None, "rights", "transport", "source"])
def test_lifecycle_cleanup_on_success_or_failure(failure):
    calls, frames = [], []
    session = FakeSession(calls, fail=failure == "rights")
    consumer = FakeConsumer(calls)
    if failure == "source":
        consumer.done.set()

    class Sink:
        def send(self, frame):
            if failure == "transport":
                raise BrokenPipeError()
            frames.append(frame)

    def run():
        collector.collect(
            Sink(),
            0.01,
            session_factory=lambda: session,
            consumer_factory=lambda *a, **kw: consumer,
        )

    if failure:
        with pytest.raises((OSError, RuntimeError)):
            run()
    else:
        run()
        assert frames[0]["type"] == "ready"
        assert frames[-1]["type"] == "stopped"
        assert frames[-1]["cleanup_confirmed"]
        assert [f["message_sequence"] for f in frames] == list(range(1, len(frames) + 1))
    assert calls[-2:] == ["stop", "close"]


def test_session_uses_only_owned_name_and_retries_failed_cleanup(monkeypatch):
    session = collector.EtwSession()
    commands = []
    results = iter([0, 5, 0, 0x80070005, 0x80300002])

    def command(*args):
        commands.append(args)
        return next(results)

    monkeypatch.setattr(session, "_command", command)
    session.start()
    with pytest.raises(OSError):
        session.close()
    session.close()
    with pytest.raises(OSError):
        session.start()
    session.close()
    assert all(session.name in command for command in commands)


def test_overflow_and_identity_loss_are_not_healthy():
    batch = FakeConsumer([]).drain(8)
    assert not collector.unhealthy(batch)
    batch["events"]["missing_ImageName"] = 2  # normal for stop v2
    assert not collector.unhealthy(batch)
    batch["events"]["missing_CreateTime"] = 1
    assert collector.unhealthy(batch)


def test_pipe_acl_only_grants_current_user_and_system():
    import win32security

    with EventPipeServer(uuid4().hex) as server:
        descriptor = win32security.GetSecurityInfo(
            server.handle, win32security.SE_KERNEL_OBJECT, win32security.DACL_SECURITY_INFORMATION
        )
        acl = descriptor.GetSecurityDescriptorDacl()
        sids = {
            win32security.ConvertSidToStringSid(acl.GetAce(index)[2])
            for index in range(acl.GetAceCount())
        }
        assert sids == {user_sid(), "S-1-5-18"}


def test_pipe_client_cannot_send_commands():
    import win32file

    channel = uuid4().hex
    with EventPipeServer(channel) as server, EventPipeClient(channel) as client:
        server.accept(500)
        with pytest.raises(pywintypes.error) as error:
            win32file.WriteFile(client.handle, b"command")
        assert error.value.winerror == 5


def test_partial_frame_timeout_closes_reader():
    import struct

    import win32file

    channel = uuid4().hex
    with EventPipeServer(channel) as server, EventPipeClient(channel) as client:
        server.accept(500)
        header = struct.pack("<I", 100)
        server._operation(lambda ov: win32file.WriteFile(server.handle, header, ov), 500)
        with pytest.raises(TimeoutError):
            client.receive(20)
        assert client.handle is None


def test_collector_retains_image_and_precise_identity_with_overflow_sequence():
    import ctypes as C

    consumer = EtwConsumer("unit", capacity=2, include_image_names=True)
    fields = {
        "ProcessID": (42).to_bytes(4, "little"),
        "CreateTime": (116444736000000123).to_bytes(8, "little"),
        "ImageName": "C:\\Тест\\app.exe\0".encode("utf-16-le"),
    }
    consumer._property = lambda _, name: fields[name]
    event = EventRecord()
    event.EventHeader.ProviderId = GUID.from_buffer_copy(KERNEL_PROCESS)
    event.EventHeader.EventDescriptor.Id = 1
    event.EventHeader.TimeStamp = 116444736000000456
    for _ in range(3):
        consumer._receive(C.pointer(event))
    first = consumer.drain(1)
    assert first["events"]["overflow"] == 1
    assert first["records"][0]["sequence"] == 2
    assert first["records"][0]["image_name"] == "C:\\Тест\\app.exe"
    assert first["records"][0]["creation_time_ns"] == 12300
    assert first["records"][0]["generated_at_ns"] == 45600
    assert consumer.drain()["records"][0]["sequence"] == 3
    assert consumer.drain()["records"] == []


def test_stream_marks_record_loss_and_preserves_delayed_timestamps():
    stream = EventStream()
    envelope = {"schema_version": 1, "stream_id": "test"}
    stream.accept(envelope | {"type": "ready", "message_sequence": 1})
    record = {
        "kind": "stop",
        "pid": 42,
        "sequence": 2,
        "creation_time_ns": 100,
        "generated_at_ns": 200,
        "received_at_ns": 2000000000,
    }
    returned = stream.accept(
        envelope
        | {
            "type": "batch",
            "message_sequence": 2,
            "records": [record],
            "healthy": True,
            "data_complete": True,
        }
    )
    assert returned[0]["generated_at_ns"] == 200
    assert stream.gap and not stream.healthy
    with pytest.raises(ValueError, match="generation"):
        stream.accept(envelope | {"type": "batch", "message_sequence": 3, "stream_id": "other"})


def test_stream_clean_drain_is_not_a_data_gap():
    stream = EventStream()
    envelope = {"schema_version": 1, "stream_id": "test"}
    stream.accept(envelope | {"type": "ready", "message_sequence": 1})
    stream.accept(
        envelope
        | {
            "type": "draining",
            "message_sequence": 2,
            "records": [],
            "healthy": False,
            "data_complete": True,
        }
    )
    stream.accept(envelope | {"type": "stopped", "message_sequence": 3})
    assert stream.stopped and not stream.gap and not stream.healthy
