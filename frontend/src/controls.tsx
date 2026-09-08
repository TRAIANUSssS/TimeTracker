import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { dateLabel, isoDate, minuteValue, timeLabel } from "./format";
import type { Filters } from "./types";

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
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
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M5.5 7a7.5 7.5 0 0 1 12-2L20 8M4 16l2.5 3a7.5 7.5 0 0 0 12-2" />
      </>
    ),
    gear: (
      <>
        <path d="m9 3-.5 2-2 .9-1.9-.6L2.8 9l1.5 1.5v3L2.8 15l1.8 3.7 1.9-.6 2 .9.5 2h4l.5-2 2-.9 1.9.6 1.8-3.7-1.5-1.5v-3L21.2 9l-1.8-3.7-1.9.6-2-.9-.5-2Z" />
        <circle cx="12" cy="12" r="3" />
      </>
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
    const end = new Date(),
      start = new Date();
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
                          className={`${outside ? "outside" : ""} ${day >= low && day <= high ? "in-range" : ""} ${day === low || day === high ? "range-end" : ""} ${day === isoDate(new Date()) ? "today" : ""}`}
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
    if (next[0] === next[1]) {
      setError("Начало и конец должны отличаться");
      return;
    }
    setError("");
    onChange(next[0], next[1]);
  }
  const a = valid(values[0], 0)
      ? minuteValue(values[0])
      : minuteValue(filters.time_from),
    b = valid(values[1], 1)
      ? minuteValue(values[1])
      : minuteValue(filters.time_to);
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
              setValues(values.map((x, j) => (j === i ? timeLabel(n) : x)));
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
                setValues(values.map((x, j) => (j === i ? timeLabel(n) : x)));
              }
            }}
            onKeyUp={(e) => {
              if (e.key.startsWith("Arrow")) commit();
            }}
          />
        ))}
        <div className="slider-ticks">
          {["00:00", "06:00", "12:00", "18:00", "24:00"].map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </div>
      {textInput(1)}
      <div className="time-hint" role={error ? "alert" : undefined}>
        {error || (b < a ? "До следующего дня" : "")}
      </div>
    </div>
  );
}
