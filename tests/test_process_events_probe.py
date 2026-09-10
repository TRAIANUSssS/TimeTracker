"""The diagnostic prototype must not confuse event time, identity or COM ownership."""

import sys
import threading
from types import SimpleNamespace

import pytest

from time_tracker.diagnostics.process_events import (
    FILETIME_UNIX_EPOCH,
    TIMEOUT,
    TraceUnavailable,
    WmiProcessTrace,
    error_code,
    normalize_trace,
)


class ComError(Exception):
    def __init__(self, code, *, wrapped=True):
        self.hresult = -2147352567 if wrapped else code
        self.excepinfo = (None, None, None, None, None, code) if wrapped else None


@pytest.mark.parametrize("wrapped", [False, True])
def test_hresult_unwraps_dispatch_exception(wrapped):
    assert error_code(ComError(-2147217405, wrapped=wrapped)) == 0x80041003


def test_trace_timestamp_is_filetime_event_time_with_submillisecond_precision():
    event = normalize_trace(
        "Win32_ProcessStartTrace", 42, str(FILETIME_UNIX_EPOCH + 12345), received_at_ns=2000000
    )
    assert event.kind == "start"
    assert event.pid == 42
    assert event.generated_at_ns == 1234500
    assert event.received_at_ns == 2000000
    # WMI does not give a process creation identity; never label this as creation_time.
    assert not hasattr(event, "creation_time")


def test_stop_and_start_of_reused_pid_remain_distinct_observations():
    old = normalize_trace("Win32_ProcessStopTrace", 42, FILETIME_UNIX_EPOCH + 1, received_at_ns=400)
    new = normalize_trace(
        "Win32_ProcessStartTrace", 42, FILETIME_UNIX_EPOCH + 2, received_at_ns=300
    )
    assert old.generated_at_ns < new.generated_at_ns
    assert old.received_at_ns > new.received_at_ns
    assert old != new  # Arrival order alone cannot identify the stopped process.


@pytest.mark.parametrize(
    "pid,timestamp", [(-1, FILETIME_UNIX_EPOCH), (2**32, FILETIME_UNIX_EPOCH), (42, 1)]
)
def test_invalid_trace_fields_rejected(pid, timestamp):
    with pytest.raises(ValueError):
        normalize_trace("Win32_ProcessStartTrace", pid, timestamp, received_at_ns=0)


def test_other_process_trace_classes_ignored():
    assert normalize_trace("OtherTrace", 42, 1, received_at_ns=0) is None


@pytest.fixture
def com(monkeypatch):
    calls = []
    events = []

    def next_event(timeout):
        calls.append(("next", timeout))
        item = events.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    source = SimpleNamespace(NextEvent=next_event)
    service = SimpleNamespace(Security_=SimpleNamespace())

    def query(*args):
        calls.append(("query", args))
        return source

    service.ExecNotificationQuery = query
    locator = SimpleNamespace(ConnectServer=lambda *args: service)
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            COINIT_MULTITHREADED=0,
            CoInitializeEx=lambda mode: calls.append(("init", mode)),
            CoUninitialize=lambda: calls.append("uninit"),
        ),
    )
    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(com_error=ComError))
    monkeypatch.setitem(sys.modules, "win32com.client", SimpleNamespace(Dispatch=lambda _: locator))
    return SimpleNamespace(calls=calls, events=events, locator=locator, service=service)


def test_subscription_timeout_delivery_and_cleanup_on_owner(com):
    com.events.extend(
        [
            ComError(TIMEOUT),
            SimpleNamespace(
                Path_=SimpleNamespace(Class="Win32_ProcessStopTrace"),
                ProcessID=42,
                TIME_CREATED=str(FILETIME_UNIX_EPOCH + 1),
            ),
        ]
    )
    with WmiProcessTrace() as source:
        assert source.next() is None
        assert source.next().kind == "stop"
        failures = []

        def other_thread():
            try:
                source.next()
            except RuntimeError as error:
                failures.append(str(error))

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(2)
        assert failures == ["WMI must be used on its COM owner thread"]
    assert source._source is None and source._service is None
    assert com.calls == [
        ("init", 0),
        ("query", ("SELECT * FROM Win32_ProcessTrace", "WQL", 0x30)),
        ("next", 250),
        ("next", 250),
        "uninit",
    ]
    source.close()
    assert com.calls.count("uninit") == 1


@pytest.mark.parametrize("operation", ["connect", "subscribe"])
def test_access_denied_closes_com_and_can_retry(com, operation):
    def denied(*_):
        raise ComError(-2147217405)

    if operation == "connect":
        com.locator.ConnectServer = denied
    else:
        com.service.ExecNotificationQuery = denied
    source = WmiProcessTrace("Win32_ProcessStartTrace")
    for _ in range(2):
        with pytest.raises(TraceUnavailable, match="0x80041003"):
            with source:
                pytest.fail("Failed source cannot be treated as a healthy subscription")
        assert source._owner is None and source._service is None
    assert com.calls.count("uninit") == 2


def test_source_failure_is_not_silently_treated_as_timeout(com):
    com.events.append(ComError(0x80041001))
    with pytest.raises(TraceUnavailable, match="0x80041001"):
        with WmiProcessTrace() as source:
            source.next()
    assert com.calls[-1] == "uninit"


def test_unbounded_wait_and_arbitrary_wql_not_allowed(com):
    with pytest.raises(ValueError):
        WmiProcessTrace("__InstanceCreationEvent WITHIN 1")
    with WmiProcessTrace() as source:
        for timeout in (-1, 0, 1001):
            with pytest.raises(ValueError):
                source.next(timeout)
