"""Bounded, local evidence for the “missing application” troubleshooter."""

import ntpath

import psutil

from time_tracker.domain.identity import normalize_executable_path


def _process_name(pid):
    try:
        return psutil.Process(pid).name() or f"PID {pid}"
    except (psutil.Error, OSError):
        return f"PID {pid}"


def diagnose_process(controller, *, query=None, pid=None, since=None):
    """Compare a direct Windows observation with runtime and persisted state."""
    try:
        observed = controller.provider.processes.snapshot()
        foreground = controller.provider.foreground()
    except (psutil.Error, OSError) as error:
        raise RuntimeError("Не удалось получить список процессов Windows.") from error

    needle = query.casefold().strip() if query is not None else None
    selected = []
    for item in observed:
        process_name = _process_name(item.identity.pid)
        searchable = " ".join(
            value
            for value in (
                process_name,
                item.executable_path,
                item.file_description,
                item.product_name,
            )
            if value
        ).casefold()
        if (pid is not None and item.identity.pid == pid) or (
            needle is not None and needle in searchable
        ):
            selected.append((item, process_name))
    selected = selected[:20]

    state = controller.runtime.state
    now = controller.clock.now_ms()
    result = {
        "observed_at": now,
        "tracking_paused": controller.runtime.tracking_paused,
        "system_state": state.flags.effective.value if state is not None else None,
        "collection": {
            "source": "etw" if controller.process_events is not None else "polling",
            "healthy": controller._event_healthy if controller.process_events is not None else True,
        },
        "foreground_pid": foreground.process.identity.pid if foreground is not None else None,
        "matches": [],
    }
    with controller.runtime.database.reader() as connection:
        for observation, process_name in selected:
            path = observation.executable_path
            if path:
                path = normalize_executable_path(path)
            application = None
            if path:
                application = connection.execute(
                    """SELECT a.id,a.name,a.ignored,e.exe_name
                       FROM executables e JOIN applications a ON a.id=e.application_id
                       WHERE e.path=?""",
                    (path,),
                ).fetchone()
            identity = observation.identity
            runtime_process = None
            if state is not None:
                runtime_process = next(
                    (
                        value
                        for key, value in state.running_processes.items()
                        if key.pid == identity.pid
                        and (
                            identity.creation_time is None
                            or key.creation_time == identity.creation_time
                        )
                    ),
                    None,
                )
            stored = connection.execute(
                "SELECT id,executable_id FROM process_sessions WHERE pid=? "
                "ORDER BY detected_at DESC,id DESC LIMIT 1",
                (identity.pid,),
            ).fetchone()
            foreground_saved = False
            if application is not None and since is not None:
                foreground_saved = (
                    connection.execute(
                        """SELECT 1 FROM foreground_sessions
                           WHERE application_id=? AND started_at < ?
                             AND COALESCE(ended_at, ?) > ? LIMIT 1""",
                        (application["id"], now + 1, now, since),
                    ).fetchone()
                    is not None
                )
            result["matches"].append(
                {
                    "pid": identity.pid,
                    "process_started_at": identity.creation_time,
                    "process_name": process_name,
                    "executable_path": path,
                    "display_name": (
                        application["name"]
                        if application is not None
                        else observation.file_description
                        or observation.product_name
                        or (ntpath.splitext(ntpath.basename(path))[0] if path else process_name)
                    ),
                    "tracker_known": runtime_process is not None,
                    "session_saved": stored is not None,
                    "application_id": application["id"] if application is not None else None,
                    "application_name": application["name"] if application is not None else None,
                    "ignored": bool(application["ignored"]) if application is not None else False,
                    "is_foreground": (
                        foreground is not None and foreground.process.identity.pid == identity.pid
                    ),
                    "foreground_saved_since_start": foreground_saved,
                }
            )
    return result
