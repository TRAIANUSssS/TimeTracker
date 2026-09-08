# Time Tracker — техническое ТЗ для Codex

## 1. Цель проекта

Создать локальный time tracker для Windows, который:

- постоянно работает в системном трее;
- отслеживает запущенные приложения;
- отслеживает foreground-приложение;
- сохраняет title активного окна;
- определяет состояния пользователя/системы:
  - `ACTIVE`
  - `IDLE`
  - `LOCKED`
  - `SLEEP`
- хранит историю локально в SQLite;
- предоставляет локальный HTTP API для web-интерфейса на `localhost`;
- считает статистику по интервалам, а не по 3–5-секундным сэмплам.

MVP включает ядро трекера, SQLite-модель, state machine, API для статистики
и основной dashboard по `time_tracker_ui_spec.md`. Реализацию можно вести по этапам:
сначала ядро/API, затем web-интерфейс.

Полный визуальный UI-spec находится в `time_tracker_ui_spec.md`. Это ТЗ включает технические требования,
которые следуют из согласованного MVP-интерфейса: фильтрацию, сортировку, иконки приложений,
timeline/heatmap API и frontend-поведение, влияющее на архитектуру.

---

# 2. Целевая платформа

MVP:

- Windows 10/11
- Python
- SQLite
- FastAPI для локального API
- приложение должно иметь tray icon и уметь запускаться вместе с Windows

В будущем архитектура должна позволять добавить другие платформы, поэтому Windows-specific код необходимо изолировать от бизнес-логики.

---

# 3. Главный архитектурный принцип

Windows/polling слой не должен напрямую писать в SQLite.

Общий поток:

```text
Windows API / Polling
        ↓
Normalized Tracker Events
        ↓
Tracker State Manager
        ↓
Session Manager
        ↓
SQLite Repository
        ↓
FastAPI
```

Windows-specific слой отвечает только за получение данных из ОС и генерацию нормализованных событий.

State/session logic не должна зависеть от способа получения данных.

Это необходимо для того, чтобы позднее можно было заменить polling foreground-window на event-driven Windows hooks без переписывания хранения и статистики.

---

# 4. Polling в MVP

Использовать polling как основной механизм.

Рекомендуемые интервалы:

```text
Foreground window: 2 sec
Idle state:        2 sec
Running processes: 5 sec
Heartbeat:         5 sec
```

Допускается небольшая погрешность в определении времени старта/остановки процессов.

Для `IDLE` следует восстанавливать точный момент начала:

```text
idle_started_at = last_input_time + idle_threshold
```

а не использовать время очередного poll.

---

# 5. Windows data sources

Необходимо получать:

## Foreground window

- HWND активного окна
- PID процесса
- executable path
- executable filename
- window title
- `FileDescription`
- `ProductName`
- иконку executable/application, если Windows позволяет её получить

`FileDescription` / `ProductName` используются уже в MVP для формирования красивого display name.
Они НЕ используются в MVP для автоматического объединения приложений после переустановки/обновления.

Базовые Windows API:

- `GetForegroundWindow`
- `GetWindowThreadProcessId`
- получение title окна
- `psutil.Process(pid)` для process metadata

## Running processes

Через `psutil.process_iter()`.

Процесс нельзя идентифицировать только по PID, так как Windows повторно использует PID.

Логическая идентичность процесса:

```text
PID + process creation time
```

## Idle

Через `GetLastInputInfo`.

Порог MVP:

```text
5 minutes
```

## Lock / unlock

Отслеживать Windows session lock/unlock events.

## Sleep / wake

Отслеживать suspend/resume events Windows.

---

# 6. Application vs Executable

Эти сущности должны быть разделены уже в MVP.

## Application

Логическое приложение:

```text
Visual Studio Code
Telegram
Google Chrome
```

## Executable

Конкретный путь к `.exe`:

```text
C:\Users\...\Code.exe
D:\Programs\VSCode\Code.exe
```

В MVP новый неизвестный executable path создаёт новое `application`.

Это правило применяется только к достоверно полученному пути, которого ещё нет в БД.
Отсутствующий путь не создаёт application/executable с фиктивным общим path.
Путь нормализуется единообразно перед lookup/INSERT; различие регистра и разделителей
не должно создавать дубликаты одного Windows executable. Одного `exe_name` недостаточно
для установления идентичности приложения.

В POST-MVP должна появиться автоматическая привязка нового executable к уже существующему application по:

```text
ProductName
Publisher
OriginalFilename
```

Схема БД должна позволять сделать это без миграции foreground/running history.

Для этого предусмотрена `application_aliases` (§8.8): старый application ID может
ссылаться на основной ID. Исторические записи сохраняют исходные ID. В MVP таблица
создаётся пустой; автоматическое/ручное объединение и UI управления им — POST-MVP.

## Display name в MVP

При создании нового `application` имя определять по следующему приоритету:

```text
1. FileDescription
2. ProductName
3. executable filename без .exe
4. "Unknown application"
```

Не использовать это правило для автоматического merge приложений в MVP.

---

## Иконки приложений в MVP

Иконку приложения следует извлекать из `.exe` средствами Windows Shell API
(например, `SHGetFileInfo` / `ExtractIconEx` или эквивалентом).

Иконки не хранить BLOB-ами в SQLite.

Рекомендуемый локальный cache:

```text
data/
├── tracker.db
└── icons/
    ├── app_17.png
    ├── app_18.png
    └── app_19.png
```

Имя файла может строиться по `application_id`.

Требования:

- извлекать иконку при первом создании application/executable;
- не выполнять повторное извлечение на каждом polling cycle;
- при ошибке не падать;
- при отсутствии иконки frontend показывает нейтральный fallback с первой буквой display name;
- в будущем cache можно обновлять при смене preferred executable.

---



# 7. SQLite

Использовать SQLite.

При старте приложения:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

WAL нужен для одновременной записи tracker-а и чтения FastAPI.

Все timestamps хранить в UTC.

Рекомендуемый формат:

```text
INTEGER milliseconds since Unix epoch
```

UI/API могут принимать локальные timestamps, но перед SQL-запросами backend обязан конвертировать их в UTC milliseconds.

---

# 8. Таблицы

## 8.1 applications

```sql
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL,

    ignored INTEGER NOT NULL DEFAULT 0,
    track_titles INTEGER NOT NULL DEFAULT 1,

    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
```

### Поля

`ignored`

- `0` — приложение участвует в статистике
- `1` — исключается из таблицы приложений и расчёта context switches
- сырые исторические записи не удаляются

Общее активное время и heatmap считаются по системному `ACTIVE`, включая ignored activity.
На timeline такая активность отображается как `other_activity` без имени и title приложения.

`track_titles`

- `1` — сохранять title активного окна
- `0` — сохранять foreground session, но `window_title = NULL`

---

## 8.2 executables

```sql
CREATE TABLE executables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    application_id INTEGER NOT NULL,

    path TEXT NOT NULL,
    exe_name TEXT NOT NULL,

    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,

    FOREIGN KEY (application_id)
        REFERENCES applications(id),

    UNIQUE(path)
);
```

---

## 8.3 process_sessions

```sql
CREATE TABLE process_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    executable_id INTEGER,

    pid INTEGER NOT NULL,
    process_started_at INTEGER,

    detected_at INTEGER NOT NULL,
    ended_at INTEGER,

    FOREIGN KEY (executable_id)
        REFERENCES executables(id)
);
```

`process_started_at` — creation time процесса по данным ОС.

`detected_at` — когда tracker впервые увидел процесс.

