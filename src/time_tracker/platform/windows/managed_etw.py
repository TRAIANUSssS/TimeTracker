"""Task Scheduler adapter. The UI never runs elevated and cannot edit the task."""

import logging
import subprocess
import sys
from contextlib import contextmanager
from functools import cached_property, wraps
from pathlib import Path

import pythoncom
import pywintypes
import win32api
import win32con
import win32event
import win32process
import win32security
from win32com.client import Dispatch
from win32com.shell import shell, shellcon

from time_tracker.platform.windows.event_pipe import EventPipeClient, user_sid

logger = logging.getLogger(__name__)
CHANNEL = "managed"
HELPER_NAME = "TimeTrackerETW.exe"
SEE_MASK_NOASYNC = 0x00000100  # Also named SEE_MASK_FLAG_DDEWAIT in older pywin32.


def validate_user_sid(sid):
    value = win32security.ConvertStringSidToSid(sid)
    canonical = win32security.ConvertSidToStringSid(value)
    if sid != canonical or win32security.LookupAccountSid(None, value)[2] != 1:
        raise ValueError("A Windows user SID is required")
    return canonical


def task_name(sid):
    return "TimeTracker-ETW-" + validate_user_sid(sid)


def install_directory(sid):
    base = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAM_FILES, 0, 0))
    return base / task_name(sid)


def com_apartment(function):
    @wraps(function)
    def call(*args, **kwargs):
        pythoncom.CoInitialize()
        failure = None
        try:
            result = function(*args, **kwargs)
        except Exception as error:
            # Release COM references retained by failed call frames before uninitializing.
            error.__traceback__ = None
            error.__context__ = None
            failure = error
        finally:
            pythoncom.CoUninitialize()
        if failure is not None:
            raise failure
        return result

    return call


@contextmanager
def scheduler():
    service = Dispatch("Schedule.Service")
    service.Connect()
    yield service, service.GetFolder("\\")


def find_task(folder, sid):
    try:
        return folder.GetTask(task_name(sid))
    except pywintypes.com_error as error:
        code = error.excepinfo[5] if error.excepinfo else error.hresult
        if code & 0xFFFFFFFF == 0x80070002:
            return None
        raise


def bundled_helper():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "collector" / "TimeTrackerETW" / HELPER_NAME
    return (
        Path(__file__).resolve().parents[4]
        / "dist"
        / "TimeTracker"
        / "collector"
        / "TimeTrackerETW"
        / HELPER_NAME
    )


class ManagedEtw:
    def __init__(self):
        self.sid = user_sid()

    @com_apartment
    def installed(self):
        from time_tracker.platform.windows.etw_setup import verify_owned_task

        with scheduler() as (_, folder):
            task = find_task(folder, self.sid)
            if task is None or not task.Enabled:
                return False
            verify_owned_task(task, self.sid, install_directory(self.sid))
            return True

    def available(self):
        return bundled_helper().is_file()

    @cached_property
    def _bundled_digest(self):
        from time_tracker.platform.windows.etw_setup import package_digest

        return package_digest(bundled_helper().parent) if self.available() else None

    @com_apartment
    def versions(self):
        from time_tracker.platform.windows.etw_setup import verify_owned_task

        bundled = self._bundled_digest
        installed = None
        with scheduler() as (_, folder):
            task = find_task(folder, self.sid)
            if task is not None:
                verify_owned_task(task, self.sid, install_directory(self.sid))
                installed = Path(task.Definition.Actions.Item(1).Path).parent.name.removeprefix(
                    "version-"
                )
        return {
            "installed_version": installed[:12] if installed else None,
            "bundled_version": bundled[:12] if bundled else None,
            "update_available": bool(installed and bundled and installed != bundled),
        }

    @com_apartment
    def ensure_running(self):
        from time_tracker.platform.windows.etw_setup import verify_owned_task

        with scheduler() as (_, folder):
            task = find_task(folder, self.sid)
            if task is None or not task.Enabled:
                raise OSError("ETW component is not installed or is disabled")
            verify_owned_task(task, self.sid, install_directory(self.sid))
            if task.State not in (2, 4):  # queued / running; task policy also ignores duplicates
                task.Run(None)

    def client(self, channel, *, control=False):
        try:
            self.ensure_running()
        except Exception as error:
            # ProcessEventSource retries transport failures; COM exceptions must not
            # escape its reader thread and permanently disable automatic recovery.
            raise OSError("Cannot start the installed ETW task") from error
        return EventPipeClient(channel, control=control)

    @com_apartment
    def configure(self, action):
        if action not in ("install", "remove"):
            raise ValueError("Unsupported ETW setup action")
        helper = bundled_helper()
        if not helper.is_file():
            raise OSError("ETW component is missing from this application package")
        try:
            process = shell.ShellExecuteEx(
                fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC,
                lpVerb="runas",
                lpFile=str(helper),
                lpParameters=subprocess.list2cmdline(["--" + action, "--owner-sid", self.sid]),
                lpDirectory=str(helper.parent),
                nShow=win32con.SW_HIDE,
            )["hProcess"]
        except pywintypes.error as error:
            if error.winerror == 1223:
                raise PermissionError(
                    "Подтверждение Windows отменено. Режим не изменён."
                ) from error
            raise
        try:
            while win32event.WaitForSingleObject(process, 500) == win32event.WAIT_TIMEOUT:
                pass
            code = win32process.GetExitCodeProcess(process)
            if code:
                raise OSError(
                    f"Настройка компонента не завершена (код {code}). "
                    "Проверьте сообщение установщика и повторите попытку."
                )
        finally:
            win32api.CloseHandle(process)
