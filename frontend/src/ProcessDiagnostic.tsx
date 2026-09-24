import { useState } from "react";

type Candidate = {
  pid: number;
  process_started_at: number | null;
  process_name: string;
  executable_path: string | null;
  display_name: string;
  tracker_known: boolean;
  session_saved: boolean;
  application_id: number | null;
  application_name: string | null;
  ignored: boolean;
  is_foreground: boolean;
  foreground_saved_since_start: boolean;
};

type Snapshot = {
  observed_at: number;
  tracking_paused: boolean;
  system_state: "ACTIVE" | "IDLE" | "LOCKED" | "SLEEP" | null;
  collection: { source: "polling" | "etw"; healthy: boolean };
  foreground_pid: number | null;
  matches: Candidate[];
};

type Result = {
  title: string;
  body: string;
  action?: "apps";
};

async function inspect(body: { query?: string; pid?: number; since?: number }) {
  const response = await fetch("/diagnostics/process", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error("diagnostic failed");
  return (await response.json()) as Snapshot;
}

function conclusion(snapshots: Snapshot[], candidate: Candidate): Result {
  const latest = [...snapshots]
    .reverse()
    .flatMap((item) => item.matches)
    .find((item) => item.pid === candidate.pid);
  if (snapshots.some((item) => item.tracking_paused))
    return {
      title: "Сбор активности приостановлен",
      body: "Возобновите запись и повторите проверку — во время паузы процессы и активные окна не записываются.",
    };
  if (!latest)
    return {
      title: "Процесс завершился во время проверки",
      body: "Запустите приложение снова и оставьте его открытым до окончания проверки.",
    };
  if (!latest.executable_path)
    return {
      title: "Windows не дала прочитать исполняемый файл",
      body: "PID виден, но TimeTracker не может связать его с приложением. Такое бывает у защищённых и системных процессов.",
    };
  if (latest.ignored)
    return {
      title: "Приложение исключено из статистики",
      body: `«${latest.application_name || latest.display_name}» обнаружено, но его отображение выключено.`,
      action: "apps",
    };
  if (!latest.tracker_known || !latest.session_saved || !latest.application_id)
    return {
      title: "Процесс виден Windows, но ещё не зарегистрирован",
      body: "Подождите несколько секунд и повторите проверку. Если это короткий процесс, оптимизированный режим обнаруживает его надёжнее Polling.",
    };
  const foreground = snapshots.some((item) =>
    item.matches.some(
      (match) => match.pid === candidate.pid && match.is_foreground,
    ),
  );
  if (!foreground)
    return {
      title: "Приложение не было активным окном",
      body: "Процесс запущен и записывается, но во время проверки его окно не оказалось на переднем плане. На главной отключите фильтр «Только активные», чтобы увидеть время работы в фоне.",
    };
  if (!snapshots.some((item) => item.system_state === "ACTIVE"))
    return {
      title: "Компьютер не считался активным",
      body: "Окно найдено, но время пришлось на простой, блокировку или сон и поэтому не добавилось к активному времени приложения.",
    };
  if (
    snapshots.some((item) =>
      item.matches.some(
        (match) =>
          match.pid === candidate.pid && match.foreground_saved_since_start,
      ),
    )
  )
    return {
      title: "Активность записывается правильно",
      body: `TimeTracker сохранил активность как «${latest.application_name || latest.display_name}». Проверьте выбранный день, диапазон времени и фильтр «Только активные».`,
      action: "apps",
    };
  if (
    snapshots.some(
      (item) => item.collection.source === "etw" && !item.collection.healthy,
    )
  )
    return {
      title: "Оптимизированный источник временно недоступен",
      body: "Сейчас используется резервная проверка процессов. Повторите диагностику через несколько секунд.",
    };
  return {
    title: "Активное окно найдено, но запись не появилась",
    body: "Проверка обнаружила разрыв между Windows и историей TimeTracker. Скопируйте отчёт — он поможет найти причину по журналу.",
  };
}

export function ProcessDiagnostic({
  navigate,
}: {
  navigate: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [samples, setSamples] = useState<Snapshot[]>([]);
  const [seconds, setSeconds] = useState(8);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setSnapshot(null);
    setSelected(null);
    setSamples([]);
    setSeconds(8);
    setResult(null);
    setError("");
  };
  const search = async () => {
    if (!query.trim()) return;
    setBusy(true);
    setError("");
    try {
      const next = await inspect({ query: query.trim() });
      setSnapshot(next);
      setSelected(next.matches.length === 1 ? next.matches[0] : null);
    } catch {
      setError("Не удалось проверить процессы. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  };
  const run = async () => {
    if (!selected) return;
    setBusy(true);
    setError("");
    setSamples([]);
    const started = Date.now();
    const collected: Snapshot[] = [];
    try {
      for (let remaining = 8; remaining > 0; remaining -= 1) {
        setSeconds(remaining);
        const next = await inspect({ pid: selected.pid, since: started });
        collected.push(next);
        setSamples([...collected]);
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
      const final = await inspect({ pid: selected.pid, since: started });
      collected.push(final);
      setSamples([...collected]);
      setResult(conclusion(collected, selected));
    } catch {
      setError(
        "Проверка прервалась. Оставьте приложение открытым и повторите попытку.",
      );
    } finally {
      setBusy(false);
    }
  };
  const report = JSON.stringify(
    {
      generated_at: new Date().toISOString(),
      candidate: selected,
      samples,
      result,
    },
    null,
    2,
  );

  return (
    <div className="process-diagnostic-entry">
      <div>
        <h3>Не видите приложение в статистике?</h3>
        <p>Проверьте, на каком этапе оно перестаёт попадать в историю.</p>
      </div>
      <button className="soft-button" onClick={() => setOpen(true)}>
        Проверить приложение
      </button>
      {open && (
        <div className="diagnostic-overlay" role="presentation">
          <section
            className="diagnostic-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="diagnostic-title"
          >
            <button
              className="diagnostic-close"
              aria-label="Закрыть"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                reset();
              }}
            >
              ×
            </button>
            <p className="diagnostic-kicker">Локальная диагностика</p>
            <h2 id="diagnostic-title">Не вижу приложение в статистике</h2>
            {!snapshot ? (
              <>
                <p>
                  Запустите нужное приложение и введите его название или имя
                  процесса.
                </p>
                <div className="diagnostic-search">
                  <input
                    value={query}
                    autoFocus
                    placeholder="Например, Discord или discord.exe"
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void search();
                    }}
                  />
                  <button
                    className="soft-button"
                    disabled={busy || !query.trim()}
                    onClick={() => void search()}
                  >
                    {busy ? "Ищем…" : "Найти"}
                  </button>
                </div>
              </>
            ) : result ? (
              <div className="diagnostic-result">
                <span aria-hidden="true">✓</span>
                <h3>{result.title}</h3>
                <p>{result.body}</p>
                <div className="settings-actions">
                  <button
                    className="soft-button"
                    onClick={() => {
                      reset();
                    }}
                  >
                    Проверить снова
                  </button>
                  <button
                    className="text-button"
                    onClick={() => void navigator.clipboard.writeText(report)}
                  >
                    Скопировать отчёт
                  </button>
                  {result.action === "apps" && (
                    <button
                      className="soft-button"
                      onClick={() => {
                        setOpen(false);
                        navigate("/settings/apps");
                      }}
                    >
                      Открыть приложения
                    </button>
                  )}
                </div>
              </div>
            ) : busy && samples.length > 0 ? (
              <div className="diagnostic-observing" role="status">
                <strong>{seconds}</strong>
                <h3>Переключитесь в нужное приложение</h3>
                <p>
                  Поработайте в нём до окончания проверки и затем вернитесь
                  сюда.
                </p>
              </div>
            ) : snapshot.matches.length === 0 ? (
              <div className="diagnostic-empty">
                <h3>Подходящий процесс не найден</h3>
                <p>
                  Проверьте, что приложение запущено, или попробуйте имя файла с
                  расширением .exe.
                </p>
                <button className="soft-button" onClick={reset}>
                  Изменить поиск
                </button>
              </div>
            ) : (
              <>
                <p>
                  Выберите процесс, затем переключитесь в его окно на 8 секунд.
                </p>
                <div className="diagnostic-candidates">
                  {snapshot.matches.map((candidate) => (
                    <label
                      className={
                        selected?.pid === candidate.pid ? "selected" : ""
                      }
                      key={`${candidate.pid}-${candidate.process_started_at}`}
                    >
                      <input
                        type="radio"
                        name="diagnostic-process"
                        checked={selected?.pid === candidate.pid}
                        onChange={() => setSelected(candidate)}
                      />
                      <span>
                        <strong>{candidate.display_name}</strong>
                        <small>
                          {candidate.process_name} · PID {candidate.pid}
                        </small>
                        <small>
                          {candidate.executable_path || "Путь недоступен"}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
                <div className="settings-actions diagnostic-actions">
                  <button className="text-button" onClick={reset}>
                    Назад
                  </button>
                  <button
                    className="soft-button"
                    disabled={!selected}
                    onClick={() => void run()}
                  >
                    Начать проверку
                  </button>
                </div>
              </>
            )}
            {error && (
              <p className="settings-error" role="alert">
                {error}
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
