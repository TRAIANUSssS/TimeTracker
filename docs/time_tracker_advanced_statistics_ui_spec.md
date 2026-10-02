# TimeTracker — Advanced Statistics UI Specification

## 1. Назначение документа

Этот документ описывает UI/UX и поведение страницы **Расширенная статистика** в TimeTracker.

Страница должна быть визуально и функционально продолжением текущей основной страницы TimeTracker.

Основная задача страницы:

```text
дать пользователю более глубокий анализ активности
без превращения интерфейса в BI-систему
```

Страница должна отвечать на три группы вопросов:

```text
1. Как прошёл выбранный период?
2. Как менялась активность во времени?
3. Какие приложения и переходы сформировали эту активность?
```

Документ предназначен для реализации frontend-части в Codex и должен использоваться вместе с:

- основной технической спецификацией TimeTracker;
- общей UI specification;
- settings UI specification;
- существующей реализацией основной страницы.

---

# 2. Общий визуальный стиль

Сохранить текущий стиль TimeTracker без заметного визуального расхождения.

Основные характеристики:

```text
calm
semi-premium
soft pink
white / near-white
blurred pink blobs
glass-like panels
Manrope
rounded corners
subtle shadows
desktop-first
```

Страница должна ощущаться как:

```text
тот же TimeTracker,
но с более глубоким уровнем аналитики
```

Не использовать:

- тёмный dashboard;
- BI-style dense grid;
- множество мелких KPI cards;
- агрессивные цвета;
- тяжёлые borders;
- большое количество legends;
- pie / donut charts;
- слишком много разных типов графиков одновременно.

---

# 3. Общий layout

Использовать ту же desktop-сетку, что и на основной странице.

```css
width: min(68vw, 1280px);
margin: 0 auto;
```

Целевой монитор:

```text
1920×1080
```

Небольшой vertical scroll допустим.

Структура страницы:

```text
Header
↓
Global filters
↓
KPI block
↓
Charts row
↓
Detail block
↓
bottom spacing
```

---

# 4. Header

Использовать существующий header.

```text
TimeTracker

Основная   Расширенная                              ⚙
           ───────────
```

На этой странице:

```text
Расширенная = active tab
```

Active underline должен работать так же, как на основной странице.

---

# 5. Global filters

В верхней части страницы оставить тот же подход к фильтрации, что и на основной странице.

Структура:

```text
[ Date range ]      [ Time range slider ]      Сбросить
```

Не показывать:

```text
Только активные
```

На расширенной странице этот filter не нужен.

---

# 6. Date range

Использовать текущий date range picker без redesign.

Формат:

```text
DD.MM.YY–DD.MM.YY
```

Пример:

```text
08.09.26–14.09.26
```

---

# 7. Time range

Использовать тот же range slider, что на основной странице.

Default:

```text
current personal day, for example 00:00–24:00
```

Полный день использует ту же полуоткрытую границу, что основная страница и backend.
`23:59` остаётся точной исключённой границей и не подменяет конец суток.

Slider step:

```text
15 минут
```

Ручной ввод:

```text
1-minute precision
```

Если включён personal day:

```text
slider boundaries follow personal day start
```

---

# 8. Filter influence

Date/time filters должны влиять на всю страницу одновременно:

- KPI;
- weekly activity chart;
- activity dynamics chart;
- application table;
- transitions view;
- top transitions.

Не делать отдельные независимые filters для каждого блока.

---

# 9. Основная архитектура страницы

Страница состоит из трёх крупных аналитических блоков:

```text
1. Интересные цифры
2. Графики
3. Детализация
```

---

# 10. Блок 1 — KPI

Использовать одну широкую glass card.

Не делать четыре отдельные floating cards.

Внутри card:

```text
4 равномерно распределённых KPI
```

Визуально можно использовать:

- subtle vertical dividers;
- spacing;
- alignment.

---

# 11. KPI component structure

Каждый KPI всегда имеет одинаковую структуру:

```text
Название метрики
Крупное значение
Дополнительный контекст
```

Важно:

третья строка не обязана быть одинакового типа у всех KPI.

Она отвечает на вопрос:

```text
Что ещё полезно знать про это значение?
```

---

# 12. KPI 1 — Переключения

Label:

```text
Переключения
```

Main value:

```text
184
```

Context:

```text
−12% к прошлой неделе
```

