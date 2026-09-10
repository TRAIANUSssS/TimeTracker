"""Windows executable identity rules usable without importing Windows APIs."""

import ntpath
from pathlib import PureWindowsPath


def process_creation_ms(unix_ns: int) -> int:
    """Match psutil Windows: Unix 100-ns ticks -> double seconds -> rounded ms."""
    return round(float(unix_ns // 100) / 10_000_000 * 1000)


def normalize_executable_path(path: str) -> str:
    """Normalize known absolute Windows paths; never invent a path for unknown processes."""
    if not path or "\x00" in path:
        raise ValueError("An executable needs a nonempty path without null characters")
    path = path.replace("/", "\\")
    if path.lower().startswith("\\\\?\\unc\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    if path.startswith("\\\\.\\") or not PureWindowsPath(path).is_absolute():
        raise ValueError("An executable needs an absolute drive or UNC path")
    normalized = ntpath.normcase(ntpath.normpath(path))
    if not PureWindowsPath(normalized).name:
        raise ValueError("An executable path must include a filename")
    return normalized
