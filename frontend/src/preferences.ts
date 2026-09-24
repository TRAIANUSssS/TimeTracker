import { useCallback, useEffect, useRef, useState } from "react";

export type TimeUnits = { days: boolean; hours: boolean; minutes: boolean };
export type Display = {
  time_units: TimeUnits;
  personal_day_start: string;
  timezone: string | null;
};
export type Recording = { tracking_paused: boolean; autostart: boolean | null };
export type Preferences = { display: Display; recording: Recording };
export const defaultDisplay: Display = {
  time_units: { days: true, hours: true, minutes: true },
  personal_day_start: "00:00",
  timezone: null,
};
export const palette = [
  "#F6A6C1",
  "#8CB6EF",
  "#89DCE2",
  "#A6AFE9",
  "#9DD8C4",
  "#F5D879",
  "#98CD98",
  "#C4AFE9",
  "#A2B6C5",
  "#C5A8C9",
  "#F3B184",
  "#EDA39C",
];
export async function request<T>(path: string, changes?: unknown): Promise<T> {
  const response = await fetch(
    path,
    changes === undefined
      ? { cache: "no-store" }
      : {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(changes),
        },
  );
  if (!response.ok) throw new Error("Не удалось сохранить настройку");
  return response.json();
}
export function usePreferences() {
  const [value, setValue] = useState<Preferences | null>(null);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const revision = useRef(0);
  const busy = useRef(false);
  const reload = useCallback(async () => {
    const current = revision.current;
    try {
      const next = await request<Preferences>("/settings/preferences");
      if (current === revision.current && !busy.current) {
        setValue(next);
        setError(false);
      }
    } catch {
      if (current === revision.current) setError(true);
    }
  }, []);
  useEffect(() => {
    void reload();
    const timer = setInterval(() => {
      if (!document.hidden) void reload();
    }, 5000);
    return () => {
      clearInterval(timer);
      revision.current++;
    };
  }, [reload]);
  const save = async (
    section: "display" | "recording",
    changes: Partial<Display> | Partial<Recording>,
  ) => {
    if (busy.current) return;
    revision.current++;
    busy.current = true;
    setSaving(true);
    try {
      const next = await request<Display | Recording>(
        `/settings/${section}`,
        changes,
      );
      setValue((previous) =>
        previous ? { ...previous, [section]: next } : previous,
      );
      setError(false);
    } finally {
      revision.current++;
      busy.current = false;
      setSaving(false);
    }
  };
  return { value, error, saving, reload, save };
}
export type PreferencesState = ReturnType<typeof usePreferences>;