или:

```text
Прошлый период: 209
```

Не использовать green/red семантику как good/bad.

Количество переключений само по себе не является положительной или отрицательной метрикой.

Изменение показывать нейтрально.

---

# 13. KPI 2 — На активный час

Label:

```text
На активный час
```

Main value:

```text
24,3
```

Meaning:

```text
application context switches / active hours
```

Context:

```text
Прошлая неделя: 26,1
```

или equivalent previous-period value.

---

# 14. KPI 3 — Самый длинный фокус

Label:

```text
Самый длинный фокус
```

Main value:

```text
1 ч. 47 м.
```

Context:

```text
Visual Studio Code
```

Здесь third line специально показывает приложение, а не comparison.

Это не должно визуально выбиваться, поскольку структура component остаётся одинаковой:

```text
label
value
context
```

Focus означает непрерывный `ACTIVE` в одном non-ignored foreground-приложении.
Смена HWND/title внутри того же приложения не разрывает focus. Другое приложение,
ignored/unknown activity, IDLE, LOCKED, SLEEP, no-data и граница personal day разрывают его.

---

# 15. KPI 4 — В среднем в день

Label:

```text
В среднем в день
```

Main value:

```text
5 ч. 18 м.
```

Context:

```text
Прошлая неделя: 4 ч. 51 м.
```

Для диапазона больше недели можно использовать:

```text
Прошлый период: ...
```

---

# 16. KPI typography

Label:

```text
14–15 px
font-weight: 500
muted
```

Value:

```text
30–38 px
font-weight: 700
```

Context:

```text
13–14 px
muted
```

KPI values должны быть визуально главным элементом card.

---

# 17. KPI card dimensions

Card:

```text
width: 100%
border-radius: 24–28 px
padding: 24–30 px
```

Ориентировочно:

```text
4 equal columns
```

Допустимы very subtle dividers между KPI.

---

# 18. Блок 2 — Charts row

Ниже KPI расположить два графика в одну строку.

Layout:

```text
left chart  ~40%
right chart ~60%
```

Пример:

```text
┌──────────────────────┐  ┌──────────────────────────────┐
│ Активность за неделю │  │ Динамика активного времени  │
└──────────────────────┘  └──────────────────────────────┘
```

Gap:

```text
16–24 px
```

---

# 19. Chart cards

Оба графика находятся в отдельных glass cards.

Рекомендуемо:

```text
border-radius: 22–26 px
padding: 20–24 px
```

Card height должна быть примерно одинаковой.

Не делать charts слишком высокими.

Цель:

```text
они важны,
но не должны вытеснять table/details block
```

---

# 20. Left chart — weekly activity

Default title:

```text
Активность за неделю
```

Для диапазона от 2 до 7 дней использовать 7 weekday slots с отдельными vertical bars.
Заполняются только даты выбранного периода; остальные slots остаются ghost.

Для диапазона ровно в 1 день график даёт недельный контекст: выбранный день и шесть
предыдущих календарных дней. Это расширение относится только к этому графику — KPI,
динамика, приложения и переходы по-прежнему считаются строго за выбранный день.
Обычные дни используют более светлый `pink-300`, а выбранный день и текущая
календарная дата, если она попала в график, сохраняют основной насыщенный градиент.
Дополнительная обводка, фон вокруг bar или точечный маркер не используются.

X-axis:

```text
Пн
Вт
Ср
Чт
Пт
Сб
Вс
```

---

# 21. Weekly bars

Использовать:

```text
7 separate rounded bars
```

Не использовать одну continuous weekly strip.

Причина:

```text
отдельные bars позволяют мгновенно сравнить дни
```

Bar style:

```text
soft pink gradient
rounded top
```

---

# 22. Weekly chart average line

Через график проходит horizontal dashed line.

Meaning:

```text
Среднее активное время за прошлую неделю
```

Legend:

```text
Среднее за прошлую неделю
```

Tooltip:

```text
Среднее за предыдущую неделю
4 ч. 38 м. в день
```

---

# 23. Weekly average semantics

Для обычной недели average считается по всем 7 календарным дням.

Если в день не было activity:

```text
0 часов
```

входит в среднее, если tracker наблюдал этот день. Прошедший день без tracking data
показывается как no-data и исключается из среднего. Это состояние визуально отличается
от наблюдавшегося нуля.

