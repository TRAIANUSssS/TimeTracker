"""Conservative, versioned classification of Windows executable paths."""

from __future__ import annotations

import ntpath
import os
from enum import StrEnum

from time_tracker.domain.identity import normalize_executable_path

CATALOG_VERSION = 1


class ProcessCategory(StrEnum):
    SYSTEM = "system"
    USER = "user"
    UNKNOWN = "unknown"


# Only background Windows infrastructure belongs here. Interactive tools such as
# cmd.exe, PowerShell, Explorer and Task Manager deliberately remain user-facing.
_SYSTEM_LOCATIONS: dict[str, frozenset[str]] = {
    "aggregatorhost.exe": frozenset({"system32"}),
    "audiodg.exe": frozenset({"system32"}),
    "backgroundtaskhost.exe": frozenset({"system32"}),
    "compattelrunner.exe": frozenset({"system32"}),
    "comppkgsrv.exe": frozenset({"system32"}),
    "csrss.exe": frozenset({"system32"}),
    "dashost.exe": frozenset({"system32"}),
    "dataexchangehost.exe": frozenset({"system32"}),
    "devicecensus.exe": frozenset({"system32"}),
    "dllhost.exe": frozenset({"system32", "syswow64"}),
    "dmclient.exe": frozenset({"system32"}),
    "dwm.exe": frozenset({"system32"}),
    "fontdrvhost.exe": frozenset({"system32"}),
    "lsaiso.exe": frozenset({"system32"}),
    "lsass.exe": frozenset({"system32"}),
    "midisrv.exe": frozenset({"system32"}),
    "mpsigstub.exe": frozenset({"system32"}),
    "ngciso.exe": frozenset({"system32"}),
    "runtimebroker.exe": frozenset({"system32"}),
    "searchfilterhost.exe": frozenset({"system32"}),
    "searchindexer.exe": frozenset({"system32"}),
    "searchprotocolhost.exe": frozenset({"system32"}),
    "securityhealthservice.exe": frozenset({"system32"}),
    "services.exe": frozenset({"system32"}),
    "sihost.exe": frozenset({"system32"}),
    "smss.exe": frozenset({"system32"}),
    "spoolsv.exe": frozenset({"system32"}),
    "sppsvc.exe": frozenset({"system32"}),
    "svchost.exe": frozenset({"system32"}),
    "taskhostw.exe": frozenset({"system32"}),
    "trustedinstaller.exe": frozenset({"servicing"}),
    "userinit.exe": frozenset({"system32"}),
    "vds.exe": frozenset({"system32"}),
    "vmcompute.exe": frozenset({"system32"}),
    "vmwp.exe": frozenset({"system32"}),
    "wininit.exe": frozenset({"system32"}),
    "winlogon.exe": frozenset({"system32"}),
    "wlanext.exe": frozenset({"system32"}),
    "wmiprvse.exe": frozenset({"system32\\wbem", "syswow64\\wbem"}),
    "wmiapsrv.exe": frozenset({"system32\\wbem", "syswow64\\wbem"}),
    "wudfhost.exe": frozenset({"system32"}),
}


def _windows_root(path: str, supplied: str | None) -> str | None:
    root = supplied or os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if root:
        return ntpath.normcase(ntpath.normpath(root.replace("/", "\\")))
    drive, tail = ntpath.splitdrive(path)
    parts = [part for part in tail.split("\\") if part]
    if drive and parts and parts[0].casefold() == "windows":
        return ntpath.normcase(ntpath.join(drive, "\\", parts[0]))
    return None


def classify_executable(path: str, *, windows_root: str | None = None) -> ProcessCategory:
    """Classify a path; only exact catalog entries can become system processes."""
    normalized = normalize_executable_path(path)
    root = _windows_root(normalized, windows_root)
    if root is None:
        return ProcessCategory.USER
    try:
        relative = ntpath.relpath(normalized, root)
    except ValueError:
        return ProcessCategory.USER
    if relative == ntpath.pardir or relative.startswith(ntpath.pardir + "\\"):
        return ProcessCategory.USER

    relative = relative.casefold()
    executable = ntpath.basename(relative)
    directory = ntpath.dirname(relative)
    if directory in _SYSTEM_LOCATIONS.get(executable, ()):
        return ProcessCategory.SYSTEM
    return ProcessCategory.UNKNOWN


def combine_categories(categories: list[ProcessCategory]) -> ProcessCategory:
    """Classify one application conservatively when it owns several executables."""
    if categories and all(item is ProcessCategory.SYSTEM for item in categories):
        return ProcessCategory.SYSTEM
    if categories and all(item is ProcessCategory.USER for item in categories):
        return ProcessCategory.USER
    return ProcessCategory.UNKNOWN
