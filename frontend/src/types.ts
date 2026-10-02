export type Filters = {
  date_from: string;
  date_to: string;
  time_from: string;
  time_to: string;
  timezone: string;
  active_only: boolean;
  personal_day_start?: string;
  full_day?: string;
};
export type AppRow = {
  application_id: number;
  name: string;
  active_ms: number;
  running_ms: number;
  icon_url: string;
  color?: string | null;
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
  color?: string | null;
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

export type AdvancedApplication = {
  id: number;
  name: string;
  icon_url: string;
  color?: string | null;
  participation?: number | null;
};
export type FocusSession = {
  duration_ms: number;
  started_at: number;
  ended_at: number;
  application: AdvancedApplication;
};
export type AdvancedKpi = {
  has_tracking_data: boolean;
  context_switches: number;
  context_switches_per_active_hour: number | null;
  longest_focus: FocusSession | null;
  average_active_per_day_ms: number | null;
  comparison: {
    has_tracking_data: boolean;
    previous_context_switches: number;
    context_switches_change_percent: number | null;
    previous_switches_per_active_hour: number | null;
    previous_average_active_per_day_ms: number | null;
  };
};
export type AdvancedWeekDay = {
  weekday: number;
  date?: string | null;
  active_ms?: number | null;
  tracked_ms?: number | null;
  status?: "data" | "no_data" | "future" | null;
  average_active_ms?: number | null;
  sample_days?: number | null;
};
export type AdvancedWeekly = {
  mode: "week" | "weekday_average";
  days: AdvancedWeekDay[];
  previous_period_average_ms: number | null;
};
export type DynamicsPoint = {
  start: string;
  end: string;
  label?: string | null;
  end_label?: string | null;
  active_ms: number | null;
  total_active_ms: number | null;
  average_per_day_ms: number | null;
  sample_days: number;
  status: "data" | "no_data" | "future";
};
export type AdvancedDynamics = {
  granularity: "hour" | "day" | "week" | "month";
  points: DynamicsPoint[];
};
export type AdvancedAppRow = AppRow & {
  usage_ratio: number | null;
  launch_count: number;
  average_session_ms: number | null;
  max_session_ms: number | null;
};
export type AdvancedApps = {
  has_tracking_data: boolean;
  items: AdvancedAppRow[];
};
export type Transition = {
  from_application_id: number;
  to_application_id: number;
  count: number;
};
export type AdvancedTransitions = {
  has_tracking_data: boolean;
  top_transitions: Transition[];
  default_applications: AdvancedApplication[];
  selected_applications: AdvancedApplication[];
  applications: AdvancedApplication[];
  matrix: Transition[];
};