Будущие дни текущей незавершённой недели:

```text
не считать нулём
```

и визуально показывать как empty/ghost.

---

# 24. Weekly chart tooltips

Hover bar:

```text
Среда
6 ч. 14 м.
```

Если exact date полезна:

```text
Среда, 24 сентября
6 ч. 14 м.
```

---

# 25. Weekly chart for ranges > 7 days

Если выбран диапазон больше 7 дней, component остаётся на том же месте, но меняет смысл.

Title:

```text
По дням недели
```

Bars:

```text
Пн–Вс
```

Каждый bar означает:

```text
среднее active time
для соответствующего дня недели
внутри выбранного периода
```

Tooltip:

```text
Среда
В среднем: 5 ч. 27 м.
```

---

# 26. Comparison line for long ranges

Для диапазона > 7 дней dashed line означает:

```text
среднее active time
за предыдущий период той же длины
```

Пример:

выбран:

```text
01.09–30.09
```

comparison:

```text
предыдущие 30 дней
```

Не сравнивать месяц только с одной неделей.

---

# 27. Right chart — activity dynamics

Title:

```text
Динамика активного времени
```

Chart type:

```text
smooth line + subtle area fill
```

Не использовать второй bar chart.

---

# 28. Dynamics visual style

Line:

```text
soft pink
2–3 px
```

Points:

```text
small round nodes
```

Area:

```text
very subtle pink translucent fill
```

Grid:

```text
very faint
```

---

# 29. Dynamics aggregation

Automatically select aggregation based on selected date range.

Recommended:

```text
1 day         → hourly
2–31 days     → daily
1–6 months    → weekly
>6 months     → monthly
```

В почасовом режиме каждая точка показывает active time внутри соответствующего часа
выбранного дня. Шкала Y имеет фиксированный ориентир 0–60 минут (кроме повторённого
DST-часа, если фактическая длительность больше). `no_data` и ещё не наступившие часы
не подменяются нулями и разрывают линию. Tooltip показывает дату, часовой интервал и
активное время.

Не добавлять manual:

```text
День / Неделя / Месяц
```

в первой версии.

---

# 30. Dynamics tooltip — daily

Example:

```text
24 сентября
6 ч. 18 м.
```

---

# 31. Dynamics tooltip — weekly

Example:

```text
16–22 сентября

Среднее: 5 ч. 02 м. / день
Всего: 35 ч. 14 м.
```

---

# 32. Dynamics tooltip — monthly

Example:

```text
Сентябрь 2026

Среднее: 5 ч. 14 м. / день
Всего: 157 ч. 04 м.
```

---

# 33. Блок 3 — Detail section

Ниже charts расположить одну large glass card.

Верхняя часть:

```text
[ Приложения ] [ Переходы ]
```

Это segmented control.

Default:

```text
Приложения
```

---

# 34. Segmented control

Active segment:

```text
soft pink fill
white or dark readable text
```

Inactive:

```text
light neutral background
muted text
```

Animation:

```text
180–220 ms
ease-out
```

---

# 35. Applications view

При active:

```text
Приложения
```

показывать extended analytics table.

Columns:

```text
#
Приложение
Активно
Запущено
Использование
Запуски
Средняя сессия
Макс. сессия
```

---

# 36. Applications table — semantics

## Активно

```text
foreground ∩ ACTIVE
```

## Запущено

```text
application running time
```

## Использование

```text
active_ms / running_ms
```

## Запуски

```text
count of running sessions whose started_at is inside selected windows
```

## Средняя сессия

```text
average full duration of those running sessions
```

## Макс. сессия

```text
longest running session
```

Running time по-прежнему пересекается с выбранными окнами. Session duration не обрезается
границей фильтра: закрытая сессия заканчивается фактическим `ended_at`, открытая — единым
request timestamp `now`. Сессия, начавшаяся до периода, участвует в `Запущено`, но не
считается новым запуском и не входит в average/max session cohort.

---

# 37. Использование column

Не показывать technical title:

```text
Foreground / Running ratio
```

UI name:

```text
Использование
```

Tooltip:

```text
Доля времени, когда приложение находилось на переднем плане,
относительно времени, когда оно было запущено.
```

---

# 38. Usage visualization

В column `Использование`:

```text
small mini progress bar + percentage
```

Example:

```text
██████░░░░  62%
```

Bar должен быть заметно компактнее bars основной страницы.

