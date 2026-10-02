"""Statistics from one read-only SQLite snapshot and one request timestamp."""

from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from time_tracker.domain.intervals import Coverage, duration, intersect, union
from time_tracker.domain.time_windows import TimeSelection, time_label


def application_json(app, *, active_ms=0):
    return {
        "id": app["id"],
        "name": app["name"],
        "ignored": bool(app["ignored"]),
        "track_titles": bool(app["track_titles"]),
        "color": app["color"],
        "category": app["category"],
        "icon_url": f"/applications/{app['id']}/icon",
        "active_ms": active_ms,
    }


def application_active_totals(connection, now):
    """Return foreground time that overlaps ACTIVE state, across all saved history."""
    return {
        row["application_id"]: row["active_ms"]
        for row in connection.execute(
            """
            SELECT f.application_id,
                   COALESCE(SUM(
                       MAX(0,
                           MIN(COALESCE(f.ended_at, ?), COALESCE(s.ended_at, ?))
                           - MAX(f.started_at, s.started_at)
                       )
                   ), 0) AS active_ms
            FROM foreground_sessions AS f
            JOIN system_state_sessions AS s
              ON s.state = 'ACTIVE'
             AND s.started_at < COALESCE(f.ended_at, ?)
             AND COALESCE(s.ended_at, ?) > f.started_at
            GROUP BY f.application_id
            """,
            (now, now, now, now),
        )
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

    def _application_totals(self):
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
        return totals

    def apps(self, active_only=True):
        totals = self._application_totals()
        sort_key = "active_ms" if active_only else "running_ms"
        items = [
            {
                "application_id": app_id,
                "name": self.applications[app_id]["name"],
                **values,
                "color": self.applications[app_id]["color"],
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

    def daily_activity(self):
        """Return one record per personal-day anchor without conflating zero and no data."""
        grouped = defaultdict(list)
        for cell in self.cells:
            grouped[cell.date].extend(cell.windows)
        result = []
        day = self.selection.date_from
        while day <= self.selection.date_to:
            windows = union(grouped[day])
            elapsed = intersect(windows, [(-(2**63), self.now)])
            tracked_ms = self.tracked.measure(windows)
            active_ms = self.active.measure(windows)
            if not windows:
                status = "no_data"
            elif not elapsed:
                status = "future"
            elif tracked_ms:
                status = "data"
            else:
                status = "no_data"
            result.append(
                {
                    "date": day.isoformat(),
                    "weekday": day.isoweekday(),
                    "active_ms": active_ms if status == "data" else None,
                    "tracked_ms": tracked_ms,
                    "status": status,
                }
            )
            day += timedelta(days=1)
        return result

    def _daily_average(self):
        observed = [day for day in self.daily_activity() if day["status"] == "data"]
        if not observed:
            return None
        return round(sum(day["active_ms"] for day in observed) / len(observed))

    def longest_focus(self):
        """Longest ACTIVE foreground run in one app, split at personal-day boundaries."""
        grouped = defaultdict(list)
        for row in self._sessions("foreground_sessions"):
            app = self.applications[row["application_id"]]
            if not app["ignored"]:
                grouped[row["application_id"]].append((row["started_at"], row["ended_at"]))
        day_windows = defaultdict(list)
        for cell in self.cells:
            day_windows[cell.date].extend(cell.windows)
        best = None
        for windows in day_windows.values():
            eligible = intersect(windows, self.by_state["ACTIVE"])
            for app_id, sessions in grouped.items():
                for start, end in intersect(sessions, eligible):
                    candidate = {
                        "duration_ms": end - start,
                        "started_at": start,
                        "ended_at": end,
                        "application": {
                            "id": app_id,
                            "name": self.applications[app_id]["name"],
                            "icon_url": f"/applications/{app_id}/icon",
                        },
                    }
                    if best is None or candidate["duration_ms"] > best["duration_ms"]:
                        best = candidate
        return best

    def advanced_kpi(self, previous):
        switches = self.context_switches()["context_switches"]
        active_ms = self.system()["active_ms"]
        previous_switches = (
            previous.context_switches()["context_switches"] if previous else 0
        )
        previous_active_ms = previous.system()["active_ms"] if previous else 0
        previous_average = previous._daily_average() if previous else None

        def per_hour(count, active):
            return round(count / (active / 3_600_000), 1) if active else None

        return {
            "has_tracking_data": bool(self.tracked.intervals),
            "context_switches": switches,
            "context_switches_per_active_hour": per_hour(switches, active_ms),
            "longest_focus": self.longest_focus(),
            "average_active_per_day_ms": self._daily_average(),
            "comparison": {
                "has_tracking_data": bool(previous and previous.tracked.intervals),
                "previous_context_switches": previous_switches,
                "context_switches_change_percent": (
                    round((switches - previous_switches) / previous_switches * 100, 1)
                    if previous_switches
                    else None
                ),
                "previous_switches_per_active_hour": per_hour(
                    previous_switches, previous_active_ms
                ),
                "previous_average_active_per_day_ms": previous_average,
            },
        }

    def advanced_weekly(self, previous):
        records = self.daily_activity()
        previous_average = previous._daily_average() if previous else None
        if self.selection.days <= 7:
            return {
                "mode": "week",
                "days": records,
                "previous_period_average_ms": previous_average,
            }
        grouped = defaultdict(list)
        for record in records:
            grouped[record["weekday"]].append(record)
        days = []
        for weekday in range(1, 8):
            observed = [r for r in grouped[weekday] if r["status"] == "data"]
            days.append(
                {
                    "weekday": weekday,
                    "average_active_ms": (
                        round(sum(r["active_ms"] for r in observed) / len(observed))
                        if observed
                        else None
                    ),
                    "sample_days": len(observed),
                }
            )
        return {
            "mode": "weekday_average",
            "days": days,
            "previous_period_average_ms": previous_average,
        }

    def advanced_dynamics(self):
        if self.selection.days == 1:
            points = []
            for cell in self.cells:
                windows = union(cell.windows)
                elapsed = intersect(windows, [(-(2**63), self.now)])
                tracked_ms = self.tracked.measure(windows)
                active_ms = self.active.measure(windows)
                if not windows:
                    status = "no_data"
                elif not elapsed:
                    status = "future"
                elif tracked_ms:
                    status = "data"
                else:
                    status = "no_data"

                start_label = time_label(cell.minute_from)
                if cell.minute_to == 1440:
                    end_date = cell.local_date + timedelta(days=1)
                    end_label = "00:00"
                else:
                    end_date = cell.local_date
                    end_label = time_label(cell.minute_to)
                points.append(
                    {
                        "start": f"{cell.local_date.isoformat()}T{start_label}",
                        "end": f"{end_date.isoformat()}T{end_label}",
                        "label": start_label,
                        "end_label": end_label,
                        "active_ms": active_ms if status == "data" else None,
                        "total_active_ms": active_ms if status == "data" else None,
                        "average_per_day_ms": None,
                        "sample_days": 1 if status == "data" else 0,
                        "status": status,
                    }
                )
            return {"granularity": "hour", "points": points}

        records = self.daily_activity()
        days = self.selection.days
        granularity = "day" if days <= 31 else "week" if days <= 183 else "month"
        grouped = defaultdict(list)
        bounds = {}
        for record in records:
            day = date.fromisoformat(record["date"])
            if granularity == "day":
                key = day
                start, end = day, day + timedelta(days=1)
            elif granularity == "week":
                start = day - timedelta(days=day.weekday())
                end = start + timedelta(days=7)
                key = start
            else:
                start = day.replace(day=1)
                end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
                key = start
            grouped[key].append(record)
            bounds[key] = (start, end)
        points = []
        for key, bucket in sorted(grouped.items()):
            observed = [r for r in bucket if r["status"] == "data"]
            total = sum(r["active_ms"] for r in observed)
            status = (
                "data"
                if observed
                else "future"
                if all(r["status"] == "future" for r in bucket)
                else "no_data"
            )
            start, end = bounds[key]
            points.append(
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "active_ms": total if status == "data" else None,
                    "total_active_ms": total if status == "data" else None,
                    "average_per_day_ms": round(total / len(observed)) if observed else None,
                    "sample_days": len(observed),
                    "status": status,
                }
            )
        return {"granularity": granularity, "points": points}

    def advanced_apps(self):
        totals = self._application_totals()
        sessions = defaultdict(list)
        selected = Coverage(self.past)
        for row in self._sessions("application_running_sessions"):
            app = self.applications[row["application_id"]]
            if (
                not app["ignored"]
                and row["ended_at"] > row["started_at"]
                and selected.contains(row["started_at"])
            ):
                sessions[row["application_id"]].append(row["ended_at"] - row["started_at"])
        app_ids = set(totals) | set(sessions)
        items = []
        for app_id in app_ids:
            app = self.applications[app_id]
            if app["ignored"]:
                continue
            values = totals[app_id]
            durations = sessions[app_id]
            if not any((*values.values(), len(durations))):
                continue
            items.append(
                {
                    "application_id": app_id,
                    "name": app["name"],
                    "icon_url": f"/applications/{app_id}/icon",
                    "color": app["color"],
                    **values,
                    "usage_ratio": (
                        values["active_ms"] / values["running_ms"]
                        if values["running_ms"]
                        else None
                    ),
                    "launch_count": len(durations),
                    "average_session_ms": (
                        round(sum(durations) / len(durations)) if durations else None
                    ),
                    "max_session_ms": max(durations) if durations else None,
                }
            )
        items.sort(key=lambda item: (-item["active_ms"], item["application_id"]))
        return {"has_tracking_data": bool(self.tracked.intervals), "items": items}

    def _transition_counts(self):
        if not self.past:
            return {}
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
        run_starts = [
            row[0]
            for row in self.connection.execute(
                "SELECT started_at FROM tracker_runs ORDER BY started_at"
            )
        ]
        counts = defaultdict(int)
        for row in rows:
            at = row["started_at"]
            if row["ended_at"] is not None and row["ended_at"] <= at:
                continue
            if (
                previous is not None
                and previous["application_id"] != row["application_id"]
                and bisect_right(run_starts, previous["started_at"])
                == bisect_right(run_starts, at)
                and self.active.contains(at)
            ):
                counts[(previous["application_id"], row["application_id"])] += 1
            previous = row
        return dict(counts)

    def advanced_transitions(self, application_ids=None):
        if application_ids:
            if len(application_ids) > 10 or len(set(application_ids)) != len(application_ids):
                raise ValueError("Choose up to ten distinct applications")
            if any(
                app_id not in self.applications or self.applications[app_id]["ignored"]
                for app_id in application_ids
            ):
                raise ValueError("Choose existing non-ignored applications")
        counts = self._transition_counts()
        participation = defaultdict(int)
        for (source, target), count in counts.items():
            participation[source] += count
            participation[target] += count
        default_ids = sorted(
            participation, key=lambda app_id: (-participation[app_id], app_id)
        )[:10]
        selected_ids = default_ids if not application_ids else application_ids

        def app_json(app_id):
            app = self.applications[app_id]
            return {
                "id": app_id,
                "name": app["name"],
                "icon_url": f"/applications/{app_id}/icon",
                "color": app["color"],
                "participation": participation[app_id],
            }

        pairs = [
            {"from_application_id": source, "to_application_id": target, "count": count}
            for (source, target), count in counts.items()
        ]
        pairs.sort(
            key=lambda item: (
                -item["count"],
                item["from_application_id"],
                item["to_application_id"],
            )
        )
        selected_set = set(selected_ids)
        candidates = [
            app_json(app_id)
            for app_id, app in self.applications.items()
            if not app["ignored"]
        ]
        candidates.sort(key=lambda app: (app["name"].casefold(), app["id"]))
        return {
            "has_tracking_data": bool(self.tracked.intervals),
            "top_transitions": pairs[:3],
            "default_applications": [app_json(app_id) for app_id in default_ids],
            "selected_applications": [app_json(app_id) for app_id in selected_ids],
            "applications": candidates,
            "matrix": [
                pair
                for pair in pairs
                if pair["from_application_id"] in selected_set
                and pair["to_application_id"] in selected_set
            ],
        }

    def timeline(self, *, include_titles=True):
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
                                "title": fg["window_title"] if include_titles else None,
                                "color": app["color"],
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
        return {"context_switches": sum(self._transition_counts().values())}

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
