"""Bounded real-time Kernel-Process consumer shared by collector and diagnostics.

Structures follow evntrace.h/evntcons.h. TDH resolves manifest properties by name,
so payload offsets are not guessed from an event version.
"""

import ctypes as C
import threading
import time
from collections import Counter, deque
from uuid import UUID

FILETIME_UNIX_EPOCH = 116444736000000000

U16, U32, U64 = C.c_uint16, C.c_uint32, C.c_uint64
P = C.c_void_p
KERNEL_PROCESS = UUID("22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716").bytes_le


class GUID(C.Structure):
    _fields_ = [("Data1", U32), ("Data2", U16), ("Data3", U16), ("Data4", C.c_ubyte * 8)]


class EventDescriptor(C.Structure):
    _fields_ = [
        ("Id", U16),
        ("Version", C.c_ubyte),
        ("Channel", C.c_ubyte),
        ("Level", C.c_ubyte),
        ("Opcode", C.c_ubyte),
        ("Task", U16),
        ("Keyword", U64),
    ]


class EventHeader(C.Structure):
    _fields_ = [
        ("Size", U16),
        ("HeaderType", U16),
        ("Flags", U16),
        ("EventProperty", U16),
        ("ThreadId", U32),
        ("ProcessId", U32),
        ("TimeStamp", U64),
        ("ProviderId", GUID),
        ("EventDescriptor", EventDescriptor),
        ("ProcessorTime", U64),
        ("ActivityId", GUID),
    ]


class EventRecord(C.Structure):
    _fields_ = [
        ("EventHeader", EventHeader),
        ("BufferContext", U32),
        ("ExtendedDataCount", U16),
        ("UserDataLength", U16),
        ("ExtendedData", P),
        ("UserData", P),
        ("UserContext", P),
    ]


class LegacyHeader(C.Structure):
    _fields_ = [
        ("Size", U16),
        ("FieldTypeFlags", U16),
        ("Version", U32),
        ("ThreadId", U32),
        ("ProcessId", U32),
        ("TimeStamp", U64),
        ("Guid", GUID),
        ("ProcessorTime", U64),
    ]


class LegacyEvent(C.Structure):
    _fields_ = [
        ("Header", LegacyHeader),
        ("InstanceId", U32),
        ("ParentInstanceId", U32),
        ("ParentGuid", GUID),
        ("MofData", P),
        ("MofLength", U32),
        ("ClientContext", U32),
    ]


class LogHeader(C.Structure):
    _fields_ = [
        ("BufferSize", U32),
        ("Version", U32),
        ("ProviderVersion", U32),
        ("NumberOfProcessors", U32),
        ("EndTime", U64),
        ("TimerResolution", U32),
        ("MaximumFileSize", U32),
        ("LogFileMode", U32),
        ("BuffersWritten", U32),
        ("StartBuffers", U32),
        ("PointerSize", U32),
        ("EventsLost", U32),
        ("CpuSpeedInMHz", U32),
        ("LoggerName", P),
        ("LogFileName", P),
        ("TimeZone", C.c_ubyte * 172),
        ("BootTime", U64),
        ("PerfFreq", U64),
        ("StartTime", U64),
        ("ReservedFlags", U32),
        ("BuffersLost", U32),
    ]


class LogFile(C.Structure):
    _fields_ = [
        ("LogFileName", C.c_wchar_p),
        ("LoggerName", C.c_wchar_p),
        ("CurrentTime", U64),
        ("BuffersRead", U32),
        ("ProcessTraceMode", U32),
        ("CurrentEvent", LegacyEvent),
        ("LogfileHeader", LogHeader),
        ("BufferCallback", P),
        ("BufferSize", U32),
        ("Filled", U32),
        ("EventsLost", U32),
        ("EventRecordCallback", P),
        ("IsKernelTrace", U32),
        ("Context", P),
    ]


