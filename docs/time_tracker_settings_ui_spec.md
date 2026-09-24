# TimeTracker — Settings UI Specification

## 1. Назначение документа

Этот документ описывает UI/UX и поведение страницы **Настройки** для TimeTracker.

Документ предназначен для реализации frontend-части страницы настроек в Codex и должен использоваться вместе с основной технической спецификацией TimeTracker и общей UI-спецификацией проекта.

Цель страницы настроек:

- сохранить визуальный стиль текущего TimeTracker;
- не превращать интерфейс в тяжёлую административную панель;
- сгруппировать большое количество настроек в понятные категории;
- сделать наиболее частые настройки быстрыми и очевидными;
- отделить обычные настройки от потенциально опасных действий;
- оставить архитектурный запас для второго этапа настроек.

---

# 2. Общий визуальный стиль

Страница должна быть визуально продолжением существующей главной страницы TimeTracker.

Основные характеристики:

```text
calm
semi-premium
soft pink
white / near-white
large blurred pink blobs
glass-like panels
rounded controls
Manrope
lots of whitespace
```

Не использовать:

- тяжёлые admin-panel стили;
- тёмный sidebar;
- плотные таблицы;
- множество отдельных карточек;
- толстые borders;
- насыщенные gradients;
- слишком яркие status colors;
- модальные окна для обычных безопасных настроек.

Основной шрифт:

```text
Manrope
```

---

# 3. Основной layout страницы

Страница сохраняет общий layout приложения.

Пример:

```text
TimeTracker                                               ⚙

Основная   Расширенная


Настройки

┌──────────────────────┐    ┌─────────────────────────────────────────┐
│ Сбор активности      │    │                                         │
│ Отображение          │    │  Содержимое выбранного раздела          │
│ Приложения и         │    │                                         │
│ приватность          │    │                                         │
│ Запись и запуск      │    │                                         │
└──────────────────────┘    └─────────────────────────────────────────┘
```

Фактически левая часть не должна выглядеть как отдельная тяжёлая карточка.

Рекомендуемая композиция:

```text
left settings navigation
+
right glass content panel
```

---

# 4. Размеры layout

Использовать ту же desktop-сетку, что и на основной странице.

```css
width: min(68vw, 1280px);
margin: 0 auto;
```

Целевой монитор:

```text
1920×1080
```

Небольшой вертикальный scroll допустим.

Рекомендуемые размеры:

```text
settings navigation width: 220–250 px
gap between navigation and content: 32–40 px
content panel: remaining width
```

---

# 5. Header

Использовать существующий header приложения без визуального изменения:

```text
TimeTracker
Основная
Расширенная
gear button
```

Gear остаётся в правом верхнем углу.

На странице `/settings` gear может оставаться визуально active либо без отдельного состояния.

---

# 6. Заголовок страницы

Над settings navigation:

```text
Настройки
```

Рекомендуемо:

```text
font-size: 30–36 px
font-weight: 700
```

---

# 7. Категории настроек

Первый релиз страницы содержит четыре категории:

```text
Сбор активности
Отображение
Приложения и приватность
Запись и запуск
```

Не создавать отдельный пункт:

```text
Личный день
```

Он входит в:

```text
Отображение
```

Автозапуск Windows входит в:

```text
Запись и запуск
```

---

# 8. Settings navigation

Navigation располагается слева.

Каждый пункт:

```text
icon + label
```

Пример:

```text
[icon] Сбор активности
[icon] Отображение
[icon] Приложения и приватность
[icon] Запись и запуск
```

Active item:

- soft pink background;
- pink icon;
- pink/dark-pink text;
- rounded pill-like shape.

Пример:

```css
background: rgba(241, 109, 159, 0.12);
border-radius: 14–16px;
```

Не использовать:

- vertical border;
- dark active block;
- strong shadow.

---

# 9. Suggested navigation icons

Допустимые варианты:

```text
Сбор активности          → activity / waveform / signal
Отображение              → monitor / display
Приложения и приватность → shield / app grid
Запись и запуск          → play / record / power
```

Использовать одну icon library.

Рекомендуемо:

```text
lucide-react
```

---

# 10. Right content panel

В правой части находится одна большая glass-like surface.

Рекомендуемо:

```css
background: rgba(255,255,255,0.72);
backdrop-filter: blur(24px);
border-radius: 28px;
box-shadow: 0 18px 50px rgba(65,35,50,0.07);
```

Padding:

```text
32–40 px
```

