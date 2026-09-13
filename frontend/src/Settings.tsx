import { useEffect, useRef, useState } from "react";

type Status = {
  mode: "polling" | "etw";
  active_mode: "polling" | "etw" | "external";
  effective_mode: "polling" | "etw";
  installed: boolean;
  can_install: boolean;
  busy: boolean;
  error: string | null;
  restart_required: boolean;
  external: boolean;
  token: string;
};

export function Settings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingMode, setPendingMode] = useState<Status["mode"] | null>(null);
  const revision = useRef(0);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      const started = revision.current;
      try {
        const response = await fetch("/settings/collection", {
          signal: abort.signal,
        });
        if (!response.ok)
          throw new Error("Не удалось загрузить настройки сбора.");
        const next = await response.json();
        if (started === revision.current) {
          setStatus(next);
          setLoadError("");
        }
      } catch (e) {
        if (!abort.signal.aborted && started === revision.current)
          setLoadError((e as Error).message);
      } finally {
        if (!abort.signal.aborted) timer = setTimeout(refresh, 3000);
      }
    };
    void refresh();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, []);

  const act = async (action: string) => {
    if (!status) return;
    revision.current += 1;
    if (action === "polling" || action === "etw") setPendingMode(action);
    setSending(true);
    setError("");
    try {
      const response = await fetch("/settings/collection", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-TimeTracker-Token": status.token,
        },
        body: JSON.stringify({ action }),
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : "Не удалось изменить настройки.",
        );
      setStatus(body);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      revision.current += 1;
      setPendingMode(null);
      setSending(false);
    }
  };
  const disabled = sending || !!status?.busy || !!status?.external;
  return (
    <section className="collection-settings" aria-label="Настройки сбора">
      <h2>Режим сбора</h2>
      <p>
        Выберите способ отслеживания приложений. История сохраняется при смене
        режима.
      </p>
      {!status ? (
        <p>Загрузка настроек…</p>
      ) : (
        <>
          <fieldset disabled={disabled}>
            <legend>Режим при следующем запуске</legend>
            <label>
              <input
                type="radio"
                name="collection-mode"
                checked={(pendingMode ?? status.mode) === "polling"}
                onChange={() => void act("polling")}
              />
              <span>
                <strong>Обычный</strong>
                <small>
                  Периодическая проверка процессов. Не требует установки
                  компонентов.
                </small>
              </span>
            </label>
            <label>
              <input
                type="radio"
                name="collection-mode"
                checked={(pendingMode ?? status.mode) === "etw"}
                disabled={!status.installed}
                onChange={() => void act("etw")}
              />
              <span>
                <strong>Экономичный (ETW)</strong>
                <small>
                  События запуска и завершения процессов с редкой сверкой.
                  Требует фонового компонента.
                </small>
              </span>
            </label>
          </fieldset>
          {sending && <p role="status">Сохраняем настройку…</p>}
          <p role="status">
            Сейчас:{" "}
            {status.effective_mode === "etw"
              ? "экономичный режим работает"
              : status.active_mode === "etw" || status.external
                ? "обычный опрос — экономичный источник пока недоступен"
                : "обычный режим"}
            .
          </p>
          {status.restart_required && (
            <p className="settings-notice">
              Настройка сохранена. Выйдите через меню трея и запустите
              TimeTracker снова, чтобы применить режим.
            </p>
          )}
          {status.external && (
            <p>
              Источник задан параметром запуска. Настройки режима для этого
              запуска недоступны.
            </p>
          )}
          <h3>Фоновый компонент</h3>
          <p>
            {status.installed ? "Установлен." : "Не установлен."} Компонент
            запускается автоматически вместе с приложением в экономичном режиме
            и завершает работу после выхода.
          </p>
          <p>
            Установка, обновление и удаление потребуют подтверждения
            администратора Windows. При обычных запусках подтверждение не
            требуется. При отказе компонента запись продолжается через обычный
            опрос; короткие процессы во время отказа могут быть пропущены.
          </p>
          <div className="settings-actions">
            <button
              className="text-button"
              disabled={
                disabled || !status.can_install || status.active_mode === "etw"
              }
              onClick={() => void act("install")}
            >
              {status.installed
                ? "Обновить / восстановить компонент"
                : "Установить и выбрать экономичный режим"}
            </button>
            {status.installed && (
              <button
                className="text-button"
                disabled={
                  disabled ||
                  !status.can_install ||
                  status.active_mode === "etw"
                }
                onClick={() => void act("remove")}
              >
                Удалить компонент
              </button>
            )}
          </div>
          {status.active_mode === "etw" && (
            <p>
              Для обновления или удаления компонента сначала выберите обычный
              режим и перезапустите приложение.
            </p>
          )}
          {!status.can_install && (
            <p>
              В этой сборке нет установщика компонента. Распакуйте полный пакет
              TimeTracker с папкой collector.
            </p>
          )}
          {status.busy && (
            <p role="status">
              Выполняется настройка. Подтвердите запрос Windows и дождитесь
              завершения.
            </p>
          )}
        </>
      )}
      {(error || loadError || status?.error) && (
        <p className="settings-error" role="alert">
          {error || loadError || status?.error}
        </p>
      )}
    </section>
  );
}
