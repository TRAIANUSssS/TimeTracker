# TimeTracker

Локальный трекер времени для Windows 10/11: приложения, активные окна,
состояния пользователя и статистика по интервалам. Планируемый стек — Python,
SQLite, FastAPI и локальный web-интерфейс.

**Текущий статус:** завершены хранение и ядро сессий. Реализованы SQLite, миграции,
обработка событий, состояния ACTIVE/IDLE/LOCKED/SLEEP, восстановление после сбоя
и блокировка второго экземпляра. Ядро проверяется на управляемых наблюдениях и часах.
Следующий этап — сбор Windows-активности и трей; API и dashboard появятся позднее.

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
│       │   └── windows/         # источники данных Windows
│       ├── storage/
│       │   ├── database.py     # подключения, WAL, чтение и запись
│       │   ├── schema.py       # исходная схема и ограничения
│       │   ├── migrations.py   # версии схемы и атомарное обновление
│       │   ├── repositories.py # операции с типизированными записями
│       │   ├── tracker_store.py # адаптер транзакций для ядра
│       │   └── transactions.py # транзакции и вложенные savepoints
│       ├── api/                # FastAPI и контракты
│       └── tray/               # трей и жизненный цикл
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

Зависимости описаны в `pyproject.toml`. Сейчас устанавливаются инструменты
разработки pytest и Ruff. FastAPI, Windows-интеграции и остальные runtime-зависимости
будут добавлены вместе с использующим их кодом.

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
3. Windows: процессы, foreground, idle, сон, блокировка и трей.
4. Статистика и API: пересечения, фильтры, timeline/heatmap и параметры приложений.
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