Не создавать отдельную card на каждую настройку.

Настройки внутри panel разделяются:

- whitespace;
- section headings;
- alignment;
- очень лёгкими dividers при необходимости.

---

# 11. Routing

Рекомендуемые routes:

```text
/                    → Основная
/advanced            → Расширенная
/settings            → Настройки
/settings/activity   → Сбор активности
/settings/display    → Отображение
/settings/apps       → Приложения и приватность
/settings/recording  → Запись и запуск
```

Допустима реализация settings subsection через внутренний state, но route-based navigation предпочтительнее.

При переходе на `/settings` default subsection:

```text
Приложения и приватность
```

или последний открытый подраздел, если позже будет добавлено persistence.

Для MVP допустимо всегда открывать:

```text
Приложения и приватность
```

---

# 12. Первый релиз — Сбор активности

Раздел:

```text
Сбор активности
```

Subtitle:

```text
Настройте способ получения данных об активности приложений.
```

Основные элементы:

```text
Текущий режим
ETW-компонент
status
install / update / remove
fallback status
```

---

# 13. Текущий режим сбора

Показывать:

```text
Текущий режим
● ETW
```

или:

```text
Текущий режим
● Polling
```

Status должен быть очевиден без технических знаний.

Не показывать пользователю внутренние детали реализации без необходимости.

---

# 14. ETW status states

Минимальные состояния:

## ETW используется

```text
● Подключён
ETW используется для сбора активности
```

## ETW установлен, но fallback активен

```text
● Используется Polling

ETW временно недоступен.
TimeTracker использует резервный режим.
```

## ETW не установлен

```text
ETW-компонент не установлен

[Установить ETW]
```

## ETW update available

```text
ETW-компонент
Версия 1.2.0

Доступно обновление 1.3.0

[Обновить]
```

---

# 15. ETW actions

Поддержать:

```text
Установить
Обновить
Удалить
```

Основное действие:

```text
soft pink button
```

Secondary/destructive:

```text
text button
```

Для удаления ETW необходимо confirmation.

Пример:

```text
Удалить ETW-компонент?

После удаления TimeTracker продолжит работу в режиме Polling.

[Отмена] [Удалить]
```

---

# 16. ETW fallback wording

Не использовать только слово:

```text
fallback
```

в основном UI.

Показывать человекочитаемый текст:

```text
Используется резервный режим Polling
```

Технический термин `fallback` можно показывать только в tooltip/debug info.

---

# 17. Первый релиз — Отображение

Раздел:

```text
Отображение
```

Subtitle:

```text
Настройте формат времени и границы статистического дня.
```

Содержит:

```text
Единицы времени
Личный день
```

---

# 18. Единицы времени

Доступные единицы:

```text
Дни
Часы
Минуты
```

UI:

```text
[✓ Дни] [✓ Часы] [✓ Минуты]
```

Можно использовать:

- checkbox chips;
- segmented checkbox-like controls.

Не использовать dropdown.

---

# 19. Time units semantics

Выбранные единицы определяют формат durations во всём UI.

Если выбраны:

```text
Часы
```

пример:

```text
12 ч. 30 м.
→
12,5 ч.
```

Если выбраны:

```text
Дни + Минуты
```

пример:

```text
3 д. 10 ч. 5 м.
→
3 д. 605 м.
```

То есть невыбранные более мелкие единицы преобразуются в самую мелкую выбранную единицу.

---

# 20. Live formatting preview

Под выбором units обязательно показывать preview:

```text
Пример
3 д. 10 ч. 5 м.
```

или:

```text
Пример
3 д. 605 м.
```

Preview обновляется мгновенно при изменении units.

Использовать заранее определённую test duration, чтобы пользователь сразу понимал результат.

---

# 21. Личный день

Setting:

```text
Начало суток
```

Default:

```text
00:00
```

UI:

```text
Начало суток                              [02:00]
```

Описание:

```text
Статистический день будет идти с 02:00
до 02:00 следующего календарного дня.
```

---

# 22. Personal day semantics

Если:

```text
Начало суток = 02:00
```

то статистический день:

```text
22.09.2026
```

означает:

```text
22.09.2026 02:00
→
23.09.2026 02:00
```

Это должно влиять на:

- date filters;
- total active time;
- app statistics;
- timeline;
- heatmap;
- context switches;
- daily grouping.

---

# 23. Time slider with personal day

Главный time slider должен использовать границы личного дня.

Пример:

```text
Personal day start = 02:00
```

