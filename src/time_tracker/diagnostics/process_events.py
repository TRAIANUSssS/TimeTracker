"""Bounded WMI trace prototype, deliberately separate from production collection.

TIME_CREATED is an event timestamp, never a substitute for process creation time.
The source returns scalar observations only; it neither resolves metadata nor writes history.
"""

import threading
import time
from dataclasses import dataclass

FILETIME_UNIX_EPOCH = 116444736000000000
TRACE_CLASSES = ("Win32_ProcessTrace", "Win32_ProcessStartTrace", "Win32_ProcessStopTrace")
TIMEOUT = 0x80043001


@dataclass(frozen=True, slots=True)
class ProcessTrace:
    kind: str
    pid: int
    generated_at_ns: int
    received_at_ns: int


class TraceUnavailable(RuntimeError):
    def __init__(self, hresult):
        self.hresult = hresult & 0xFFFFFFFF
        super().__init__(f"WMI process trace unavailable: 0x{self.hresult:08X}")


def error_code(error):
    info = getattr(error, "excepinfo", None)
    code = info[5] if info and info[5] else error.hresult
    return code & 0xFFFFFFFF


def normalize_trace(class_name, pid, timestamp, *, received_at_ns):
    kinds = {"Win32_ProcessStartTrace": "start", "Win32_ProcessStopTrace": "stop"}
    if class_name not in kinds:
        return None
    pid, timestamp = int(pid), int(timestamp)
    if not 0 <= pid <= 0xFFFFFFFF or timestamp < FILETIME_UNIX_EPOCH:
        raise ValueError("Invalid process trace fields")
    return ProcessTrace(
        kinds[class_name], pid, (timestamp - FILETIME_UNIX_EPOCH) * 100, received_at_ns
    )


class WmiProcessTrace:
    """One semisynchronous subscription, created/read/released on its COM owner thread."""

    def __init__(self, class_name="Win32_ProcessTrace"):
        if class_name not in TRACE_CLASSES:
            raise ValueError("Unsupported process trace class")
        self.class_name = class_name
        self._owner = None
        self._service = self._source = None
        self._com = self._com_error = None

    def __enter__(self):
        import pythoncom
        import pywintypes
        from win32com.client import Dispatch

        if self._owner is not None:
            raise RuntimeError("Trace already opened")
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        self._owner = threading.get_ident()
        self._com, self._com_error = pythoncom, pywintypes.com_error
        failure = None
        try:
            locator = Dispatch("WbemScripting.SWbemLocator")
            try:
                self._service = locator.ConnectServer(".", r"root\cimv2")
            finally:
                locator = None
            self._service.Security_.ImpersonationLevel = 3
            self._source = self._service.ExecNotificationQuery(
                f"SELECT * FROM {self.class_name}", "WQL", 0x30
            )
        except pywintypes.com_error as error:
            failure = error_code(error)
            # Do not keep COM dispatch objects alive through the exception traceback.
            error.__traceback__ = None
        except BaseException:
            self.close()
            raise
        if failure is not None:
            self.close()
            raise TraceUnavailable(failure)
        return self

    def next(self, timeout_ms=250):
        self._check_owner()
        if not 1 <= timeout_ms <= 1000:
            raise ValueError("Finite timeout in 1..1000 ms required")
        try:
            event = self._source.NextEvent(timeout_ms)
        except self._com_error as error:
            code = error_code(error)
            error.__traceback__ = None
            if code == TIMEOUT:
                return None
            raise TraceUnavailable(code) from None
        try:
            return normalize_trace(
                event.Path_.Class,
                event.ProcessID,
                event.TIME_CREATED,
                received_at_ns=time.time_ns(),
            )
        finally:
            event = None

    def _check_owner(self):
        if self._owner != threading.get_ident():
            raise RuntimeError("WMI must be used on its COM owner thread")

    def close(self):
        if self._owner is None:
            return
        self._check_owner()
        self._source = self._service = None
        self._com.CoUninitialize()
        self._owner = None

    def __exit__(self, *_):
        self.close()
