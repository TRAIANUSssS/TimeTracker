"""Immutable storage records. All timestamps are UTC Unix milliseconds."""

from dataclasses import dataclass
from enum import StrEnum


class SystemState(StrEnum):
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    LOCKED = "LOCKED"
    SLEEP = "SLEEP"


@dataclass(frozen=True, slots=True)
class Application:
    id: int
    name: str
    ignored: bool
    track_titles: bool
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class Executable:
    id: int
    application_id: int
    path: str
    exe_name: str
    first_seen_at: int
    last_seen_at: int


@dataclass(frozen=True, slots=True)
class ProcessSession:
    id: int
    executable_id: int | None
    pid: int
    process_started_at: int | None
    detected_at: int
    ended_at: int | None


@dataclass(frozen=True, slots=True)
class ApplicationRunningSession:
    id: int
    application_id: int
    started_at: int
    ended_at: int | None


@dataclass(frozen=True, slots=True)
class ForegroundSession:
    id: int
    application_id: int
    executable_id: int | None
    hwnd: int | None
    window_title: str | None
    started_at: int
    ended_at: int | None


@dataclass(frozen=True, slots=True)
class SystemStateSession:
    id: int
    state: SystemState
    started_at: int
    ended_at: int | None


@dataclass(frozen=True, slots=True)
class TrackerRun:
    id: int
    started_at: int
    last_heartbeat_at: int
    last_persisted_at: int
    ended_at: int | None
    exit_reason: str | None
    version: str | None

    @property
    def recovery_at(self) -> int:
        return max(self.last_heartbeat_at, self.last_persisted_at)


@dataclass(frozen=True, slots=True)
class ApplicationAlias:
    application_id: int
    canonical_application_id: int
    created_at: int