Full-day slider:

```text
02:00 ───────────────────────────── 02:00
```

Правая граница означает следующий календарный день.

Полный диапазон:

```text
02:00 → 01:59 следующего дня
```

Визуальные labels должны ясно показывать crossing midnight.

---

# 24. Первый релиз — Приложения и приватность

Это основной табличный settings section.

Title:

```text
Приложения и приватность
```

Subtitle:

```text
Настройте видимость приложений и параметры приватности.
```

---

# 25. Applications section layout

Структура:

```text
Приложения и приватность
subtitle

[ Search applications...                  ]  Обнаружено приложений: N

#   Приложение            Цвет    Заголовки      В статистике
----------------------------------------------------------------
1   Google Chrome          ●       [ON]            [ON]
2   Firefox                ●       [ON]            [ON]
3   Visual Studio Code     ●       [ON]            [ON]
...
```

---

# 26. Applications search

Search field:

```text
Поиск приложений...
```

Слева:

```text
search icon
```

Search работает client-side по уже загруженному списку.

Искать по:

```text
application.name
```

Можно также учитывать executable name, если он уже доступен frontend.

Не делать API request на каждую букву.

---

# 27. Application count

Справа от search:

```text
Обнаружено приложений: 84
```

Muted style.

Если search активен, допустимо показывать:

```text
Найдено: 7 из 84
```

---

# 28. Applications table columns

MVP columns:

```text
#
Приложение
Цвет
Заголовки
В статистике
```

---

# 29. Rank column

Rank используется только как визуальный row index.

Не является persistent application property.

Размер:

```text
32–40 px
```

Muted.

---

# 30. Application column

Содержит:

```text
24×24 icon
application name
```

Пример:

```text
[Chrome icon] Google Chrome
```

Long names:

```text
ellipsis
```

Full name можно показывать tooltip.

---

# 31. Application color

Column:

```text
Цвет
```

Показывать небольшой filled circle:

```text
●
```

Размер:

```text
16–20 px
```

При click открывается color popover.

---

# 32. Color palette popover

Не использовать unrestricted RGB/HEX color picker в MVP.

Показывать curated pastel palette.

Пример:

```text
● ● ● ● ●
● ● ● ● ●

Авто
```

`Авто` возвращает автоматически назначенный цвет.

Цвет используется в:

- day timeline;
- future charts;
- application-specific visual elements.

---

# 33. Suggested app color palette

Можно использовать палитру из общей UI specification:

```text
soft blue
pink
cyan
periwinkle
mint
pale yellow
soft green
lavender
muted blue-gray
muted lilac
soft orange
soft coral
```

Не позволять пользователю случайно создать визуально агрессивный neon color.

---

# 34. Заголовки column

Column name:

```text
Заголовки
```

Не использовать негативную формулировку:

```text
Не сохранять новые заголовки окон
```

Toggle semantics:

```text
ON  = сохранять новые window titles
OFF = не сохранять новые window titles
```

В backend это соответствует:

```text
track_titles
```

---

# 35. Заголовки tooltip

Рядом с column header допустима info icon.

Tooltip:

```text
Если выключить, TimeTracker продолжит учитывать
активность приложения, но новые заголовки его окон
не будут сохраняться.
```

Важно:

```text
существующие исторические title автоматически не удаляются
```

Это можно дополнительно указать в tooltip.

---

# 36. В статистике column

Column:

```text
В статистике
```

Toggle semantics:

```text
ON  = приложение учитывается
OFF = приложение исключено
```

Backend может продолжать использовать:

```text
ignored = true/false
```

Но UI должен показывать положительную формулировку.

---

# 37. Statistics tooltip

Tooltip:

```text
Если выключить, приложение перестанет отображаться
в статистике. Уже собранные данные не удаляются.
```

---

# 38. Ignored app timeline behavior

Если:

```text
В статистике = OFF
```

приложение:

- не показывается отдельным application entry;
- не участвует в app table stats;
- не участвует в context switches;
- raw history сохраняется.

В timeline его active interval может отображаться как:

```text
Другая активность
```

чтобы временная шкала не имела ложного пустого промежутка.

---

# 39. Future strict privacy option

Не реализовывать в первом release.

Будущая настройка:

```text
Не показывать вообще
```

Смысл:

- не показывать название приложения;
- не показывать app-specific activity;
- возможно не учитывать даже в общей активности.

Это отдельный более строгий privacy mode и не должен смешиваться с текущим `В статистике`.

