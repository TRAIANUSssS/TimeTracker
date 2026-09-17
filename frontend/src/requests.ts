import { useEffect, useRef, useState } from "react";
import { dayCount } from "./format";
import type { Activity, Apps, Filters, System } from "./types";

export type Resource<T> = {
  data: T | null;
  pending: boolean;
  refreshing: boolean;
  delayed: boolean;
  error: boolean;
  key: string;
};
export class LatestRequest {
  private generation = 0;
  private controller?: AbortController;
  cancel() {
    this.generation++;
    this.controller?.abort();
  }
  async run<T>(
    work: (signal: AbortSignal) => Promise<T>,
    commit: (data: T) => void,
    fail: () => void,
  ) {
    this.cancel();
    const generation = this.generation;
    const controller = (this.controller = new AbortController());
    try {
      const data = await work(controller.signal);
      if (generation === this.generation) commit(data);
    } catch {
      if (generation === this.generation) fail();
    }
  }
}
function useResource<T>(
  key: string,
  work: (signal: AbortSignal) => Promise<T>,
  background = false,
): Resource<T> {
  const [state, setState] = useState<Resource<T>>({
    data: null,
    pending: true,
    refreshing: false,
    delayed: false,
    error: false,
    key: "",
  });
  const gate = useRef(new LatestRequest());
  useEffect(() => {
    setState((s) => ({
      ...s,
      pending: !background || s.data === null,
      refreshing: background && s.data !== null,
      delayed: false,
      error: false,
      key,
    }));
    const timer = background
      ? undefined
      : setTimeout(
          () =>
            setState((s) =>
              s.key === key && s.pending ? { ...s, delayed: true } : s,
            ),
          150,
        );
    void gate.current.run(
      work,
      (data) => {
        if (timer) clearTimeout(timer);
        setState({
          data,
          pending: false,
          refreshing: false,
          delayed: false,
          error: false,
          key,
        });
      },
      () => {
        if (timer) clearTimeout(timer);
        setState((s) => ({
          ...s,
          pending: false,
          refreshing: false,
          delayed: false,
          error: background && s.data !== null ? false : true,
          key,
        }));
      },
    );
    const current = gate.current;
    return () => {
      if (timer) clearTimeout(timer);
      current.cancel();
    };
  }, [key]); // Key includes every request parameter; work is deliberately captured for this generation.
  return state.key === key
    ? state
    : {
        ...state,
        pending: true,
        refreshing: false,
        delayed: false,
        error: false,
      };
}
async function get(path: string, signal: AbortSignal) {
  const response = await fetch(path, { signal, cache: "no-store" });
  if (!response.ok) throw new Error("Request failed");
  return response;
}
export function useDashboard(f: Filters, refresh: number, background = false) {
  const { active_only, ...base } = f;
  const query = new URLSearchParams(base).toString(),
    key = `${query}&refresh=${refresh}`;
  const mode =
    dayCount(f) === 1 ? "timeline" : dayCount(f) <= 14 ? "dates" : "weekdays";
  const apps = useResource<Apps & { activeOnly: boolean }>(
    `${key}&active_only=${active_only}`,
    async (signal) => ({
      ...(await (
        await get(`/stats/apps?${query}&active_only=${active_only}`, signal)
      ).json()),
      activeOnly: active_only,
    }),
    background,
  );
  const system = useResource<System>(
    key,
    async (signal) => (await get(`/stats/system?${query}`, signal)).json(),
    background,
  );
  const activity = useResource<Activity>(
    key,
    async (signal) => {
      const response = await get(
        `/stats/${mode === "timeline" ? "timeline" : "activity"}?${query}`,
        signal,
      );
      const data = await response.json();
      return {
        mode,
        segments: mode === "timeline" ? data : [],
        cells: mode === "timeline" ? [] : data,
        windows: JSON.parse(
          response.headers.get("X-TimeTracker-Windows") || "[]",
        ),
        timezone: f.timezone,
      };
    },
    background,
  );
  return {
    apps,
    system,
    activity,
    mode,
    pending: apps.pending || system.pending || activity.pending,
  };
}
