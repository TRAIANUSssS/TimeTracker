# Хранилище: этап 1

## Модели и границы ответственности

`domain/models.py` содержит неизменяемые dataclasses для восьми сущностей ТЗ
и `SystemState`. Timestamps передаются целыми UTC Unix milliseconds; преобразование
часовых поясов будет добавлено в статистический слой. Модели не импортируют SQLite
или Windows API.

`domain/identity.py` нормализует достоверные абсолютные Windows-пути: регистр,
разделители, сегменты `.`/`..`, префиксы `\\?\` и `\\?\UNC\`. Относительные/пустые
пути отвергаются. Это лексическая идентичность: физические aliases файловой системы
(symlink, junction, короткие 8.3-имена) автоматически не объединяются.

Репозитории отвечают за сохранение записей. Решения о смене foreground/system state,
подсчёте процессов приложения, backdated IDLE, recovery и согласовании RAM с БД
будет принимать session manager следующего этапа.

## SQLite и миграции

- База создаётся явно через `Database.initialize()` или CLI `--init-db`.
- Используются WAL и `synchronous=FULL`; foreign keys включаются для каждого подключения.
- Подключения принадлежат вызывающему потоку. Общего подключения между polling и API нет.
- `Database.reader()` открывает файл в режиме `ro`, включает query_only и предоставляет
  read transaction для согласованного чтения одной статистической выборки.
- `Database.transaction()` открывает writer и `BEGIN IMMEDIATE`. Конкурирующий writer
  ожидает до 5 секунд по умолчанию; после этого ошибка передаётся вызывающему коду.
- Версия схемы хранится в `PRAGMA user_version`; идентификатор формата TimeTracker
  `0x5454524B` — в `PRAGMA application_id`.
- Все ожидающие миграции, изменения данных и обновления версии применяются одной
  транзакцией. Неудачная миграция откатывается целиком; `executescript()` не используется.
- Новая версия приложения не должна редактировать уже выпущенную миграцию:
  нужно добавить `Migration(n + 1, name, statements)` в конец `MIGRATIONS`.
- Более новая схема, чужой application_id и непустая база без версии отклоняются.

Таблицы создаются в STRICT-режиме, поэтому требуется SQLite 3.37+. Версия проверяется
до инициализации. Все timestamps хранятся как INTEGER; текстовые даты не принимаются.

По сравнению с примерной схемой ТЗ добавлены CHECK для boolean-полей и временных
границ, единственность открытых foreground/system/run записей и известной process
identity. Composite foreign key запрещает foreground с executable другого приложения.
Aliases ограничены одноуровневыми связями без циклов, но операции merge пока отсутствуют.

## Пример записи

```python
from time_tracker.domain.models import SystemState
from time_tracker.storage.database import Database
from time_tracker.storage.repositories import Repositories

db = Database("data/example.db")
db.initialize()

with db.transaction() as connection:
    repo = Repositories(connection)
    app = repo.applications.create("Example", at=1_000)
    exe = repo.executables.create(app.id, "C:/Apps/Example.exe", at=1_000)
    run = repo.runs.start(at=1_000, version="development")
    sessions = Repositories(connection, run_id=run.id)
    sessions.processes.start(
        pid=123, process_started_at=500, detected_at=1_000, executable_id=exe.id
    )
    sessions.running.start(app.id, at=1_000)
    sessions.foreground.start(app.id, at=1_000, executable_id=exe.id, hwnd=42)
    sessions.system_states.start(SystemState.ACTIVE, at=1_000)
```

В этом примере times — искусственные миллисекунды для иллюстрации. Он оставляет
открытые sessions/run; автоматического завершения или recovery на этом этапе нет.

Каждый метод записи использует транзакцию либо savepoint внутри внешней транзакции.
Несколько операций одного события нужно группировать через `Database.transaction()`
или `storage.transactions.transaction(connection)`. Отмена внешней транзакции
отменяет и ранее успешные вызовы репозиториев.

Открытие, закрытие и уточнение сессии требуют `run_id` действующего запуска.
Изменения сессии и `last_persisted_at = max(previous, observation_time)` атомарны.
Ошибка записи не продвигает границу восстановления. Heartbeat обновляет отдельное
монотонное поле. `TrackerRun.recovery_at` возвращает максимум этих двух границ.

`runs.finish()` требует предварительного закрытия всех sessions. Сам алгоритм
штатного завершения и crash recovery реализуется следующим этапом.
При запуске будущего tracker single-instance lock берётся до работы с БД;
уникальный индекс открытого run дополняет его, но не заменяет блокировку процесса.

## Неизвестные процессы и параметры приложений

Процесс с недоступным путём сохраняется с `executable_id=None`. Позднее метод
`resolve_executable()` может связать его с executable только при совпадении
сохранённых PID и creation time. Без creation time уверенная ретроспективная
привязка не выполняется. Running session создаёт session manager с момента
определения приложения, а не задним числом.

`applications.update_settings()` обновляет только сохранённые flags. Будущая команда
PATCH должна через session manager одновременно обновить RAM и при необходимости
перекрыть foreground session на границе изменения title policy. Сам repository не
закрывает текущую session. Новые foreground records дополнительно маскируют title,
если у приложения отключён track_titles; старые titles не удаляются.

Запросы статистики, пересечения интервалов и применение aliases к агрегатам относятся
к последующим этапам. Текущие методы чтения возвращают исходные записи.

## Справочные материалы

- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html).
- [SQLite STRICT tables](https://www.sqlite.org/stricttables.html).
- [SQLite savepoints](https://www.sqlite.org/lang_savepoint.html).
