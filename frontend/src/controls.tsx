import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  dateLabel,
  isoDate,
  minuteValue,
  timeLabel,
  personalToday,
} from "./format";
import type { Filters } from "./types";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    activity: <path d="M3 12h4l3-8 4 16 3-8h4" />,
    monitor: (
      <>
        <rect x="3" y="4" width="18" height="13" rx="2" />
        <path d="M12 17v4m-4 0h8" />
      </>
    ),
    shield: <path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4Z" />,
    play: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m10 8 6 4-6 4Z" />
      </>
    ),
    search: (
      <>
        <circle cx="10" cy="10" r="7" />
        <path d="m16 16 5 5" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="3" />
        <path d="M7 3v4m10-4v4M3 11h18m-13 4h2m4 0h2m-8 3h2" />
      </>
    ),
    chevron: <path d="m7 10 5 5 5-5" />,
    left: <path d="m14 6-6 6 6 6" />,
    right: <path d="m10 6 6 6-6 6" />,
    refresh: (
      <>
        <path d="M21 12a9 9 0 0 0-15.2-6.5L3 8" />
        <path d="M3 3v5h5" />
        <path d="M3 12a9 9 0 0 0 15.2 6.5L21 16" />
        <path d="M21 21v-5h-5" />
      </>
    ),
    gear: (
      <path
        fill="currentColor"
        stroke="none"
        d="M19.43 12.98c.04-.32.07-.65.07-.98s-.02-.66-.07-.98l2.11-1.65a.51.51 0 0 0 .12-.64l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.3 7.3 0 0 0-1.69-.98l-.38-2.65A.5.5 0 0 0 14 2h-4a.5.5 0 0 0-.5.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46a.51.51 0 0 0 .12.64l2.11 1.65c-.04.32-.07.65-.07.98s.02.66.07.98l-2.11 1.65a.51.51 0 0 0-.12.64l2 3.46c.12.22.37.31.6.22l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.23.09.48 0 .6-.22l2-3.46a.51.51 0 0 0-.12-.64l-2.11-1.65ZM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5Z"
      />
    ),
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v6m0-10v.1" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 6v6l4 3" />
      </>
    ),
    lock: (
      <>
        <rect x="5" y="10" width="14" height="11" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v12m-5-5 5 5 5-5" />
        <path d="M5 20h14" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.clock}
    </svg>
  );
}

