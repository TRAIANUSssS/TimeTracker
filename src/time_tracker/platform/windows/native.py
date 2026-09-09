"""Small, explicitly typed Win32 bindings; imported only on Windows."""

import ctypes
from ctypes import wintypes

import win32api
import win32gui
import win32process

from time_tracker.diagnostics.performance import measured


class LastInputInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.UINT), ("tick", wintypes.DWORD)]


class SessionInfoLevel1(ctypes.Structure):
    _fields_ = [
        ("session_id", wintypes.DWORD),
        ("state", ctypes.c_int),
        ("flags", wintypes.LONG),
        ("station", wintypes.WCHAR * 33),
        ("user", wintypes.WCHAR * 21),
        ("domain", wintypes.WCHAR * 18),
        ("logon", ctypes.c_longlong),
        ("connect", ctypes.c_longlong),
        ("disconnect", ctypes.c_longlong),
        ("last_input", ctypes.c_longlong),
        ("current", ctypes.c_longlong),
        ("counters", wintypes.DWORD * 6),
    ]


class SessionInfo(ctypes.Structure):
    _fields_ = [("level", wintypes.DWORD), ("data", SessionInfoLevel1)]


def idle_duration(tick64: int, last_tick32: int) -> int:
    """Unsigned subtraction handles the 49.7-day GetLastInputInfo tick wrap."""
    return (tick64 - last_tick32) & 0xFFFFFFFF


class WindowsAPI:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self.user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
        self.user32.GetLastInputInfo.restype = wintypes.BOOL
        self.kernel32.GetTickCount64.argtypes = []
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self.wts.WTSQuerySessionInformationW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
        self.wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        self.wts.WTSFreeMemory.restype = None
        self.user32.SetTimer.argtypes = [
            wintypes.HWND,
            ctypes.c_size_t,
            wintypes.UINT,
            ctypes.c_void_p,
        ]
        self.user32.SetTimer.restype = ctypes.c_size_t
        self.user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        self.user32.KillTimer.restype = wintypes.BOOL
        self.user32.RegisterSuspendResumeNotification.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.user32.RegisterSuspendResumeNotification.restype = wintypes.HANDLE
        self.user32.UnregisterSuspendResumeNotification.argtypes = [wintypes.HANDLE]
        self.user32.UnregisterSuspendResumeNotification.restype = wintypes.BOOL

    def register_power_notifications(self, hwnd: int) -> int:
        # Modern Standby/DAM delivers these notifications only to opted-in desktop apps.
        handle = self.user32.RegisterSuspendResumeNotification(hwnd, 0)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    @staticmethod
    def modern_standby_supported() -> bool:
        # SYSTEM_POWER_CAPABILITIES, Windows 10 SDK: 32 byte flags, 3 battery scales,
        # then 5 DWORD wake states. AoAc is byte 20 (not exposed by pywin32's wrapper).
        capabilities = (ctypes.c_ubyte * 76)()
        library = ctypes.WinDLL("powrprof", use_last_error=True)
        library.GetPwrCapabilities.argtypes = [ctypes.c_void_p]
        library.GetPwrCapabilities.restype = ctypes.c_ubyte
        if not library.GetPwrCapabilities(ctypes.byref(capabilities)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(capabilities[20])

    def unregister_power_notifications(self, handle: int) -> None:
        if not self.user32.UnregisterSuspendResumeNotification(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    @measured("native.idle")
    def idle_ms(self) -> int:
        info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return idle_duration(self.kernel32.GetTickCount64(), info.tick)

    @measured("native.lock")
    def is_locked(self) -> bool:
        buffer = ctypes.c_void_p()
        size = wintypes.DWORD()
        if not self.wts.WTSQuerySessionInformationW(
            None, 0xFFFFFFFF, 25, ctypes.byref(buffer), ctypes.byref(size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if size.value < ctypes.sizeof(SessionInfo):
                raise OSError("Truncated WTS session information")
            info = ctypes.cast(buffer, ctypes.POINTER(SessionInfo)).contents
            if info.level != 1 or info.data.flags not in (0, 1):
                raise OSError("Windows session lock state is unknown")
            # Disconnected RDP/fast-user-switch sessions cannot be active user time.
            return info.data.flags == 0 or info.data.state != 0
        finally:
            self.wts.WTSFreeMemory(buffer)

    @staticmethod
    @measured("native.foreground")
    def foreground() -> tuple[int, int, str] | None:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd or not win32gui.IsWindow(hwnd):
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            title = win32gui.GetWindowText(hwnd)
            if not pid or win32gui.GetForegroundWindow() != hwnd:
                return None
            return hwnd, pid, title
        except win32gui.error as error:
            raise OSError("Windows foreground window is unavailable") from error

    @staticmethod
    @measured("metadata.read")
    def file_metadata(path: str) -> tuple[str | None, str | None]:
        try:
            translations = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")
        except win32api.error:
            return None, None
        for language, codepage in translations:
            prefix = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\"
            values = []
            for field in ("FileDescription", "ProductName"):
                try:
                    values.append(win32api.GetFileVersionInfo(path, prefix + field) or None)
                except win32api.error:
                    values.append(None)
            if any(values):
                return tuple(values)
        return None, None
