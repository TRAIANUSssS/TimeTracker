export type Filters = {
  date_from: string;
  date_to: string;
  time_from: string;
  time_to: string;
  timezone: string;
  active_only: boolean;
};
export type AppRow = {
  application_id: number;
  name: string;
  active_ms: number;
  running_ms: number;
  icon_url: string;
};
export type Apps = {
  has_tracking_data: boolean;
  has_running_data: boolean;
  items: AppRow[];
};
export type System = {
  active_ms: number;
  idle_ms: number;
  locked_ms: number;
  sleep_ms: number;
};
export type Segment = {
  type: string;
  started_at: number;
  ended_at: number;
  application_id?: number;
  name?: string;
  title?: string | null;
};
export type Cell = {
  date?: string;
  local_date?: string;
  weekday?: number;
  day_offset: number;
  hour: number;
  local_time_from: string;
  local_time_to: string;
  intensity: number | null;
  hour_occurrences?: number;
  active_ms?: number;
  window_ms?: number;
  tracked_ms?: number;
  status?: string;
  sample_days?: number;
  total_active_ms?: number;
  total_window_ms?: number;
  total_tracked_ms?: number;
  average_active_ms?: number | null;
  missing_hour_days?: number;
  repeated_hour_days?: number;
};
export type Activity = {
  mode: "timeline" | "dates" | "weekdays";
  segments: Segment[];
  cells: Cell[];
  windows: [number, number][];
  timezone: string;
};
