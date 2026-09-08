"""Frozen windowed executable: double-click starts tracking, tools stay explicit."""

import multiprocessing
import sys

from time_tracker.main import main, tray_main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if any(arg in sys.argv for arg in ("--version", "--help", "-h", "--init-db")):
        raise SystemExit(main(sys.argv[1:]))
    # tray_main supplies --track; tolerate its explicit form from Windows Run.
    if "--track" in sys.argv:
        sys.argv.remove("--track")
    raise SystemExit(tray_main())