export function DateRange({
  filters,
  onChange,
}: {
  filters: Filters;
  onChange: (from: string, to: string) => void;
}) {
  const [open, setOpen] = useState(false),
    [month, setMonth] = useState(new Date(`${filters.date_from}T12:00:00`));
  const [anchor, setAnchor] = useState<string | null>(null),
    [hover, setHover] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const click = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) {
        setOpen(false);
        setAnchor(null);
      }
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setAnchor(null);
      }
    };
    document.addEventListener("pointerdown", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", click);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  const select = (day: string) => {
    if (!anchor) {
      setAnchor(day);
      setHover(day);
    } else {
      const [from, to] = [anchor, day].sort();
      onChange(from, to);
      setAnchor(null);
      setOpen(false);
    }
  };
  const preset = (days: number) => {
    const end = new Date(`${personalToday()}T12:00:00`),
      start = new Date(end);
    start.setDate(start.getDate() - days + 1);
    onChange(isoDate(start), isoDate(end));
    setOpen(false);
    setAnchor(null);
  };
  return (
    <div className="date-range" ref={root}>
      <button
        className="date-trigger"
        aria-label="Выбрать диапазон дат"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          setAnchor(null);
          setMonth(new Date(`${filters.date_from}T12:00:00`));
        }}
      >
        <Icon name="calendar" />
        <span>
          {dateLabel(filters.date_from, true)} —{" "}
          {dateLabel(filters.date_to, true)}
        </span>
        <Icon name="chevron" size={16} />
      </button>
      {open && (
        <div
          className="calendar-popover"
          role="dialog"
          aria-label="Диапазон дат"
        >
          <div className="calendar-top">
            <button
              className="icon-button"
              aria-label="Предыдущий месяц"
              onClick={() =>
                setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))
              }
            >
              <Icon name="left" />
            </button>
            <span>
              {anchor ? "Выберите последнюю дату" : "Выберите первую дату"}
            </span>
            <button
              className="icon-button"
              aria-label="Следующий месяц"
              onClick={() =>
                setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))
              }
            >
              <Icon name="right" />
            </button>
          </div>
          <div className="calendars">
            {[0, 1].map((offset) => {
              const first = new Date(
                  month.getFullYear(),
                  month.getMonth() + offset,
                  1,
                ),
                pad = (first.getDay() + 6) % 7;
              const [low, high] = anchor
                ? [anchor, hover || anchor].sort()
                : [filters.date_from, filters.date_to];
              return (
                <div className="calendar-month" key={offset}>
                  <h3>
                    {first.toLocaleDateString("ru-RU", {
                      month: "long",
                      year: "numeric",
                    })}
                  </h3>
                  <div className="calendar-grid">
                    {["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map((d) => (
                      <span className="weekday" key={d}>
                        {d}
                      </span>
                    ))}
                    {Array.from({ length: 42 }, (_, i) => {
                      const d = new Date(
                          first.getFullYear(),
                          first.getMonth(),
                          i - pad + 1,
                        ),
                        day = isoDate(d),
                        outside = d.getMonth() !== first.getMonth();
                      return (
                        <button
                          key={day}
                          aria-label={day}
                          disabled={outside}
                          className={`${outside ? "outside" : ""} ${day >= low && day <= high ? "in-range" : ""} ${day === low || day === high ? "range-end" : ""} ${day === personalToday() ? "today" : ""}`}
                          onMouseEnter={() => setHover(day)}
                          onClick={() => select(day)}
                        >
                          {d.getDate()}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="date-presets">
            <button onClick={() => preset(1)}>Сегодня</button>
            <button onClick={() => preset(7)}>Последние 7 дней</button>
            <button onClick={() => preset(30)}>Последние 30 дней</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function TimeRange({
  filters,
  onChange,
}: {
  filters: Filters;
  onChange: (from: string, to: string) => void;
}) {
  const [values, setValues] = useState([filters.time_from, filters.time_to]),
    [error, setError] = useState("");
  const cancelled = useRef(false);
  const dayStart = minuteValue(filters.personal_day_start || "00:00");
  const clockLabel = (offset: number) =>
    dayStart === 0 && offset === 1440
      ? "24:00"
      : timeLabel((dayStart + offset) % 1440);
  const position = (value: string, end: boolean) => {
    const raw = minuteValue(value);
    if (end && (raw === dayStart || (dayStart === 0 && raw === 1440)))
      return 1440;
    return (raw - dayStart + 1440) % 1440;
  };
  useEffect(() => {
    setValues([filters.time_from, filters.time_to]);
    setError("");
  }, [filters.time_from, filters.time_to]);
  const valid = (value: string, index: number) =>
    /^([01]\d|2[0-3]):[0-5]\d$/.test(value) ||
    (index === 1 && value === "24:00");
  function commit(next = values) {
    if (!next.every(valid)) {
      setError("Введите время в формате ЧЧ:ММ");
      return;
    }
    if (next[0] === next[1] && minuteValue(next[0]) !== dayStart) {
      setError("Начало и конец должны отличаться");
      return;
    }
    setError("");
    onChange(next[0], next[1]);
  }
  const a = valid(values[0], 0)
      ? position(values[0], false)
      : position(filters.time_from, false),
    b = valid(values[1], 1)
      ? position(values[1], true)
      : position(filters.time_to, true);
  const fill =
    a <= b
      ? `linear-gradient(to right, var(--neutral-200) ${a / 14.4}%, var(--pink-400) ${a / 14.4}%, var(--pink-400) ${b / 14.4}%, var(--neutral-200) ${b / 14.4}%)`
      : `linear-gradient(to right,var(--pink-400) ${b / 14.4}%,var(--neutral-200) ${b / 14.4}%,var(--neutral-200) ${a / 14.4}%,var(--pink-400) ${a / 14.4}%)`;
  const textInput = (i: number) => (
    <input
      className="time-value"
      aria-label={i === 0 ? "Начало времени" : "Конец времени"}
      aria-invalid={!!error}
      value={values[i]}
      maxLength={5}
      spellCheck={false}
      onChange={(e) =>
        setValues(values.map((v, j) => (i === j ? e.target.value : v)))
      }
      onBlur={() => {
        if (cancelled.current) cancelled.current = false;
        else commit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          cancelled.current = true;
          setValues([filters.time_from, filters.time_to]);
          setError("");
          e.currentTarget.blur();
        }
      }}
    />
  );
  return (
    <div className="time-control">
      {textInput(0)}
      <div className="time-slider">
        <div className="slider-track" style={{ background: fill }} />
        {[a, b].map((v, i) => (
          <input
            key={i}
            type="range"
            aria-label={i === 0 ? "Начало диапазона" : "Конец диапазона"}
            min="0"
            max="1440"
            step="1"
            value={v}
            title={values[i]}
            onChange={(e) => {
              const n = Math.min(
                i === 0 ? 1425 : 1440,
                Math.round(Number(e.target.value) / 15) * 15,
              );
              setValues(values.map((x, j) => (j === i ? clockLabel(n) : x)));
            }}
            onPointerUp={() => commit()}
            onKeyDown={(e) => {
              if (
                ["ArrowLeft", "ArrowDown", "ArrowRight", "ArrowUp"].includes(
                  e.key,
                )
              ) {
                e.preventDefault();
                const n = Math.max(
                  0,
                  Math.min(
                    i === 0 ? 1425 : 1440,
                    v + (["ArrowLeft", "ArrowDown"].includes(e.key) ? -15 : 15),
                  ),
                );
                setValues(values.map((x, j) => (j === i ? clockLabel(n) : x)));
              }
            }}
            onKeyUp={(e) => {
              if (e.key.startsWith("Arrow")) commit();
            }}
          />
        ))}
        <div className="slider-ticks">
          {[0, 360, 720, 1080, 1440].map((offset) => (
            <span key={offset}>
              {clockLabel(offset)}
              {dayStart > 0 && dayStart + offset >= 1440 ? "⁺¹" : ""}
            </span>
          ))}
        </div>
      </div>
      {textInput(1)}
      <div className="time-hint" role={error ? "alert" : undefined}>
        {error ||
          (dayStart + b + (b < a ? 1440 : 0) >= 2880
            ? "Конец — через 2 дня"
            : b < a || (dayStart > 0 && b + dayStart >= 1440)
              ? "Конец — на следующий день"
              : "")}
      </div>
    </div>
  );
}
