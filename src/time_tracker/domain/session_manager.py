"""Single-owner event processing with atomic persistence and commit-before-publish RAM state."""

import logging
import ntpath
from collections import Counter
from dataclasses import replace
from threading import get_ident

from time_tracker.domain.events import (
    ApplicationSettingsChanged,
    ForegroundChanged,
    ForegroundObservation,
    Heartbeat,
    IdleEnded,
    IdleObserved,
    IdleStarted,
    ProcessesObserved,
    ProcessIdentity,
    ProcessObservation,
    ProcessStarted,
    ProcessStopped,
    SessionLocked,
    SessionUnlocked,
    SystemSleep,
    SystemWake,
    TrackerEvent,
    TrackerSnapshot,
    TrackerStarted,
    TrackerStopping,
)
from time_tracker.domain.identity import normalize_executable_path
from time_tracker.domain.models import Executable, SystemState
from time_tracker.domain.ports import TrackerRepositories, TrackerStore
from time_tracker.domain.system_state import IDLE_THRESHOLD_MS, SystemFlags, idle_reached
from time_tracker.domain.tracker_state import ForegroundRuntime, ProcessRuntime, TrackerState

logger = logging.getLogger(__name__)


class ClockOrderError(ValueError):
    """Lifecycle timestamps would overlap saved history or create negative intervals."""