---

# 40. Applications table row styling

Row height:

```text
44–52 px
```

Рекомендуемо:

```text
48 px
```

Rows разделяются:

- whitespace;
- very subtle 1px divider.

Не делать каждую row отдельной card.

---

# 41. Toggle switch style

ON:

```text
pink
```

OFF:

```text
soft gray
```

Размер:

```text
44–48 px width
24–26 px height
```

Допустимо показывать справа:

```text
Вкл.
Выкл.
```

но это не обязательно, если toggle визуально однозначен.

---

# 42. Application table sorting

MVP:

- не добавлять sortable column headers;
- не добавлять drag reorder;
- не добавлять manual sorting controls.

Default sort:

```text
application.name ASC
```

или текущий backend order.

Рекомендуемо:

```text
application.name ASC
```

для settings, поскольку это справочник, а не статистика.

---

# 43. Applications pagination

Не нужна для MVP.

Даже несколько сотен discovered applications допустимо отобразить одной таблицей.

При необходимости позже можно добавить virtualized list.

---

# 44. First release — Запись и запуск

Раздел:

```text
Запись и запуск
```

Subtitle:

```text
Управляйте записью активности и запуском TimeTracker.
```

---

# 45. Recording status

Верхний блок:

```text
Запись активности

● Запись активна

TimeTracker сейчас собирает данные
об использовании приложений.

[Приостановить]
```

Paused state:

```text
● Запись приостановлена

Новые данные сейчас не сохраняются.

[Возобновить]
```

---

# 46. Pause semantics

При pause:

- новые tracking sessions не создаются;
- программа продолжает работать в tray;
- dashboard/settings доступны;
- состояние pause сохраняется до явного resume, включая app restart.

Рекомендуемо сохранять состояние между reload web UI.

---

# 47. Global paused indicator

Если tracking paused, пользователь должен видеть это не только в settings.

На основной странице рядом с gear / header показывать заметный, но спокойный indicator:

```text
Пауза
```

или:

```text
amber dot + Пауза
```

Не использовать alarm-style red.

---

# 48. Autostart

Setting:

```text
Запускать вместе с Windows
```

Control:

```text
toggle
```

Default отражает текущий реальный autostart state.

Autostart больше не должен быть скрытой tray-only настройкой.

---

# 49. Save behavior

Обычные безопасные settings должны сохраняться автоматически при изменении.

Примеры:

```text
time units
personal day start
application color
track titles
in statistics
autostart
```

Не добавлять общую кнопку:

```text
Сохранить настройки
```

для всей страницы.

Это уменьшает UI clutter.

---

# 50. Save feedback

После успешного autosave:

- не показывать toast на каждое изменение;
- можно использовать very subtle check/status;
- отсутствие feedback допустимо, если изменение визуально применилось.

При ошибке:

```text
Не удалось сохранить настройку
```

и вернуть control в предыдущее состояние либо показать retry.

---

# 51. Destructive actions

Confirmation обязательно для:

```text
Удалить ETW-компонент
future history deletion
future data reset
```

Confirmation не нужен для:

```text
toggle titles
toggle statistics
change color
change units
change personal day
pause/resume
autostart
```

---

# 52. Status colors

Status color palette должна оставаться мягкой.

Пример:

```text
success       → muted green
fallback/info → muted amber
error         → muted red
neutral       → gray
active pink   → primary pink
```

Не использовать яркие системные цвета.

---

# 53. Loading state

Settings navigation может отображаться сразу.

Content panel при loading:

```text
soft skeleton
```

Для applications table:

- search skeleton;
- 6–8 row skeletons.

Не показывать fullscreen spinner.

---

# 54. Error state

Если section data не загрузилась:

```text
Не удалось загрузить настройки
```

Button:

```text
Повторить
```

Не показывать raw backend errors.

---

# 55. Empty applications state

Если приложений ещё не обнаружено:

```text
Приложения пока не обнаружены
```

Subtitle:

```text
Запустите несколько приложений, и они появятся здесь.
```

---

# 56. Applications search empty state

Если search ничего не нашёл:

```text
Ничего не найдено
```

Subtitle:

```text
Попробуйте изменить поисковый запрос.
```

---

# 57. Settings page animations

Использовать ту же motion system, что на основной странице:

```text
calm
short
ease-out
```

Recommended:

```text
navigation active pill: 180–220 ms
section content fade:   150–220 ms
toggle:                 150–200 ms
color popover:          120–180 ms
tooltip:                100–150 ms
```

