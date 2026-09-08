"""Statistics from one read-only SQLite snapshot and one request timestamp."""

from bisect import bisect_right
from collections import defaultdict

from time_tracker.domain.intervals import Coverage, duration, intersect, union
from time_tracker.domain.time_windows import TimeSelection, time_label


def application_json(app):
    return {
        "id": app["id"],
        "name": app["name"],
        "ignored": bool(app["ignored"]),
        "track_titles": bool(app["track_titles"]),
        "icon_url": f"/applications/{app['id']}/icon",
    }


class Statistics:
    def __init__(self, connection, selection: TimeSelection, now: int):
        self.connection = connection
        self.selection = selection
        self.now = now
        self.cells = selection.cells()
        self.windows = union(w for cell in self.cells for w in cell.windows)
        self.past = intersect(self.windows, [(-(2**63), now)])
        self.lower = self.past[0][0] if self.past else now
        self.upper = self.past[-1][1] if self.past else now
        self.applications = {r["id"]: r for r in connection.execute("SELECT * FROM applications")}
        self.states = self._sessions("system_state_sessions")
        self.by_state = {
            state: intersect(
                [(r["started_at"], r["ended_at"]) for r in self.states if r["state"] == state],
                self.past,
            )
            for state in ("ACTIVE", "IDLE", "LOCKED", "SLEEP")
        }
        self.tracked = Coverage(w for windows in self.by_state.values() for w in windows)
        self.active = Coverage(self.by_state["ACTIVE"])

    def _sessions(self, table):
        # Table identifiers are internal constants, never request inputs.
        if not self.past:
            return []
        rows = self.connection.execute(
            f"SELECT * FROM {table} WHERE started_at < ? "
            "AND COALESCE(ended_at, ?) > ? ORDER BY started_at,id",
            (self.upper, self.now, self.lower),
        )
        return [
            dict(r)
            | {"ended_at": min(r["ended_at"] if r["ended_at"] is not None else self.now, self.now)}
            for r in rows
        ]

    def system(self):
        return {
            f"{state.lower()}_ms": duration(windows) for state, windows in self.by_state.items()
        }

    def apps(self, active_only=True):
        totals = defaultdict(lambda: {"active_ms": 0, "running_ms": 0})
        awake = union(
            w for state, windows in self.by_state.items() if state != "SLEEP" for w in windows
        )
        for table, key, windows in (
            ("foreground_sessions", "active_ms", self.by_state["ACTIVE"]),
            ("application_running_sessions", "running_ms", awake),
        ):
            grouped = defaultdict(list)
            for row in self._sessions(table):
                if not self.applications[row["application_id"]]["ignored"]:
                    grouped[row["application_id"]].append((row["started_at"], row["ended_at"]))
            for app_id, sessions in grouped.items():
                totals[app_id][key] = duration(intersect(sessions, windows))
        sort_key = "active_ms" if active_only else "running_ms"
        items = [
            {
                "application_id": app_id,
                "name": self.applications[app_id]["name"],
                **values,
                "icon_url": f"/applications/{app_id}/icon",
            }
            for app_id, values in totals.items()
            if values[sort_key] > 0
        ]
        items.sort(key=lambda item: (-item[sort_key], item["application_id"]))
        return {
            "has_tracking_data": bool(self.tracked.intervals),
            "has_running_data": any(v["running_ms"] > 0 for v in totals.values()),
            "items": items,
        }

    def timeline(self):
        foreground = self._sessions("foreground_sessions")
        # A sweep handles the three-way intersection and gaps in linear time after sorting.
        points = {t for w in self.past for t in w}
        for row in [*self.states, *foreground]:
            points.update((max(self.lower, row["started_at"]), min(self.upper, row["ended_at"])))
        ordered = sorted(points)
        selected = Coverage(self.past)
        si = fi = 0
        result = []
        for start, end in zip(ordered, ordered[1:], strict=False):
            if not selected.contains(start):
                continue
            while si < len(self.states) and self.states[si]["ended_at"] <= start:
                si += 1
            while fi < len(foreground) and foreground[fi]["ended_at"] <= start:
                fi += 1
            state = (
                self.states[si]
                if si < len(self.states) and self.states[si]["started_at"] <= start
                else None
            )
            fg = (
                foreground[fi]
                if fi < len(foreground) and foreground[fi]["started_at"] <= start
                else None
            )
            data = {"type": "no_data"}
            if state is not None:
                data = {"type": state["state"].lower()}
                if state["state"] == "ACTIVE":
                    data = {"type": "unknown_activity"}
                    if fg is not None:
                        app = self.applications[fg["application_id"]]
                        data = (
                            {"type": "other_activity"}
                            if app["ignored"]
                            else {
                                "type": "application",
                                "application_id": app["id"],
                                "name": app["name"],
                                "title": fg["window_title"],
                            }
                        )
            if (
                result
                and result[-1]["ended_at"] == start
                and {k: v for k, v in result[-1].items() if k not in ("started_at", "ended_at")}
                == data
            ):
                result[-1]["ended_at"] = end
            else:
                result.append(data | {"started_at": start, "ended_at": end})
        return result

    def context_switches(self):
        if not self.past:
            return {"context_switches": 0}
        # Preserve the preceding non-ignored app even if it ended before the filter boundary.
        query = (
            "SELECT f.* FROM foreground_sessions f JOIN applications a "
            "ON a.id=f.application_id WHERE a.ignored=0 AND f.started_at < ? "
            "AND (f.ended_at IS NULL OR f.ended_at > f.started_at) "
        )
        previous = self.connection.execute(
            query + "AND f.started_at < ? ORDER BY f.started_at DESC,f.id DESC LIMIT 1",
            (self.upper, self.lower),
        ).fetchone()
        rows = self.connection.execute(
            query + "AND f.started_at >= ? ORDER BY f.started_at,f.id", (self.upper, self.lower)
        )
        runs = self.connection.execute(
            "SELECT started_at FROM tracker_runs ORDER BY started_at"
        ).fetchall()
        run_starts = [r[0] for r in runs]
        count = 0
        for row in rows:
            at = row["started_at"]
            if row["ended_at"] is not None and row["ended_at"] <= at:
                continue
            if (
                previous is not None
                and previous["application_id"] != row["application_id"]
                and bisect_right(run_starts, previous["started_at"]) == bisect_right(run_starts, at)
                and self.active.contains(at)
            ):
                count += 1
            previous = row
        return {"context_switches": count}

    def activity(self):
        cells = []
        for cell in self.cells:
            window_ms = duration(cell.windows)
            active_ms = self.active.measure(cell.windows)
            tracked_ms = self.tracked.measure(cell.windows)
            status = (
                "missing_hour"
                if not window_ms
                else "data"
                if tracked_ms
                else "no_data"
                if any(s < self.now for s, _ in cell.windows)
                else "future"
            )
            cells.append(
                {
                    "date": cell.date.isoformat(),
                    "day_offset": cell.day_offset,
                    "local_date": cell.local_date.isoformat(),
                    "hour": cell.hour,
                    "local_time_from": time_label(cell.minute_from),
                    "local_time_to": time_label(cell.minute_to),
                    "hour_occurrences": cell.occurrences,
                    "active_ms": active_ms,
                    "window_ms": window_ms,
                    "tracked_ms": tracked_ms,
                    "status": status,
                    "intensity": min(1.0, max(0.0, active_ms / window_ms)) if window_ms else None,
                }
            )
        if self.selection.days <= 14:
            return cells
        groups = defaultdict(list)
        for cell, record in zip(self.cells, cells, strict=True):
            groups[cell.date.isoweekday(), cell.day_offset, cell.hour].append(record)
        result = []
        for (weekday, day_offset, hour), records in sorted(groups.items()):
            samples = sum(r["window_ms"] > 0 for r in records)
            active = sum(r["active_ms"] for r in records)
            window = sum(r["window_ms"] for r in records)
            result.append(
                {
                    "weekday": weekday,
                    "day_offset": day_offset,
                    "hour": hour,
                    "local_time_from": records[0]["local_time_from"],
                    "local_time_to": records[0]["local_time_to"],
                    "sample_days": samples,
                    "total_active_ms": active,
                    "total_window_ms": window,
                    "total_tracked_ms": sum(r["tracked_ms"] for r in records),
                    "missing_hour_days": sum(r["hour_occurrences"] == 0 for r in records),
                    "repeated_hour_days": sum(r["hour_occurrences"] > 1 for r in records),
                    "average_active_ms": active / samples if samples else None,
                    "intensity": min(1.0, max(0.0, active / window)) if window else None,
                }
            )
        return result
