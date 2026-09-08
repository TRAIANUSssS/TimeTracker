import type { Filters } from "./types";
export const palette = [
  "#AFCBFF",
  "#F6A6C1",
  "#A9DFE8",
  "#B9C9F4",
  "#A8E0C2",
  "#F6D999",
  "#B7DCC4",
  "#C3B2EE",
  "#AAB9CE",
  "#D9C7DD",
];
export const appColor = (id: number) => palette[id % palette.length];
export const dayNames = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
export const longDayNames = [
  "Понедельник",
  "Вторник",
  "Среда",
  "Четверг",
  "Пятница",
  "Суббота",
  "Воскресенье",
];
export function duration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms <= 0) return "0 м.";
  if (ms < 60000) return "<1 м.";
  const m = Math.floor(ms / 60000),
    d = Math.floor(m / 1440),
    h = Math.floor((m % 1440) / 60);
  return [d ? `${d} д.` : "", h ? `${h} ч.` : "", m % 60 ? `${m % 60} м.` : ""]
    .filter(Boolean)
    .join(" ");
}
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
export function dateLabel(day: string, year = false) {
  const [y, m, d] = day.split("-");
  return `${d}.${m}${year ? `.${y}` : ""}`;
}
export function defaults(): Filters {
  const today = isoDate(new Date());
  return {
    date_from: today,
    date_to: today,
    time_from: "00:00",
    time_to: "24:00",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    active_only: true,
  };
}
export function dayCount(f: Filters) {
  return (
    Math.round((Date.parse(f.date_to) - Date.parse(f.date_from)) / 86400000) + 1
  );
}
export const minuteValue = (s: string) =>
  Number(s.slice(0, 2)) * 60 + Number(s.slice(3));
export const timeLabel = (n: number) =>
  `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
export function localStamp(
  at: number,
  zone: string,
  withDate = false,
  withOffset = false,
) {
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    ...(withDate ? { day: "2-digit", month: "2-digit" } : {}),
    ...(withOffset ? { timeZoneName: "shortOffset" } : {}),
  }).format(at);
}
export function localDay(at: number, zone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(at);
  return ["year", "month", "day"]
    .map((k) => parts.find((p) => p.type === k)!.value)
    .join("-");
}
