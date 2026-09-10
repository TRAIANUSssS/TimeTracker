# Проверки TimeTracker

Запуск из корня проекта:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Текущее покрытие хранения, ядра, Windows-интеграции и API:

`test_etw_shutdown.py` проверяет завершение ETW через настоящий локальный канал и
отдельную SQLite без повышения прав: финальный буфер, несколько пачек, cutoff времени,
разрыв/тайм-аут, гонку подключения, естественное завершение и проверку управляющей команды.
Проверка реального ETW при выходе: `tools/check_etw_integration.py --stop-early`;
порядок запуска сборщика описан в [etw-integration.md](../docs/etw-integration.md).

Кеш процессов дополнительно проверяется в `test_windows_collectors.py`: свежая
identity при попадании в кеш, stale psutil-объект, PID reuse во время exe/metadata,
исчезновение, утрата/восстановление доступа, очистка кеша и общий retry metadata
нескольких процессов одного executable без повторного чтения иконки.

- `test_performance.py`: вложенные CPU/wall таймеры, ограниченные выборки,
  потоки, отключённый режим, сохранение исключений и отказ диагностического файла.
- `test_benchmark_runner.py`: нормализация CPU, раздельные состояния,
  защита от PID reuse и read-only проверка тестовой истории.
- Автоматические живые замеры и ручные сценарии: [performance.md](../docs/performance.md).

- `test_database.py`: создание/повторное открытие БД, WAL, foreign keys,
  read-only подключения, чтение во время записи, откат транзакций и миграций,
  применение новой версии, отказ от чужой/более новой БД;
- `test_repositories.py`: сохранение и чтение сессий, атомарность last_persisted_at,
  ограничения интервалов и открытых записей, неизвестные процессы, executable identity,
  параметры приложений, сохранность старых titles и ограничения aliases;
- `test_cli.py`: установка схемы через CLI в том числе в путь с кириллицей/пробелами,
  повторная инициализация, обработка ошибок и отсутствие неявного создания истории;
- `test_session_manager.py`: счётчики процессов, замена snapshot без разрыва running,
  повторное использование PID, неизвестные пути/creation time, foreground до process poll,
  отсутствие записей при неизменных наблюдениях, устаревшие/неполные snapshots,
  title policy и ignored, приоритеты состояний, точная граница IDLE, сон и пробуждение,
  атомарность БД/RAM, штатное завершение и crash recovery;
- `test_runtime.py`: fake provider/clock, владение одним потоком, блокировка второго
  экземпляра до доступа к БД, отказ CLI при занятой БД, освобождение блокировки
  при ошибках и аварийном выходе дочернего процесса, восстановление и перевод часов назад;
- `test_windows_collectors.py`: PID reuse и кеш psutil, отказ доступа к metadata,
  процессы, исчезнувшие при чтении, token неизвестного creation time, гонка владельца
  окна, Win32-ошибка foreground, переполнение tick count и кеш иконок;
- `test_collection_controller.py`: интервалы опроса, порядок heartbeat, сбои polling,
  повторные resume, ожидание свежего snapshot, сверка lock state, медленный resolver;
- `test_windows_integration.py`: настоящее скрытое окно и Win32 message loop
  с искусственными наблюдениями, WTS/power сообщения и ветка «Выход» меню,
  запрет второго CLI tracker, обработка ошибки callback и выхода во время записи;
- `test_windows_live.py`: отдельная opt-in проверка настоящего desktop polling,
  heartbeat, извлечения иконки и трея с автоматическим завершением.

`test_power_history.py` проверяет чтение временных меток Kernel-Power, пары
Modern Standby/hibernate и воспроизводит последовательность пользовательского теста
с коротким промежуточным пробуждением: 430 + 9213 = 9643 ms SLEEP.
Проверяются позднее получение пары, атомарность коррекции БД/RAM, границы run,
сохранение LOCKED по краям, удаление устаревшего foreground, повторная обработка,
быстрый unlock перед медленным snapshot и новый сон во время его чтения.
Live smoke на AoAc-машине использует настоящий `PowerHistory` вместе с остальными
источниками, но сам не переводит компьютер в сон.

Все SQLite-файлы создаются в `tmp_path`. Обычный набор тестов не собирает пользовательскую
активность. Windows message tests работают в отдельном дочернем процессе с timeout,
без перевода компьютера в сон или блокировки экрана. Ошибки записи моделируются
откатом внешней транзакции и SQLite trigger, отклоняющим закрытие сессии.

Для короткой проверки на настоящем рабочем столе Windows:

```powershell
$env:TIME_TRACKER_WINDOWS_SMOKE = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_windows_live.py -q
Remove-Item Env:TIME_TRACKER_WINDOWS_SMOKE
```

