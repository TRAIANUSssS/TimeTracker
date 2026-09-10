"""Benchmark accounting and real IPC recovery, without an elevated ETW subscription."""

import concurrent.futures
import importlib.util
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from tests.test_etw_collector import FakeConsumer, FakeSession
from tests.test_etw_shutdown import envelope
from tests.test_process_event_integration import Provider, rows

from time_tracker.collector import CollectionController
from time_tracker.platform.windows.event_pipe import EventPipeServer
from time_tracker.platform.windows.event_source import ProcessEventSource
from time_tracker.runtime import TrackerRuntime
from time_tracker.worker import CollectionWorker


@pytest.fixture
def runner(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "tools"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "event_benchmark_test", directory / "benchmark_process_events.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cpu_includes_collector_and_weights_by_time(runner):
    result = runner.sample_summary(
        [
            dict(elapsed=0, cpu=10, collector_cpu=50, state="ACTIVE"),
            dict(elapsed=2, cpu=11, collector_cpu=51, state="ACTIVE"),
            dict(elapsed=10, cpu=13, collector_cpu=52, state="IDLE"),
        ],
        4,
    )
    assert result["ALL"]["cpu_seconds_per_minute"] == 30
    assert result["ALL"]["cpu_percent_machine"] == 12.5
    assert result["ACTIVE"]["seconds"] == 2
    assert result["TRANSITION"]["seconds"] == 8


def test_abba_and_failed_runs_never_claim_a_saving(runner):
    assert [m for _, m, _ in runner.plan(["quiet"])] == ["polling", "etw", "etw", "polling"]
    results = [
        dict(
            scenario=s,
            mode=m,
            passed=True,
            states={
                "ALL": dict(
                    worker_cpu=10 if m == "polling" else 4,
                    collector_cpu=0 if m == "polling" else 1,
                    seconds=60,
                )
            },
        )
        for _, m, s in runner.plan(["quiet"])
    ]
    assert runner.compare(results)["quiet"]["states"]["ALL"]["reduction_percent"] == 50
    results[-1]["passed"] = False
    assert runner.compare(results) == {"quiet": {"comparable": False}}


def test_cpu_handle_and_awake_clock_use_real_windows_counters(runner):
    handle = runner.CpuHandle(os.getpid())
    try:
        first = handle.sample()
        sum(range(100000))
        assert handle.sample() >= first
        assert runner.awake_seconds() > 0
        assert handle.resources()["handles"] > 0
    finally:
        handle.close()


def test_trial_drives_real_pipe_and_persists_complete_report(runner, tmp_path, monkeypatch):
    """A fake desktop/ETW source tests plumbing, never performance or real process coverage."""
    from types import SimpleNamespace

    provider = Provider()
    monkeypatch.setattr(runner, "WindowsAPI", lambda: None)
    monkeypatch.setattr(runner, "WindowsProvider", lambda *args: provider)
    monkeypatch.setattr(runner, "SystemClock", lambda: provider)
    channel = uuid4().hex
    calls = []
    with EventPipeServer(channel) as server, concurrent.futures.ThreadPoolExecutor() as pool:

        def serve():
            server.accept(5000)
            runner.collect(
                server,
                30,
                session_factory=lambda: FakeSession(calls),
                consumer_factory=lambda *a, **kw: FakeConsumer(calls),
            )

        pending = pool.submit(serve)
        args = SimpleNamespace(
            output=tmp_path / "trial",
            mode="etw",
            scenario="quiet",
            channel=channel,
            warmup=0,
            duration=1,
        )
        assert runner.trial(args) == 0
        pending.result(timeout=5)
    import json

    report = json.loads((args.output / "report.json").read_text())
    assert report["passed"] and report["shutdown_complete"]
    assert report["source"]["generations"] == 1
    assert report["states"]["ALL"]["collector_cpu"] >= 0
    assert calls[-2:] == ["stop", "close"]


@pytest.mark.parametrize("fault", ["disconnect", "sequence", "overflow"])
def test_reader_and_worker_recover_after_real_pipe_fault(database, fault):
    channel = uuid4().hex
    provider = Provider()
    source = ProcessEventSource(channel, capacity=1 if fault == "overflow" else 4096)
    runtime = TrackerRuntime(database, provider, clock=provider)
    controller = CollectionController(runtime, provider, provider, process_events=source)
    worker = CollectionWorker(controller)

    def wait(predicate):
        deadline = time.monotonic() + 10
        while not predicate():
            assert not worker.done.is_set(), worker.error
            assert time.monotonic() < deadline
            time.sleep(0.02)

    def send_ready(server, generation):
        server.send(
            envelope(
                "ready",
                1,
                started_at_ns=1000000000,
                capabilities=["finish"],
                collector_pid=os.getpid(),
            )
            | {"stream_id": generation}
        )
        server.send(
            envelope("batch", 2, healthy=True, data_complete=True, records=[])
            | {"stream_id": generation}
        )

    try:
        with EventPipeServer(channel) as first:
            worker.start()
            first.accept(3000)
            assert worker.ready.wait(3)
            provider.at = 5000
            send_ready(first, "first")
            wait(lambda: controller._event_healthy)
            calls = provider.calls
            if fault != "disconnect":
                record = dict(
                    kind="stop",
                    pid=42,
                    creation_time_ns=1100000000,
                    generated_at_ns=1450000000,
                    received_at_ns=5000000000,
                )
                records = (
                    [record | {"sequence": 3}]
                    if fault == "sequence"
                    else [record | {"sequence": 1}, record | {"sequence": 2}]
                )
                first.send(
                    envelope("batch", 3, healthy=True, data_complete=True, records=records)
                    | {"stream_id": "first"}
                )
                wait(lambda: source.status()["invalid"])
        wait(lambda: not controller._event_healthy and provider.calls > calls)
        with EventPipeServer(channel) as second:
            second.accept(10000)
            send_ready(second, "second")
            wait(lambda: controller._event_generation == "second" and controller._event_healthy)
            assert not source.status()["invalid"]
            assert source.status()["generations"] == 2
            assert source.status()["faults"] == (0 if fault == "disconnect" else 1)
            worker.request_stop()
            assert second.receive_control(3000)["stream_id"] == "second"
            second.send(
                envelope(
                    "stopped",
                    3,
                    cleanup_confirmed=True,
                    data_complete=True,
                    last_sequence=0,
                    finish_requested=True,
                )
                | {"stream_id": "second"}
            )
            assert worker.done.wait(5)
        assert worker.error is None
        assert controller.shutdown_complete
        assert rows(database, "tracker_runs")[0]["ended_at"] == 5000
        assert all(row["ended_at"] is not None for row in rows(database, "process_sessions"))
    finally:
        worker.request_stop()
        worker.join()
