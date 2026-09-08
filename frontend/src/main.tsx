import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/manrope";
import "./styles.css";
import { DateRange, Icon, TimeRange } from "./controls";
import { AppsTable, Empty, ErrorState, TableSkeleton } from "./Table";
import { Heatmap, Timeline, Tip } from "./Activity";
import { defaults, duration } from "./format";
import { useDashboard } from "./requests";

function App() {
  const [filters, setFilters] = useState(defaults),
    [expanded, setExpanded] = useState(false),
    [refresh, setRefresh] = useState(0),
    [path, setPath] = useState(location.pathname);
  const data = useDashboard(filters, refresh),
    defaultFilters = defaults();
  const isDefault = JSON.stringify(filters) === JSON.stringify(defaultFilters);
  const retry = () => setRefresh((n) => n + 1);
  useEffect(() => {
    const pop = () => setPath(location.pathname);
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  const navigate = (next: string) => {
    history.pushState({}, "", next);
    setPath(next);
  };
  return (
    <>
      <div className="background" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <main className="page-container">
        <header>
          <div className="header-top">
            <h1>TimeTracker</h1>
            <button
              className={`settings-button ${path === "/settings" ? "selected" : ""}`}
              aria-label="Настройки"
              title="Настройки"
              onClick={() => navigate(path === "/settings" ? "/" : "/settings")}
            >
              <Icon name="gear" />
            </button>
          </div>
          <nav className="tabs" aria-label="Разделы">
            <a
              href="/"
              className={path === "/" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                navigate("/");
              }}
            >
              Основная
            </a>
            <a
              href="/advanced"
              className={path === "/advanced" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                navigate("/advanced");
              }}
            >
              Расширенная
            </a>
            <i
              style={{
                transform:
                  path === "/advanced" ? "translateX(134px)" : "translateX(0)",
                opacity: path === "/settings" ? 0 : 1,
                width: path === "/advanced" ? 124 : 96,
              }}
            />
          </nav>
        </header>
        <div hidden={path !== "/"}>
          <section className="filters" aria-label="Фильтры статистики">
            <label className="active-filter">
              <input
                type="checkbox"
                checked={filters.active_only}
                onChange={(e) =>
                  setFilters({ ...filters, active_only: e.target.checked })
                }
              />
              <span>Только активные</span>
            </label>
            <DateRange
              filters={filters}
              onChange={(date_from, date_to) =>
                setFilters({ ...filters, date_from, date_to })
              }
            />
            <TimeRange
              filters={filters}
              onChange={(time_from, time_to) =>
                setFilters({ ...filters, time_from, time_to })
              }
            />
            <button
              className="text-button reset"
              disabled={isDefault}
              onClick={() => setFilters(defaults())}
            >
              Сбросить
            </button>
            <button
              className="icon-button refresh"
              aria-label="Обновить статистику"
              title="Обновить статистику"
              disabled={data.pending}
              onClick={retry}
            >
              <span className={data.pending ? "spinning" : ""}>
                <Icon name="refresh" />
              </span>
            </button>
          </section>
          <section
            className={`total-time ${data.system.pending && data.system.delayed ? "updating" : ""}`}
            aria-label="Общее активное время"
          >
            <span>Общее активное время</span>
            {data.system.error ? (
              <ErrorState retry={retry} />
            ) : data.system.data ? (
              <strong>{duration(data.system.data.active_ms)}</strong>
            ) : (
              <strong className={data.system.delayed ? "kpi-skeleton" : ""}>
                —
              </strong>
            )}
          </section>
          <section
            className={`hero-card ${data.apps.pending && data.apps.delayed ? "updating" : ""}`}
            aria-label="Время в приложениях"
            aria-busy={data.apps.pending}
          >
            {data.apps.error ? (
              <ErrorState retry={retry} />
            ) : data.apps.data ? (
              <AppsTable
                data={data.apps.data}
                activeOnly={data.apps.data.activeOnly}
                expanded={expanded}
                onExpand={() => setExpanded(!expanded)}
              />
            ) : data.apps.delayed ? (
              <TableSkeleton />
            ) : (
              <div className="initial-table-space" />
            )}
          </section>
          <section
            className={`activity-section ${data.activity.pending && data.activity.delayed ? "updating" : ""}`}
            aria-label="Активность по времени суток"
            aria-busy={data.activity.pending}
          >
            <div className="activity-heading">
              <h2>Активность по времени суток</h2>
              <Tip
                content={
                  <>
                    <span>
                      Для короткого периода показаны конкретные даты. Для
                      длинного периода — средняя активность по дням недели.
                    </span>
                    <span>
                      Цвет показывает долю активности в выбранной части часа. ⁺¹
                      — следующий день. Отсутствующие при переводе часов
                      интервалы не учитываются в среднем.
                    </span>
                  </>
                }
              >
                <Icon name="info" size={18} />
              </Tip>
              <span className="activity-caption">
                {data.mode === "timeline"
                  ? "Хронология дня"
                  : data.mode === "dates"
                    ? "По дням"
                    : "В среднем по дням недели"}
              </span>
            </div>
            {data.activity.error ? (
              <ErrorState retry={retry} />
            ) : data.activity.data && data.activity.data.mode === data.mode ? (
              data.mode === "timeline" ? (
                <Timeline data={data.activity.data} />
              ) : (
                <Heatmap data={data.activity.data} />
              )
            ) : (
              <div
                className={`activity-placeholder ${data.activity.delayed ? "skeleton" : ""}`}
              />
            )}
          </section>
        </div>
        {path === "/advanced" && (
          <div className="placeholder-card">
            <Empty
              title="Расширенная статистика появится позже"
              subtitle="Здесь будут дополнительные метрики и аналитика."
            />
          </div>
        )}
        {path === "/settings" && (
          <div className="placeholder-card">
            <Empty title="Настройки появятся позже" />
            <button className="text-button" onClick={() => navigate("/")}>
              Вернуться на основную
            </button>
          </div>
        )}
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
