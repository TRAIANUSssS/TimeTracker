"""Pure system-state priority and idle-threshold rules."""

from dataclasses import dataclass

from time_tracker.domain.models import SystemState

IDLE_THRESHOLD_MS = 5 * 60 * 1000


@dataclass(frozen=True, slots=True)
class SystemFlags:
    is_sleeping: bool = False
    is_locked: bool = False
    idle_timeout_reached: bool = False

    @property
    def effective(self) -> SystemState:
        if self.is_sleeping:
            return SystemState.SLEEP
        if self.is_locked:
            return SystemState.LOCKED
        if self.idle_timeout_reached:
            return SystemState.IDLE
        return SystemState.ACTIVE


def idle_reached(observed_at: int, last_input_at: int, threshold_ms: int) -> bool:
    if last_input_at > observed_at:
        raise ValueError("Last input cannot be later than its observation")
    return observed_at - last_input_at >= threshold_ms
