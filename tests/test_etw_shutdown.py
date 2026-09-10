"""Final delivery through real Windows IPC and SQLite, without ETW privileges."""

import concurrent.futures
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.test_etw_collector import FakeConsumer, FakeSession
from tests.test_process_event_integration import Provider, item, rows, setup

from time_tracker.collector import CollectionController
from time_tracker.platform.windows import etw_collector
from time_tracker.platform.windows.event_pipe import EventPipeClient, EventPipeServer
from time_tracker.platform.windows.event_source import ProcessEventSource
from time_tracker.platform.windows.event_stream import EventStream
from time_tracker.runtime import TrackerRuntime
from time_tracker.worker import CollectionWorker


def envelope(kind, sequence, **fields):
    return dict(schema_version=1, stream_id="test", type=kind, message_sequence=sequence, **fields)


def test_finish_flushes_multiple_batches_before_sqlite_shutdown(database, monkeypatch):
    provider = Provider()
    provider.event_process = lambda record: item(pid=record["pid"])
    calls = []
    records = []
    for pid in range(100, 140):
        for kind, at in (("start", 1100), ("stop", 1450)):
            records.append(
                dict(
                    kind=kind,
                    pid=pid,
                    creation_time_ns=1100000000,
                    generated_at_ns=at * 1000000,
                    received_at_ns=9000000000,
                    sequence=len(records) + 1,
                    image_name="C:/Apps/one.exe",
                )
            )
    records.append(records[0] | {"sequence": 81, "generated_at_ns": 6000000000})

    class TailConsumer(FakeConsumer):
        def close(self):
            super().close()
            provider.at = 9000  # shutdown wait must not extend tracked time

        def drain(self, limit):
            batch = super().drain(limit)
            if self.done.is_set():
                batch["records"] = records[:limit]
                del records[:limit]
                batch["pending"] = len(records)
                batch["last_sequence"] = 81
            return batch

    # Keep the domain clock deterministic, while retaining real bounded I/O waits.
    monkeypatch.setattr(
        etw_collector,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic,
            process_time=time.process_time,
            time_ns=lambda: 1000000000,
        ),
    )
    channel = uuid4().hex
    source = ProcessEventSource(channel)
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(runtime, provider, provider, process_events=source)
    worker = CollectionWorker(controller)
    with EventPipeServer(channel) as server, concurrent.futures.ThreadPoolExecutor() as pool:
        worker.start()
        server.accept(3000)
        collecting = pool.submit(
            etw_collector.collect,
            server,
            60,
            session_factory=lambda: FakeSession(calls),
            consumer_factory=lambda *a, **kw: TailConsumer(calls),
        )
        try:
            assert worker.ready.wait(3) and source.connected.wait(3)
            assert rows(database, "process_sessions") == []
            provider.at = 5000
            worker.request_stop()
            assert worker.done.wait(5)
            worker.join()
            assert worker.error is None
            collecting.result(timeout=3)
        finally:
            worker.request_stop()
            worker.join()
        assert controller.shutdown_complete
        assert controller.shutdown_events == 80
        assert source.finish_status() == (True, True, 0)
        assert calls[-2:] == ["stop", "close"]
    sessions = rows(database, "process_sessions")
    assert len(sessions) == 40
    assert {(r["detected_at"], r["ended_at"]) for r in sessions} == {(1100, 1450)}
    run = rows(database, "tracker_runs")[0]
    assert (run["ended_at"], run["exit_reason"]) == (5000, "normal")
    with database.reader() as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("failure", ["disconnect", "timeout", "unsupported"])
def test_failed_finish_is_bounded_and_not_recorded_as_normal(database, failure):
    provider = Provider()
    channel = uuid4().hex
    source = ProcessEventSource(channel)
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(
        runtime,
        provider,
        provider,
        process_events=source,
        shutdown_timeout=0.8,
    )
    with EventPipeServer(channel) as server:
        controller.start()
        try:
            server.accept(3000)
            server.send(
                envelope(
                    "ready",
                    1,
                    started_at_ns=1000000000,
                    capabilities=[] if failure == "unsupported" else ["finish"],
                )
            )
            server.send(envelope("batch", 2, healthy=True, data_complete=True, records=[]))
            assert source.connected.wait(3)
            if failure == "disconnect":
                server.close()
            provider.at = 5000
            began = time.monotonic()
            controller.stop()
            assert time.monotonic() - began < 2
        finally:
            controller.close_sources()
            runtime.abort()
    assert not controller.shutdown_complete
    run = rows(database, "tracker_runs")[0]
    assert (run["ended_at"], run["exit_reason"]) == (5000, "events_incomplete")