class SessionManager:
    def __init__(
        self,
        store: TrackerStore,
        *,
        idle_threshold_ms: int = IDLE_THRESHOLD_MS,
        version: str | None = None,
    ) -> None:
        if idle_threshold_ms <= 0:
            raise ValueError("Idle threshold must be positive")
        self._store = store
        self._threshold = idle_threshold_ms
        self._version = version
        self._state: TrackerState | None = None
        self._owner = get_ident()

    @property
    def state(self) -> TrackerState | None:
        """Return an isolated snapshot; callers cannot mutate live runtime dictionaries."""
        self._check_owner()
        return self._state.copy() if self._state is not None else None

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("Send commands to the tracker owner thread")

    def _snapshot_flags(self, snapshot: TrackerSnapshot) -> SystemFlags:
        return SystemFlags(
            is_sleeping=snapshot.is_sleeping,
            is_locked=snapshot.is_locked,
            idle_timeout_reached=idle_reached(
                snapshot.observed_at, snapshot.last_input_at, self._threshold
            ),
        )

    def start(self, snapshot: TrackerSnapshot) -> None:
        """Recover and initialize in one transaction; the runtime must already hold its lock."""
        self._check_owner()
        if self._state is not None:
            raise RuntimeError("Tracker is already started")
        flags = self._snapshot_flags(snapshot)
        at = snapshot.observed_at
        with self._store.transaction() as root:
            latest = root.runs.get_latest()
            if latest is not None and at < max(
                latest.ended_at or latest.recovery_at, latest.recovery_at
            ):
                raise ClockOrderError("Startup precedes the last confirmed history boundary")
            previous = root.runs.get_open()
            if previous is not None:
                recovering = root.for_run(previous.id)
                for sessions in (
                    recovering.processes,
                    recovering.running,
                    recovering.foreground,
                    recovering.system_states,
                ):
                    for session in sessions.list_open():
                        sessions.end(session.id, at=previous.recovery_at)
                recovering.runs.finish(previous.id, at=previous.recovery_at, reason="crash")
            run = root.runs.start(at=at, version=self._version)
            repo = root.for_run(run.id)
            state = TrackerState(
                run=run,
                flags=flags,
                system_session=repo.system_states.start(flags.effective, at=at),
                last_event_at=at,
                last_input_at=snapshot.last_input_at,
                applications={app.id: app for app in repo.applications.list_all()},
            )
            self._reconcile(state, repo, snapshot.processes, at, complete=True)
            self._set_foreground(state, repo, snapshot.foreground, at)
            self._sync_running(state, repo, at)
            self._refresh_run(state, repo)
        self._state = state
        if previous is not None:
            logger.info("Recovered run %s at %s", previous.id, previous.recovery_at)
        logger.info("Started run %s in %s", state.run.id, state.flags.effective)

    def handle(self, event: TrackerEvent) -> bool:
        """Return False for stale observations. Effective idle boundaries may be backdated."""
        self._check_owner()
        if isinstance(event, TrackerStarted):
            self._check_snapshot_time(event.observed_at, event.snapshot)
            self.start(event.snapshot)
            return True
        if self._state is None:
            raise RuntimeError("Tracker is not started")
        if event.observed_at < self._state.last_event_at:
            if isinstance(event, TrackerStopping):
                raise ClockOrderError("Shutdown precedes an accepted event")
            logger.debug("Ignoring stale %s observation", event.kind)
            return False
        state = self._state.copy()
        with self._store.transaction() as root:
            repo = root.for_run(state.run.id)
            if isinstance(event, TrackerStopping):
                self._shutdown(state, repo, event.observed_at)
            else:
                self._dispatch(state, repo, event)
                self._sync_running(state, repo, event.observed_at)
                self._refresh_run(state, repo)
            state.last_event_at = event.observed_at
        if isinstance(event, TrackerStopping):
            self._state = None
            logger.info("Stopped run %s", state.run.id)
        else:
            if self._state.flags.effective != state.flags.effective:
                logger.info("System state changed to %s", state.flags.effective)
            self._state = state
        return True

    @staticmethod
    def _refresh_run(state: TrackerState, repo: TrackerRepositories) -> None:
        run = repo.runs.get(state.run.id)
        if run is None:
            raise RuntimeError("Current run disappeared")
        state.run = run

    @staticmethod
    def _check_snapshot_time(at: int, snapshot: TrackerSnapshot) -> None:
        if snapshot.observed_at != at:
            raise ValueError("Resume/start needs a fresh snapshot with the event timestamp")

    def _dispatch(
        self, state: TrackerState, repo: TrackerRepositories, event: TrackerEvent
    ) -> None:
        at = event.observed_at
        if isinstance(event, (SystemWake, SessionUnlocked)):
            self._check_snapshot_time(at, event.snapshot)
            if isinstance(event, SystemWake) and event.snapshot.is_sleeping:
                raise ValueError("Wake snapshot cannot still be sleeping")
            if isinstance(event, SessionUnlocked) and event.snapshot.is_locked:
                raise ValueError("Unlock snapshot cannot still be locked")
            state.last_input_at = event.snapshot.last_input_at
            self._change_system(state, repo, self._snapshot_flags(event.snapshot), at)
            self._reconcile(state, repo, event.snapshot.processes, at, complete=True)
            self._set_foreground(state, repo, event.snapshot.foreground, at)
        elif isinstance(event, SessionLocked):
            self._change_system(state, repo, replace(state.flags, is_locked=True), at)
        elif isinstance(event, SystemSleep):
            self._change_system(state, repo, replace(state.flags, is_sleeping=True), at)
        elif isinstance(event, IdleObserved):
            idle = idle_reached(at, event.last_input_at, self._threshold)
            if isinstance(event, IdleStarted) and not idle:
                raise ValueError("IDLE_STARTED precedes the idle threshold")
            if isinstance(event, IdleEnded) and idle:
                raise ValueError("IDLE_ENDED requires recent input")
            state.last_input_at = event.last_input_at
            boundary = at
            if idle and state.flags.effective == SystemState.ACTIVE:
                boundary = max(
                    event.last_input_at + self._threshold, state.system_session.started_at
                )
            self._change_system(
                state, repo, replace(state.flags, idle_timeout_reached=idle), boundary
            )
        elif isinstance(event, Heartbeat):
            repo.runs.heartbeat(state.run.id, at=at)
        elif isinstance(event, ApplicationSettingsChanged):
            self._settings(state, repo, event)
        elif isinstance(
            event, (ProcessStarted, ProcessStopped, ProcessesObserved, ForegroundChanged)
        ):
            if state.flags.is_sleeping:
                return  # Resume supplies fresh process/foreground snapshots.
            if isinstance(event, ProcessStarted):
                self._observe_process(state, repo, event.process, at)
            elif isinstance(event, ProcessStopped):
                self._remove_process(state, repo, event.identity, at)
            elif isinstance(event, ProcessesObserved):
                self._reconcile(state, repo, event.processes, at, complete=event.complete)
            else:
                self._set_foreground(state, repo, event.foreground, at)
        else:
            raise TypeError(f"Unsupported tracker event: {type(event).__name__}")

    def _change_system(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        flags: SystemFlags,
        at: int,
    ) -> None:
        if state.system_session.state != flags.effective:
            repo.system_states.end(state.system_session.id, at=at)
            state.system_session = repo.system_states.start(flags.effective, at=at)
        state.flags = flags
        if flags.is_locked or flags.is_sleeping:
            self._clear_foreground(state, repo, at)

    def _executable(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        observation: ProcessObservation,
        at: int,
    ) -> Executable | None:
        if observation.executable_path is None:
            return None
        path = normalize_executable_path(observation.executable_path)
        if path in state.executables:
            return state.executables[path]
        executable = repo.executables.find_by_path(path)
        if executable is None:
            names = (
                observation.file_description,
                observation.product_name,
                ntpath.splitext(ntpath.basename(path))[0],
            )
            name = next(
                (name.strip() for name in names if name and name.strip()), "Unknown application"
            )
            application = repo.applications.create(name, at=at)
            executable = repo.executables.create(application.id, path, at=at)
            state.applications[application.id] = application
        elif executable.application_id not in state.applications:
            application = repo.applications.get(executable.application_id)
            if application is None:
                raise RuntimeError("Executable has no application")
            state.applications[application.id] = application
        state.executables[path] = executable
        return executable

    def _observe_process(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        observation: ProcessObservation,
        at: int,
    ) -> ProcessRuntime:
        identity = observation.identity
        executable = self._executable(state, repo, observation, at)
        for other in list(state.running_processes):
            if other.pid == identity.pid and other != identity:
                self._remove_process(state, repo, other, at)
        current = state.running_processes.get(identity)
        if current is not None:
            if executable is None or (
                current.executable is not None and executable.id == current.executable.id
            ):
                current = replace(current, last_observed_at=at)
                state.running_processes[identity] = current
                return current
            if current.executable is None and identity.creation_time is not None:
                session = repo.processes.resolve_executable(
                    current.session.id,
                    executable_id=executable.id,
                    expected_pid=identity.pid,
                    expected_creation_time=identity.creation_time,
                    at=at,
                )
                current = ProcessRuntime(session, executable.application_id, executable, at)
                state.running_processes[identity] = current
                return current
            # New path, or unknown creation time: no retrospective reassignment.
            self._remove_process(state, repo, identity, at)
        session = repo.processes.start(
            pid=identity.pid,
            process_started_at=identity.creation_time,
            detected_at=at,
            executable_id=executable.id if executable else None,
        )
        current = ProcessRuntime(
            session, executable.application_id if executable else None, executable, at
        )
        state.running_processes[identity] = current
        return current

    def _remove_process(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        identity: ProcessIdentity,
        at: int,
    ) -> None:
        process = state.running_processes.pop(identity, None)
        if process is None:
            return
        if state.foreground is not None and state.foreground.identity == identity:
            self._clear_foreground(state, repo, at)
        repo.processes.end(process.session.id, at=at)
        if process.executable is not None:
            executable = repo.executables.touch(process.executable.id, at=process.last_observed_at)
            state.executables[executable.path] = executable

    def _reconcile(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        observations: tuple[ProcessObservation, ...],
        at: int,
        *,
        complete: bool,
    ) -> None:
        if len({item.identity.pid for item in observations}) != len(observations):
            raise ValueError(
                "A normalized process snapshot must have at most one observation per PID"
            )
        seen = {observation.identity for observation in observations}
        for observation in observations:
            self._observe_process(state, repo, observation, at)
        if complete:
            for identity in list(state.running_processes):
                if identity not in seen:
                    self._remove_process(state, repo, identity, at)

    @staticmethod
    def _sync_running(state: TrackerState, repo: TrackerRepositories, at: int) -> None:
        counts = dict(
            Counter(
                process.application_id
                for process in state.running_processes.values()
                if process.application_id is not None
            )
        )
        for application_id in list(state.open_running_sessions):
            if application_id not in counts:
                session = state.open_running_sessions.pop(application_id)
                repo.running.end(session.id, at=at)
        for application_id in sorted(counts):
            if application_id not in state.open_running_sessions:
                state.open_running_sessions[application_id] = repo.running.start(
                    application_id, at=at
                )
        state.application_process_counts = counts

    @staticmethod
    def _clear_foreground(state: TrackerState, repo: TrackerRepositories, at: int) -> None:
        if state.foreground is not None:
            repo.foreground.end(state.foreground.session.id, at=at)
            state.foreground = None

    def _set_foreground(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        observation: ForegroundObservation | None,
        at: int,
    ) -> None:
        if state.flags.is_locked or state.flags.is_sleeping:
            return
        if observation is None:
            self._clear_foreground(state, repo, at)
            return
        process = self._observe_process(state, repo, observation.process, at)
        if process.executable is None or process.application_id is None:
            self._clear_foreground(state, repo, at)
            return
        app = state.applications[process.application_id]
        title = observation.title if app.track_titles else None
        if state.foreground is not None:
            previous = state.foreground.session
            if (
                previous.application_id,
                previous.executable_id,
                previous.hwnd,
                previous.window_title,
            ) == (app.id, process.executable.id, observation.hwnd, title):
                state.foreground = replace(state.foreground, identity=observation.process.identity)
                return
        self._clear_foreground(state, repo, at)
        state.foreground = ForegroundRuntime(
            observation.process.identity,
            repo.foreground.start(
                app.id,
                at=at,
                executable_id=process.executable.id,
                hwnd=observation.hwnd,
                window_title=title,
            ),
        )

    def _settings(
        self,
        state: TrackerState,
        repo: TrackerRepositories,
        event: ApplicationSettingsChanged,
    ) -> None:
        if event.ignored is None and event.track_titles is None:
            raise ValueError("At least one setting must be supplied")
        for value in (event.ignored, event.track_titles):
            if value is not None and type(value) is not bool:
                raise ValueError("Application settings must be booleans")
        previous = state.applications.get(event.application_id)
        if previous is None:
            raise LookupError("Application does not exist")
        ignored = previous.ignored if event.ignored is None else event.ignored
        titles = previous.track_titles if event.track_titles is None else event.track_titles
        if (ignored, titles) == (previous.ignored, previous.track_titles):
            return
        app = repo.applications.update_settings(
            previous.id, at=event.observed_at, ignored=ignored, track_titles=titles
        )
        state.applications[app.id] = app
        foreground = state.foreground
        if (
            titles != previous.track_titles
            and foreground is not None
            and foreground.session.application_id == app.id
        ):
            self._clear_foreground(state, repo, event.observed_at)
            state.foreground = ForegroundRuntime(
                foreground.identity,
                repo.foreground.start(
                    app.id,
                    at=event.observed_at,
                    executable_id=foreground.session.executable_id,
                    hwnd=foreground.session.hwnd,
                    window_title=None,
                ),
            )

    def _shutdown(self, state: TrackerState, repo: TrackerRepositories, at: int) -> None:
        self._clear_foreground(state, repo, at)
        for identity in list(state.running_processes):
            self._remove_process(state, repo, identity, at)
        self._sync_running(state, repo, at)
        repo.system_states.end(state.system_session.id, at=at)
        repo.runs.finish(state.run.id, at=at, reason="normal")