`executable_id = NULL` допустим для наблюдаемого процесса с недоступным путём.
PID и доступный `process_started_at` сохраняются, application/running session пока
не создаётся. Runtime использует отдельный идентификатор наблюдения для процесса,
у которого creation time неизвестен; один PID не доказывает идентичность после разрыва.

Если путь стал доступен и подтверждён тот же экземпляр `(pid, process_started_at)`,
можно заполнить `executable_id` в прежней process session. Начало логической running
session — момент достоверного определения приложения, без начисления времени назад.
Если идентичность подтвердить нельзя, закрыть прежнее наблюдение и открыть новое.

---

## 8.4 application_running_sessions

```sql
CREATE TABLE application_running_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    application_id INTEGER NOT NULL,

    started_at INTEGER NOT NULL,
    ended_at INTEGER,

    FOREIGN KEY (application_id)
        REFERENCES applications(id)
);
```

Эта таблица хранит логические running intervals приложения.

Chrome с 20 процессами должен иметь одну running session, а не 20.

Правило:

```text
application process count 0 → 1
    open running session

1 → 2 → ... → N
    nothing

1 → 0
    close running session
```

---

## 8.5 foreground_sessions

```sql
CREATE TABLE foreground_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    application_id INTEGER NOT NULL,
    executable_id INTEGER,

    hwnd INTEGER,

    window_title TEXT,

    started_at INTEGER NOT NULL,
    ended_at INTEGER,

    FOREIGN KEY (application_id)
        REFERENCES applications(id),

    FOREIGN KEY (executable_id)
        REFERENCES executables(id)
);
```

Foreground session закрывается и создаётся новая, если изменилось хотя бы одно:

```text
application_id
executable_id
hwnd
window_title
```

Даже смена title внутри одного приложения создаёт новую foreground session.

Пример:

```text
main.py — VS Code
↓
database.py — VS Code
```

Это две foreground sessions.

---

## 8.6 system_state_sessions

```sql
CREATE TABLE system_state_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    state TEXT NOT NULL
        CHECK (
            state IN (
                'ACTIVE',
                'IDLE',
                'LOCKED',
                'SLEEP'
            )
        ),

    started_at INTEGER NOT NULL,
    ended_at INTEGER
);
```

Foreground history и system state history должны быть независимыми.

Active time приложения определяется как пересечение:

```text
foreground session
∩
system_state = ACTIVE
```

---

## 8.7 tracker_runs

```sql
CREATE TABLE tracker_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    started_at INTEGER NOT NULL,
    last_heartbeat_at INTEGER NOT NULL,
    last_persisted_at INTEGER NOT NULL,

    ended_at INTEGER,

    exit_reason TEXT,
    version TEXT
);
```

Используется для crash recovery.

`last_persisted_at` — максимальная временная граница сохранённых изменений sessions
текущего запуска. Обновляется в той же транзакции, что и изменения sessions;
при создании tracker run равен `started_at`.

## 8.8 application_aliases

```sql
CREATE TABLE application_aliases (
    application_id INTEGER PRIMARY KEY,
    canonical_application_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,

    FOREIGN KEY (application_id) REFERENCES applications(id),
    FOREIGN KEY (canonical_application_id) REFERENCES applications(id),
    CHECK (application_id <> canonical_application_id)
);
```

Если соответствия нет, canonical ID равен собственному ID приложения.
Связи одноуровневые: canonical ID не должен сам быть alias; циклы запрещены.
Будущая операция merge атомарно перенаправляет все затронутые aliases на один корень.
Имя, ignored, track_titles и icon берутся у основного приложения.

Контракт будущих статистических запросов:

- разрешить исходные IDs в canonical IDs до группировки, фильтров и context switches;
- объединить пересекающиеся running intervals одной canonical application и только
  затем считать длительность с исключением сна;
- не складывать ранее вычисленные running_ms разных aliases;
- сохранять исходные foreground/running записи; смена alias не переписывает историю.

Пример: `[10:00, 11:00)` и `[10:30, 11:30)` после merge дают 90 минут до вычитания сна.
В MVP таблица пустая. SQL-примеры §25–27 описывают этот режим; до включения merge
необходимо добавить canonical resolution и объединение интервалов в repository.

---

# 9. Индексы

Минимально:

```sql
CREATE INDEX idx_running_app_time
ON application_running_sessions (
    application_id,
    started_at,
    ended_at
);

CREATE INDEX idx_foreground_app_time
ON foreground_sessions (
    application_id,
    started_at,
    ended_at
);

CREATE INDEX idx_system_state_time
ON system_state_sessions (
    state,
    started_at,
    ended_at
);

CREATE INDEX idx_process_executable
ON process_sessions (
    executable_id,
    detected_at
);
```

Запретить две одновременно открытые running sessions одного приложения:

```sql
CREATE UNIQUE INDEX idx_one_open_running_session
ON application_running_sessions(application_id)
WHERE ended_at IS NULL;
```

Желательно также обеспечить только одну открытую system-state session и одну открытую foreground session на tracker instance.

До открытия БД и crash recovery необходимо получить single-instance lock для данной БД.
Блокировку удерживать до полного завершения tracker. Второй экземпляр не запускает сбор
и recovery поверх работающего первого экземпляра.

---

# 10. TrackerState в RAM

SQLite не должна использоваться как runtime state storage.

В памяти хранить:

```python
TrackerState:
    tracker_run_id

    system_state

    foreground

    running_processes

    application_process_counts

    open_running_sessions
```

Пример:

```python
running_processes = {
    (pid, creation_time): ProcessState(...)
}
```

```python
application_process_counts = {
    application_id: count
}
```

---

# 11. Нормализованные события

Заложить общий тип `TrackerEvent`.

Минимальные события:

```text
PROCESS_STARTED
PROCESS_STOPPED

FOREGROUND_CHANGED

IDLE_STARTED
IDLE_ENDED

SESSION_LOCKED
SESSION_UNLOCKED

SYSTEM_SLEEP
SYSTEM_WAKE

TRACKER_STARTED
TRACKER_STOPPING
```

Windows/polling слой должен генерировать эти события.

State/session manager должен обрабатывать их.

---

# 12. System State Machine

Состояния:

```text
ACTIVE
IDLE
LOCKED
SLEEP
```

Внутренне рекомендуется хранить флаги:

```python
is_sleeping
is_locked
idle_timeout_reached
```

Effective state:

```python
if is_sleeping:
    return SLEEP

if is_locked:
    return LOCKED

if idle_timeout_reached:
    return IDLE

return ACTIVE
```

Приоритет:

```text
SLEEP
  ↓
LOCKED
  ↓
IDLE
  ↓
ACTIVE
```

Каждая смена effective state:

1. закрывает текущую `system_state_session`
2. открывает новую

---

# 13. IDLE

Порог MVP:

```text
5 minutes
```

Если пользователь не вводил mouse/keyboard в течение 5 минут:

```text
ACTIVE → IDLE
```

Время старта IDLE:

```text
last_input_at + 5 minutes
```

Во время IDLE:

- foreground session продолжает существовать;
- running sessions продолжают существовать;
- foreground time не считается как active time.

Пример:

```text
Chrome foreground:
10:00 → 11:00

System state:
ACTIVE 10:00 → 10:20
IDLE   10:20 → 10:50
ACTIVE 10:50 → 11:00

Chrome active time = 30 min
```

---

# 14. LOCKED

При Windows lock:

```text
is_locked = True
```

effective state становится `LOCKED`.

При unlock:

```text
is_locked = False
```

