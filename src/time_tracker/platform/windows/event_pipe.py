"""Local, current-user-only JSON transport with bounded I/O and finish control."""

import json
import re
import struct
import time

import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32pipe
import win32security

MAX_FRAME = 2 * 1024 * 1024


def user_sid():
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
        return win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()


def pipe_name(channel="default"):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", channel):
        raise ValueError("Channel must contain 1..64 ASCII letters, digits, underscores or hyphens")
    return rf"\\.\pipe\TimeTracker-ETW-{user_sid()}-{channel}"


def encode_frame(message):
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if not 1 <= len(data) <= MAX_FRAME:
        raise ValueError("Event frame exceeds size limit")
    return data


def decode_frame(data):
    if not 1 <= len(data) <= MAX_FRAME:
        raise ValueError("Invalid event frame size")
    value = json.loads(data)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Unsupported event protocol")
    return value


class EventPipe:
    """One overlapped operation at a time; caller owns the handle and thread."""

    def __init__(self, handle):
        self.handle = handle

    def _operation(self, begin, timeout_ms):
        if not 1 <= timeout_ms <= 60000:
            raise ValueError("I/O timeout must be in 1..60000 ms")
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        issued = False
        try:
            try:
                issued = True
                result = begin(overlapped)
                if result == 535:  # pywin32 returns ERROR_PIPE_CONNECTED directly
                    issued = False
                    return 0
            except pywintypes.error as error:
                if error.winerror == 535:  # client connected before ConnectNamedPipe
                    issued = False
                    return 0
                if error.winerror != 997:  # ERROR_IO_PENDING
                    issued = False
                    raise
            try:
                return win32file.GetOverlappedResult(self.handle, overlapped, False)
            except pywintypes.error as error:
                if error.winerror != 996:  # ERROR_IO_INCOMPLETE
                    raise
            if (
                win32event.WaitForSingleObject(overlapped.hEvent, timeout_ms)
                != win32event.WAIT_OBJECT_0
            ):
                raise TimeoutError("Event pipe I/O timed out")
            return win32file.GetOverlappedResult(self.handle, overlapped, False)
        finally:
            # Cancellation is asynchronous: retain OVERLAPPED and buffer until the
            # kernel has finished with them, including during Ctrl+C and timeouts.
            try:
                if issued:
                    try:
                        win32file.CancelIo(self.handle)  # sole I/O on this handle and thread
                    except pywintypes.error as error:
                        if error.winerror != 1168:  # ERROR_NOT_FOUND: already completed
                            raise
                    try:
                        win32file.GetOverlappedResult(self.handle, overlapped, True)
                    except pywintypes.error:
                        pass
            finally:
                overlapped.hEvent.Close()

    def close(self):
        if self.handle is not None:
            self.handle.Close()
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class EventPipeServer(EventPipe):
    def __init__(self, channel="default"):
        name = pipe_name(channel)
        security = pywintypes.SECURITY_ATTRIBUTES()
        security.SECURITY_DESCRIPTOR = (
            win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                f"D:P(A;;GA;;;SY)(A;;GA;;;{user_sid()})S:(ML;;NW;;;ME)",
                win32security.SDDL_REVISION_1,
            )
        )
        super().__init__(
            win32pipe.CreateNamedPipe(
                name,
                win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED | 0x00080000,
                win32pipe.PIPE_TYPE_BYTE | 0x8,
                1,  # FIRST_PIPE_INSTANCE and PIPE_REJECT_REMOTE_CLIENTS above
                65536,
                4096,
                1000,
                security,
            )
        )

    def accept(self, timeout_ms=30000):
        self._operation(lambda ov: win32pipe.ConnectNamedPipe(self.handle, ov), timeout_ms)

    def send(self, message, timeout_ms=2000):
        payload = encode_frame(message)
        data = struct.pack("<I", len(payload)) + payload
        count = self._operation(lambda ov: win32file.WriteFile(self.handle, data, ov), timeout_ms)
        if count != len(data):
            raise OSError("Incomplete event frame write")

    def receive_control(self, timeout_ms=250):
        return EventPipeClient.receive(self, timeout_ms, max_frame=4096)


class EventPipeClient(EventPipe):
    def __init__(self, channel="default", *, control=False):
        super().__init__(
            win32file.CreateFile(
                pipe_name(channel),
                win32con.GENERIC_READ | (0x2 if control else 0),  # FILE_WRITE_DATA only
                0,
                None,
                win32con.OPEN_EXISTING,
                win32file.FILE_FLAG_OVERLAPPED | 0x00100000,  # SECURITY_SQOS_PRESENT: anonymous
                None,
            )
        )

    def request_finish(self, stream_id):
        EventPipeServer.send(
            self, {"schema_version": 1, "type": "finish", "stream_id": stream_id}, 500
        )

    def receive(self, timeout_ms=5000, *, max_frame=MAX_FRAME):
        deadline = time.monotonic() + timeout_ms / 1000
        received_any = False

        def read_exact(size):
            nonlocal received_any
            data = bytearray()
            while len(data) < size:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms < 1:
                    raise TimeoutError("Event frame read timed out")
                buffer = win32file.AllocateReadBuffer(size - len(data))
                count = self._operation(
                    lambda ov, buffer=buffer: win32file.ReadFile(self.handle, buffer, ov),
                    remaining_ms,
                )
                if not count:
                    raise BrokenPipeError("Event pipe closed")
                received_any = True
                data.extend(buffer[:count])
            return bytes(data)

        try:
            size = struct.unpack("<I", read_exact(4))[0]
            if not 1 <= size <= max_frame:
                raise ValueError("Invalid event frame size")
            return decode_frame(read_exact(size))
        except BaseException:
            if received_any:
                self.close()  # a partial frame cannot be resumed as a new header
            raise