Без bounce/spring.

---

# 58. Section switching

При click navigation item:

1. active pill плавно перемещается / меняется;
2. current content слегка fade-out;
3. next section fade-in.

Не делать full-page reload визуально.

---

# 59. Second stage settings

Не реализовывать в первом release, но architecture должна позволять добавить.

Будущие sections:

```text
Данные
Диагностика
```

---

# 60. Second stage — Data

Реализовано 24.09.2026:

```text
Export CSV
Export JSON
```

Одна строка — непрерывный интервал приложения или состояния системы. Период синхронен
с основной страницей; titles выключены по умолчанию и включаются явно. CSV предназначен
для Excel, JSON содержит метаданные периода и версию схемы.

Остаётся на следующий шаг:

```text
Auto-clean history
Delete selected date range
```

---

# 61. Second stage — Diagnostics

Планируется:

```text
Нет моего процесса
System process diagnostics
Windows system process list
Exclusion rules
ETW technical diagnostics
```

---

# 62. Sidebar extensibility

Settings navigation должна позволять позже добавить:

```text
Данные
Диагностика
```

без redesign.

Пример будущего списка:

```text
Сбор активности
Отображение
Приложения и приватность
Запись и запуск

Данные
Диагностика
```

Можно визуально отделить advanced sections небольшим gap.

---

# 63. Recommended component tree

```text
SettingsPage
├── AppBackground
├── AppHeader
├── SettingsTitle
└── SettingsLayout
    ├── SettingsNavigation
    │   ├── ActivityNavItem
    │   ├── DisplayNavItem
    │   ├── AppsPrivacyNavItem
    │   └── RecordingNavItem
    │
    └── SettingsPanel
        ├── ActivitySettings
        ├── DisplaySettings
        ├── AppsPrivacySettings
        │   ├── AppsHeader
        │   ├── AppsSearch
        │   ├── AppsCount
        │   ├── AppsTable
        │   │   └── ApplicationSettingsRow
        │   └── ColorPickerPopover
        └── RecordingSettings
```

---

# 64. Applications row data model

Frontend row минимум:

```ts
type ApplicationSettingsRow = {
  id: number;
  name: string;
  iconUrl?: string | null;
  color?: string | null;
  trackTitles: boolean;
  includedInStats: boolean;
};
```

Backend mapping может быть:

```text
trackTitles       ↔ applications.track_titles
includedInStats   ↔ !applications.ignored
```

---

# 65. Settings API expectations

Точные endpoints могут отличаться, но frontend нужен API уровня:

```text
GET    /settings
PATCH  /settings/display
PATCH  /settings/recording
GET    /settings/activity-source

GET    /applications
PATCH  /applications/{id}
GET    /applications/{id}/icon

POST   /etw/install
POST   /etw/update
DELETE /etw
```

Это interface expectation, а не обязательное точное именование backend routes.

---

# 66. Application PATCH examples

Изменить color:

```json
{
  "color": "#F6A6C1"
}
```

Выключить titles:

```json
{
  "track_titles": false
}
```

Исключить из stats:

```json
{
  "ignored": true
}
```

---

# 67. Display settings model

Пример:

```json
{
  "time_units": {
    "days": true,
    "hours": true,
    "minutes": true
  },
  "personal_day_start": "00:00"
}
```

---

# 68. Recording settings model

Пример:

```json
{
  "tracking_paused": false,
  "autostart": true
}
```

---

# 69. Activity source model

Пример:

```json
{
  "mode": "etw",
  "etw_installed": true,
  "etw_connected": true,
  "fallback_active": false,
  "installed_version": "1.2.0",
  "latest_version": "1.2.0"
}
```

Fallback:

```json
{
  "mode": "polling",
  "etw_installed": true,
  "etw_connected": false,
  "fallback_active": true
}
```

---

# 70. Important UX wording

Использовать положительные формулировки.

Хорошо:

```text
Заголовки
В статистике
Запускать вместе с Windows
```

Избегать:

```text
Не сохранять заголовки
Не исключать из статистики
Не отключать автозапуск
```

---

# 71. Privacy explanation

В section `Приложения и приватность` желательно коротко пояснить:

```text
Отключение заголовков влияет на новую запись.
Видимость в статистике применяется ко всей истории.
Собранные данные не удаляются.
```

Можно показать это как muted note внизу panel либо через tooltips.

---

# 72. Current mockup reference

Согласованный визуальный референс страницы:

```text
Settings
→ active subsection: Приложения и приватность
→ left lightweight navigation
→ large right glass panel
→ search
→ applications table
→ pastel color dots
→ positive ON/OFF toggles
```

Главный визуальный приоритет:

```text
Settings должны выглядеть частью TimeTracker,
а не отдельной административной системой.
```

---

# 73. MVP Settings acceptance criteria

Settings UI считается готовым, если:

1. Страница визуально совпадает с текущим TimeTracker.
2. Используется Manrope.
3. Сохраняется pink/white blurred-background aesthetic.
4. Settings разделены на четыре категории.
5. Navigation находится слева.
6. Active navigation item имеет soft pink pill.
7. Right content находится в одной large glass panel.
8. Не создаётся отдельная card для каждой маленькой настройки.
9. `Приложения и приватность` реализованы таблицей.
10. В таблице есть search.
11. Показывается количество discovered applications.
12. Иконки приложений отображаются в таблице.
13. Для каждого приложения можно выбрать pastel color.
14. Color picker содержит curated palette + `Авто`.
15. `Заголовки` — positive toggle.
16. `В статистике` — positive toggle.
17. Изменение application settings сохраняется автоматически.
18. Существующая история не удаляется при toggle.
19. `Отображение` позволяет выбрать дни/часы/минуты.
20. Есть live preview форматирования времени.
21. `Личный день` позволяет выбрать начало суток.
22. Personal day влияет на границы статистического дня.
23. Main time slider адаптируется под personal day start.
24. `Сбор активности` показывает Polling/ETW status.
25. ETW install/update/remove доступны из settings.
26. Fallback mode отображается понятным человеческим текстом.
27. `Запись и запуск` содержит pause/resume.
28. Recording status хорошо заметен.
29. Autostart перенесён в settings.
30. Paused state виден и на основной странице.
31. Loading/error/empty states оформлены в стиле приложения.
32. Второй этап можно добавить без redesign navigation.

---

# 74. Согласованные правила реализации — 22.09.2026

- Хотя бы одна единица времени всегда выбрана. Дробная часть возможна только у
  последней выводимой единицы. Для одной выбранной единицы значения меньше 10
  округляются до десятых, остальные — до целого. В составном формате остаток часов
  или минут больше 1 округляется до целого; меньший остаток — до десятых. Очень
  короткое ненулевое время показывается как `<0,1` выбранной единицы. Округление
  выполняется до разложения, чтобы не появлялись значения вроде `23 ч. 60 м.`.
- Пауза сохраняется между перезагрузками страницы и перезапусками приложения.
  Текущие интервалы закрываются; возобновление создаёт новый run со свежим snapshot.
  Время паузы остаётся `no_data`, включая общую активность, running time и heatmap.
  Настройки, dashboard и трей продолжают работать. Настройка паузы и граница записи
  сохраняются атомарно; блокировка базы удерживается и во время паузы.
- Личный день — полуоткрытый диапазон `[начало, начало следующего дня)`.
  Запись `02:00 → 01:59` выше — только иллюстрация; последняя минута включается полностью.
  «Сегодня» до границы личного дня означает предыдущую календарную дату.
  Часовой пояс сохраняется как IANA timezone; DST учитывается в API.
  Смена границы пересчитывает отчёты по всей истории, не переписывая исходные интервалы.
- `ignored` меняет таблицу приложений и переключения за все даты, сохраняя общую
  активность и heatmap. В timeline используется безымянная «Другая активность».
  `track_titles` управляет только новой записью заголовков.
- Ручной выбор Polling/ETW сохраняется. Применение выбранного режима требует
  перезапуска. Обновление и удаление ETW выполняются после перехода на Polling
  и перезапуска; установка требует штатного подтверждения Windows.
- Доступное обновление ETW определяется сравнением установленного компонента
  с комплектом текущей сборки TimeTracker, без сетевой проверки. До появления
  семантических версий показываются идентификаторы сборок из хеша пакета.
- Реализация включает необходимые изменения ядра, хранения и API. Предпочтения
  хранятся в SQLite (миграция 3), пользовательский цвет — в `applications.color`;
  `null` означает автоматический цвет.
- `GET /settings/preferences` возвращает display/recording; изменения принимают
  `PATCH /settings/display`, `PATCH /settings/recording`, `PATCH /applications/{id}`.
  Управление ETW использует существующие `GET/POST /settings/collection`.
  HTML-маршруты настроек сохраняются отдельно от GET API предпочтений.