---

# 39. Usage semantics

Не окрашивать low ratio красным, high ratio зелёным.

Например:

```text
Telegram 3%
Spotify 8%
```

могут быть абсолютно нормальными.

Использовать только pink/neutral visualization.

---

# 40. Application table row

Row height:

```text
36–44 px
```

Application icon:

```text
24×24 px
```

Long names:

```text
ellipsis
```

Hover:

```text
very subtle background
```

---

# 41. Table sorting

Default sort:

```text
active_ms DESC
```

Можно показывать small sort indicator:

```text
Активно ↓
```

В первой версии можно ограничить sorting одной активной колонкой.

Не требуется full multi-column sorting.

---

# 42. Table row count

Default:

```text
10 rows
```

Можно reuse:

```text
Показать все
```

из основной страницы.

Если список already loaded:

```text
expand locally
```

без нового API request.

---

# 43. Transitions view

При active:

```text
Переходы
```

detail card показывает:

```text
Top transitions
+
transition matrix
```

---

# 44. Top transitions

Разместить над matrix внутри того же card.

Title:

```text
Самые частые переходы
```

Показывать:

```text
Top 3
```

Example:

```text
Visual Studio Code → Google Chrome      47
Google Chrome → Visual Studio Code      39
Visual Studio Code → PyCharm            31
```

Использовать icons + names при наличии места.

---

# 45. Transition matrix

Default size:

```text
up to 10 × 10
```

При 2–9 приложениях с переходами matrix адаптивно уменьшается. Empty state используется,
только если нет переходов или участвует менее двух приложений.

Apps selection:

```text
10 applications with highest participation in transitions
```

Не выбирать top-10 только по active time.

Meaning of participation:

```text
incoming + outgoing transitions
```

---

# 46. Matrix axes

Обе оси используют один и тот же app set.

Это обязательное правило.

Пример:

```text
selectedApps = 10
rows = selectedApps
columns = selectedApps
```

---

# 47. Matrix labels

Для compact layout использовать:

```text
application icons only
```

Full name показывать tooltip.

Это позволяет сохранить matrix компактной.

---

# 48. Matrix cell

Cell intensity:

```text
transition count
```

Color:

```text
near-white
→
soft pink
```

Не использовать rainbow heatmap.

---

# 49. Matrix values

По умолчанию числа внутри всех cells можно не показывать.

Main view:

```text
color intensity only
```

Hover tooltip:

```text
Visual Studio Code → Google Chrome
47 переходов
```

Если числа визуально не перегружают layout, допустимо показывать только для cells с высокой intensity.

---

# 50. Matrix diagonal

Cells:

```text
App → same App
```

не являются application context switches.

Diagonal:

```text
empty / disabled / dash
```

---

# 51. Custom matrix application selection

Каждая app icon по axis должна быть clickable.

При click:

```text
open application picker popover
```

---

# 52. Application picker

Popover:

```text
[ 🔍 Поиск приложения... ]

Google Chrome
Visual Studio Code
Telegram
PyCharm
...
```

Search:

```text
client-side
```

Rows show:

```text
icon + application name
```

---

# 53. Matrix app replacement

Если пользователь заменяет приложение:

```text
Chrome → Firefox
```

замена применяется одновременно:

```text
к строке
и
к колонке
```

Apps set остаётся одинаковым по обеим axes.

---

# 54. Duplicate protection

Нельзя выбрать приложение, которое уже присутствует среди 10 selected apps.

В picker:

```text
already selected apps
```

должны быть disabled или hidden.

---

# 55. Reset matrix apps

Если пользователь изменил default app set, показывать subtle action:

```text
Сбросить к топ-10
```

Это возвращает автоматически выбранные top transition apps.

---

# 56. Transition matrix persistence

Для первой версии допустимо:

```text
не сохранять custom selected apps между browser sessions
```

При reload:

```text
default top-10
```

POST-MVP можно добавить persistence.

---

# 57. Window switches

Метрика:

```text
Переключения окон
```

не входит в первую версию visible UI.

Перенести во вторую итерацию расширенной статистики.

---

# 58. Focus distribution

Полное распределение focus sessions не входит в первую версию.

В первой версии используется только:

```text
Самый длинный фокус
```

в KPI.

POST-MVP:

```text
focus session distribution
focus duration histogram
average focus duration
```

---

