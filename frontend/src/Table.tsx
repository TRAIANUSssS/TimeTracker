import { useLayoutEffect, useRef, useState } from "react";
import { appColor, duration } from "./format";
import { Icon } from "./controls";
import type { Apps, AppRow } from "./types";

function AppIcon({ app }: { app: AppRow }) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className="app-icon"
      style={failed ? { background: appColor(app.application_id) } : {}}
    >
      {failed ? (
        <span>{app.name[0]?.toUpperCase()}</span>
      ) : (
        <img src={app.icon_url} alt="" onError={() => setFailed(true)} />
      )}
    </span>
  );
}
export function Empty({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name="clock" size={26} />
      </span>
      <h2>{title}</h2>
      {subtitle && <p>{subtitle}</p>}
    </div>
  );
}
export function ErrorState({ retry }: { retry: () => void }) {
  return (
    <div className="error-state" role="alert">
      <span>Не удалось загрузить статистику</span>
      <button className="text-button" onClick={retry}>
        Повторить
      </button>
    </div>
  );
}
export function TableSkeleton() {
  return (
    <div className="table-skeleton" aria-label="Загрузка приложений">
      {Array.from({ length: 10 }, (_, i) => (
        <div className="skeleton-row" key={i}>
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      ))}
    </div>
  );
}
export function AppsTable({
  data,
  activeOnly,
  expanded,
  onExpand,
}: {
  data: Apps;
  activeOnly: boolean;
  expanded: boolean;
  onExpand: () => void;
}) {
  const refs = useRef(new Map<number, HTMLDivElement>()),
    positions = useRef(new Map<number, number>());
  const items = expanded ? data.items : data.items.slice(0, 10),
    metric = activeOnly ? "active_ms" : "running_ms";
  useLayoutEffect(() => {
    const next = new Map<number, number>();
    for (const item of items) {
      const el = refs.current.get(item.application_id);
      if (!el) continue;
      const top = el.offsetTop;
      next.set(item.application_id, top);
      const previous = positions.current.get(item.application_id);
      if (previous !== undefined && previous !== top)
        el.animate(
          [
            { transform: `translateY(${previous - top}px)` },
            { transform: "translateY(0)" },
          ],
          { duration: 250, easing: "ease-out" },
        );
    }
    positions.current = next;
  }, [data, expanded]);
  if (!data.has_tracking_data)
    return (
      <Empty
        title="Нет данных за выбранный период"
        subtitle="Измените даты или временной диапазон."
      />
    );
  if (!data.items.length)
    return (
      <Empty
        title={
          data.has_running_data
            ? "Нет активных приложений за выбранный период"
            : "Нет учитываемых приложений за выбранный период"
        }
        subtitle={
          data.has_running_data
            ? "Отключите «Только активные», чтобы увидеть запущенные приложения."
            : undefined
        }
      />
    );
  const max = data.items[0][metric];
  return (
    <>
      <div className="table-header table-grid">
        <span />
        <span />
        <span />
        <span />
        <span>Активно</span>
        <span>Запущено</span>
      </div>
      <div className="table-rows" style={{ height: items.length * 40 }}>
        {items.map((app, index) => {
          const ratio = max ? app[metric] / max : 0;
          return (
            <div
              className="app-row table-grid"
              data-testid="app-row"
              data-app-id={app.application_id}
              key={app.application_id}
              ref={(node) => {
                if (node) refs.current.set(app.application_id, node);
                else refs.current.delete(app.application_id);
              }}
            >
              <span className="rank">{index + 1}</span>
              <AppIcon app={app} />
              <span className="app-name" title={app.name}>
                {app.name}
              </span>
              <div className="progress-cell">
                <div className="progress-track">
                  <div style={{ width: `${ratio * 100}%` }} />
                </div>
                <span>{Math.round(ratio * 100)}%</span>
              </div>
              <span className="time-number">{duration(app.active_ms)}</span>
              <span className="time-number">{duration(app.running_ms)}</span>
            </div>
          );
        })}
      </div>
      {data.items.length > 10 && (
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
