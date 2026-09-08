# TimeTracker

Локальный трекер времени для Windows 10/11: приложения, активные окна,
состояния пользователя и статистика по интервалам. Планируемый стек — Python,
SQLite, FastAPI и локальный web-интерфейс.

**Текущий статус:** завершены хранение, ядро и сбор Windows-активности. Трекер
запускается в трее, записывает процессы, активные окна, IDLE/LOCKED/SLEEP,
сохраняет heartbeat и восстанавливает историю после сбоя. Метаданные и иконки
приложений кешируются локально. Реализованы статистика и локальный FastAPI:
пересечения интервалов, фильтры с DST, timeline/heatmap и параметры приложений.
Dashboard и автозапуск появятся на этапе UI и сборки.

## Документы

- [Техническое ТЗ](time_tracker_codex_spec_v2.md) — модель данных, правила и API.
- [UI-спецификация](time_tracker_ui_spec.md) — интерфейс и его поведение.
- [Визуальный референс](<ChatGPT Image 8 сент. 2026 г., 15_15_12.png>) — композиция и стиль.

Числа на референсе иллюстративны; расчёты определяются техническим ТЗ.

## Структура

```text
TimeTracker/
├── pyproject.toml
├── README.md
├── time_tracker_codex_spec_v2.md
├── time_tracker_ui_spec.md
├── src/
│   └── time_tracker/
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py              # сборка приложения и точка входа
│       ├── paths.py             # расположение локальной базы
│       ├── runtime.py           # запуск, блокировка, heartbeat и завершение
│       ├── application.py       # сборка Windows-приложения и журнал
│       ├── collector.py         # последовательные опросы и уведомления
│       ├── domain/
│       │   ├── models.py        # типизированные записи и SystemState
│       │   ├── identity.py      # нормализация Windows executable path
│       │   ├── events.py        # нормализованные наблюдения и команды
│       │   ├── ports.py         # контракты хранения, часов и snapshot provider
│       │   ├── system_state.py  # приоритет системных состояний
│       │   ├── tracker_state.py # состояние и кеши в памяти
│       │   └── session_manager.py # переходы, сессии и recovery
│       ├── platform/
│       │   ├── instance_lock.py # блокировка БД на время работы tracker
│       │   └── windows/         # Win32 API, процессы, provider и кеш иконок
│       ├── storage/
│       │   ├── database.py     # подключения, WAL, чтение и запись
│       │   ├── schema.py       # исходная схема и ограничения
│       │   ├── migrations.py   # версии схемы и атомарное обновление
│       │   ├── repositories.py # операции с типизированными записями
│       │   ├── tracker_store.py # адаптер транзакций для ядра
│       │   └── transactions.py # транзакции и вложенные savepoints
│       ├── api/                # FastAPI и контракты
│       └── tray/tray_app.py     # скрытое окно Windows, меню трея и выход
├── tests/                      # тесты ядра, хранения и API
├── docs/                       # документация реализации
└── frontend/                   # будущий web-интерфейс
```

Модули внутри пакетов добавляются по мере реализации. Windows-адаптеры получают
наблюдения, domain обрабатывает события, storage сохраняет историю. API читает
статистику и передаёт команды изменения общему обработчику записи.

## Подготовка окружения

Требуется Python 3.12 или новее. Команды выполняются в PowerShell из корня проекта.
Активация виртуального окружения и изменение ExecutionPolicy не нужны.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Зависимости описаны в `pyproject.toml`: на Windows устанавливаются psutil, pywin32
и Pillow; для разработки — pytest и Ruff. После обновления репозитория повторите
команду `pip install -e ".[dev]"`, чтобы установить новые зависимости и точки входа.
Для API устанавливаются FastAPI и Uvicorn, для часовых поясов — tzdata;
HTTP-тесты используют httpx.

## Запуск трекера

Из PowerShell:

```powershell
.\.venv\Scripts\python.exe -m time_tracker --track
```

Для запуска без консольного окна:

```powershell
Start-Process -FilePath .\.venv\Scripts\time-tracker-tray.exe -WindowStyle Hidden
```

