"""An OS-owned lock per database, released automatically when the process exits."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


class AlreadyRunningError(RuntimeError):
    """Another tracker owns this database's runtime lock."""


class InstanceLock:
    def __init__(self, database_path: Path) -> None:
        database_path = database_path.expanduser().resolve()
        self.path = database_path.with_name(database_path.name + ".lock")
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        if self._file is not None:
            raise AlreadyRunningError("This runtime already owns the database lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise AlreadyRunningError("A tracker is already using this database") from error
            raise
        except BaseException:
            handle.close()
            raise
        self._file = handle

    def release(self) -> None:
        if self._file is not None:
            handle, self._file = self._file, None
            handle.close()
        # Keep the lock file: deleting it can let two processes lock different inodes.

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