# 59. Window title analytics

`Время по заголовкам окон` не показывать отдельной большой таблицей в первой версии.

POST-MVP рекомендуется показывать через app details.

Example:

```text
Visual Studio Code
├── TimeTracker          8 ч. 14 м.
├── Feed Validator       5 ч. 42 м.
└── Mediaparser          2 ч. 08 м.
```

---

# 60. Loading behavior

Страница использует тот же loading principle, что основная:

```text
не показывать skeleton мгновенно
```

Recommended:

```text
150 ms delay
```

Если API response быстрее:

```text
no skeleton flash
```

---

# 61. KPI skeleton

KPI card:

```text
4 placeholder columns
```

Каждая:

```text
label line
large value line
small context line
```

---

# 62. Charts skeleton

Charts:

```text
faint chart-shaped placeholder
```

Не использовать large centered spinner.

---

# 63. Table skeleton

Показывать:

```text
8–10 placeholder rows
```

с column-aligned placeholders.

---

# 64. Error states

Если entire page API не загрузился:

```text
Не удалось загрузить расширенную статистику
```

Action:

```text
Повторить
```

Если одна часть не загрузилась:

```text
charts can fail independently
table can fail independently
```

Не блокировать всю страницу из-за одного failed widget.

---

# 65. Empty state

Если за выбранный period нет данных:

```text
Нет данных за выбранный период
```

Subtitle:

```text
Измените даты или временной диапазон.
```

---

# 66. Empty transitions

Если недостаточно transitions:

```text
Недостаточно переходов для построения матрицы
```

Subtitle:

```text
Матрица появится после того, как накопится больше активности.
```

---

# 67. Motion system

Использовать текущую motion system:

```text
calm
short
ease-out
```

Recommended:

```text
tab underline:             180–220 ms
KPI refresh fade:          150–200 ms
chart update:              250–350 ms
segmented control:         180–220 ms
table reorder:             220–280 ms
matrix cell transition:    200–300 ms
tooltip:                   100–150 ms
```

Без bounce/spring.

---

# 68. Filter update behavior

При изменении filters:

1. сохранить current data visually;
2. немного снизить opacity;
3. загрузить new data;
4. обновить KPI;
5. animate charts;
6. update table/matrix;
7. restore full opacity.

Не очищать страницу мгновенно.

---

# 69. API expectations — overview

Frontend ожидает data endpoints уровня:

```text
GET /stats/advanced/kpi
GET /stats/advanced/weekly
GET /stats/advanced/dynamics
GET /stats/advanced/apps
GET /stats/advanced/transitions
```

Точное именование может отличаться.

---

# 70. KPI API example

Example response:

```json
{
  "context_switches": 184,
  "context_switches_per_active_hour": 24.3,
  "longest_focus_ms": 6420000,
  "longest_focus_application": {
    "id": 17,
    "name": "Visual Studio Code"
  },
  "average_active_per_day_ms": 19080000,
  "comparison": {
    "context_switches_change_percent": -12.0,
    "previous_switches_per_active_hour": 26.1,
    "previous_average_active_per_day_ms": 17460000
  }
}
```

---

# 71. Weekly API example

Short range:

```json
{
  "mode": "week",
  "days": [
    {
      "weekday": 1,
      "date": "2026-09-21",
      "active_ms": 18000000,
      "future": false
    }
  ],
  "previous_period_average_ms": 16680000
}
```

Long range:

```json
{
  "mode": "weekday_average",
  "days": [
    {
      "weekday": 1,
      "average_active_ms": 17400000
    }
  ],
  "previous_period_average_ms": 16200000
}
```

---

# 72. Dynamics API example

```json
{
  "granularity": "day",
  "points": [
    {
      "start": "2026-09-22",
      "end": "2026-09-23",
      "active_ms": 22680000,
      "average_per_day_ms": 22680000
    }
  ]
}
```

Weekly/monthly responses may additionally include:

```text
total_active_ms
average_per_day_ms
```

---

# 73. Applications analytics API example

```json
[
  {
    "application_id": 17,
    "name": "Visual Studio Code",
    "icon_url": "/applications/17/icon",
    "active_ms": 67320000,
    "running_ms": 90600000,
    "usage_ratio": 0.743,
    "launch_count": 12,
    "average_session_ms": 7550000,
    "max_session_ms": 18840000
  }
]
```

