import { Fragment, useEffect, useRef, useState } from "react";
import { Tip } from "./Activity";
import { Icon } from "./controls";
import {
  applicationName,
  dateLabel,
  dayCount,
  dayNames,
  duration,
} from "./format";
import type { useAdvanced } from "./requests";
import { AppIcon, Empty, ErrorState } from "./Table";
import type {
  AdvancedAppRow,
  AdvancedApplication,
  AdvancedDynamics,
  AdvancedTransitions,
  AdvancedWeekly,
  Filters,
} from "./types";

type AdvancedData = ReturnType<typeof useAdvanced>;

function ReferenceIcon({ app }: { app: AdvancedApplication }) {
  return (
    <AppIcon
      app={{
        application_id: app.id,
        name: app.name,
        icon_url: app.icon_url,
        color: app.color,
        active_ms: 0,
        running_ms: 0,
      }}
    />
  );
}

function percent(value: number | null) {
  return value == null
    ? "—"
    : value.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

function KpiSkeleton() {
  return (
    <div
      className="advanced-kpi-card kpi-skeletons"
      aria-label="Загрузка показателей"
    >
      {Array.from({ length: 4 }, (_, index) => (
        <div className="advanced-kpi" key={index}>
          <i />
          <i />
          <i />
        </div>
      ))}
    </div>
  );
}

function Kpis({
  data,
  filters,
  retry,
}: {
  data: AdvancedData["kpi"];
  filters: Filters;
  retry: () => void;
}) {
  if (data.error)
    return (
      <section className="advanced-kpi-card advanced-section-error">
        <ErrorState retry={retry} />
      </section>
    );
  if (!data.data)
    return data.delayed ? (
      <KpiSkeleton />
    ) : (
      <div className="advanced-kpi-space" />
    );
  const value = data.data,
    comparison = value.comparison,
    week = dayCount(filters) === 7,
    change = comparison.context_switches_change_percent,
    switchContext = !comparison.has_tracking_data
      ? "Нет данных для сравнения"
      : change == null
        ? `Прошлый период: ${comparison.previous_context_switches}`
        : `${change > 0 ? "+" : change < 0 ? "−" : ""}${Math.abs(change).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% ${week ? "к прошлой неделе" : "к прошлому периоду"}`;
  return (
    <section
      className={`advanced-kpi-card ${data.pending && data.delayed ? "updating" : ""}`}
    >
      <div className="advanced-kpi">
        <span>Переключения</span>
        <strong>{value.context_switches.toLocaleString("ru-RU")}</strong>
        <small>{switchContext}</small>
      </div>
      <div className="advanced-kpi">
        <span>На активный час</span>
        <strong>{percent(value.context_switches_per_active_hour)}</strong>
        <small>
          {comparison.has_tracking_data
            ? `Прошлый период: ${percent(comparison.previous_switches_per_active_hour)}`
            : "Нет данных для сравнения"}
        </small>
      </div>
      <div className="advanced-kpi">
        <span>Самый длинный фокус</span>
        <strong>{duration(value.longest_focus?.duration_ms)}</strong>
        <small>
          {applicationName(value.longest_focus?.application.name) || "—"}
        </small>
      </div>
      <div className="advanced-kpi">
        <span>В среднем в день</span>
        <strong>{duration(value.average_active_per_day_ms)}</strong>
        <small>
          {comparison.has_tracking_data
            ? `Прошлый период: ${duration(comparison.previous_average_active_per_day_ms)}`
            : "Нет данных для сравнения"}
        </small>
      </div>
    </section>
  );
}

function ChartSkeleton({ label }: { label: string }) {
  return (
    <div className="advanced-chart-skeleton" aria-label={label}>
      <i />
      <i />
      <i />
      <i />
      <i />
    </div>
  );
}

function russianDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
  });
}

