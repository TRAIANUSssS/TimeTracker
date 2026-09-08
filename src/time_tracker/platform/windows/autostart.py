"""Opt-in current-user Windows logon startup. Never requires administrator rights."""

import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TimeTracker"


def startup_command(database_path: Path, port: int) -> str:
    if getattr(sys, "frozen", False):
        args = [sys.executable]
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            raise OSError("pythonw.exe is required for console-free startup")
        args = [str(pythonw), "-m", "time_tracker"]
    args += ["--track", "--database", str(database_path.resolve()), "--api-port", str(port)]
    command = subprocess.list2cmdline(args)
    if len(command) > 260:
        raise ValueError(
            "Windows Run command exceeds 260 characters; use a shorter installation path"
        )
    return command


class Autostart:
    def __init__(self, database_path, port, *, key=RUN_KEY):
        self.database_path = Path(database_path)
        self.port = port
        self.key = key

    def enabled(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value == startup_command(self.database_path, self.port)
        except FileNotFoundError:
            return False

    def set_enabled(self, enabled: bool) -> None:
        import winreg

        if enabled:
            command = startup_command(self.database_path, self.port)
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, self.key, access=winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, self.key, access=winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
