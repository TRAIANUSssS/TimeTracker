import { useState } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import {
  appColor,
  dateLabel,
  dayNames,
  duration,
  localDay,
  localStamp,
  longDayNames,
} from "./format";
import type { Activity, Cell, Segment } from "./types";

const names: Record<string, string> = {
  idle: "Нет активности",
  locked: "Компьютер заблокирован",
  sleep: "Режим сна",
  other_activity: "Другая активность",
  unknown_activity: "Неизвестное приложение",
  no_data: "Нет данных",
};
const colors: Record<string, string> = {
  idle: "#E7E9ED",
  locked: "#DDD4DA",
  sleep: "#F0F1F3",
  other_activity: "#D8DCE3",
  unknown_activity: "#C8CCD4",
};
export function Tip({
  children,
  content,
  className = "",
  style = {},
}: {
  children?: ReactNode;
  content: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [position, setPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const show = (element: HTMLElement) => {
    const r = element.getBoundingClientRect();
    setPosition({
      left: Math.max(
        12,
        Math.min(window.innerWidth - 334, r.left + r.width / 2 - 160),
      ),
      top:
        r.bottom + 150 > window.innerHeight
          ? Math.max(12, r.top - 148)
          : r.bottom + 10,
    });
  };
  return (
    <span
      className={`tip-target ${className}`}
      style={style}
      tabIndex={0}
      onMouseEnter={(e) => show(e.currentTarget)}
      onMouseLeave={() => setPosition(null)}
      onFocus={(e) => show(e.currentTarget)}
      onBlur={() => setPosition(null)}
    >
      {children}
      {position &&
        createPortal(
          <div className="tooltip" role="tooltip" style={position}>
            {content}
          </div>,
          document.body,
        )}
    </span>
  );
}
function segmentTip(s: Segment, zone: string) {
  return (
    <>
      <strong>{s.name || names[s.type]}</strong>
      <span>
        {localStamp(s.started_at, zone, true, true)} —{" "}
        {localStamp(s.ended_at, zone, true, true)}
      </span>
      <span>{duration(s.ended_at - s.started_at)}</span>
      {s.title && <p>{s.title}</p>}
    </>
  );
}
function midnightMarkers(start: number, end: number, zone: string) {
  const result: { at: number; day: string }[] = [];
  let cursor = start,
    day = localDay(start, zone);
  while (cursor < end) {
    const probe = Math.min(end, cursor + 3600000),
      next = localDay(probe, zone);
    if (next !== day) {
      let lo = cursor,
        hi = probe;
      while (hi - lo > 1) {
        const mid = Math.floor((lo + hi) / 2);
        if (localDay(mid, zone) === day) lo = mid;
        else hi = mid;
      }
      if (hi < end) result.push({ at: hi, day: localDay(hi, zone) });
      day = next;
    }
    cursor = probe;
  }
  return result;
}
export function Timeline({ data }: { data: Activity }) {
  if (!data.windows.length)
    return (
      <div className="activity-empty">
        Выбранное время отсутствует из-за перевода часов
      </div>
    );
  const start = data.windows[0][0],
    end = data.windows.at(-1)![1],
    span = end - start;
  const percentage = (at: number) => (100 * (at - start)) / span;
  const markers = midnightMarkers(start, end, data.timezone);
  const tickCount = 6,
    ticks = Array.from(
      { length: tickCount + 1 },
      (_, i) => start + (span * i) / tickCount,
    );
  const legend = new Map<string, { color: string; name: string }>();
  data.segments.forEach((s) => {
    if (s.type === "no_data") return;
    const key = s.application_id ? `app-${s.application_id}` : s.type;
    if (!legend.has(key))
      legend.set(key, {
        color: s.application_id ? appColor(s.application_id) : colors[s.type],
        name: s.name || names[s.type],
      });
  });
  return (
    <div className="timeline" data-testid="timeline">
      <div className="timeline-band">
        {data.segments.map((s, i) => (
          <Tip
            key={`${s.started_at}-${i}`}
            className={`timeline-segment ${s.type}`}
            style={{
              left: `${percentage(s.started_at)}%`,
              width: `${(100 * (s.ended_at - s.started_at)) / span}%`,
              background: s.application_id
                ? appColor(s.application_id)
                : colors[s.type],
            }}
            content={segmentTip(s, data.timezone)}
          />
        ))}
        {data.windows.slice(0, -1).map((w, i) => (
          <Tip
            key={w[1]}
            className="timeline-segment unselected"
            style={{
              left: `${percentage(w[1])}%`,
              width: `${percentage(data.windows[i + 1][0]) - percentage(w[1])}%`,
            }}
            content="Этот участок не входит в выбранное время"
          />
        ))}
      </div>
      {markers.map((m) => (
        <div
          className="midnight-marker"
          key={m.at}
          style={{ left: `${percentage(m.at)}%` }}
          data-testid="midnight-marker"
        >
          <i />
          <span>
            {dateLabel(m.day)} · {localStamp(m.at, data.timezone)}
          </span>
        </div>
      ))}
      <div className="timeline-labels">
        {ticks.map((t, i) => (
          <span key={t} style={{ left: `${percentage(t)}%` }}>
            {i === tickCount && localStamp(t, data.timezone) === "00:00"
              ? "24:00"
              : localStamp(t, data.timezone)}
          </span>
        ))}
      </div>
      <div className="timeline-legend">
        {[...legend].map(([key, v]) => (
          <span key={key}>
            <i style={{ background: v.color }} />
            {v.name}
          </span>
        ))}
      </div>
      {!legend.size && (
        <p className="activity-empty">Нет активности для отображения</p>
      )}
    </div>
  );
}
function cellStatus(cell: Cell) {
  return (
    cell.status ||
    (!cell.total_window_ms
      ? "missing_hour"
      : !cell.total_tracked_ms
        ? "no_data"
        : "data")
  );
}
function cellTip(cell: Cell) {
  const status = cellStatus(cell),
    long = cell.weekday !== undefined;
  const title = long
    ? longDayNames[cell.weekday! - 1]
    : dateLabel(cell.local_date!, true);
  const tracked = long ? cell.total_tracked_ms! : cell.tracked_ms!,
    window = long ? cell.total_window_ms! : cell.window_ms!;
  return (
    <>
      <strong>
        {title}, {cell.local_time_from}–{cell.local_time_to}
        {cell.day_offset === 1 ? " · следующий день" : ""}
      </strong>
      {status === "missing_hour" ? (
        <span>Час отсутствует из-за перевода часов</span>
      ) : status === "future" ? (
        <span>Время ещё не наступило</span>
      ) : (
        <>
          {status === "no_data" && <span>Нет данных трекера</span>}
          <span>
            {long ? "Средняя активность" : "Активность"}:{" "}
            {duration(long ? cell.average_active_ms : cell.active_ms)}
          </span>
          {tracked < window && (
            <span>
              Известно: {duration(tracked)} из {duration(window)}
            </span>
          )}
          {cell.hour_occurrences === 2 && (
            <span>Час повторился: учтены обе реализации</span>
          )}
          {long && (
            <span>
              Дней в расчёте: {cell.sample_days}
              {cell.repeated_hour_days
                ? ` · с повторением часа: ${cell.repeated_hour_days}`
                : ""}
              {cell.missing_hour_days
                ? ` · пропущено: ${cell.missing_hour_days}`
                : ""}
            </span>
          )}
        </>
      )}
    </>
  );
}
export function Heatmap({ data }: { data: Activity }) {
  const rows = new Map<string, Cell[]>();
  data.cells.forEach((cell) => {
    const key = cell.date || String(cell.weekday);
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key)!.push(cell);
  });
  const columns = rows.values().next().value as Cell[] | undefined;
  if (!columns?.length)
    return <div className="activity-empty">Нет активности для отображения</div>;
  return (
    <div className="heatmap" data-testid="heatmap" data-mode={data.mode}>
      <div
        className="heatmap-row heatmap-hours"
        style={{
          gridTemplateColumns: `82px repeat(${columns.length}, minmax(0,1fr))`,
        }}
      >
        <span />
        {columns.map((c) => (
          <span key={`${c.day_offset}-${c.hour}`}>
            {String(c.hour).padStart(2, "0")}
            {c.day_offset === 1 && <sup>+1</sup>}
          </span>
        ))}
      </div>
      {[...rows].map(([key, cells]) => (
        <div
          className="heatmap-row"
          key={key}
          style={{
            gridTemplateColumns: `82px repeat(${columns.length}, minmax(0,1fr))`,
          }}
        >
          <span className="heatmap-date">
            {data.mode === "weekdays"
              ? dayNames[Number(key) - 1]
              : dateLabel(key)}
          </span>
          {cells.map((c) => {
            const status = cellStatus(c),
              ratio = c.intensity || 0;
            const rgb = [248, 246, 247].map((n, i) =>
              Math.round(n + ([241, 109, 159][i] - n) * ratio),
            );
            return (
              <Tip
                key={`${c.day_offset}-${c.hour}`}
                className={`heat-cell ${status}`}
                style={
                  status === "data"
                    ? { background: `rgb(${rgb.join(",")})` }
                    : {}
                }
                content={cellTip(c)}
              />
            );
          })}
        </div>
      ))}
      <div className="heatmap-legend">
        <span>Меньше</span>
        <i />
        <span>Больше активности</span>
      </div>
    </div>
  );
}