def test_no_helper_needs_no_finish_ack(database):
    provider = Provider()
    source = ProcessEventSource(uuid4().hex)
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(runtime, provider, provider, process_events=source)
    controller.start()
    try:
        provider.at = 5000
        controller.stop()
        assert controller.shutdown_complete
        assert rows(database, "tracker_runs")[0]["exit_reason"] == "normal"
    finally:
        controller.close_sources()
        runtime.abort()


@pytest.mark.parametrize(
    "final",
    [
        {},
        {"cleanup_confirmed": False},
        {"data_complete": False},
        {"last_sequence": 1},
    ],
)
def test_missing_or_false_final_proof_is_incomplete(final):
    stream = EventStream()
    stream.accept(envelope("ready", 1))
    proof = dict(cleanup_confirmed=True, data_complete=True, last_sequence=0)
    stream.accept(envelope("stopped", 2, **(proof | final if final else {})))
    assert stream.stopped and stream.gap and not stream.complete


@pytest.mark.parametrize(
    "command",
    [
        {"schema_version": 1, "type": "finish", "stream_id": "other"},
        {"schema_version": 1, "type": "execute", "stream_id": FakeSession.name},
        {"schema_version": 1, "type": "finish", "stream_id": FakeSession.name, "pid": 1},
    ],
)
def test_control_rejects_other_generation_or_commands_and_cleans_up(command):
    calls, messages = [], []
    sink = SimpleNamespace(send=messages.append, receive_control=lambda _: command)
    with pytest.raises(ValueError, match="control"):
        etw_collector.collect(
            sink,
            60,
            session_factory=lambda: FakeSession(calls),
            consumer_factory=lambda *a, **kw: FakeConsumer(calls),
        )
    assert calls[-2:] == ["stop", "close"]
    assert all(message["type"] != "stopped" for message in messages)


def test_duplex_control_read_timeout_preserves_next_frame():
    channel = uuid4().hex
    with EventPipeServer(channel) as server, EventPipeClient(channel, control=True) as client:
        server.accept(500)
        with pytest.raises(TimeoutError):
            server.receive_control(20)
        client.request_finish("test")
        assert server.receive_control() == dict(schema_version=1, type="finish", stream_id="test")


def test_shutdown_keeps_checkpoint_pending_event_and_closes_at_cutoff(database):
    controller, provider, source = setup(database)
    controller._event_pending.append(({"kind": "start", "generated_at_ns": 1100000000}, 1000))
    source.records.append({"kind": "stop", "generated_at_ns": 1450000000})
    provider.at = 5000
    try:
        controller.stop()
        session = rows(database, "process_sessions")[0]
        assert (session["detected_at"], session["ended_at"]) == (1100, 1450)
        assert controller.shutdown_events == 2
    finally:
        controller.close_sources()
        controller.runtime.abort()


def test_finish_requested_during_ready_handshake_targets_that_generation():
    channel = uuid4().hex
    source = ProcessEventSource(channel)
    with EventPipeServer(channel) as server:
        source.start()
        try:
            server.accept(3000)
            source.begin_finish()
            server.send(envelope("ready", 1, started_at_ns=1000000000, capabilities=["finish"]))
            assert server.receive_control(2000)["stream_id"] == "test"
            server.send(
                envelope(
                    "stopped",
                    2,
                    cleanup_confirmed=True,
                    data_complete=True,
                    last_sequence=0,
                    finish_requested=True,
                )
            )
            assert source.finished.wait(3)
            deadline = time.monotonic() + 3
            while not source.finish_status()[0] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert source.finish_status() == (True, True, 0)
            assert source.finish_requested
        finally:
            source.close()


def test_natural_finish_keeps_queued_tail_for_later_tracker_exit(database):
    channel = uuid4().hex
    provider = Provider()
    source = ProcessEventSource(channel)
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(runtime, provider, provider, process_events=source)
    with EventPipeServer(channel) as server:
        controller.start()
        try:
            server.accept(3000)
            server.send(envelope("ready", 1, started_at_ns=1000000000, capabilities=["finish"]))
            server.send(
                envelope(
                    "draining",
                    2,
                    data_complete=True,
                    records=[
                        dict(
                            kind="start",
                            pid=42,
                            creation_time_ns=1100000000,
                            sequence=1,
                            generated_at_ns=1100000000,
                            received_at_ns=5000000000,
                            image_name="C:/Apps/one.exe",
                        )
                    ],
                )
            )
            server.send(
                envelope(
                    "stopped",
                    3,
                    cleanup_confirmed=True,
                    data_complete=True,
                    last_sequence=1,
                    finish_requested=False,
                )
            )
            assert source.finished.wait(3)
            provider.at = 5000
            controller.stop()
            assert controller.shutdown_complete and controller.shutdown_events == 1
            assert rows(database, "process_sessions")[0]["ended_at"] == 5000
        finally:
            controller.close_sources()
            runtime.abort()