После этого effective state нужно вычислить заново.

Не следует безусловно выставлять `ACTIVE`.

---

# 15. SLEEP

При suspend:

```text
is_sleeping = True
```

effective state = `SLEEP`.

При resume:

```text
is_sleeping = False
```

После этого заново вычислить effective state.

Он может стать:

```text
LOCKED
ACTIVE
IDLE
```

в зависимости от текущего состояния системы.

Сырые process/running sessions могут оставаться открытыми во время сна, однако
`running_ms` в статистике считается только как пересечение running sessions с
`ACTIVE`, `IDLE`, `LOCKED` и выбранными окнами. `SLEEP` не добавляет время в «Запущено».
После resume перед продолжением сбора перечитать процессы и foreground window;
не начислять активность старому foreground по устаревшему snapshot.

---

# 16. Foreground State Machine

В памяти:

```python
current_foreground = {
    application_id,
    executable_id,
    hwnd,
    title,
    started_at
}
```

Каждый foreground poll возвращает snapshot.

Если ничего не изменилось:

```text
same application
same executable
same hwnd
same title
```

ничего не записывать.

Не создавать periodic samples.

Если изменилось любое поле:

```text
close old foreground session
open new foreground session
```

Все изменения выполнять в одной SQLite transaction.

Если poll достоверно не смог определить foreground, закрыть прежнюю foreground session
на момент наблюдения и очистить текущий foreground. Не продлевать её до успешного resolver.
Системный `ACTIVE` без определённого foreground отображается как `unknown_activity`;
следующее успешное наблюдение открывает новую foreground session без заполнения пропуска назад.

---

# 17. Running Process State Machine

Каждый process polling формирует snapshot процессов.

Сравнить с предыдущим snapshot:

```text
NEW
DEAD
UNCHANGED
```

## PROCESS_STARTED

1. определить executable path, если доступен
2. если путь недоступен — создать наблюдение с `executable_id = NULL` и завершить
   обработку без увеличения application process count
3. если достоверный путь доступен, найти `executables.path`; если его ещё нет:
   - создать application
   - создать executable
4. создать `process_session`
5. увеличить `application_process_counts[application_id]`
6. если count был `0` и стал `1`:
   - открыть `application_running_session`

## PROCESS_STOPPED

1. закрыть `process_session`
2. уменьшить process count приложения, только если процесс был связан с приложением
3. если count стал `0`:
   - закрыть `application_running_session`

Если процесс исчез между polling, использовать время обнаружения отсутствия как `ended_at`.

Погрешность до process polling interval допустима.

### Согласование foreground и process polling

Foreground observation сначала регистрирует обнаруженный процесс в общем state manager,
а затем открывает foreground session. Running session открывается тем же timestamp,
не ожидая следующего process poll. Повторный process snapshot не увеличивает count ещё раз.
Подтверждённое завершение текущего foreground-процесса также закрывает его foreground session.
Snapshots обрабатываются последовательно с учётом времени наблюдения; устаревший snapshot
не должен отменять более новое foreground/process observation.

Недоступность metadata не равна завершению процесса. При временной ошибке чтения
сохранять уже подтверждённую связь с приложением, пока подтверждена идентичность процесса.
Неудача всего process poll не превращается в пустой snapshot и массовый PROCESS_STOPPED.

---

# 18. Context switch

Зафиксированное определение:

> Context switch = переход между двумя разными не-ignored приложениями, произошедший тогда, когда effective system state был `ACTIVE`.

Примеры:

```text
VS Code → Chrome
+1
```

```text
Chrome window 1 → Chrome window 2
0
```

```text
VS Code → IDLE → VS Code
0
```

```text
VS Code → ignored app → VS Code
0
```

Ignored приложения должны быть логически исключены из цепочки статистики.

Context switches не нужно хранить отдельной таблицей.

Они вычисляются из последовательности `foreground_sessions`.

---

# 19. Window switches

Переход между разными HWND внутри одного или разных приложений может позднее использоваться как отдельная метрика.

Не хранить отдельными событиями.

Данные уже есть в `foreground_sessions`.

---

# 20. Crash Recovery

Heartbeat:

```text
every 5 sec
```

Обновлять:

```sql
UPDATE tracker_runs
SET last_heartbeat_at = MAX(last_heartbeat_at, ?)
WHERE id = ?;
```

Каждая транзакция, изменяющая sessions, также обновляет `last_persisted_at` до
максимума прежнего значения и временных границ записанных изменений. Это именно
границы наблюдений, а не `process_started_at` из метаданных ОС.
Heartbeat и события обрабатываются последовательно одним владельцем записи;
heartbeat не должен обгонять ещё не сохранённые предыдущие события.

Граница восстановления:

```text
recovery_at = max(last_heartbeat_at, last_persisted_at)
```

Она не может быть раньше начала любой сохранённой открытой session.
Для интервалов обеспечить `ended_at >= started_at` (для process history — `detected_at`);
нулевые интервалы не участвуют в статистике.

При старте tracker:

1. найти предыдущий `tracker_runs`, где `ended_at IS NULL`
2. вычислить `recovery_at`
3. закрыть этим timestamp все незакрытые:
   - `process_sessions`
   - `application_running_sessions`
   - `foreground_sessions`
   - `system_state_sessions`
4. предыдущему tracker run:
   - `ended_at = recovery_at`
   - `exit_reason = 'crash'`
5. создать новый tracker run

Все recovery operations выполнить transaction.

Например, heartbeat в 10:00:00, открытие session в 10:00:03 и crash в 10:00:04
дают `recovery_at = 10:00:03`, а не окончание session раньше её начала.
Промежуток после recovery boundary до нового запуска остаётся без данных.

---

# 21. Normal Shutdown

При штатном завершении:

1. получить один timestamp `now`
2. одной transaction закрыть:
   - open process sessions
   - open running sessions
   - current foreground session
   - current system state session
   - tracker run
3. установить:

```text
exit_reason = 'normal'
```

---

# 22. Startup

Порядок:

0. получить single-instance lock для данной БД; если она уже используется tracker,
   не выполнять следующие шаги и не изменять историю
1. открыть SQLite
2. включить WAL + foreign keys
3. выполнить crash recovery
4. создать новый tracker run
5. получить:
   - current processes
   - foreground window
   - idle duration
   - lock state
6. построить initial runtime state
7. открыть необходимые sessions
8. запустить polling loops

Если приложение уже было запущено до tracker startup, не следует дорисовывать running history назад во времени.

Для `application_running_session.started_at` использовать время старта tracker.

`process_started_at` при этом можно сохранить реальное creation time процесса, если оно доступно.

---

# 23. Transactions

События, затрагивающие несколько строк, должны быть atomic.

Пример foreground change:

```sql
BEGIN;

UPDATE foreground_sessions
SET ended_at = ?
WHERE id = ?;

INSERT INTO foreground_sessions (...);

COMMIT;
```

Пример process count `0 → 1`:

- создание `process_session`
- создание `application_running_session`

должно выполняться одной transaction.

---

# 24. Статистика — общий принцип

UI задаёт не просто один непрерывный datetime range, а:

```text
date_from
date_to
time_from
time_to
timezone
```

Пример:

```text
date_from = 2026-09-01
date_to   = 2026-09-07
time_from = 08:00
time_to   = 18:00
timezone  = Europe/Moscow
```

Это означает отдельное окно времени для каждого локального дня:

```text
01.09 08:00–18:00
02.09 08:00–18:00
...
07.09 08:00–18:00
```

Это НЕ означает один непрерывный диапазон:

