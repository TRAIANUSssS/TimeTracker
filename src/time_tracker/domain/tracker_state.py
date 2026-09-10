"""Runtime caches copied before each atomic event; persisted records are immutable."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from time_tracker.diagnostics.performance import measured
from time_tracker.domain.events import ProcessIdentity
from time_tracker.domain.models import (
    Application,
    ApplicationRunningSession,
    Executable,
    ForegroundSession,
    ProcessSession,
    SystemStateSession,
    TrackerRun,
)
from time_tracker.domain.system_state import SystemFlags


@dataclass(frozen=True, slots=True)
class ProcessRuntime:
    session: ProcessSession
    application_id: int | None
    executable: Executable | None
    last_observed_at: int


@dataclass(frozen=True, slots=True)
class ForegroundRuntime:
    identity: ProcessIdentity
    session: ForegroundSession


@dataclass(slots=True)
class TrackerState:
    run: TrackerRun
    flags: SystemFlags
    system_session: SystemStateSession
    last_event_at: int
    last_input_at: int
    last_process_snapshot_at: int = 0
    foreground: ForegroundRuntime | None = None
    running_processes: dict[ProcessIdentity, ProcessRuntime] = field(default_factory=dict)
    application_process_counts: dict[int, int] = field(default_factory=dict)
    open_running_sessions: dict[int, ApplicationRunningSession] = field(default_factory=dict)
    applications: dict[int, Application] = field(default_factory=dict)
    executables: dict[str, Executable] = field(default_factory=dict)

    @measured("state.copy")
    def copy(self) -> TrackerState:
        return replace(
            self,
            running_processes=self.running_processes.copy(),
            application_process_counts=self.application_process_counts.copy(),
            open_running_sessions=self.open_running_sessions.copy(),
            applications=self.applications.copy(),
            executables=self.executables.copy(),
        )
