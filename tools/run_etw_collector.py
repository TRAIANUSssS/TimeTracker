"""Run the standalone collector from a source checkout."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from time_tracker.platform.windows.etw_collector import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