```text
01.09 08:00 → 07.09 18:00
```

Backend обязан:

1. построить выбранные окна в локальном часовом поясе;
2. каждое окно отдельно перевести в UTC;
3. преобразовать границы в UTC milliseconds;
4. выполнить статистические пересечения с набором этих окон.

Это необходимо в том числе для корректной работы в часовых поясах с DST.

### Локальное время, неполные часы и DST

Использовать IANA timezone через Python `zoneinfo`; включить `tzdata` в зависимости
Windows-сборки. Длительности вычислять по UTC timestamps, не вычитать локальные часы.
Источник timezone для dashboard — часовой пояс браузера; все запросы одного набора
фильтров передают его явно. Неверная/неизвестная timezone отклоняется с `422`.

Выбор локального времени означает все реальные моменты, удовлетворяющие локальным
date/time условиям. При повторении времени учитываются обе его реализации; при
несуществующем времени отсутствующая часть пропускается, не переносится на другой час.
Например, при повторении 02:00–03:00 выбор 02:15–02:45 даёт два интервала по 30 минут,
а не один непрерывный интервал от первого 02:15 до второго 02:45.

`selected_windows` поэтому может содержать несколько непересекающихся UTC-интервалов
на одну локальную дату. Перед агрегированием исключить пересечения/дубликаты этих окон.
Полный день при DST может длиться 23 или 25 часов; фактическая длительность берётся из UTC.
На timeline повторяющиеся локальные подписи различаются UTC offset в tooltip.

Часовая ячейка heatmap объединяет все выбранные реальные части одного локального часа.
`window_ms` — сумма их длительностей; это длительность выбора, не время работы tracker.
`tracked_ms` — пересечение этих частей со всеми известными system-state sessions.
Отсутствие наблюдений не уменьшает window_ms и отдельно обозначается в UI.

Официальная справка: https://docs.python.org/3/library/zoneinfo.html

## Дефолт фильтра

При первом открытии / после `Сбросить`:

```text
date_from = today
date_to   = today
time_from = 00:00
time_to   = 24:00
active_only = true
```

Секунды в UI не выбираются.

Полный локальный день — `[00:00, 00:00 следующего дня)`. В UI и API конец полного
дня обозначается `24:00`; backend преобразует его в полночь следующей локальной даты.
`24:00` допустимо только для `time_to`; `time_from` принимает `00:00..23:59`.
Обычное `23:59` остаётся точной исключённой границей и не обозначает конец суток.
Одинаковые `time_from` и `time_to` отклонять как пустой диапазон.

Range slider двигается с шагом:

```text
15 minutes
```

При этом пользователь должен иметь возможность вручную ввести минуты с точностью до одной минуты.

## Диапазон через полночь

Если:

```text
time_to < time_from
```

считать интервал переходящим через полночь.

Пример:

```text
22:00–03:00
```

для даты `08.09` означает:

```text
08.09 22:00 → 09.09 03:00
```

На timeline переход через локальную полночь отмечается тонкой серой вертикальной
линией и подписью новой даты, например `09.09 · 00:00`. Линия — маркер, не временной
сегмент: не изменяет длительности и не раздвигает соседние интервалы.

## Реализация SQL

Существующие SQL ниже используют одну пару:

```text
:from_ts
:to_ts
```

и являются корректным примитивом для одного выбранного окна.

Для нескольких дней backend должен агрегировать результаты по всем сформированным окнам.

Предпочтительный вариант — выполнить один SQL через CTE/`VALUES`:

```sql
WITH selected_windows(start_ts, end_ts) AS (
    VALUES
        (?, ?),
        (?, ?),
        (?, ?)
)
...
```

и пересекать sessions с `selected_windows`.

Допускается выполнить несколько параметризованных запросов и суммировать результат в backend,
если реализация остаётся корректной и достаточно быстрой.

Границы каждого окна:

```text
start inclusive
end exclusive
```

Для open sessions использовать:

```text
:now_ts = current UTC milliseconds
```

Базовое пересечение одной session с одним окном:

```sql
started_at < :to_ts
AND COALESCE(ended_at, :now_ts) > :from_ts
```

Длительность пересечения:

```sql
MIN(COALESCE(ended_at, :now_ts), :to_ts)
-
MAX(started_at, :from_ts)
```

`Общее активное время` — это сумма:

```text
system_state = ACTIVE
∩
selected windows
```

Это не сумма running time и не сумма foreground time приложений.

Heatmap использует этот же системный `ACTIVE`, включая ignored/unknown activity.
`active_only` влияет только на таблицу приложений, её сортировку и progress bars.
Общее активное время может быть больше суммы активного времени видимых приложений.

---

# 25. Running time query

`running_ms = running session ∩ (ACTIVE | IDLE | LOCKED) ∩ selected window`.
Сон и промежутки без system-state history исключаются. System-state intervals
должны быть непересекающимися, иначе JOIN приведёт к двойному учёту.

```sql
SELECT
    a.id,
    a.name,

    SUM(
        MIN(COALESCE(rs.ended_at, :now_ts), COALESCE(ss.ended_at, :now_ts), :to_ts)
        -
        MAX(rs.started_at, ss.started_at, :from_ts)
    ) AS duration_ms

FROM application_running_sessions rs

JOIN applications a
    ON a.id = rs.application_id

JOIN system_state_sessions ss
    ON ss.state IN ('ACTIVE', 'IDLE', 'LOCKED')
    AND ss.started_at < COALESCE(rs.ended_at, :now_ts)
    AND COALESCE(ss.ended_at, :now_ts) > rs.started_at

WHERE
    a.ignored = 0

    AND rs.started_at < :to_ts
    AND COALESCE(rs.ended_at, :now_ts) > :from_ts
    AND ss.started_at < :to_ts
    AND COALESCE(ss.ended_at, :now_ts) > :from_ts

GROUP BY
    a.id,
    a.name

ORDER BY
    duration_ms DESC;
```

---

# 26. Active time query

Active time = foreground interval intersected with system state `ACTIVE`.

```sql
SELECT
    a.id,
    a.name,

    SUM(
        MIN(
            COALESCE(fs.ended_at, :now_ts),
            COALESCE(ss.ended_at, :now_ts),
            :to_ts
        )
        -
        MAX(
            fs.started_at,
            ss.started_at,
            :from_ts
        )
    ) AS duration_ms

FROM foreground_sessions fs

JOIN applications a
    ON a.id = fs.application_id

JOIN system_state_sessions ss
    ON ss.state = 'ACTIVE'

    AND ss.started_at < COALESCE(fs.ended_at, :now_ts)
    AND COALESCE(ss.ended_at, :now_ts) > fs.started_at

WHERE
    a.ignored = 0

    AND fs.started_at < :to_ts
    AND COALESCE(fs.ended_at, :now_ts) > :from_ts

    AND ss.started_at < :to_ts
    AND COALESCE(ss.ended_at, :now_ts) > :from_ts

GROUP BY
    a.id,
    a.name

HAVING duration_ms > 0

ORDER BY
    duration_ms DESC;
```

---

# 27. Main dashboard stats query

Для MVP основной API должен возвращать одновременно:

- `active_ms`
- `running_ms`

Рекомендуется использовать отдельные CTE, чтобы избежать multiplication при JOIN interval tables.

