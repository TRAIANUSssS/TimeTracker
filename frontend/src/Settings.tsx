import { useEffect, useRef, useState } from "react";
import { DateRange, Icon, TimeRange } from "./controls";
import { Settings as CollectionSettings } from "./CollectionSettings";
import {
  appColor,
  applicationName,
  defaults,
  duration,
  isLockApplication,
} from "./format";
import { palette, request } from "./preferences";
import type { PreferencesState, TimeUnits } from "./preferences";
import type { Filters } from "./types";
import { Tip } from "./Activity";

const sections = [
  ["activity", "Сбор активности", "activity"],
  ["display", "Отображение", "monitor"],
  ["apps", "Приложения и приватность", "shield"],
  ["recording", "Запись и запуск", "play"],
  ["data", "Данные", "download"],
];
function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="setting-switch"
      role="switch"
      aria-label={label}
      aria-checked={checked}
      disabled={disabled}
      onClick={onChange}
    >
      <span className="switch-track">
        <i />
      </span>
      <span>{checked ? "Вкл." : "Выкл."}</span>
    </button>
  );
}
function Skeleton() {
  return (
    <div
      className="settings-skeleton"
      role="status"
      aria-label="Загрузка настроек"
    >
      {Array.from({ length: 7 }, (_, i) => (
        <div className="skeleton" key={i} />
      ))}
    </div>
  );
}
function LoadError({ retry }: { retry: () => void }) {
  return (
    <div className="settings-empty" role="alert">
      <p>Не удалось загрузить настройки</p>
      <button className="soft-button" onClick={retry}>
        Повторить
      </button>
    </div>
  );
}
type Application = {
  id: number;
  name: string;
  icon_url: string;
  color: string | null;
  track_titles: boolean;
  ignored: boolean;
  active_ms: number;
};
function ColorPicker({
  app,
  disabled,
  save,
}: {
  app: Application;
  disabled: boolean;
  save: (changes: Partial<Application>) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLButtonElement>(".palette button")?.focus();
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <div
      className="color-picker"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        className="color-trigger"
        ref={trigger}
        disabled={disabled}
        aria-label={`Цвет: ${app.name}`}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <i style={{ background: app.color || appColor(app.id) }} />
      </button>
      {open && (
        <div
          className="color-popover"
          role="dialog"
          aria-label={`Цвет приложения ${app.name}`}
        >
          <div className="palette">
            {palette.map((color) => (
              <button
                key={color}
                aria-label={color}
                aria-pressed={app.color === color}
                style={{ background: color }}
                onClick={() => {
                  save({ color });
                  setOpen(false);
                  trigger.current?.focus();
                }}
              >
                {app.color === color ? "✓" : ""}
              </button>
            ))}
          </div>
          <button
            className="text-button"
            onClick={() => {
              save({ color: null });
              setOpen(false);
              trigger.current?.focus();
            }}
          >
            Авто
          </button>
        </div>
      )}
    </div>
  );
}
function AppsPrivacy({ onChanged }: { onChanged: () => void }) {
  const [apps, setApps] = useState<Application[] | null>(null),
    [query, setQuery] = useState(""),
    [sort, setSort] = useState<"activity" | "name">("activity"),
    [enabledOnly, setEnabledOnly] = useState(false);
  const [error, setError] = useState(false),
    [saveErrors, setSaveErrors] = useState<Record<number, boolean>>({});
  const [pending, setPending] = useState<Set<number>>(new Set());
  const locks = useRef(new Set<number>());
  const load = () => {
    setError(false);
    request<Application[]>("/applications")
      .then(setApps)
      .catch(() => setError(true));
  };
  useEffect(load, []);
  const save = async (app: Application, changes: Partial<Application>) => {
    if (locks.current.has(app.id)) return;
    locks.current.add(app.id);
    setPending(new Set(locks.current));
    setSaveErrors((previous) => ({ ...previous, [app.id]: false }));
    try {
      const next = await request<Application>(
        `/applications/${app.id}`,
        changes,
      );
      setApps(
        (previous) =>
          previous?.map((item) =>
            item.id === app.id ? { ...next, active_ms: item.active_ms } : item,
          ) || null,
      );
      onChanged();
    } catch {
      setSaveErrors((previous) => ({ ...previous, [app.id]: true }));
    } finally {
      locks.current.delete(app.id);
      setPending(new Set(locks.current));
    }
  };
  const filtered = apps
    ?.filter((app) => {
      const needle = query.trim().toLocaleLowerCase();
      const matches = (applicationName(app.name) || app.name)
        .toLocaleLowerCase()
        .includes(needle);
      return matches && (!enabledOnly || !app.ignored);
    })
    .sort((a, b) =>
      sort === "activity"
        ? b.active_ms - a.active_ms || a.name.localeCompare(b.name, "ru") || a.id - b.id
        : a.name.localeCompare(b.name, "ru") || a.id - b.id,
    );
  return (
    <>
      <h2>Приложения и приватность</h2>
      <p className="settings-subtitle">
        Настройте видимость приложений и параметры приватности.
      </p>
      {error ? (
        <LoadError retry={load} />
      ) : !apps ? (
        <Skeleton />
      ) : (
        <>
          <div className="apps-search-row">
            <label className="apps-search">
              <Icon name="search" />
              <input
                aria-label="Поиск приложений"
                placeholder="Поиск приложений…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <span>
              {query.trim() || enabledOnly
                ? `Показано: ${filtered!.length} из ${apps.length}`
                : `Обнаружено приложений: ${apps.length}`}
            </span>
          </div>
          <div className="apps-table-controls">
            <div className="apps-sort" aria-label="Сортировка приложений">
              <span>Сортировка:</span>
              <button
                type="button"
                aria-pressed={sort === "activity"}
                onClick={() => setSort("activity")}
              >
                По активности
              </button>
              <button
                type="button"
                aria-pressed={sort === "name"}
                onClick={() => setSort("name")}
              >
                По названию
              </button>
            </div>
            <label className="apps-enabled-filter">
              <input
                type="checkbox"
                checked={enabledOnly}
                onChange={(event) => setEnabledOnly(event.target.checked)}
              />
              <span>Только включённые</span>
            </label>
          </div>
          {!filtered?.length ? (
            <div className="settings-empty">
              <h3>
                {apps.length
                  ? "Ничего не найдено"
                  : "Приложения пока не обнаружены"}
              </h3>
              <p>
                {apps.length
                  ? "Попробуйте изменить поисковый запрос."
                  : "Запустите несколько приложений, и они появятся здесь."}
              </p>
            </div>
          ) : (
            <div className="settings-table-wrap">
              <table className="settings-table">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Приложение</th>
                    <th scope="col">
                      Активность{" "}
                      <Tip content="Активное время приложения за всю сохранённую историю.">
                        <Icon name="info" size={16} />
                      </Tip>
                    </th>
                    <th scope="col">Цвет</th>
                    <th scope="col">
                      Заголовки{" "}
                      <Tip content="Если выключить, новые заголовки окон не будут сохраняться. Существующие заголовки останутся в истории.">
                        <Icon name="info" size={16} />
                      </Tip>
                    </th>
                    <th scope="col">
                      В статистике{" "}
                      <Tip content="Скрывает приложение из таблицы и переключений за все даты. Общая активность и тепловая карта сохраняются; в хронологии — «Другая активность». История не удаляется.">
                        <Icon name="info" size={16} />
                      </Tip>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((app, index) => (
                    <tr key={app.id}>
                      <td>{index + 1}</td>
                      <td>
                        <div className="settings-app-name">
                          <span className="settings-app-icon">
                            {isLockApplication(app.name) ? (
                              <Icon name="lock" size={16} />
                            ) : (
                              app.name.slice(0, 1).toUpperCase()
                            )}
                            <img
                              src={app.icon_url}
                              alt=""
                              loading="lazy"
                              onError={(event) => {
                                event.currentTarget.style.display = "none";
                              }}
                            />
                          </span>
                          <span title={applicationName(app.name)}>
                            {applicationName(app.name)}
                          </span>
                        </div>
                        {saveErrors[app.id] && (
                          <span className="settings-error" role="alert">
                            Не удалось сохранить настройку. Повторите изменение.
                          </span>
                        )}
                      </td>
                      <td className="settings-app-activity">{duration(app.active_ms)}</td>
                      <td>
                        <ColorPicker
                          app={app}
                          disabled={pending.has(app.id)}
                          save={(changes) => void save(app, changes)}
                        />
                      </td>
                      <td>
                        <Switch
                          label={`Заголовки: ${app.name}`}
                          checked={app.track_titles}
                          disabled={pending.has(app.id)}
                          onChange={() =>
                            void save(app, { track_titles: !app.track_titles })
                          }
                        />
                      </td>
                      <td>
                        <Switch
                          label={`В статистике: ${app.name}`}
                          checked={!app.ignored}
                          disabled={pending.has(app.id)}
                          onChange={() =>
                            void save(app, { ignored: !app.ignored })
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="settings-note">
            Отключение заголовков влияет на новую запись. Видимость в статистике
            применяется ко всей истории. Собранные данные не удаляются.
          </p>
        </>
      )}
    </>
  );
}
function DisplaySettings({ preferences }: { preferences: PreferencesState }) {
  const display = preferences.value!.display;
  const [preview, setPreview] = useState(display.time_units),
    [start, setStart] = useState(display.personal_day_start),
    [error, setError] = useState("");
  useEffect(() => {
    setPreview(display.time_units);
    setStart(display.personal_day_start);
  }, [display.personal_day_start, JSON.stringify(display.time_units)]);
  const units: [keyof TimeUnits, string][] = [
    ["days", "Дни"],
    ["hours", "Часы"],
    ["minutes", "Минуты"],
  ];
  const changeUnits = async (key: keyof TimeUnits) => {
    const next = { ...preview, [key]: !preview[key] };
    if (!Object.values(next).some(Boolean)) return;
    setPreview(next);
    setError("");
    try {
      await preferences.save("display", { time_units: next });
    } catch {
      setPreview(display.time_units);
      setError("Не удалось сохранить настройку");
    }
  };
  const saveStart = async () => {
    if (start === display.personal_day_start) return;
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(start)) {
      setStart(display.personal_day_start);
      return;
    }
    setError("");
    try {
      await preferences.save("display", {
        personal_day_start: start,
        timezone:
          display.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
    } catch {
      setStart(display.personal_day_start);
      setError("Не удалось сохранить настройку");
    }
  };
  return (
    <>
      <h2>Отображение</h2>
      <p className="settings-subtitle">
        Настройте формат времени и границы статистического дня.
      </p>
      <div className="settings-group">
        <h3>Единицы времени</h3>
        <p>
          Выберите хотя бы одну единицу для длительностей во всём приложении.
        </p>
        <div className="unit-chips">
          {units.map(([key, label]) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={preview[key]}
                disabled={
                  preferences.saving ||
                  (preview[key] &&
                    Object.values(preview).filter(Boolean).length === 1)
                }
                onChange={() => void changeUnits(key)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
        <div className="format-preview">
          <span>Пример</span>
          <strong>{duration((3 * 1440 + 605) * 60000, preview)}</strong>
        </div>
      </div>
      <div className="settings-group">
        <h3>Личный день</h3>
        <div className="setting-row">
          <label htmlFor="personal-day">Начало суток</label>
          <input
            id="personal-day"
            type="time"
            value={start}
            disabled={preferences.saving}
            onChange={(e) => setStart(e.target.value)}
            onBlur={() => void saveStart()}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
              if (e.key === "Escape") setStart(display.personal_day_start);
            }}
          />
        </div>
        <p>
          Статистический день идёт с {display.personal_day_start} до{" "}
          {display.personal_day_start} следующего календарного дня.
        </p>
        <p className="settings-note">
          Часовой пояс:{" "}
          {display.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone}
          . История пересчитывается по выбранной границе, исходные данные
          сохраняются.
        </p>
      </div>
      {error && (
        <p className="settings-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
function RecordingSettings({
  preferences,
  onChanged,
}: {
  preferences: PreferencesState;
  onChanged: () => void;
}) {
  const recording = preferences.value!.recording,
    [error, setError] = useState("");
  const save = async (changes: Parameters<PreferencesState["save"]>[1]) => {
    setError("");
    try {
      await preferences.save("recording", changes);
      onChanged();
    } catch {
      setError("Не удалось сохранить настройку");
    }
  };
  return (
    <>
      <h2>Запись и запуск</h2>
      <p className="settings-subtitle">
        Управляйте записью активности и запуском TimeTracker.
      </p>
      <div className="settings-group">
        <h3>Запись активности</h3>
        <p
          className={`recording-status ${recording.tracking_paused ? "paused" : ""}`}
        >
          <i />
          {recording.tracking_paused
            ? "Запись приостановлена"
            : "Запись активна"}
        </p>
        <p>
          {recording.tracking_paused
            ? "Новые данные сейчас не сохраняются. Пауза действует до возобновления, в том числе после перезапуска."
            : "TimeTracker сейчас собирает данные об использовании приложений."}
        </p>
        <button
          className="soft-button"
          disabled={preferences.saving}
          onClick={() =>
            void save({ tracking_paused: !recording.tracking_paused })
          }
        >
          {recording.tracking_paused ? "Возобновить" : "Приостановить"}
        </button>
      </div>
      <div className="settings-group">
        <div className="setting-row">
          <h3>Запускать вместе с Windows</h3>
          <Switch
            label="Запускать вместе с Windows"
            checked={!!recording.autostart}
            disabled={preferences.saving || recording.autostart === null}
            onChange={() => void save({ autostart: !recording.autostart })}
          />
        </div>
        <p>
          {recording.autostart === null
            ? "Не удалось получить состояние автозапуска."
            : "TimeTracker будет запускаться в трее при входе в Windows."}
        </p>
      </div>
      {error && (
        <p className="settings-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
function DataSettings({
  filters,
  onFiltersChange,
}: {
  filters: Filters;
  onFiltersChange: (filters: Filters) => void;
}) {
  const [includeTitles, setIncludeTitles] = useState(false),
    [downloading, setDownloading] = useState<"csv" | "json" | null>(null),
    [error, setError] = useState("");
  const changeTime = (time_from: string, time_to: string) =>
    onFiltersChange({
      ...filters,
      time_from,
      time_to,
      full_day: String(
        time_from === (filters.personal_day_start || "00:00") &&
          (time_to === time_from ||
            (time_from === "00:00" && time_to === "24:00")),
      ),
    });
  const download = async (format: "csv" | "json") => {
    setDownloading(format);
    setError("");
    try {
      const params = new URLSearchParams({
        date_from: filters.date_from,
        date_to: filters.date_to,
        time_from: filters.time_from,
        time_to: filters.time_to,
        timezone: filters.timezone,
        personal_day_start: filters.personal_day_start || "00:00",
        full_day: filters.full_day || "false",
        include_titles: String(includeTitles),
      });
      const response = await fetch(`/export/${format}?${params}`);
      if (!response.ok) throw new Error(String(response.status));
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const filename =
        /filename="?([^";]+)"?/.exec(disposition)?.[1] ||
        `timetracker-export.${format}`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError("Не удалось подготовить экспорт. Попробуйте ещё раз.");
    } finally {
      setDownloading(null);
    }
  };
  return (
    <>
      <h2>Данные</h2>
      <p className="settings-subtitle">
        Скачайте подробную историю активности за выбранный период.
      </p>
      <div className="settings-group export-period">
        <div className="setting-row">
          <div>
            <h3>Период экспорта</h3>
            <p>Этот же период будет выбран на основной странице.</p>
          </div>
          <button
            className="text-button"
            disabled={JSON.stringify(filters) === JSON.stringify(defaults())}
            onClick={() => onFiltersChange(defaults())}
          >
            Сбросить
          </button>
        </div>
        <div className="export-filter-controls">
          <DateRange
            filters={filters}
            onChange={(date_from, date_to) =>
              onFiltersChange({ ...filters, date_from, date_to })
            }
          />
          <TimeRange filters={filters} onChange={changeTime} />
        </div>
        <p className="personal-day-caption">
          День: {filters.personal_day_start || "00:00"}–
          {filters.personal_day_start || "00:00"} следующего дня · часовой пояс:{" "}
          {filters.timezone}
        </p>
      </div>
      <div className="settings-group">
        <label className="export-title-option">
          <input
            type="checkbox"
            checked={includeTitles}
            onChange={(event) => setIncludeTitles(event.target.checked)}
          />
          <span>
            <strong>Включить заголовки окон</strong>
            <small>
              Заголовки могут содержать названия документов, сайтов и переписок.
            </small>
          </span>
        </label>
      </div>
      <div className="settings-group export-format">
        <h3>Формат файла</h3>
        <p>
          Одна строка — непрерывный интервал приложения или состояния системы.
          CSV подходит для Excel, JSON сохраняет метаданные периода и версию
          схемы.
        </p>
        <div className="export-actions">
          <button
            className="soft-button"
            disabled={downloading !== null}
            onClick={() => void download("csv")}
          >
            {downloading === "csv" ? "Подготовка…" : "Экспорт CSV"}
          </button>
          <button
            className="soft-button"
            disabled={downloading !== null}
            onClick={() => void download("json")}
          >
            {downloading === "json" ? "Подготовка…" : "Экспорт JSON"}
          </button>
        </div>
        {error && (
          <p className="settings-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </>
  );
}
export function Settings({
  path,
  navigate,
  preferences,
  onChanged,
  filters,
  onFiltersChange,
}: {
  path: string;
  navigate: (path: string) => void;
  preferences: PreferencesState;
  onChanged: () => void;
  filters: Filters;
  onFiltersChange: (filters: Filters) => void;
}) {
  const active = sections.some(([id]) => path === `/settings/${id}`)
    ? path.split("/")[2]
    : "apps";
  return (
    <div className="settings-layout">
      <aside>
        <h2 className="settings-title">Настройки</h2>
        <nav className="settings-nav" aria-label="Категории настроек">
          {sections.map(([id, label, icon]) => (
            <a
              key={id}
              href={`/settings/${id}`}
              aria-current={active === id ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                navigate(`/settings/${id}`);
              }}
            >
              <Icon name={icon} size={23} />
              <span>{label}</span>
            </a>
          ))}
        </nav>
      </aside>
      <section
        className="settings-panel"
        key={active}
        aria-label={sections.find(([id]) => id === active)![1]}
      >
        {active === "apps" ? (
          <AppsPrivacy onChanged={onChanged} />
        ) : active === "activity" ? (
          <CollectionSettings navigate={navigate} />
        ) : preferences.error ? (
          <LoadError retry={() => void preferences.reload()} />
        ) : !preferences.value ? (
          <Skeleton />
        ) : active === "display" ? (
          <DisplaySettings preferences={preferences} />
        ) : active === "data" ? (
          <DataSettings filters={filters} onFiltersChange={onFiltersChange} />
        ) : (
          <RecordingSettings preferences={preferences} onChanged={onChanged} />
        )}
      </section>
    </div>
  );
}