function localToday(timezone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value || "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function WeeklyChart({
  value,
  filters,
}: {
  value: AdvancedWeekly;
  filters: Filters;
}) {
  const byWeekday = new Map(value.days.map((day) => [day.weekday, day])),
    oneDay = dayCount(filters) === 1,
    today = localToday(filters.timezone),
    values = value.days
      .map((day) =>
        value.mode === "week" ? day.active_ms : day.average_active_ms,
      )
      .filter((item): item is number => item != null),
    max = Math.max(1, value.previous_period_average_ms || 0, ...values),
    averageBottom =
      value.previous_period_average_ms == null
        ? null
        : (value.previous_period_average_ms / max) * 100;
  return (
    <div className="weekly-chart" data-testid="advanced-weekly-chart">
      <div className="weekly-legend">
        <i />
        <span>Среднее за прошлый период</span>
      </div>
      <div className="weekly-plot">
        {averageBottom != null && (
          <Tip
            className="weekly-average"
            style={{ bottom: `${Math.min(100, averageBottom)}%` }}
            content={
              <>
                <strong>Среднее за предыдущий период</strong>
                <span>{duration(value.previous_period_average_ms)} в день</span>
              </>
            }
          >
            <i />
          </Tip>
        )}
        <div className="weekly-bars">
          {dayNames.map((name, index) => {
            const day = byWeekday.get(index + 1),
              amount =
                value.mode === "week" ? day?.active_ms : day?.average_active_ms,
              status = day?.status || (day ? "data" : "outside"),
              height = amount == null ? 0 : Math.max(2, (amount / max) * 100),
              tooltip =
                value.mode === "week" ? (
                  <>
                    <strong>
                      {day?.date ? `${name}, ${russianDate(day.date)}` : name}
                    </strong>
                    <span>
                      {status === "future"
                        ? "Время ещё не наступило"
                        : status === "no_data"
                          ? "Нет данных трекера"
                          : day
                            ? duration(amount)
                            : "Вне выбранного периода"}
                    </span>
                  </>
                ) : (
                  <>
                    <strong>{name}</strong>
                    <span>
                      {amount == null
                        ? "Нет данных трекера"
                        : `В среднем: ${duration(amount)}`}
                    </span>
                    {!!day?.sample_days && (
                      <span>Дней с данными: {day.sample_days}</span>
                    )}
                  </>
                );
            const selected = oneDay && day?.date === filters.date_to,
              current = day?.date === today;
            return (
              <div
                className={`weekly-slot ${status}${selected ? " selected" : ""}${current ? " today" : ""}`}
                key={name}
              >
                <Tip content={tooltip}>
                  <button
                    aria-label={`${name}: ${amount == null ? "нет данных" : duration(amount)}`}
                  >
                    <i style={{ height: `${height}%` }} />
                  </button>
                </Tip>
                <span>{name}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

type PlotPoint = { x: number; y: number; index: number };

function paths(points: Array<PlotPoint | null>, bottom: number) {
  const groups: PlotPoint[][] = [];
  for (const point of points) {
    if (!point) continue;
    if (!groups.length || points[point.index - 1] == null) groups.push([]);
    groups.at(-1)!.push(point);
  }
  return groups.map((group) => {
    const line = group.reduce((path, point, index) => {
      if (!index) return `M ${point.x} ${point.y}`;
      const previous = group[index - 1],
        middle = (previous.x + point.x) / 2;
      return `${path} C ${middle} ${previous.y}, ${middle} ${point.y}, ${point.x} ${point.y}`;
    }, "");
    return {
      line,
      area: `${line} L ${group.at(-1)!.x} ${bottom} L ${group[0].x} ${bottom} Z`,
    };
  });
}

function pointLabel(
  value: string,
  granularity: AdvancedDynamics["granularity"],
  label?: string | null,
) {
  if (granularity === "hour") return label || value.slice(11, 16);
  const date = new Date(`${value}T12:00:00`);
  if (granularity === "month")
    return date
      .toLocaleDateString("ru-RU", { month: "short" })
      .replace(".", "");
  return dateLabel(value);
}

function DynamicsChart({ value }: { value: AdvancedDynamics }) {
  const width = 620,
    height = 190,
    left = 42,
    right = 16,
    top = 16,
    bottom = 154,
    plotWidth = width - left - right,
    plotHeight = bottom - top,
    amounts = value.points.map((point) =>
      value.granularity === "hour" || value.granularity === "day"
        ? point.active_ms
        : point.average_per_day_ms,
    ),
    max = Math.max(
      value.granularity === "hour" ? 3_600_000 : 1,
      ...amounts.filter((amount): amount is number => amount != null),
    ),
    coordinates = amounts.map((amount, index) =>
      amount == null
        ? null
        : {
            x:
              left +
              (value.points.length === 1
                ? plotWidth / 2
                : (index / (value.points.length - 1)) * plotWidth),
            y: bottom - (amount / max) * plotHeight,
            index,
          },
    ),
    curves = paths(coordinates, bottom),
    labelStep = Math.max(1, Math.ceil(value.points.length / 7));
  return (
    <div className="dynamics-chart" data-testid="advanced-dynamics-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Динамика активного времени"
      >
        <defs>
          <linearGradient id="advanced-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#f16d9f" stopOpacity=".24" />
            <stop offset="1" stopColor="#f16d9f" stopOpacity=".02" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((part) => {
          const y = bottom - part * plotHeight;
          return (
            <g key={part}>
              <line
                className="dynamics-grid"
                x1={left}
                x2={width - right}
                y1={y}
                y2={y}
              />
              <text x={left - 8} y={y + 4}>
                {duration(max * part)}
              </text>
            </g>
          );
        })}
        {curves.map((curve, index) => (
          <Fragment key={index}>
            <path className="dynamics-area" d={curve.area} />
            <path className="dynamics-line" d={curve.line} />
          </Fragment>
        ))}
      </svg>
      <div className="dynamics-points">
        {coordinates.map((point, index) => {
          if (!point) return null;
          const record = value.points[index],
            amount = amounts[index];
          return (
            <Tip
              key={record.start}
              className="dynamics-point"
              style={{
                left: `${(point.x / width) * 100}%`,
                top: `${(point.y / height) * 100}%`,
              }}
              content={
                <>
                  <strong>
                    {value.granularity === "hour"
                      ? `${russianDate(record.start.slice(0, 10))}, ${record.label}–${record.end_label}`
                      : value.granularity === "day"
                        ? russianDate(record.start)
                        : value.granularity === "month"
                          ? new Date(
                              `${record.start}T12:00:00`,
                            ).toLocaleDateString("ru-RU", {
                              month: "long",
                              year: "numeric",
                            })
                          : `${russianDate(record.start)}–${russianDate(new Date(Date.parse(record.end) - 86400000).toISOString().slice(0, 10))}`}
                  </strong>
                  <span>
                    {value.granularity === "hour" || value.granularity === "day"
                      ? duration(amount)
                      : `Среднее: ${duration(amount)} / день`}
                  </span>
                  {value.granularity !== "hour" &&
                    value.granularity !== "day" && (
                      <span>Всего: {duration(record.total_active_ms)}</span>
                    )}
                </>
              }
            >
              <i />
            </Tip>
          );
        })}
      </div>
      <div className="dynamics-labels">
        {value.points.map((point, index) => (
          <span
            className={point.status}
            key={point.start}
            style={{
              left: `${value.points.length === 1 ? 50 : (index / (value.points.length - 1)) * 100}%`,
            }}
          >
            {index % labelStep === 0 || index === value.points.length - 1
              ? pointLabel(point.start, value.granularity, point.label)
              : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function Charts({
  data,
  filters,
  retry,
}: {
  data: AdvancedData;
  filters: Filters;
  retry: () => void;
}) {
  return (
    <section className="advanced-charts">
      <article
        className={`advanced-chart-card weekly-card ${data.weekly.pending && data.weekly.delayed ? "updating" : ""}`}
      >
        <h2>
          {data.weekly.data?.mode === "weekday_average"
            ? "По дням недели"
            : "Активность за неделю"}
        </h2>
        {data.weekly.error ? (
          <ErrorState retry={retry} />
        ) : data.weekly.data ? (
          <WeeklyChart value={data.weekly.data} filters={filters} />
        ) : data.weekly.delayed ? (
          <ChartSkeleton label="Загрузка активности за неделю" />
        ) : null}
      </article>
      <article
        className={`advanced-chart-card dynamics-card ${data.dynamics.pending && data.dynamics.delayed ? "updating" : ""}`}
      >
        <h2>Динамика активного времени</h2>
        {data.dynamics.error ? (
          <ErrorState retry={retry} />
        ) : data.dynamics.data ? (
          <DynamicsChart value={data.dynamics.data} />
        ) : data.dynamics.delayed ? (
          <ChartSkeleton label="Загрузка динамики" />
        ) : null}
      </article>
    </section>
  );
}

function AdvancedTable({
  items,
  expanded,
  onExpand,
}: {
  items: AdvancedAppRow[];
  expanded: boolean;
  onExpand: () => void;
}) {
  const shown = expanded ? items : items.slice(0, 10);
  return (
    <>
      <div className="advanced-table-wrap">
        <table className="advanced-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Приложение</th>
              <th>Активно ↓</th>
              <th>Запущено</th>
              <th>
                <Tip content="Доля времени на переднем плане относительно времени, когда приложение было запущено.">
                  Использование
                </Tip>
              </th>
              <th>Запуски</th>
              <th>Средняя сессия</th>
              <th>Макс. сессия</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((app, index) => {
              const ratio =
                app.usage_ratio == null ? null : Math.max(0, app.usage_ratio);
              return (
                <tr key={app.application_id} data-testid="advanced-app-row">
                  <td>{index + 1}</td>
                  <td>
                    <AppIcon app={app} />
                    <span title={applicationName(app.name)}>
                      {applicationName(app.name)}
                    </span>
                  </td>
                  <td>{duration(app.active_ms)}</td>
                  <td>{duration(app.running_ms)}</td>
                  <td>
                    <Tip
                      content={
                        ratio == null
                          ? "Нет running-данных"
                          : `${percent(ratio * 100)}% времени приложение было на переднем плане.`
                      }
                    >
                      <span className="usage-cell">
                        <i>
                          <i
                            style={{
                              width: `${Math.min(100, (ratio || 0) * 100)}%`,
                            }}
                          />
                        </i>
                        <span>
                          {ratio == null ? "—" : `${Math.round(ratio * 100)}%`}
                        </span>
                      </span>
                    </Tip>
                  </td>
                  <td>{app.launch_count}</td>
                  <td>{duration(app.average_session_ms)}</td>
                  <td>{duration(app.max_session_ms)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {items.length > 10 && (
        <div className="expand-wrap">
          <button className="expand-button" onClick={onExpand}>
            {expanded ? "Свернуть" : "Показать все"}
            <span className={expanded ? "rotated" : ""}>
              <Icon name="chevron" size={16} />
            </span>
          </button>
        </div>
      )}
    </>
  );
}

function ApplicationPicker({
  applications,
  selected,
  onChoose,
  onClose,
}: {
  applications: AdvancedApplication[];
  selected: number[];
  onChoose: (id: number) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState(""),
    root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const pointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) onClose();
    };
    const key = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", pointer);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);
  const query = search.trim().toLocaleLowerCase("ru-RU"),
    available = applications.filter(
      (app) =>
        !selected.includes(app.id) &&
        app.name.toLocaleLowerCase("ru-RU").includes(query),
    );
  return (
    <div
      className="matrix-picker"
      role="dialog"
      aria-label="Выбор приложения"
      ref={root}
    >
      <label>
        <Icon name="search" size={17} />
        <input
          autoFocus
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Поиск приложения..."
        />
      </label>
      <div>
        {available.map((app) => (
          <button key={app.id} onClick={() => onChoose(app.id)}>
            <ReferenceIcon app={app} />
            <span>{applicationName(app.name)}</span>
          </button>
        ))}
        {!available.length && <p>Подходящих приложений нет</p>}
      </div>
    </div>
  );
}

function TransitionsView({
  value,
  customIds,
  onChange,
}: {
  value: AdvancedTransitions;
  customIds: number[];
  onChange: (ids: number[]) => void;
}) {
  const [picker, setPicker] = useState<number | null>(null),
    apps = value.selected_applications,
    names = new Map(value.applications.map((app) => [app.id, app])),
    counts = new Map(
      value.matrix.map((item) => [
        `${item.from_application_id}:${item.to_application_id}`,
        item.count,
      ]),
    ),
    max = Math.max(1, ...value.matrix.map((item) => item.count)),
    selected = apps.map((app) => app.id),
    replace = (id: number) => {
      if (picker == null) return;
      onChange(
        selected.map((current, index) => (index === picker ? id : current)),
      );
      setPicker(null);
    };
  if (!value.top_transitions.length || apps.length < 2)
    return (
      <Empty
        title="Недостаточно переходов для построения матрицы"
        subtitle="Матрица появится после того, как накопится больше активности."
      />
    );
  return (
    <div className="transitions-view">
      <section className="top-transitions">
        <h3>Самые частые переходы</h3>
        {value.top_transitions.map((transition) => {
          const source = names.get(transition.from_application_id),
            target = names.get(transition.to_application_id);
          if (!source || !target) return null;
          return (
            <div key={`${source.id}:${target.id}`}>
              <ReferenceIcon app={source} />
              <span>{applicationName(source.name)}</span>
              <Icon name="right" size={15} />
              <ReferenceIcon app={target} />
              <span>{applicationName(target.name)}</span>
              <strong>{transition.count}</strong>
            </div>
          );
        })}
      </section>
      <section className="matrix-section">
        <div className="matrix-heading">
          <div>
            <h3>Матрица переходов</h3>
            <p>Строка — откуда, столбец — куда</p>
          </div>
          {!!customIds.length && (
            <button className="text-button" onClick={() => onChange([])}>
              Сбросить к топ-10
            </button>
          )}
        </div>
        <div
          className="transition-matrix"
          role="grid"
          style={{
            gridTemplateColumns: `38px repeat(${apps.length}, minmax(26px, 38px))`,
          }}
        >
          <span />
          {apps.map((app, index) => (
            <Tip content={applicationName(app.name)} key={`head-${app.id}`}>
              <button
                aria-label={`Заменить ${app.name}`}
                onClick={() => setPicker(index)}
              >
                <ReferenceIcon app={app} />
              </button>
            </Tip>
          ))}
          {apps.map((source, row) => (
            <Fragment key={source.id}>
              <Tip content={applicationName(source.name)}>
                <button
                  aria-label={`Заменить ${source.name}`}
                  onClick={() => setPicker(row)}
                >
                  <ReferenceIcon app={source} />
                </button>
              </Tip>
              {apps.map((target) => {
                const count = counts.get(`${source.id}:${target.id}`) || 0,
                  diagonal = source.id === target.id;
                return (
                  <Tip
                    key={`${source.id}:${target.id}`}
                    content={
                      <>
                        <strong>
                          {applicationName(source.name)} →{" "}
                          {applicationName(target.name)}
                        </strong>
                        <span>
                          {diagonal
                            ? "Одинаковое приложение"
                            : `${count} переходов`}
                        </span>
                      </>
                    }
                  >
                    <span
                      className={`matrix-cell ${diagonal ? "diagonal" : ""}`}
                      role="gridcell"
                      style={
                        diagonal
                          ? undefined
                          : {
                              backgroundColor: `rgba(241,109,159,${0.05 + (count / max) * 0.78})`,
                            }
                      }
                    >
                      {diagonal
                        ? "—"
                        : count >= max * 0.72 && count
                          ? count
                          : ""}
                    </span>
                  </Tip>
                );
              })}
            </Fragment>
          ))}
        </div>
        {picker != null && (
          <ApplicationPicker
            applications={value.applications}
            selected={selected}
            onChoose={replace}
            onClose={() => setPicker(null)}
          />
        )}
      </section>
    </div>
  );
}

function Detail({
  data,
  retry,
  customIds,
  onApplicationIds,
}: {
  data: AdvancedData;
  retry: () => void;
  customIds: number[];
  onApplicationIds: (ids: number[]) => void;
}) {
  const [view, setView] = useState<"apps" | "transitions">("apps"),
    [expanded, setExpanded] = useState(false),
    resource = view === "apps" ? data.apps : data.transitions;
  return (
    <section
      className={`advanced-detail-card ${resource.pending && resource.delayed ? "updating" : ""}`}
    >
      <div
        className="advanced-segments"
        role="tablist"
        aria-label="Детализация"
      >
        <button
          role="tab"
          aria-selected={view === "apps"}
          onClick={() => setView("apps")}
        >
          Приложения
        </button>
        <button
          role="tab"
          aria-selected={view === "transitions"}
          onClick={() => setView("transitions")}
        >
          Переходы
        </button>
      </div>
      {resource.error ? (
        <ErrorState retry={retry} />
      ) : view === "apps" && data.apps.data ? (
        data.apps.data.has_tracking_data ? (
          data.apps.data.items.length ? (
            <AdvancedTable
              items={data.apps.data.items}
              expanded={expanded}
              onExpand={() => setExpanded(!expanded)}
            />
          ) : (
            <Empty title="Нет учитываемых приложений за выбранный период" />
          )
        ) : (
          <Empty
            title="Нет данных за выбранный период"
            subtitle="Измените даты или временной диапазон."
          />
        )
      ) : view === "transitions" && data.transitions.data ? (
        <TransitionsView
          value={data.transitions.data}
          customIds={customIds}
          onChange={onApplicationIds}
        />
      ) : resource.delayed ? (
        <div
          className="advanced-table-skeleton"
          aria-label="Загрузка детализации"
        >
          {Array.from({ length: 9 }, (_, index) => (
            <i key={index} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function Advanced({
  data,
  filters,
  retry,
  customIds,
  onApplicationIds,
}: {
  data: AdvancedData;
  filters: Filters;
  retry: () => void;
  customIds: number[];
  onApplicationIds: (ids: number[]) => void;
}) {
  const noData = data.kpi.data && !data.kpi.data.has_tracking_data;
  return (
    <div className="advanced-page">
      {noData ? (
        <section className="advanced-empty-card">
          <Empty
            title="Нет данных за выбранный период"
            subtitle="Измените даты или временной диапазон."
          />
        </section>
      ) : (
        <>
          <Kpis data={data.kpi} filters={filters} retry={retry} />
          <Charts data={data} filters={filters} retry={retry} />
          <Detail
            data={data}
            retry={retry}
            customIds={customIds}
            onApplicationIds={onApplicationIds}
          />
        </>
      )}
    </div>
  );
}