```sql
WITH running AS (
    SELECT
        rs.application_id,

        SUM(
            MIN(COALESCE(rs.ended_at, :now_ts), COALESCE(ss.ended_at, :now_ts), :to_ts)
            -
            MAX(rs.started_at, ss.started_at, :from_ts)
        ) AS running_ms

    FROM application_running_sessions rs

    JOIN system_state_sessions ss
        ON ss.state IN ('ACTIVE', 'IDLE', 'LOCKED')
        AND ss.started_at < COALESCE(rs.ended_at, :now_ts)
        AND COALESCE(ss.ended_at, :now_ts) > rs.started_at

    WHERE
        rs.started_at < :to_ts
        AND COALESCE(rs.ended_at, :now_ts) > :from_ts
        AND ss.started_at < :to_ts
        AND COALESCE(ss.ended_at, :now_ts) > :from_ts

    GROUP BY rs.application_id
),

active AS (
    SELECT
        fs.application_id,

        SUM(
            MIN(
                COALESCE(fs.ended_at, :now_ts),
                COALESCE(ss.ended_at, :now_ts),
                :to_ts
            )
            -
            MAX(
                fs.started_at,
                ss.started_at,
                :from_ts
            )
        ) AS active_ms

    FROM foreground_sessions fs

    JOIN system_state_sessions ss
        ON ss.state = 'ACTIVE'
        AND ss.started_at < COALESCE(fs.ended_at, :now_ts)
        AND COALESCE(ss.ended_at, :now_ts) > fs.started_at

    WHERE
        fs.started_at < :to_ts
        AND COALESCE(fs.ended_at, :now_ts) > :from_ts
        AND ss.started_at < :to_ts
        AND COALESCE(ss.ended_at, :now_ts) > :from_ts

    GROUP BY fs.application_id
)

SELECT
    a.id,
    a.name,

    COALESCE(active.active_ms, 0) AS active_ms,
    COALESCE(running.running_ms, 0) AS running_ms

FROM applications a

LEFT JOIN active
    ON active.application_id = a.id

LEFT JOIN running
    ON running.application_id = a.id

WHERE
    a.ignored = 0

    AND CASE WHEN :active_only
        THEN COALESCE(active.active_ms, 0) > 0
        ELSE COALESCE(running.running_ms, 0) > 0
    END

ORDER BY
    CASE WHEN :active_only
        THEN COALESCE(active.active_ms, 0)
        ELSE COALESCE(running.running_ms, 0)
    END DESC,
    a.id ASC;
```

В обеих CTE учитывается пересечение всех трёх интервалов. Состояние, пересекающее
длинную session, но находящееся вне selected window, не должно попадать в SUM.
`active_only` — boolean API parameter, передаваемый в SQL как 0 или 1.

---

# 28. System state stats query

```sql
SELECT
    state,

    SUM(
        MIN(COALESCE(ended_at, :now_ts), :to_ts)
        -
        MAX(started_at, :from_ts)
    ) AS duration_ms

FROM system_state_sessions

WHERE
    started_at < :to_ts
    AND COALESCE(ended_at, :now_ts) > :from_ts

GROUP BY state;
```

---

# 29. Context switches query requirements

Для MVP требуется endpoint, возвращающий число context switches за период.

При расчёте необходимо:

- учитывать только `a.ignored = 0`
- учитывать только переходы между разными `application_id`
- учитывать только переходы, timestamp которых попадает в `ACTIVE`
- учитывать приложение непосредственно перед `from_ts`, чтобы корректно обработать границу диапазона

Не считать смену HWND внутри одного приложения.

Не считать ignored приложение промежуточным переключением.

---

# 30. MVP API

Минимальный FastAPI API.

Все stats endpoints используют общий набор query parameters:

```text
date_from=YYYY-MM-DD
date_to=YYYY-MM-DD
time_from=HH:MM
time_to=HH:MM
timezone=<IANA timezone>
```

Пример:

```text
date_from=2026-09-08
date_to=2026-09-08
time_from=00:00
time_to=24:00
timezone=Europe/Moscow
```

Даты включены с обеих сторон; `date_from > date_to`, пустой временной диапазон,
невалидное время или timezone возвращают `422`. Для `/stats/timeline` разные даты
также возвращают `422`. Для `/stats/activity` требуется минимум две выбранные даты.
Каждый запрос фиксирует один `now_ts` для всех своих расчётов открытых sessions.

## GET `/stats/apps`

Дополнительный query parameter:

```text
active_only=true|false
```

### Семантика `active_only=true`

- исключить приложения с `active_ms = 0`;
- сортировать по `active_ms DESC`;
- progress bar в UI нормализуется относительно максимального `active_ms`.

### Семантика `active_only=false`

- показывать все приложения с `running_ms > 0`;
- сортировать по `running_ms DESC`;
- progress bar в UI нормализуется относительно максимального `running_ms`.

В обеих режимах возвращать обе величины:

```text
active_ms
running_ms
```

Response:

```json
{
  "has_tracking_data": true,
  "has_running_data": true,
  "items": [
    {
      "application_id": 17,
      "name": "Visual Studio Code",
      "active_ms": 16260000,
      "running_ms": 25200000,
      "icon_url": "/applications/17/icon"
    }
  ]
}
```

`has_tracking_data` — есть положительное пересечение хотя бы одной system-state
session с выбранными окнами (включая SLEEP). `has_running_data` — есть хотя бы одно
не-ignored приложение с `running_ms > 0`, до применения `active_only`.
Оба признака относятся ко всему выбранному периоду и не зависят от числа items.
Пустой результат возвращается как объект с `items: []`, не как голый массив.

Frontend не должен повторно сортировать ответ, если backend уже вернул его в требуемом порядке.

`bar_ratio` хранить в БД не нужно. Его можно вычислять на frontend относительно первого элемента `items`.

API сразу возвращает полный список приложений за период.
`Показать все` / `Свернуть` — чисто frontend behavior, дополнительный запрос не нужен.

---

## GET `/stats/system`

Response:

```json
{
  "active_ms": 25200000,
  "idle_ms": 8100000,
  "locked_ms": 3600000,
  "sleep_ms": 0
}
```

`active_ms` используется UI для:

```text
Общее активное время: N д. M ч. X м.
```

и должен учитывать выбранные date/time windows.

---

## GET `/stats/context-switches`

Response:

```json
{
  "context_switches": 184
}
```

Требования из раздела Context Switch сохраняются.

---

## GET `/applications`

Response:

```json
[
  {
    "id": 17,
    "name": "Visual Studio Code",
    "ignored": false,
    "track_titles": true,
    "icon_url": "/applications/17/icon"
  }
]
```

---

## PATCH `/applications/{application_id}`

Минимальное изменение параметров приложения без отдельной settings UI в MVP.

```json
{
  "ignored": true,
  "track_titles": false
}
```

Разрешены только эти два boolean-поля, хотя бы одно обязательно. Пропущенное поле
сохраняет прежнее значение; неизвестные поля/неверные типы/пустой объект дают `422`,
несуществующий application ID — `404`. Ответ `200` — обновлённый объект формата GET `/applications`.

API передаёт команду единственному владельцу записи tracker; изменение применяется
последовательно с событиями, одной транзакцией, с синхронизацией RAM state и БД.
Ответ отправляется после применения. `ignored` сразу меняет расчёт всей истории.
При смене `track_titles` текущая foreground session при необходимости закрывается
и открывается новая с нормализованным title на границе изменения; прошлые titles сохраняются.
При `track_titles = false` сравнивать snapshots уже с title = NULL, чтобы скрытые
изменения title не создавали лишние sessions. Граница записи учитывается в last_persisted_at.

---

## GET `/applications/{application_id}/icon`

Возвращает cached icon приложения.

Если иконки нет:

