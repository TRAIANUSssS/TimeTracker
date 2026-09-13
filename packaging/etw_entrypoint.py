"""Standalone helper; no dashboard, SQLite, or application settings under SYSTEM."""

import multiprocessing

from time_tracker.platform.windows.etw_setup import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
