"""Development entry point; application services will be wired here later."""

import argparse

from time_tracker import __version__


def main() -> int:
    """Check the installed scaffold without starting tracking or creating data."""
    parser = argparse.ArgumentParser(
        prog="time-tracker",
        description="TimeTracker project scaffold. Tracking is not implemented yet.",
    )
    parser.add_argument("--version", action="version", version=f"TimeTracker {__version__}")
    parser.parse_args()
    print("TimeTracker scaffold is ready. Tracking and dashboard are not implemented yet.")
    return 0
