import { useEffect, useRef, useState } from "react";
import type { PreferencesState } from "./preferences";

type CollectionStatus = {
  mode: "polling" | "etw";
  installed: boolean;
  can_install: boolean;
  busy: boolean;
  error: string | null;
  external: boolean;
  token: string;
};

type Mode = "polling" | "etw";

async function loadCollection(): Promise<CollectionStatus> {
  const response = await fetch("/settings/collection", { cache: "no-store" });
  if (!response.ok) throw new Error("collection unavailable");
  return response.json();
}

async function changeCollection(
  status: CollectionStatus,
  action: "polling" | "etw" | "install",
): Promise<CollectionStatus> {
  const response = await fetch("/settings/collection", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-TimeTracker-Token": status.token,
    },
    body: JSON.stringify({ action }),
  });
  if (!response.ok) throw new Error("collection change failed");
  return response.json();
}

export function Onboarding({
  preferences,
  onComplete,
}: {
  preferences: PreferencesState;
  onComplete: () => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [dayStart, setDayStart] = useState(
    preferences.value?.display.personal_day_start || "00:00",
  );
  const [mode, setMode] = useState<Mode>("etw");
  const [collection, setCollection] = useState<CollectionStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [installFailed, setInstallFailed] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void loadCollection()
      .then((next) => {
        if (mounted.current) setCollection(next);
      })
      .catch(() => undefined);
    return () => {
      mounted.current = false;
    };
  }, []);

  const goToModes = async (value: string) => {
    setBusy(true);
    setError("");
    try {
      await preferences.save("display", { personal_day_start: value });
      setDayStart(value);
      setStep(2);
    } catch {
      setError("Не удалось сохранить время начала дня. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  };

  const complete = async () => {
    try {
      if (await preferences.completeOnboarding()) onComplete();
    } catch {
      setError("Не удалось завершить настройку. Попробуйте ещё раз.");
    }
  };

  const usePolling = async (continueAfterFailure = false) => {
    setBusy(true);
    setError("");
    try {
      const current = collection || (await loadCollection());
      const next = await changeCollection(current, "polling");
      setCollection(next);
      await complete();
    } catch {
      if (continueAfterFailure) await complete();
      else setError("Не удалось сохранить обычный режим. Попробуйте ещё раз.");
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const waitForInstall = async (initial: CollectionStatus) => {
    let current = initial;
    for (let attempt = 0; attempt < 120 && current.busy; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      current = await loadCollection();
      if (mounted.current) setCollection(current);
    }
    if (
      current.busy ||
      current.error ||
      !current.installed ||
      current.mode !== "etw"
    )
      throw new Error("installation failed");
  };

  const finish = async () => {
    if (mode === "polling") {
      await usePolling();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const current = collection || (await loadCollection());
      if (current.external) throw new Error("external collection mode");
      if (current.installed) {
        const next = await changeCollection(current, "etw");
        if (next.error || next.mode !== "etw")
          throw new Error("mode change failed");
      } else {
        if (!current.can_install) throw new Error("installer unavailable");
        const next = await changeCollection(current, "install");
        if (mounted.current) setCollection(next);
        await waitForInstall(next);
      }
      await complete();
    } catch {
      if (mounted.current) setInstallFailed(true);
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <main className="onboarding-page">
      <section className="onboarding-card" aria-labelledby="onboarding-title">
        <div className="onboarding-progress" aria-label={`Шаг ${step} из 2`}>
          <span>Шаг {step} из 2</span>
          <div aria-hidden="true">
            <i className="complete" />
            <i className={step === 2 ? "complete" : ""} />
          </div>
        </div>

        <div
          className="onboarding-stage"
          key={installFailed ? "failure" : step}
        >
          {step === 1 ? (
            <>
              <h1 id="onboarding-title">Похоже, вы здесь впервые</h1>
              <p className="onboarding-lead">
                Во сколько для вас обычно заканчивается день?
              </p>
              <p>
                TimeTracker будет считать это время началом нового личного дня.
                Например, при значении 02:00 день 24 сентября продлится до 02:00
                25 сентября.
              </p>
              <p className="onboarding-hint">
                Если вы обычно ложитесь после полуночи, укажите время, когда
                день для вас действительно заканчивается.
              </p>
              <label className="onboarding-time">
                <span>Начало нового дня</span>
                <input
                  type="time"
                  value={dayStart}
                  disabled={busy}
                  onChange={(event) => setDayStart(event.target.value)}
                />
              </label>
              {error && (
                <p className="onboarding-error" role="alert">
                  {error}
                </p>
              )}
              <div className="onboarding-actions">
                <button
                  className="onboarding-skip"
                  disabled={busy}
                  onClick={() => void goToModes("00:00")}
                >
                  Пропустить
                </button>
                <button
                  className="onboarding-primary"
                  disabled={busy}
                  onClick={() => void goToModes(dayStart)}
                >
                  {busy ? "Сохраняем…" : "Далее"}
                </button>
              </div>
            </>
          ) : installFailed ? (
            <>
              <div className="onboarding-alert-icon" aria-hidden="true">
                !
              </div>
              <h1 id="onboarding-title">
                Не удалось установить оптимизированный режим.
              </h1>
              <p>
                TimeTracker продолжит работу в обычном режиме. Оптимизированный
                режим можно включить позже в настройках.
              </p>
              {error && (
                <p className="onboarding-error" role="alert">
                  {error}
                </p>
              )}
              <div className="onboarding-actions onboarding-actions-end">
                <button
                  className="onboarding-primary"
                  disabled={busy}
                  onClick={() => void usePolling(true)}
                >
                  {busy ? "Сохраняем…" : "Продолжить"}
                </button>
              </div>
            </>
          ) : (
            <>
              <h1 id="onboarding-title">Выберите режим сбора активности</h1>
              <p>
                Рекомендуем оптимизированный режим: он использует системные
                события Windows и снижает фоновую нагрузку.
              </p>
              <p className="onboarding-hint">
                Для установки потребуется один раз подтвердить запрос Windows.
                Сам TimeTracker не будет постоянно работать с правами
                администратора.
              </p>
              <fieldset className="onboarding-modes" disabled={busy}>
                <legend>Режим сбора</legend>
                <label className={mode === "polling" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="onboarding-mode"
                    checked={mode === "polling"}
                    onChange={() => setMode("polling")}
                  />
                  <span>
                    <strong>Обычный</strong>
                    <small>
                      Периодически проверяет активные процессы. Не требует
                      установки.
                    </small>
                  </span>
                </label>
                <label className={mode === "etw" ? "selected" : ""}>
                  <input
                    type="radio"
                    name="onboarding-mode"
                    checked={mode === "etw"}
                    onChange={() => setMode("etw")}
                  />
                  <span>
                    <strong>
                      Оптимизированный <em>Рекомендуется</em>
                    </strong>
                    <small>
                      Получает события Windows и создаёт меньше фоновой
                      нагрузки.
                    </small>
                  </span>
                </label>
              </fieldset>
              {busy && mode === "etw" && (
                <p className="onboarding-installing" role="status">
                  <i aria-hidden="true" /> Устанавливаем оптимизированный режим…
                </p>
              )}
              {error && (
                <p className="onboarding-error" role="alert">
                  {error}
                </p>
              )}
              <div className="onboarding-actions">
                <button
                  className="onboarding-skip"
                  disabled={busy}
                  onClick={() => void usePolling()}
                >
                  Пропустить
                </button>
                <button
                  className="onboarding-primary"
                  disabled={busy}
                  onClick={() => void finish()}
                >
                  {busy && mode === "polling" ? "Сохраняем…" : "Готово"}
                </button>
              </div>
            </>
          )}
        </div>

        <footer className="onboarding-notes">
          <span>Все эти параметры можно изменить позже в настройках.</span>
          <span>Данные хранятся локально на этом компьютере.</span>
        </footer>
      </section>
    </main>
  );
}
