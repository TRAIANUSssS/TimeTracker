"""Validated request/response contracts for the local dashboard API."""

import re
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_validator

from time_tracker.domain.time_windows import TimeSelection


class Filters(BaseModel):
    date_from: date
    date_to: date
    time_from: str = "00:00"
    time_to: str = "24:00"
    timezone: str

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def iso_date(cls, value):
        if isinstance(value, str) and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("Date must be YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def valid_selection(self):
        try:
            self.selection()
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(str(error)) from error
        return self

    def selection(self):
        return TimeSelection(
            self.date_from, self.date_to, self.time_from, self.time_to, self.timezone
        )


class AppFilters(Filters):
    active_only: bool = True


class TimelineFilters(Filters):
    @model_validator(mode="after")
    def one_day(self):
        if self.date_from != self.date_to:
            raise ValueError("Timeline requires one anchor date")
        return self


class ActivityFilters(Filters):
    @model_validator(mode="after")
    def multiple_days(self):
        if self.date_from == self.date_to:
            raise ValueError("Heatmap requires at least two anchor dates")
        return self


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ignored: StrictBool | None = None
    track_titles: StrictBool | None = None

    @model_validator(mode="after")
    def nonempty_booleans(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("Supply at least one boolean setting; null is not allowed")
        return self


class Application(BaseModel):
    id: int
    name: str
    ignored: bool
    track_titles: bool
    icon_url: str


class AppStats(BaseModel):
    application_id: int
    name: str
    active_ms: int
    running_ms: int
    icon_url: str


class AppsResponse(BaseModel):
    has_tracking_data: bool
    has_running_data: bool
    items: list[AppStats]


class SystemStats(BaseModel):
    active_ms: int
    idle_ms: int
    locked_ms: int
    sleep_ms: int


class ContextSwitches(BaseModel):
    context_switches: int


class Segment(BaseModel):
    started_at: int
    ended_at: int


class ApplicationSegment(Segment):
    type: Literal["application"]
    application_id: int
    name: str
    title: str | None


class OtherSegment(Segment):
    type: Literal["idle", "locked", "sleep", "other_activity", "unknown_activity", "no_data"]


class HourFields(BaseModel):
    day_offset: int
    hour: int
    local_time_from: str
    local_time_to: str
    intensity: float | None


class DateCell(HourFields):
    date: date
    local_date: date
    hour_occurrences: int
    active_ms: int
    window_ms: int
    tracked_ms: int
    status: Literal["data", "no_data", "future", "missing_hour"]


class WeekdayCell(HourFields):
    weekday: int
    sample_days: int
    total_active_ms: int
    total_window_ms: int
    total_tracked_ms: int
    missing_hour_days: int
    repeated_hour_days: int
    average_active_ms: float | None
