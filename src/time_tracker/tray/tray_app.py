"""Native Windows tray and hidden top-level window on the tracker owner thread."""

import logging
import signal
from collections import deque
from uuid import uuid4

import win32api
import win32con
import win32gui
import win32ts

logger = logging.getLogger(__name__)
WM_TRAY = win32con.WM_APP + 1
EXIT_COMMAND = 1003


class TrayApplication:
    def __init__(self, controller, api, *, show_icon=True, service=None):
        self.controller = controller
        self.api = api
        self.show_icon = show_icon
        self.service = service
        self.hwnd = None
        self._class_name = f"TimeTracker.{uuid4().hex}"
        self._taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
        self._icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        self._registered = False
        self._power_registration = None
        self._started = False
        self._closing = False
        self._stop_requested = False
        self._busy = False
        self._pending = deque()
        self.error = None

    def run(self):
        instance = win32api.GetModuleHandle(None)
        window_class = win32gui.WNDCLASS()
        window_class.hInstance = instance
        window_class.lpszClassName = self._class_name
        window_class.lpfnWndProc = self._window_proc
        win32gui.RegisterClass(window_class)
        previous_signal = signal.getsignal(signal.SIGINT)
        try:
            # A message-only window would miss power/taskbar broadcasts.
            self.hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_TOOLWINDOW,
                self._class_name,
                "TimeTracker",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                instance,
                None,
            )
            win32ts.WTSRegisterSessionNotification(self.hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
            self._registered = True
            self._power_registration = self.api.register_power_notifications(self.hwnd)
            logger.info("Registered Windows suspend/resume notifications")
            self._busy = True
            try:
                self.controller.start()
                self._started = True
                if self.service is not None:
                    self.service.start()
            finally:
                self._busy = False
            self._drain()
            if self.show_icon:
                self._add_icon()
            if not self.api.user32.SetTimer(self.hwnd, 1, 250, None):
                raise OSError("Cannot start the collection timer")
            signal.signal(
                signal.SIGINT, lambda *_: win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            )
            win32gui.PumpMessages()
        except BaseException:
            if self._started:
                self.controller.runtime.abort()
                self._started = False
            raise
        finally:
            signal.signal(signal.SIGINT, previous_signal)
            self._cleanup()
            win32gui.UnregisterClass(self._class_name, instance)
        if self.error is not None:
            raise RuntimeError(
                "Windows collection stopped; see the log for details"
            ) from self.error

    def _add_icon(self):
        win32gui.Shell_NotifyIcon(
            win32gui.NIM_ADD,
            (
                self.hwnd,
                0,
                win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                WM_TRAY,
                self._icon,
                "TimeTracker — запись времени",
            ),
        )

    def _menu(self):
        menu = win32gui.CreatePopupMenu()
        try:
            win32gui.AppendMenu(
                menu, win32con.MF_STRING | win32con.MF_GRAYED, 1001, "Открыть dashboard"
            )
            win32gui.AppendMenu(
                menu, win32con.MF_STRING | win32con.MF_GRAYED, 1002, "Приостановить запись"
            )
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, EXIT_COMMAND, "Выход")
            x, y = win32gui.GetCursorPos()
            try:
                win32gui.SetForegroundWindow(self.hwnd)
            except win32gui.error:
                # Windows may deny foreground activation; this must not abort tracking.
                logger.debug("Windows denied foreground activation for the tray menu")
            command = win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY | win32con.TPM_RIGHTBUTTON,
                x,
                y,
                0,
                self.hwnd,
                None,
            )
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
            if command == EXIT_COMMAND:
                self._close()
        finally:
            win32gui.DestroyMenu(menu)

    def _notify(self, kind):
        logger.info("Windows notification: %s", kind)
        self._pending.append((kind, self.controller.clock.now_ms()))
        if not self._busy and self._started:
            self._drain()

    def _drain(self):
        self._busy = True
        try:
            while self._pending and self._started:
                kind, at = self._pending.popleft()
                self.controller.notify(kind, at)
        finally:
            self._busy = False
        if self._stop_requested:
            self._close()

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == win32con.WM_TIMER and self._started and not self._busy:
                self._busy = True
                try:
                    if self.service is not None:
                        self.service.tick()
                    self.controller.tick()
                finally:
                    self._busy = False
                self._drain()
                return 0
            if message == 0x02B1:  # WM_WTSSESSION_CHANGE
                if wparam in (7, 2, 4):  # lock, console disconnect, remote disconnect
                    self._notify("lock")
                elif wparam == 8:
                    self._notify("unlock")
                elif wparam in (1, 3):
                    self._notify("recheck")
                return 0
            if message == win32con.WM_POWERBROADCAST:
                if wparam == 4:  # PBT_APMSUSPEND
                    self._notify("sleep")
                elif wparam in (7, 18):  # interactive and automatic resume
                    self._notify("wake")
                return 1
            if message == win32con.WM_QUERYENDSESSION:
                return 1
            if message == win32con.WM_ENDSESSION and wparam:
                self._close()
                return 0
            if message == win32con.WM_CLOSE:
                self._close()
                return 0
            if message == win32con.WM_DESTROY:
                if not self._closing:
                    self._close()
                return 0
            if (
                message == WM_TRAY
                and not self._busy
                and lparam in (win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP)
            ):
                self._menu()
                return 0
            if message == self._taskbar_created and self._started and self.show_icon:
                self._add_icon()
                return 0
        except BaseException as error:
            # Exceptions escaping a pywin32 callback otherwise only get printed and swallowed.
            logger.exception("Windows event processing failed")
            self.error = error
            if self._started:
                self.controller.runtime.abort()
                self._started = False
            win32gui.PostQuitMessage(1)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _close(self):
        if self._busy:
            self._stop_requested = True
            return
        if self._closing:
            return
        self._closing = True
        if self.service is not None:
            self.service.stop()
        if self._started:
            self.controller.stop()
            self._started = False
        win32gui.PostQuitMessage(0)

    def _cleanup(self):
        self._closing = True
        if self.service is not None:
            self.service.stop()
        if self._started:
            self.controller.stop()
            self._started = False
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            self.api.user32.KillTimer(self.hwnd, 1)
            if self._power_registration is not None:
                try:
                    self.api.unregister_power_notifications(self._power_registration)
                except OSError:
                    logger.warning("Failed to unregister power notifications", exc_info=True)
                self._power_registration = None
            if self._registered:
                win32ts.WTSUnRegisterSessionNotification(self.hwnd)
            if self.show_icon:
                try:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
                except win32gui.error:
                    logger.debug("Tray icon already removed")
            win32gui.DestroyWindow(self.hwnd)
        self.hwnd = None