- endpoint может вернуть `404`;
- frontend обязан использовать fallback;
- ошибка получения иконки не является ошибкой tracker-а.

---

## GET `/stats/timeline`

Используется для однодневной визуализации активности.

Предназначен для диапазона, где:

```text
date_from == date_to
```

Timeline представляет реальную последовательность дня.

Application segments строятся как:

```text
foreground_sessions
∩
system_state = ACTIVE
∩
selected time window
```

System-state segments (`IDLE`, `LOCKED`, `SLEEP`) должны присутствовать отдельно.

Пример response:

```json
[
  {
    "type": "application",
    "application_id": 17,
    "name": "Visual Studio Code",
    "started_at": 1788854400000,
    "ended_at": 1788857460000,
    "title": "database.py — TimeTracker"
  },
  {
    "type": "idle",
    "started_at": 1788857460000,
    "ended_at": 1788858960000
  },
  {
    "type": "application",
    "application_id": 21,
    "name": "Google Chrome",
    "started_at": 1788858960000,
    "ended_at": 1788861600000,
    "title": "GitHub — Google Chrome"
  }
]
```

### Ignored applications в timeline

Ignored activity нельзя просто вырезать из временной шкалы, иначе timeline будет визуально лгать.

Если во время `ACTIVE` foreground-приложение имеет `ignored = 1`,
показывать сегмент:

```json
{
  "type": "other_activity",
  "started_at": 1788858000000,
  "ended_at": 1788858600000
}
```

Без раскрытия имени ignored application.

### Пропуски и неизвестная активность

- `no_data`: в прошлом участке выбранного окна нет system-state history
  (tracker не работал, завершился аварийно или был приостановлен). Tooltip: «Нет данных».
- `unknown_activity`: system state = `ACTIVE`, но foreground не определён.
  Tooltip: «Неизвестное приложение». Входит в общее активное время и heatmap,
  но не приписывается прежнему приложению.
- Участок после `now_ts` остаётся будущей пустой частью шкалы, без выдуманных sessions.

Оба типа выводятся из истории при чтении API; не являются новыми system states.
Формат: `type`, `started_at`, `ended_at`, без application name/title.
Все сегменты располагаются по абсолютным timestamps внутри выбранного окна.
Пропуски нельзя удалять с последующим растягиванием оставшихся сегментов.

---

## GET `/stats/activity`

Используется для heatmap.

Источник `active_ms` — пересечение system-state `ACTIVE` с выбранными окнами и
часовыми ячейками; `ignored` и `active_only` не меняют эти значения.

### Диапазон 2–14 дней

Возвращать ячейки:

```text
date (дата начала выбранного окна) × day_offset × hour
```

`date` — дата строки/начала окна, `day_offset` — 0 или 1, `local_date` — фактическая
дата часа. Для 08.09, 22:00–03:00 строка 08.09 содержит часы 22, 23, 00⁺¹, 01⁺¹, 02⁺¹.
Данные после полуночи последней выбранной даты включаются согласно этому правилу.
Порядок ячеек — date ASC, day_offset ASC, hour ASC.

Пример:

```json
[
  {
    "date": "2026-09-08",
    "day_offset": 0,
    "local_date": "2026-09-08",
    "hour": 14,
    "local_time_from": "14:00",
    "local_time_to": "15:00",
    "hour_occurrences": 1,
    "active_ms": 2520000,
    "window_ms": 3600000,
    "tracked_ms": 3600000,
    "status": "data",
    "intensity": 0.7
  }
]
```

Где:

```text
intensity = active_ms / window_ms, если window_ms > 0
```

С clamp в диапазон `0.0..1.0`. Для выбора 08:30–09:00 и 15 минут активности:
window_ms = 1800000, active_ms = 900000, intensity = 0.5.
`local_time_from/to` описывают выбранную часть часа, конец 24:00 обозначает следующую полночь.

Повторившийся при DST час остаётся одной ячейкой: суммировать все реальные выбранные
части, `hour_occurrences = 2`. Например, 90 активных минут из 120 дают intensity = 0.75.
Если час полностью отсутствует из-за DST: `hour_occurrences = 0`, `window_ms = 0`,
`active_ms = 0`, `tracked_ms = 0`, `intensity = null`, `status = "missing_hour"`.
`hour_occurrences` считает реализации выбранной части часа, а не предполагает,
что каждое изменение offset обязательно равно одному часу.

Остальные статусы:

- `data`: tracked_ms > 0; нулевая активность при известных IDLE/LOCKED/SLEEP — это данные;
- `no_data`: window_ms > 0, tracked_ms = 0 и есть прошедшая часть выбранной ячейки;
- `future`: вся реально существующая выбранная часть ячейки находится после now_ts.

При частичном покрытии (`0 < tracked_ms < window_ms`) tooltip дополнительно показывает
известную длительность. Будущие и ненаблюдавшиеся части не выдумываются и не вычитаются
из длительности выбора; UI отличает их от наблюдаемой нулевой активности.

### Диапазон >14 дней

Возвращать агрегированную:

```text
weekday (даты начала окна) × day_offset × hour
```

`weekday` использует ISO-нумерацию: 1 = понедельник, ..., 7 = воскресенье.
Для ночных окон weekday определяется датой начала окна, включая часы с day_offset = 1.

В каждой группе учитывать все выбранные даты с window_ms > 0; даты без наблюдений
участвуют с нулевой активностью. Полностью отсутствующий из-за DST час не является
нулевой активностью и не входит в sample_days. Повторившийся час входит как один день.

```text
sample_days = число дат группы с window_ms > 0
average_active_ms = sum(active_ms) / sample_days
intensity = sum(active_ms) / sum(window_ms)
```

Цвет — взвешенная доля активности, не среднее арифметическое процентов по дням.
Средняя длительность в tooltip считается отдельно по формуле выше.
Если sample_days = 0, average_active_ms и intensity = null. Все нулевые знаменатели
обрабатываются явно; не заменять отсутствующий час нулём или 60 минутами.

Пример:

```json
[
  {
    "weekday": 2,
    "day_offset": 0,
    "hour": 14,
    "local_time_from": "14:00",
    "local_time_to": "15:00",
    "sample_days": 3,
    "total_active_ms": 6660000,
    "total_window_ms": 10800000,
    "total_tracked_ms": 10800000,
    "missing_hour_days": 0,
    "repeated_hour_days": 0,
    "average_active_ms": 2220000,
    "intensity": 0.6167
  }
]
```

---

# 31. Tray Application

MVP tray menu:

```text
Open dashboard
Pause tracking
Exit
```

`Pause tracking` можно реализовать минимально либо оставить как stub, если это усложняет первый этап.

Главное требование — tracker должен корректно закрывать sessions при Exit.

---

# 32. Blacklist semantics

`applications.ignored = 1`:

- не удаляет данные;
- исключает приложение из таблицы приложений и context switches;
- действует и на прошлую историю;
- ignored app логически отсутствует при вычислении context switches.

Системное общее активное время и heatmap сохраняют эту активность;
timeline показывает её как `other_activity` без имени и title приложения.

---

# 33. Window title privacy

Window title собирается уже в MVP, чтобы не потерять исторические данные для будущей статистики.

Если:

```text
track_titles = 0
```

то:

```text
window_title = NULL
```

Но foreground session всё равно сохраняется.

Старые titles автоматически не удаляются при изменении настройки.

---

# 34. Error Handling

Tracker не должен падать, если:

