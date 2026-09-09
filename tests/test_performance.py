"""Diagnostics must preserve behavior and account for nesting without double counting."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from time_tracker.diagnostics import performance


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_nested_exclusive_time_and_bounded_quantiles(tmp_path):
    now = [0]
    path = tmp_path / "perf.jsonl"
    recorder = performance.Recorder(
        path,
        capacity=2,
        metadata={},
        wall_clock=lambda: now[0],
        cpu_clock=lambda: now[0],
        process_clock=lambda: now[0],
    )
    with recorder.span("parent"):
        now[0] += 1_000_000
        with recorder.span("child"):
            now[0] += 3_000_000
        now[0] += 2_000_000
    for duration in (2, 4, 6):
        with recorder.span("sample"):
            now[0] += duration * 1_000_000
    recorder.close()
    data = records(path)[1]["stages"]
    assert data["parent"]["wall_ms"]["total"] == 6
    assert data["parent"]["exclusive_wall_ms"]["total"] == 3
    assert data["parent"]["exclusive_thread_cpu_ms"]["total"] == 3
    assert data["child"]["wall_ms"]["total"] == 3
    assert data["sample"]["count"] == 3
    assert data["sample"]["sample_count"] == 2
    assert data["sample"]["wall_ms"]["total"] == 12
    assert data["sample"]["wall_ms"]["p50"] == 4


def test_exceptions_preserve_original_and_restore_stack(tmp_path):
    path = tmp_path / "perf.jsonl"
    recorder = performance.Recorder(path, metadata={})
    error = ValueError("original")
    with pytest.raises(ValueError) as caught, recorder.span("failure"):
        raise error
    assert caught.value is error
    assert recorder.local.stack == []
    recorder.close()
    assert records(path)[1]["stages"]["failure"]["errors"] == 1


def test_thread_local_nesting_and_atomic_counts(tmp_path):
    path = tmp_path / "perf.jsonl"
    recorder = performance.Recorder(path, metadata={})

    def work(_):
        for _ in range(25):
            with recorder.span("work"):
                recorder.count("items")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(4)))
    recorder.close()
    data = records(path)[1]
    assert data["stages"]["work"]["count"] == 100
    assert data["counters"]["items"] == 100


def test_disabled_and_detail_gating_do_not_enter_recorder(monkeypatch):
    class Recorder:
        detailed = False
        closed = False

        def span(self, _):
            raise AssertionError("Clock must not run")

    @performance.measured("detail", detailed=True)
    def work(value):
        return value + 1

    monkeypatch.setattr(performance, "_active", None)
    assert work(1) == 2
    assert performance.call("off", lambda: 7) == 7
    monkeypatch.setattr(performance, "_active", Recorder())
    assert work(2) == 3
    assert performance.call("detail", lambda: 8, detailed=True) == 8


def test_periodic_flush_and_final_tail_are_not_duplicated(tmp_path):
    now = [0]
    path = tmp_path / "perf.jsonl"
    recorder = performance.Recorder(
        path,
        interval=1,
        metadata={},
        wall_clock=lambda: now[0],
        cpu_clock=lambda: now[0],
        process_clock=lambda: now[0],
    )
    with recorder.span("first"):
        now[0] += 2_000_000_000
    with recorder.span("last"):
        now[0] += 1_000_000
    recorder.close()
    recorder.close()
    data = records(path)
    assert len(data) == 3
    assert set(data[1]["stages"]) == {"first"}
    assert set(data[2]["stages"]) == {"last"}


def test_output_failure_cannot_abort_tracked_operation(tmp_path):
    recorder = performance.Recorder(tmp_path / "perf.jsonl", metadata={})
    recorder.stream.close()

    class BrokenStream:
        def write(self, _):
            raise OSError("disk full")

        def close(self):
            raise OSError("disk full on close")

    recorder.stream = BrokenStream()
    with recorder.span("success"):
        pass
    recorder.flush(force=True)
    assert recorder.closed
    recorder.close()


def test_existing_report_is_never_overwritten(tmp_path):
    path = tmp_path / "perf.jsonl"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        performance.Recorder(path, metadata={})
    assert path.read_text(encoding="utf-8") == "original"
