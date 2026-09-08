# TimeTracker

Локальный трекер времени для Windows 10/11: приложения, активные окна,
состояния пользователя и статистика по интервалам. Планируемый стек — Python,
SQLite, FastAPI и локальный web-интерфейс.

**Текущий статус:** подготовлена стартовая структура проекта. Работают установка
Python-пакета и консольная точка входа. Сбор активности, база данных, API, трей
и dashboard будут добавлены на следующих этапах.

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
│       ├── domain/              # события, состояния, логика интервалов
│       ├── platform/
│       │   └── windows/         # источники данных Windows
│       ├── storage/            # SQLite, миграции, статистика
│       ├── api/                # FastAPI и контракты
│       └── tray/               # трей и жизненный цикл
├── tests/                      # тесты ядра, хранения и API
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

Пока точка входа сообщает о готовности каркаса и завершается. Она не запускает
фоновый процесс и не создаёт историю активности.

## Проверки кода

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

План тестов и будущая команда запуска описаны в [tests/README.md](tests/README.md).

## Этапы реализации

1. Хранение: схема SQLite, миграции и repositories.
2. Ядро: runtime state, интервалы, восстановление после сбоя и тесты на fake providers.
3. Windows: процессы, foreground, idle, сон, блокировка и трей.
4. Статистика и API: пересечения, фильтры, timeline/heatmap и параметры приложений.
5. UI и сборка: dashboard по референсу, автозапуск и проверка полного приложения.

Каждый этап должен завершаться работающим результатом и соответствующими проверками.

## Файлы в Git

В репозиторий входят исходники, конфигурация, документация и визуальный референс.
`.gitignore` исключает `.venv`, Python/frontend-кеши, базы SQLite с WAL/SHM,
логи, локальные `.env`, каталоги `data/`, `logs/` и результаты сборки.

Первый коммит можно назвать `chore: scaffold TimeTracker project`.

## Справка по конфигурации

Формат пакета следует [руководству Python Packaging](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).
Параметры проверок описаны в документации [pytest](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
и [Ruff](https://docs.astral.sh/ruff/configuration/).
