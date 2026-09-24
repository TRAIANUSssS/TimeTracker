import type { Filters } from "./types";
import { defaultDisplay } from "./preferences";
import type { Display, TimeUnits } from "./preferences";
let display: Display = defaultDisplay;
export function configureFormat(value: Display) {
  display = value;
}
export function personalToday(
  now = new Date(),
  start = display.personal_day_start,
  zone = display.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
) {
  const day = localDay(now.getTime(), zone);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(now);
  const date = new Date(`${day}T12:00:00`);
  if (minuteValue(parts) < minuteValue(start)) date.setDate(date.getDate() - 1);
  return isoDate(date);
}
// Golden-angle spacing assigns every newly seen application a durable, distinct hue.
// Unlike a short palette, it does not start repeating when the app catalogue grows.
export const appColor = (id: number) =>
  `hsl(${(id * 137.508 + 338) % 360} 62% 72%)`;

export function isLockApplication(name: string | undefined) {
  return [
    "lockapp",
    "lockapp.exe",
    "lockscreen",
    "lockscreen.exe",
    "блокировка",
  ].includes(name?.trim().toLowerCase() || "");
}
export function applicationName(name: string | undefined) {
  return isLockApplication(name) ? "Блокировка" : name;
}
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
export function duration(
  ms: number | null | undefined,
  units: TimeUnits = display.time_units,
): string {
  if (ms == null) return "—";
  const selected = (
    [
      ["days", 86400000, "д."],
      ["hours", 3600000, "ч."],
      ["minutes", 60000, "м."],
    ] as const
  ).filter(([key]) => units[key]);
  if (!selected.length) return duration(ms, defaultDisplay.time_units);
  const smallest = selected[selected.length - 1];
  if (ms <= 0) return `0 ${smallest[2]}`;
  let smallestValue = ms / smallest[1];
  if (selected.length > 1) {
    let remainder = ms;
    for (const [, size] of selected.slice(0, -1)) {
      remainder -= Math.floor(remainder / size) * size;
    }
    smallestValue = remainder / smallest[1];
  }
  const fractionStep =
    selected.length === 1
      ? smallestValue < 10
        ? 0.1
        : 1
      : smallestValue > 1
        ? 1
        : 0.1;
  let remaining =
    Math.round(ms / (smallest[1] * fractionStep)) * smallest[1] * fractionStep;
  if (remaining === 0) return `<0,1 ${smallest[2]}`;
  return selected
    .map(([, size, label], index) => {
      const value =
        index === selected.length - 1
          ? remaining / size
          : Math.floor(remaining / size);
      remaining -= value * size;
      return value > 0
        ? `${value.toLocaleString("ru-RU", {
            maximumFractionDigits:
              index === selected.length - 1 && fractionStep < 1 ? 1 : 0,
          })} ${label}`
        : "";
    })
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
  const today = personalToday();
  return {
    date_from: today,
    date_to: today,
    time_from: display.personal_day_start,
    time_to:
      display.personal_day_start === "00:00"
        ? "24:00"
        : display.personal_day_start,
    timezone:
      display.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
    personal_day_start: display.personal_day_start,
    full_day: "true",
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