Этот тест кратковременно показывает значок трея и записывает реальные наблюдения
в отдельную временную БД. Он сам завершается после полного polling cycle,
проверяет закрытие сессий и целостность SQLite. В вывод не попадают названия окон.

Статистика и API:

- `test_time_windows.py`: полуоткрытые интервалы, полный день 23/24/25 часов,
  повторяющиеся частичные часы, пропущенный час/дата, DST на полчаса,
  ночные окна, timezone с дробным смещением и точный ввод минут;
- `test_stats.py`: тройные пересечения, исключение сна/пробелов из running,
  ignored и metadata flags, сортировка, открытые сессии, timeline без растягивания
  пробелов/будущего, context switches на границе фильтра, heatmap coverage,
  взвешенное среднее и согласованный WAL snapshot при изменении настроек;
- `test_api.py`: HTTP-контракты, 422/404/503, строгие boolean PATCH,
  применение команд владельцем записи, title policy, rollback, отмена до
  принятия команды, завершение с ожидающим PATCH, icon cache и реальный loopback-сервер;
- `test_windows_integration.py` также проверяет HTTP PATCH через настоящий
  Win32 message loop: ответ после записи, смена title policy и закрытие порта при выходе;
- `test_cli.py` проверяет валидацию `--api-port`.

HTTP-проверки открывают только временный loopback-порт; пользовательскую БД не меняют.

Dashboard и сборка:

- `test_dashboard_startup.py`: same-origin HTML/assets и маршруты-заглушки,
  передача полной DST-шкалы, отсутствие сборки UI, команда автозапуска и её удаление
  в отдельном ключе реестра, действия меню трея;
- `frontend/tests/dashboard.spec.ts`: 7 браузерных сценариев на Edge headless —
  фильтры/refresh/expand, запросы только нужных секций, точные минуты и ночные окна,
  ошибки/повтор, поколения запросов, midnight marker и состояния heatmap;
- `test_packaged_live.py`: opt-in запуск собранного exe с настоящим polling,
  API/PATCH, heartbeat и SQLite, загрузка dashboard в Edge через реальный API,
  отсутствие внешних запросов и штатное завершение. Вызывать после сборки
  с `TIME_TRACKER_PACKAGED_SMOKE=1`; см. [инструкцию](../docs/ui-build.md).
  Для диагностической сборки в другом каталоге указать полный путь к exe в
  `TIME_TRACKER_PACKAGED_EXE`; по умолчанию проверяется `dist/TimeTracker/TimeTracker.exe`.

`test_worker.py` проверяет настоящим потоком: владение runtime, очереди lock/sleep/wake
во время долгого poll/resume, отмену стартового snapshot, выход до старта,
переполнение с recovery и команды настроек после lifecycle. Нативные integration
тесты дополнительно блокируют источник и проверяют ответ HWND, асинхронный Exit,
финальный/отменённый WM_ENDSESSION и закрытие API.

Два opt-in smoke пропускаются по умолчанию.

`test_process_events_probe.py`: диагностический прототип WMI, FILETIME событий,
различение HRESULT/timeout, COM owner/cleanup и отказ в доступе. Production process
events ещё не подключены; доступность на ПК проверяется отдельным
`tools/probe_process_events.py` (см. отчёт этапа 5).

`test_etw_probe.py`: x64 ABI ETW, TDH-декодирование start/stop по зарегистрированной
схеме Windows без активной подписки, ошибки callback, ограничение очереди,
учёт потерь, отсутствие сессии и чтение actual process times собственного помощника.
Живая ETW-доставка проверяется обновлённым `probe_process_events.py` отдельно.

`test_etw_collector.py`: 24 проверки отдельного сборщика и IPC без повышенных прав:
реальные named pipes, ACL, запрет команд от читателя, отмена I/O, медленный/отключённый
читатель, частичный фрейм, конфликт каналов, cleanup, сохранение пути и identity,
потери и последовательности. Live-проверка повышенного сборщика с обычным читателем:
[инструкция](../docs/etw-collector.md), `tools/check_etw_collector.py`.

`test_process_event_integration.py`: 18 сценариев ETW → worker → SessionManager:
поздние/переставленные события, короткие сессии, PID reuse, история foreground,
running union, rollback, 60/5 s, checkpoint, reconnect, переполнение и реальный pipe.
`test_database.py` дополнительно проверяет миграцию 1 → 2 с сохранением истории.
Полный live-путь проверяет `tools/check_etw_integration.py` на отдельной БД;
см. [инструкцию](../docs/etw-integration.md).

Packaged smoke отдельно прошёл на текущем Windows 11 x64. Браузерные скриншоты
с искусственными данными и скриншот настоящего exe сохраняются в
`frontend/test-results/`, вне Git. Реальный вход в Windows после перезагрузки
этими проверками не выполняется; автозапуск не включается на машине пользователя.
