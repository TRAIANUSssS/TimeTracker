"""Normalized observations and commands; OS adapters do not write history directly."""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    creation_time: int | None
    observation_token: str | None = None

    def __post_init__(self) -> None:
        if self.pid < 0:
            raise ValueError("PID cannot be negative")
        if self.creation_time is None and not self.observation_token:
            raise ValueError("Unknown creation time needs a token for this continuous observation")
        if self.creation_time is not None and self.observation_token is not None:
            raise ValueError("Known process identity uses PID and creation time only")


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    identity: ProcessIdentity
    executable_path: str | None = None
    file_description: str | None = None
    product_name: str | None = None


@dataclass(frozen=True, slots=True)
class ForegroundObservation:
    process: ProcessObservation
    hwnd: int | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class TrackerSnapshot:
    observed_at: int
    processes: tuple[ProcessObservation, ...]
    foreground: ForegroundObservation | None
    last_input_at: int
    is_locked: bool = False
    is_sleeping: bool = False


class EventType(StrEnum):
    TRACKER_STARTED = "TRACKER_STARTED"
    TRACKER_STOPPING = "TRACKER_STOPPING"
    PROCESS_STARTED = "PROCESS_STARTED"
    PROCESS_STOPPED = "PROCESS_STOPPED"
    PROCESSES_OBSERVED = "PROCESSES_OBSERVED"
    FOREGROUND_CHANGED = "FOREGROUND_CHANGED"
    IDLE_OBSERVED = "IDLE_OBSERVED"
    IDLE_STARTED = "IDLE_STARTED"
    IDLE_ENDED = "IDLE_ENDED"
    SESSION_LOCKED = "SESSION_LOCKED"
    SESSION_UNLOCKED = "SESSION_UNLOCKED"
    SYSTEM_SLEEP = "SYSTEM_SLEEP"
    SYSTEM_WAKE = "SYSTEM_WAKE"
    SYSTEM_RESUMED = "SYSTEM_RESUMED"
    RESUME_NOTIFIED = "RESUME_NOTIFIED"
    SLEEP_PERIOD_RECORDED = "SLEEP_PERIOD_RECORDED"
    HEARTBEAT = "HEARTBEAT"
    APPLICATION_SETTINGS_CHANGED = "APPLICATION_SETTINGS_CHANGED"


@dataclass(frozen=True, slots=True)
class TrackerEvent:
    observed_at: int
    kind: ClassVar[EventType]


@dataclass(frozen=True, slots=True)
class TrackerStarted(TrackerEvent):
    snapshot: TrackerSnapshot
    kind: ClassVar[EventType] = EventType.TRACKER_STARTED


@dataclass(frozen=True, slots=True)
class TrackerStopping(TrackerEvent):
    kind: ClassVar[EventType] = EventType.TRACKER_STOPPING


@dataclass(frozen=True, slots=True)
class ProcessStarted(TrackerEvent):
    process: ProcessObservation
    kind: ClassVar[EventType] = EventType.PROCESS_STARTED


@dataclass(frozen=True, slots=True)
class ProcessStopped(TrackerEvent):
    identity: ProcessIdentity
    kind: ClassVar[EventType] = EventType.PROCESS_STOPPED


@dataclass(frozen=True, slots=True)
class ProcessesObserved(TrackerEvent):
    processes: tuple[ProcessObservation, ...]
    complete: bool = True
    kind: ClassVar[EventType] = EventType.PROCESSES_OBSERVED


@dataclass(frozen=True, slots=True)
class ForegroundChanged(TrackerEvent):
    foreground: ForegroundObservation | None
    kind: ClassVar[EventType] = EventType.FOREGROUND_CHANGED


@dataclass(frozen=True, slots=True)
class IdleObserved(TrackerEvent):
    last_input_at: int
    kind: ClassVar[EventType] = EventType.IDLE_OBSERVED


@dataclass(frozen=True, slots=True)
class IdleStarted(IdleObserved):
    kind: ClassVar[EventType] = EventType.IDLE_STARTED


@dataclass(frozen=True, slots=True)
class IdleEnded(IdleObserved):
    kind: ClassVar[EventType] = EventType.IDLE_ENDED


@dataclass(frozen=True, slots=True)
class SessionLocked(TrackerEvent):
    kind: ClassVar[EventType] = EventType.SESSION_LOCKED


@dataclass(frozen=True, slots=True)
class SystemSleep(TrackerEvent):
    kind: ClassVar[EventType] = EventType.SYSTEM_SLEEP


@dataclass(frozen=True, slots=True)
class SessionUnlocked(TrackerEvent):
    snapshot: TrackerSnapshot
    kind: ClassVar[EventType] = EventType.SESSION_UNLOCKED


@dataclass(frozen=True, slots=True)
class SystemWake(TrackerEvent):
    snapshot: TrackerSnapshot
    kind: ClassVar[EventType] = EventType.SYSTEM_WAKE


@dataclass(frozen=True, slots=True)
class SystemResumed(TrackerEvent):
    """Fresh user state, before the slower process/foreground snapshot is ready."""

    snapshot: TrackerSnapshot
    kind: ClassVar[EventType] = EventType.SYSTEM_RESUMED


@dataclass(frozen=True, slots=True)
class ResumeNotified(TrackerEvent):
    """Native resume boundary; retain unknown user state until a fresh observation."""

    unlocked: bool = False
    kind: ClassVar[EventType] = EventType.RESUME_NOTIFIED


@dataclass(frozen=True, slots=True)
class SleepPeriodRecorded(TrackerEvent):
    """A completed OS sleep interval received after its actual boundaries."""

    started_at: int
    ended_at: int
    kind: ClassVar[EventType] = EventType.SLEEP_PERIOD_RECORDED


@dataclass(frozen=True, slots=True)
class Heartbeat(TrackerEvent):
    kind: ClassVar[EventType] = EventType.HEARTBEAT


@dataclass(frozen=True, slots=True)
class ApplicationSettingsChanged(TrackerEvent):
    application_id: int
    ignored: bool | None = None
    track_titles: bool | None = None
    kind: ClassVar[EventType] = EventType.APPLICATION_SETTINGS_CHANGED