- процесс завершился между получением PID и чтением metadata;
- нет доступа к executable path;
- foreground HWND стал invalid;
- process запущен elevated;
- system/protected process не позволяет получить все данные;
- window title недоступен.

Использовать graceful fallback.

Минимально:

- попытаться сохранить доступный exe name/path;
- неизвестный путь сохранять через nullable process_sessions.executable_id, без
  фиктивного executable/application; недоступный title может быть NULL;
- исключение одного процесса не должно прерывать monitoring loop.

Tracker не должен требовать запуска от Administrator для основной работы.

---

# 35. Logging

Нужен локальный rotating log.

Логировать минимум:

- tracker startup/shutdown
- crash recovery
- database errors
- Windows API failures
- unhandled exceptions внутри polling loops
- создание новых applications/executables
- state transitions
- foreground resolver failures

Не логировать window title на INFO level, чтобы не дублировать потенциально чувствительные данные в log files.

---

# 36. Testing

Нужны unit tests для бизнес-логики без зависимости от Windows API.

Windows layer должен быть заменяемым mock/fake provider.

Обязательно протестировать:

## Application running

```text
0 → 1 process opens session
1 → N does not open extra session
N → 1 does not close session
1 → 0 closes session
```

## Foreground

```text
same snapshot → no DB write

title change
→ close old + open new

HWND change
→ close old + open new

application change
→ close old + open new
```

## System states

```text
ACTIVE → IDLE
IDLE → ACTIVE
ACTIVE → LOCKED
LOCKED → ACTIVE
ACTIVE → SLEEP
SLEEP → LOCKED
```

Проверить приоритет:

```text
SLEEP > LOCKED > IDLE > ACTIVE
```

## Crash recovery

Проверить закрытие всех open sessions по `max(last_heartbeat_at, last_persisted_at)`.
Обязательно: session открыта после последнего heartbeat; crash между heartbeat;
atomic запись session и last_persisted_at; повторный запуск при работающем tracker.

## Stats

Проверить пересечение с диапазоном:

```text
session starts before from
session ends after to
session fully inside
session fully outside
open session
ACTIVE state intersects foreground but is outside selected window
running session crosses SLEEP: sleep contributes zero running_ms
```

## Context switches

Проверить:

```text
VS Code → Chrome = +1
Chrome hwnd1 → Chrome hwnd2 = 0
VS Code → ignored → VS Code = 0
switch during IDLE = 0
switch during LOCKED = 0
switch during ACTIVE = +1
```

## Date/time filters

Проверить:

```text
single day 00:00–24:00
multiple days with 08:00–18:00 daily window
22:00–03:00 crossing midnight
timezone conversion
DST transition
manual minute values not divisible by 15
```

## Apps sorting

Проверить:

```text
active_only=true:
- active_ms = 0 excluded
- ORDER BY active_ms DESC

active_only=false:
- running_ms > 0 included
- ORDER BY running_ms DESC
```

## Timeline

Проверить:

```text
foreground ∩ ACTIVE creates application segments
IDLE/LOCKED/SLEEP are represented separately
ignored foreground becomes other_activity
ACTIVE with unresolved foreground becomes unknown_activity
untracked past gaps become no_data without stretching neighboring segments
midnight marker does not change durations
timeline is clipped to selected time window
```

## Heatmap

Проверить:

```text
2–14 days → date × hour
>14 days → weekday × hour average
intensity is clamped to 0..1
hour boundaries are interpreted in selected local timezone
partial hour: 15 active minutes / 30 selected minutes = 0.5
repeated hour: 90 active minutes / 120 selected minutes = 0.75
missing DST hour: null intensity, excluded from average sample_days
night window: anchor date/weekday with day_offset=1 after midnight
no_data and known zero activity have different status
long range: sum(active_ms)/sum(window_ms), not mean of daily percentages
```

## Process identity / API / merge foundation

Проверить nullable executable_id, уточнение identity без начисления running назад,
повторное использование PID после разрыва, недоступность metadata без ложного stop,
идемпотентную регистрацию одного процесса через foreground и process poll.
Проверить `/stats/apps` envelope и оба metadata flags, PATCH validation и применение
title policy к открытой session без изменения старых titles.
В MVP проверить constraints пустой application_aliases; перед включением POST-MVP merge
обязательно проверить canonical resolution, запрет циклов и union интервалов 60+60=90 минут.

## Icons / display names

Проверить:

```text
FileDescription preferred over ProductName
ProductName fallback
exe filename fallback
icon extraction failure does not crash tracker
cached icon is reused
```

---

# 36.1. MVP Web UI — технические требования, влияющие на реализацию

Полный визуальный UI-spec находится в `time_tracker_ui_spec.md`. Ниже фиксируются требования,
которые уже влияют на backend/frontend architecture.

## Основная вкладка

По умолчанию:

```text
Только активные = ON
Дата = текущий день
Время = 00:00–24:00
```

Фильтры:

- checkbox `Только активные`;
- единый date range picker;
- time range slider;
- slider step = 15 минут;
- точный ручной ввод времени до минуты;
- `Сбросить` возвращает дефолтные значения.

Рядом со «Сбросить» разместить компактную кнопку `↻`, tooltip «Обновить статистику».
Первый вход и смена фильтров загружают данные автоматически. Кнопка повторно загружает
apps, system и текущую activity visualization с сохранением filters и expanded state.
Периодического auto-refresh в MVP нет. Во время запроса кнопка показывает загрузку
и не запускает повторный такой же запрос; смена фильтра по-прежнему разрешена.

Apps, system и activity имеют отдельные frontend generation IDs. Refresh/смена
date/time/timezone инвалидирует все три, а смена active_only — только apps.
Ответы и ошибки старых generations игнорируются, даже если отмена запроса не сработала.
При смене фильтров старая activity visualization не должна смешиваться с новым режимом.
При active_only меняется только apps request; остальные данные от этого флага не зависят.
Нажатие refresh повторяет весь набор, включая ранее завершившиеся ошибкой запросы.

## Таблица приложений

По умолчанию показывать первые 10 строк.

`Показать все`:

- раскрывает уже полученный список целиком;
- не выполняет новый API request;
- после раскрытия действие меняется на `Свернуть`.

Колонки времени:

```text
Активно
Запущено
```

Progress bar:

- при `active_only=true` основан на `active_ms`;
- при `active_only=false` основан на `running_ms`;
- первая строка всегда имеет `100%`;
- остальные: `value / max_value`.

## Reorder animation

При изменении `active_only`, фильтра дат/времени или новых данных строки должны плавно менять позиции.

Требования:

- stable React/Vue/etc. key = `application_id`;
- нельзя использовать индекс строки как key;
- рекомендуемая длительность reorder: `220–280 ms`;
- progress bar resize: `250–350 ms`;
- без bounce/spring-эффекта, использовать спокойный ease-out.

## Loading / Skeleton

Не показывать skeleton мгновенно на каждый локальный запрос.

Рекомендованная логика:

```text
request started
↓
150 ms elapsed?
↓ yes
show skeleton / loading state
```

Если response пришёл быстрее — обновить данные без мигания skeleton.

При обновлении фильтра желательно временно сохранять старые данные,
слегка снижая opacity до прихода нового ответа.

## Иконки

Каждая строка должна показывать icon приложения.

Если icon endpoint недоступен или вернул ошибку:

- показать pastel fallback;
- внутри fallback допустима первая буква display name.

## Цвета timeline

Цвет application segment не хранится в SQLite.

Frontend использует ограниченную pastel palette и детерминированно выбирает цвет по `application_id`.

Пример:

```text
palette[hash(application_id) % palette.length]
```

