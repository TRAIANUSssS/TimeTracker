"""Persist process catalog classifications without changing user visibility choices."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from time_tracker.domain.process_catalog import (
    CATALOG_VERSION,
    classify_executable,
    combine_categories,
)


def refresh_process_catalog(
    connection: sqlite3.Connection, *, windows_root: str | None = None
) -> int:
    paths: dict[int, list[str]] = defaultdict(list)
    for row in connection.execute("SELECT application_id,path FROM executables ORDER BY id"):
        paths[row["application_id"]].append(row["path"])

    changed = 0
    for row in connection.execute(
        "SELECT id,category,catalog_version FROM applications ORDER BY id"
    ).fetchall():
        if not paths.get(row["id"]):
            continue
        category = combine_categories(
            [
                classify_executable(path, windows_root=windows_root)
                for path in paths.get(row["id"], ())
            ]
        )
        if row["category"] == category and row["catalog_version"] == CATALOG_VERSION:
            continue
        connection.execute(
            "UPDATE applications SET category=?,catalog_version=? WHERE id=?",
            (category, CATALOG_VERSION, row["id"]),
        )
        changed += 1
    return changed