class PropertyDescriptor(C.Structure):
    _fields_ = [("PropertyName", U64), ("ArrayIndex", U32), ("Reserved", U32)]


class EtwConsumer:
    def __init__(self, session, *, capacity=4096, include_image_names=False):
        if capacity < 1:
            raise ValueError("Positive capacity required")
        self.session = session
        self.include_image_names = include_image_names
        self._lock = threading.RLock()
        self._sequence = 0
        self.records = deque(maxlen=capacity)
        self.counts = Counter()
        self.error = None
        self.done = threading.Event()
        self._handle = None
        self._thread = None
        self._events_lost = self._buffers_lost = 0
        self._log = LogFile()
        self._api = C.WinDLL("advapi32", use_last_error=True)
        self._tdh = C.WinDLL("tdh", use_last_error=True)
        self._api.OpenTraceW.argtypes = [C.POINTER(LogFile)]
        self._api.OpenTraceW.restype = U64
        self._api.ProcessTrace.argtypes = [C.POINTER(U64), U32, P, P]
        self._api.ProcessTrace.restype = U32
        self._api.CloseTrace.argtypes = [U64]
        self._api.CloseTrace.restype = U32
        self._tdh.TdhGetPropertySize.argtypes = [
            C.POINTER(EventRecord),
            U32,
            P,
            U32,
            C.POINTER(PropertyDescriptor),
            C.POINTER(U32),
        ]
        self._tdh.TdhGetPropertySize.restype = U32
        self._tdh.TdhGetProperty.argtypes = [
            C.POINTER(EventRecord),
            U32,
            P,
            U32,
            C.POINTER(PropertyDescriptor),
            U32,
            P,
        ]
        self._tdh.TdhGetProperty.restype = U32
        self._callback = C.WINFUNCTYPE(None, C.POINTER(EventRecord))(self._receive)
        self._buffer_callback = C.WINFUNCTYPE(U32, C.POINTER(LogFile))(self._buffer)

    def _buffer(self, logfile):
        value = logfile.contents
        with self._lock:
            self._events_lost = max(
                self._events_lost, value.EventsLost, value.LogfileHeader.EventsLost
            )
            self._buffers_lost = max(self._buffers_lost, value.LogfileHeader.BuffersLost)
        return 1

    def _property(self, event, name):
        name_buffer = C.create_unicode_buffer(name)
        descriptor = PropertyDescriptor(C.addressof(name_buffer), 0xFFFFFFFF, 0)
        size = U32()
        result = self._tdh.TdhGetPropertySize(event, 0, None, 1, C.byref(descriptor), C.byref(size))
        if result:
            raise OSError(result, f"TDH size {name}")
        if not 1 <= size.value <= 65536:
            raise ValueError("Invalid TDH property length")
        buffer = C.create_string_buffer(size.value)
        result = self._tdh.TdhGetProperty(event, 0, None, 1, C.byref(descriptor), size, buffer)
        if result:
            raise OSError(result, f"TDH read {name}")
        return buffer.raw

    def _receive(self, event):
        received = time.time_ns()
        with self._lock:
            self._decode(event, received)

    def _decode(self, event, received):
        try:
            header = event.contents.EventHeader
            if bytes(header.ProviderId) != KERNEL_PROCESS or header.EventDescriptor.Id not in (
                1,
                2,
            ):
                return
            kind = "start" if header.EventDescriptor.Id == 1 else "stop"
            pid_bytes = self._property(event, "ProcessID")
            if len(pid_bytes) != 4:
                raise ValueError("Unexpected ProcessID size")
            record = {
                "kind": kind,
                "pid": int.from_bytes(pid_bytes, "little"),
                "version": header.EventDescriptor.Version,
                "generated_at_ns": (header.TimeStamp - FILETIME_UNIX_EPOCH) * 100,
                "received_at_ns": received,
            }
            if header.TimeStamp < FILETIME_UNIX_EPOCH:
                raise ValueError("Invalid event FILETIME")
            # Diagnostics retain availability; the collector needs the original
            # image name even after the process has exited before event delivery.
            for name in ("CreateTime", "ImageName"):
                try:
                    value = self._property(event, name)
                    if name == "CreateTime":
                        if len(value) != 8:
                            raise ValueError("Unexpected CreateTime size")
                        ticks = int.from_bytes(value, "little")
                        if ticks < FILETIME_UNIX_EPOCH:
                            raise ValueError("Invalid creation FILETIME")
                        record["creation_time_ns"] = (ticks - FILETIME_UNIX_EPOCH) * 100
                    else:
                        name_value = value.decode("utf-16-le").rstrip("\0")
                        record["has_image_name"] = bool(name_value)
                        if self.include_image_names and name_value:
                            record["image_name"] = name_value
                except (OSError, ValueError):
                    self.counts[f"missing_{name}"] += 1
            if kind == "start" and not record.get("has_image_name"):
                self.counts["missing_start_image"] += 1
            self.counts[kind] += 1
            self._sequence += 1
            record["sequence"] = self._sequence
            if len(self.records) == self.records.maxlen:
                self.counts["overflow"] += 1
            self.records.append(record)
        except BaseException as error:
            # ctypes would otherwise print and swallow callback exceptions.
            self.counts["decode_error"] += 1
            self.error = f"{type(error).__name__}: {error}"

    def start(self):
        if self._thread is not None:
            raise RuntimeError("ETW consumer already started")
        self._log.LoggerName = self.session
        self._log.ProcessTraceMode = 0x10000100  # REAL_TIME | EVENT_RECORD; converted FILETIME
        self._log.EventRecordCallback = C.cast(self._callback, P)
        self._log.BufferCallback = C.cast(self._buffer_callback, P)
        handle = self._api.OpenTraceW(C.byref(self._log))
        if handle == C.c_size_t(-1).value:
            raise C.WinError(C.get_last_error())
        self._handle = U64(handle)
        self._thread = threading.Thread(target=self._run, name="TimeTracker-ETW", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            result = self._api.ProcessTrace(C.byref(self._handle), 1, None, None)
            if result not in (0, 1223):  # ERROR_CANCELLED on requested shutdown
                with self._lock:
                    self.error = f"ProcessTrace: {result}"
        except BaseException as error:
            with self._lock:
                self.error = f"{type(error).__name__}: {error}"
        finally:
            self.done.set()

    def close(self):
        if self._handle is None:
            return
        # The controller stops its session before close, allowing buffered events to drain.
        self.done.wait(3)
        result = self._api.CloseTrace(self._handle)
        if result not in (0, 7007):  # ERROR_CTX_CLOSE_PENDING is documented for active readers
            self.error = self.error or f"CloseTrace: {result}"
        if self._thread is not None:
            self._thread.join(3)
            if self._thread.is_alive():
                raise RuntimeError("ETW consumer did not stop")
        self._handle = None

    def drain(self, limit=128):
        """Atomically drain a bounded batch and cumulative health counters."""
        if not 1 <= limit <= 4096:
            raise ValueError("Batch limit must be in 1..4096")
        with self._lock:
            return {
                "records": [self.records.popleft() for _ in range(min(limit, len(self.records)))],
                "events": dict(self.counts),
                "error": self.error,
                "events_lost": self._events_lost,
                "buffers_lost": self._buffers_lost,
                "last_sequence": self._sequence,
                "pending": len(self.records),
                "source_done": self.done.is_set(),
            }

    def summary(self, helper_pids):
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Stop ETW consumer before reading results")
        return {
            "events": dict(self.counts),
            "error": self.error,
            "events_lost": self._events_lost,
            "buffers_lost": self._buffers_lost,
            "helper_events": [r for r in self.records if r["pid"] in helper_pids],
        }