Значок TimeTracker появляется в трее (в том числе в области скрытых значков).
Правый или левый щелчок открывает меню; **«Выход»** завершает запись и закрывает
сессии. Dashboard и пауза пока недоступны. Приложение не добавляет себя в автозапуск.
В консольном режиме также можно завершить работу через Ctrl+C.

База по умолчанию — `%LOCALAPPDATA%\TimeTracker\tracker.db`. Для отдельной истории:

```powershell
.\.venv\Scripts\python.exe -m time_tracker --track --database .\data\tracker.db
```

Схема создаётся автоматически. Рядом с БД появляются `icons/` и `logs/tracker.log`
с ротацией. Повторный экземпляр для той же БД отклоняется до восстановления истории.
Сбор запускается явно через `--track` или `time-tracker-tray.exe`.

## Статистика и API

API запускается и завершается вместе с трекером. После `--track` откройте
**http://127.0.0.1:8765/docs** — описание endpoints и форма для пробных запросов.
Это документация API; пользовательский dashboard появится на следующем этапе.
JSON-контракт доступен на `/openapi.json`.

Пример чтения статистики за день:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8765/stats/apps?date_from=2026-09-08&date_to=2026-09-08&time_from=00:00&time_to=24:00&timezone=Europe%2FMoscow'
```

Если порт занят, можно задать другой:

```powershell
.\.venv\Scripts\python.exe -m time_tracker --track --api-port 8766
```

Сервер слушает только `127.0.0.1`. Запросы из браузера с другого origin
отклоняются. Настройки меняются через `PATCH /applications/{id}`; команда
применяется тем же потоком, который записывает события трекера.
Подробности расчётов и примеры: [docs/statistics-api.md](docs/statistics-api.md).

## Проверка запуска

```powershell
.\.venv\Scripts\python.exe -m time_tracker
.\.venv\Scripts\python.exe -m time_tracker --help
.\.venv\Scripts\time-tracker.exe --version
```

Без параметров точка входа выводит статус и завершается. Для создания базы:

```powershell
.\.venv\Scripts\python.exe -m time_tracker --init-db
```

На Windows база создаётся в `%LOCALAPPDATA%\TimeTracker\tracker.db`, независимо
от текущей рабочей директории. Можно задать другой путь:

```powershell
.\.venv\Scripts\python.exe -m time_tracker --init-db --database .\data\tracker.db
```

Повторная инициализация сохраняет данные и применяет только недостающие миграции.
Команда не создаёт tracker run, не выполняет recovery и не запускает сбор активности.
База другого приложения или более новой версии отклоняется. Инициализация также
отклоняется, если эту БД уже использует работающий tracker.

Подробности схемы и работы репозиториев: [docs/storage.md](docs/storage.md).
Контракты событий и жизненный цикл ядра: [docs/core.md](docs/core.md).
Windows-интеграция, ограничения и ручная проверка: [docs/windows.md](docs/windows.md).

## Проверки кода

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q
```

Тесты используют временные SQLite-файлы и искусственные наблюдения. Блокировка
проверяется средствами ОС, включая аварийный выход дочернего процесса; сбор
пользовательской активности не запускается. Покрытие описано в [tests/README.md](tests/README.md).

## Этапы реализации

1. **Готово:** модели, схема SQLite, миграции и repositories.
2. **Готово:** ядро сессий, runtime state, восстановление после сбоя и тесты на fake providers.
3. **Готово:** Windows-процессы, foreground, idle, сон, блокировка, иконки и трей.
4. **Готово:** статистика и API: пересечения, фильтры, timeline/heatmap и параметры приложений.
5. UI и сборка: dashboard по референсу, автозапуск и проверка полного приложения.

Каждый этап должен завершаться работающим результатом и соответствующими проверками.

## Файлы в Git

В репозиторий входят исходники, конфигурация, документация и визуальный референс.
`.gitignore` исключает `.venv`, Python/frontend-кеши, базы SQLite с WAL/SHM,
логи, локальные `.env`, каталоги `data/`, `logs/` и результаты сборки.

## Справка по конфигурации

Формат пакета следует [руководству Python Packaging](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
Параметры проверок описаны в документации [pytest](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
и [Ruff](https://docs.astral.sh/ruff/configuration/).