---

# 74. Transitions API example

```json
{
  "top_transitions": [
    {
      "from_application_id": 17,
      "to_application_id": 21,
      "count": 47
    }
  ],
  "default_applications": [
    {
      "id": 17,
      "name": "Visual Studio Code",
      "icon_url": "/applications/17/icon"
    }
  ],
  "matrix": [
    {
      "from_application_id": 17,
      "to_application_id": 21,
      "count": 47
    }
  ]
}
```

---

# 75. Comparison period

Для KPI comparisons использовать previous comparable period.

Recommended:

```text
selected 7 days
→ previous 7 days

selected 30 days
→ previous 30 days

selected 90 days
→ previous 90 days
```

Для current incomplete week, weekly chart line отдельно использует previous week semantics.

---

# 76. Application ignore behavior

Ignored applications:

- не показываются в application analytics table;
- не участвуют в application context switches;
- не входят в matrix;
- не входят в top transitions.

Raw data сохраняется согласно текущей architecture.

---

# 77. Personal day support

Все daily aggregations должны учитывать:

```text
personal_day_start
```

Это касается:

- average per day;
- weekly bars;
- dynamics daily grouping;
- longest focus day boundaries;
- previous-period comparison.

---

# 78. Time units settings

Все durations должны использовать текущую user setting:

```text
days / hours / minutes
```

Не хардкодить UI durations только в hours/minutes.

---

# 79. Tooltips

Все charts и matrix должны иметь tooltips.

Must-have:

```text
weekly bars
weekly comparison line
dynamics points
usage ratio
transition matrix cells
application icons in matrix
```

---

# 80. Performance

Расширенная страница может выполнять более тяжёлые aggregation queries, поэтому:

- не делать query на каждый slider pixel movement;
- date picker request только после complete range;
- time slider request on release;
- parallel fetch независимых sections;
- cache application icons;
- не выполнять client-side aggregation больших raw session arrays, если backend может вернуть готовую агрегацию.

---

# 81. Do not add in first release

Не добавлять:

- window switches KPI;
- focus distribution chart;
- window-title breakdown;
- productivity score;
- AI interpretation;
- recommendations;
- manual chart granularity switch;
- export controls;
- custom chart colors;
- draggable dashboard cards;
- arbitrary dashboard personalization.

---

# 82. Advanced page MVP acceptance criteria

Страница считается готовой, если:

1. Визуально полностью соответствует текущему TimeTracker.
2. Active tab = `Расширенная`.
3. Верхний global filter повторяет дизайн основной страницы.
4. Checkbox `Только активные` отсутствует.
5. KPI находятся в одной wide glass card.
6. KPI имеют одинаковую структуру label/value/context.
7. Показываются `Переключения`.
8. Показываются `На активный час`.
9. Показывается `Самый длинный фокус`.
10. В longest focus third line показывается app name.
11. Показывается `В среднем в день`.
12. Charts находятся в одной строке.
13. Left chart занимает примерно 40%.
14. Right chart занимает примерно 60%.
15. Weekly chart использует 7 отдельный rounded bars.
16. Weekly chart имеет dashed previous-period average line.
17. Для диапазона >7 дней weekly component становится weekday-average chart.
18. Dynamics chart использует smooth line + area.
19. Dynamics granularity выбирается автоматически.
20. Detail card содержит segmented control.
21. Default segment = `Приложения`.
22. Applications table содержит active/running/usage/launch/session metrics.
23. `Использование` отображается mini progress + percentage.
24. Вторая вкладка = `Переходы`.
25. Переходы показывают top-3 transitions.
26. Переходы показывают адаптивную matrix размером до 10×10.
27. Matrix по умолчанию использует top-10 apps по участию в transitions.
28. Matrix axes используют один и тот же app set.
29. Matrix labels используют app icons.
30. Matrix app icons clickable.
31. Click открывает searchable application picker.
32. Replacing app replaces it simultaneously in row and column.
33. Duplicate apps нельзя выбрать.
34. Есть `Сбросить к топ-10`.
35. Matrix tooltip показывает direction + count.
36. Ignored apps не участвуют в advanced analytics.
37. Personal day учитывается во всех daily aggregations.
38. Time units settings применяются ко всем durations.
39. Loading/error/empty states оформлены в стиле TimeTracker.
40. Страница не ощущается как отдельная BI-система.