В пределах текущей timeline одно приложение всегда должно иметь один и тот же цвет.

`IDLE`, `LOCKED`, `SLEEP`, `other_activity` используют нейтральные цвета,
не пересекающиеся с application palette.

## Однодневная timeline

Для одного выбранного дня показывать компактную единую горизонтальную ленту.

При hover на application segment tooltip показывает:

```text
Application name
HH:MM–HH:MM · duration
window title (если сохранён)
```

Для system segment:

```text
IDLE / LOCKED / SLEEP
HH:MM–HH:MM · duration
```

Для ignored application:

```text
Другая активность
HH:MM–HH:MM · duration
```

## Heatmap

Heatmap показывается только при диапазоне больше одного дня.

Режимы:

```text
2–14 дней  → конкретные даты × часы
>14 дней   → weekday × hour, средняя активность
```

Цвет ячейки строится по непрерывной интенсивности `0..1`.

Точные формулы, nullable intensity при DST и поля покрытия заданы в GET `/stats/activity`.
В ночных окнах строки привязаны к дате/weekday начала окна, а часы следующего дня
помечаются `⁺¹`; tooltip использует фактическую local_date.

### Tooltip heatmap — обязательный

Tooltip должен однозначно объяснять, что означает конкретная ячейка.

Для диапазона 2–14 дней:

```text
08.09.2026, 14:00–15:00
Активность: 42 мин.
```

Для диапазона >14 дней:

```text
Среда, 14:00–15:00
Средняя активность: 37 мин.
```

Рядом с заголовком heatmap должна быть небольшая info-иконка.

Tooltip/info explanation:

```text
Для короткого периода показаны конкретные даты.
Для длинного периода — средняя активность по дням недели.
```

---

# 37. POST-MVP

Не реализовывать сейчас, но архитектура должна позволять добавить.

## 37.1 Smart application identity

Автоматически связывать новый executable со старым application по:

```text
ProductName
Publisher
OriginalFilename
```

Также предусмотреть ручное объединение executables/applications.

Использовать application_aliases и контракт §8.8. Не переписывать исторические
application IDs; running интервалы объединять по времени до суммирования.
Добавление merge не должно сводиться к перепривязке только executables.application_id.

---

## 37.2 Settings page

Будущие настройки:

```text
Idle threshold
Track window titles
Ignored applications
Start with Windows
Pause tracking
Data retention
Export
```

---

## 37.3 Smart idle detection

Не считать IDLE, если пользователь реально потребляет media.

Возможные сигналы:

```text
video playback
audio playback
fullscreen media
presentation mode
gamepad input
```

В MVP это НЕ реализуется.

Если пользователь 20 минут смотрит YouTube без mouse/keyboard input, после 5 минут считать состояние `IDLE`.

---

## 37.4 Advanced statistics

В будущем:

```text
Foreground / Running ratio

Launch count
Average session duration
Longest session

Context switches
Window switches

Longest uninterrupted focus session

Time by window title
Time by hour
Time by day/week/month

Application transition matrix:
VS Code → Chrome
Chrome → VS Code
VS Code → Telegram
```

---

## 37.5 Window-title based analytics

Будущая аналитика может группировать title.

Примеры:

```text
VS Code
    feed-validator — 2h 14m
    mediascraper — 1h 03m
```

```text
Chrome
    YouTube — 1h 31m
    GitHub — 48m
    ChatGPT — 37m
```

Поэтому raw titles необходимо собирать уже с первой версии.

---

# 38. Не делать в MVP

Не добавлять:

- cloud sync
- account system
- authentication
- PostgreSQL/MySQL
- multi-device sync
- productivity categories
- AI classification
- complex charts
- automatic URL/browser-tab parsing
- smart media activity detection
- macOS/Linux support
- ProductName/Publisher/OriginalFilename matching
- advanced settings UI

Основная цель MVP:

> tracker должен стабильно и правдоподобно собирать локальную историю использования Windows-приложений.

---

# 39. Критерии готовности ядра MVP

MVP ядро считается готовым, если:

1. Tracker можно запустить на Windows.
2. Он живёт в tray.
3. SQLite создаётся автоматически.
4. Запущенные приложения корректно превращаются в `application_running_sessions`.
5. Foreground application отслеживается.
6. Смена window title сохраняется отдельной foreground session.
7. Через 5 минут без input состояние становится IDLE.
8. LOCKED и SLEEP отличаются от IDLE.
9. Running time продолжает считаться во время IDLE.
10. Active time считается только как foreground ∩ ACTIVE.
11. Context switch соответствует зафиксированному определению.
12. Ignored applications исключаются из исторической статистики без удаления raw data.
13. Crash recovery закрывает dangling sessions по согласованной границе heartbeat/persisted data, без отрицательных интервалов; второй экземпляр не запускает recovery поверх первого.
14. Все timestamps хранятся в UTC milliseconds.
15. FastAPI отдаёт stats за произвольный диапазон дат.
16. Tracker не падает из-за одного inaccessible/elevated/system process.
17. Нет periodic sample inserts каждые 2–5 секунд.
18. Unit tests покрывают state/session/statistics logic.
19. Приложения получают display name из Windows metadata с fallback на exe name.
20. Иконки приложений извлекаются и кешируются локально; отсутствие иконки не ломает tracker.
21. Фильтр времени применяется отдельно к каждому выбранному локальному дню.
22. Диапазоны времени через полночь корректно поддерживаются.
23. `active_only` корректно меняет фильтрацию и сортировку `/stats/apps`.
24. `/stats/timeline` корректно возвращает application/system/other_activity segments.
25. `/stats/activity` корректно отдаёт heatmap data для коротких и длинных диапазонов.
26. Heatmap UI имеет обязательные tooltips с точным временем и длительностью активности.
27. Heatmap корректно считает неполные и повторяющиеся часы, отличает missing_hour от no_data.
28. Неизвестные процессы сохраняются без фиктивных executables; foreground observation регистрирует running немедленно.
29. `/stats/apps` возвращает items и признаки наличия данных; PATCH изменяет ignored/track_titles через общий writer.
30. Схема включает пустую application_aliases и контракт будущего объединения без переписывания истории.

---

# 40. Рекомендация по структуре проекта

Допустимый вариант:

```text
app/
├── main.py
│
├── domain/
│   ├── events.py
│   ├── models.py
│   ├── tracker_state.py
│   ├── system_state.py
│   └── session_manager.py
│
├── platform/
│   └── windows/
│       ├── foreground.py
│       ├── processes.py
│       ├── idle.py
│       ├── session_events.py
│       └── power_events.py
│
├── storage/
│   ├── database.py
│   ├── migrations.py
│   ├── repositories.py
│   └── stats.py
│
├── api/
│   ├── app.py
│   ├── schemas.py
│   └── routes/
│       ├── stats.py
│       └── applications.py
│
├── tray/
│   └── tray_app.py
│
└── tests/
    ├── test_running_sessions.py
    ├── test_foreground.py
    ├── test_system_state.py
    ├── test_crash_recovery.py
    ├── test_stats.py
    └── test_context_switches.py
```

Не обязательно следовать именам файлов буквально, но разделение ответственности следует сохранить.

---

# 41. Важный принцип реализации

Приоритет:

```text
correctness
↓
stability
↓
simple architecture
↓
performance
↓
extra features
```

Не оптимизировать преждевременно.

SQLite и interval-based storage достаточно для многолетней локальной истории одного пользователя.

Главная задача первой версии — убедиться, что собранным цифрам можно доверять.
