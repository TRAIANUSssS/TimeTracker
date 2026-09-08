# TimeTracker — UI Specification

## 1. Назначение документа

Этот документ описывает UI/UX спецификацию desktop web-интерфейса TimeTracker для MVP.

Целевая платформа:

- desktop browser
- основной сценарий: Full HD monitor `1920×1080`
- mobile layout не требуется
- accessibility-specific режимы не требуются
- отдельная адаптация под screen reader, увеличенный текст и high-contrast mode не требуется

Документ предназначен для реализации frontend-интерфейса по уже согласованной backend/API спецификации.

Визуальный референс: `ChatGPT Image 8 сент. 2026 г., 15_15_12.png` в корне проекта.
Использовать его для композиции, фоновых пятен и общего характера интерфейса.
Числовые примеры на изображении иллюстративны; расчёты и поведение определяются ТЗ.

---

# 2. Общий визуальный стиль

Интерфейс должен выглядеть:

- спокойно;
- аккуратно;
- полу-премиально;
- современно;
- без корпоративной тяжеловесности;
- без чрезмерного количества карточек, рамок и декоративных разделителей.

Основной визуальный акцент:

```text
soft pink
```

Базовая среда:

```text
white / near-white
+
soft blurred pink blobs
+
semi-transparent white glass surfaces
```

Дизайн должен ощущаться лёгким и воздушным.

Не использовать:

- яркий неон;
- тяжёлые градиенты;
- тёмные массивные карточки;
- жёсткие borders;
- слишком плотную сетку;
- агрессивные shadows;
- bounce/spring-анимации;
- крупные декоративные иллюстрации.

---

# 3. Основной layout

Главный контент центрируется по горизонтали.

Рекомендуемая ширина:

```css
width: 66vw;
max-width: 1280px;
```

Допустимый диапазон:

```text
66–68vw
```

Для Full HD экран должен выглядеть естественно при ширине контента примерно:

```text
1240–1280 px
```

Рекомендуемый вариант:

```css
.page-container {
    width: min(68vw, 1280px);
    margin: 0 auto;
}
```

Минимально допустимая ширина desktop-контейнера:

```text
~1050 px
```

Mobile layout не проектировать.

---

# 4. Вертикальный layout

Страница может иметь небольшой vertical scroll.

Не требуется любой ценой помещать весь dashboard в `1080px` по высоте.

Приоритет:

```text
readability
>
comfortable spacing
>
fit-without-scroll
```

Рекомендуемая структура:

```text
Header
↓
Filters
↓
Total active time
↓
Hero statistics card
↓
Activity section
↓
bottom spacing
```

Ориентировочные вертикальные отступы:

```text
page top → header:          32–48 px
header → filters:           28–36 px
filters → total time:       24–32 px
total time → hero card:     16–24 px
hero card → activity:       24–32 px
activity → page bottom:     40–64 px
```

---

# 5. Typography

Основной шрифт:

```text
Manrope
```

Fallback:

```css
font-family:
    "Manrope",
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
```

Рекомендуемые веса:

```text
400 Regular
500 Medium
600 SemiBold
700 Bold
```

Не использовать слишком много разных размеров.

---

# 6. Типографическая шкала

## App title

```text
TimeTracker
```

Рекомендуемо:

```text
font-size: 44–52 px
font-weight: 700
line-height: 1.05–1.15
```

Цвет:

```text
white
```

Допускается очень мягкая text-shadow для читаемости поверх pink blob:

```css
text-shadow: 0 2px 12px rgba(80, 50, 65, 0.08);
```

---

## Tabs

```text
Основная
Расширенная
```

Рекомендуемо:

```text
font-size: 15–16 px
font-weight: 500
```

Active:

```text
font-weight: 600
```

---

## Filter labels / controls

```text
14–15 px
font-weight: 500
```

---

## KPI label

```text
Общее активное время
```

```text
font-size: 14–15 px
font-weight: 500
```

Цвет muted.

---

## KPI value

Пример:

```text
7 ч. 34 м.
```

```text
font-size: 32–38 px
font-weight: 700
```

---

## Table text

Application name:

```text
15–16 px
font-weight: 500
```

Column headers:

```text
14–15 px
font-weight: 600
```

Time values:

```text
14–15 px
font-weight: 500
```

---

## Section heading

```text
Активность по времени суток
```

```text
font-size: 18–20 px
font-weight: 600
```

---

# 7. Color system

Цвета ниже являются рекомендуемой отправной точкой и могут быть слегка скорректированы при визуальной настройке.

## Background

```css
--bg-base: #FBFAFB;
```

Допустим почти белый:

```text
#FAFAFB
#FBFAFB
#FCFBFC
```

---

## Primary pink

```css
--pink-500: #F16D9F;
```

Дополнительные:

```css
--pink-400: #F58AB2;
--pink-300: #F8A9C5;
--pink-200: #FBC8D9;
--pink-100: #FDE7EF;
```

---

## Text

```css
--text-primary:   #202330;
--text-secondary: #6F7480;
--text-muted:     #989DA7;
```

---

## Neutral UI

```css
--neutral-100: #F4F5F7;
--neutral-200: #E9EBEF;
--neutral-300: #D9DDE4;
```

---

# 8. Background blobs

Фон страницы:

```text
near-white base
+
2–3 very large soft pink circles/blobs
+
strong blur
```

Blob characteristics:

```text
size:        500–900 px
opacity:     0.18–0.35
blur:        120–180 px
```

Blobs желательно частично выносить за пределы viewport.

Примерное расположение:

```text
top-left / top-center
right-center
bottom-left or bottom-center
```

Не использовать чёткие края.

Не делать blob настолько насыщенным, чтобы он мешал читать текст.

---

# 9. Glass surfaces

Основной hero widget:

```css
background: rgba(255, 255, 255, 0.72);
backdrop-filter: blur(24px);
-webkit-backdrop-filter: blur(24px);
```

Радиус:

```text
24–28 px
```

Рекомендуемо:

```text
28 px
```

Shadow:

```css
box-shadow:
    0 18px 50px rgba(65, 35, 50, 0.07);
```

Не использовать заметный border.

При необходимости можно добавить почти незаметный:

```css
border: 1px solid rgba(255,255,255,0.45);
```

но только если карточка теряется на фоне.

---

# 10. Header

Структура:

```text
TimeTracker                              [gear]

Основная    Расширенная
────────
```

Gear располагается справа сверху в пределах основного container.

---

# 11. Settings button

Кнопка:

```text
circular
```

Размер:

```text
44–48 px
```

Рекомендуемо:

```text
46×46 px
```

Стиль:

```css
background: rgba(255,255,255,0.15);
border: 1px solid rgba(255,255,255,0.85);
border-radius: 50%;
```

Иконка:

```text
gear
```

Размер:

```text
18–20 px
```

Цвет:

```text
white / near-white
```

Hover:

```text
background slightly stronger
transform: translateY(-1px)
```

Не использовать scale больше `1.03`.

---

# 12. Tabs

Tabs:

```text
Основная
Расширенная
```

Active tab:

```text
Основная
```

Под активным tab расположен underline.

Underline:

```text
height: 2–3 px
border-radius: 999px
background: primary pink
```

При смене вкладки underline должен плавно перемещаться между tab positions.

Animation:

```text
180–220 ms
ease-out
```

Не использовать fade-out всей страницы.

---

# 13. Empty states для незаполненных вкладок

## Расширенная

Пока вкладка пустая.

Показывать centered empty-state:

```text
Расширенная статистика появится позже
```

Допустима небольшая muted subtitle:

```text
Здесь будут дополнительные метрики и аналитика.
```

---

## Настройки

Пока settings page пустая.

Показывать:

```text
Настройки появятся позже
```

Не показывать полностью пустой экран.

---

# 14. Filter row

Фильтры НЕ должны находиться в отдельной карточке.

Запрещено:

```text
visible border
boxed group
strong background card
```

Элементы объединяются за счёт:

```text
alignment
spacing
consistent vertical center
```

Рекомендуемая структура:

```text
[checkbox] Только активные

[date range]

[time start] ───●━━━━━━━━●─── [time end]

Сбросить

[↻]
```

Все элементы располагаются в одной horizontal row при Full HD.

Gap между смысловыми группами:

```text
28–40 px
```

---

# 15. Только активные

Default:

```text
ON
```

Поведение:

## ON

```text
active_ms > 0
sort by active_ms DESC
progress bar based on active_ms
```

## OFF

```text
show all running apps
sort by running_ms DESC
progress bar based on running_ms
```

Переключатель меняет только таблицу и progress bars. Общее активное время,
timeline и heatmap остаются независимыми от `active_only`.

---

# 16. Checkbox

Размер:

```text
20–22 px
```

Рекомендуемо:

```text
22×22 px
```

Active:

```text
soft pink fill
white check
```

Border-radius:

```text
5–7 px
```

Рекомендуемо:

```text
6 px
```

Hover:

```text
slightly stronger pink
```

Focus outline не обязателен как accessibility feature, но обычный browser focus не должен выглядеть сломанным.

---

# 17. Date range

Один визуальный элемент:

```text
08.09.26–08.09.26
```

Не делить на два отдельных input.

Допускается лёгкая translucent surface:

```css
background: rgba(255,255,255,0.55);
```

Border:

```text
none
```

Radius:

```text
12–16 px
```

Padding:

```text
10–12 px vertical
14–16 px horizontal
```

Иконка calendar слева допустима.

Chevron справа допустим.

---

# 18. Date picker popup

При открытии:

- показывать календарь;
- поддерживать selection range;
- первый click задаёт start;
- второй click задаёт end;
- если второй click по той же дате — выбран один день.

Selected range:

```text
soft pink fill
```

Start/end date:

```text
stronger pink circle / rounded cell
```

Popup:

```text
white / translucent
border-radius: 18–22 px
soft shadow
```

---

# 19. Time range control

Default:

```text
00:00–24:00
```

Структура:

```text
[00:00] ───────●━━━━━━━━━━●────── [24:00]
```

Slider drag step:

```text
15 minutes
```

Exact manual input:

```text
1-minute precision
```

Seconds не используются.

`00:00–24:00` означает `[00:00, 00:00 следующего локального дня)`.
Крайнее правое положение слайдера = 1440 минут (`24:00`), поэтому шаг 15 минут
достигает конца суток без специального округления. Ручное `23:59` означает точную
исключённую границу 23:59, не полный день. `24:00` допускается только для конца.
Одинаковые начало и конец отклоняются как пустой диапазон.
Для ночного диапазона, например `22:00–03:00`, конец относится к следующей дате.

---

# 20. Time input labels

Левое и правое значение:

```text
clickable
```

При click:

- открыть compact time picker;
- либо включить inline editing.

Формат:

```text
HH:MM
```

Пример:

```text
08:07
```

не должен округляться до 15 минут после ручного ввода.

---

# 21. Slider visual style

Track:

```text
height: 4–6 px
```

Unselected:

```text
neutral-200
```

Selected:

```text
soft pink
```

Handles:

```text
14–18 px
round
```

Рекомендуемо:

```text
16 px
```

Selected track может использовать very subtle pink gradient.

---

# 22. Reset action

Текст:

```text
Сбросить
```

Не использовать обычную boxed button.

Стиль:

```text
text action
pink
```

Hover:

```text
underline or slightly darker pink
```

Если фильтры уже default:

```text
disabled / muted
```

Default state:

```text
today
00:00–24:00
Только активные = ON
```

---

# 22.1. Обновление статистики

Рядом со «Сбросить» разместить небольшую icon button `↻` с tooltip «Обновить статистику».
Кнопка использует общий лёгкий стиль controls; кликабельная область около 32–36 px.
Нажатие повторно загружает таблицу, общее активное время и текущую timeline/heatmap,
сохраняя выбранные фильтры и раскрытие «Показать все».

При входе и изменении фильтров запросы выполняются автоматически.
Периодического автообновления в MVP нет. Во время refresh иконка показывает загрузку,
повторный click заблокирован до завершения набора запросов; менять фильтры можно.
Старые данные сохраняются слегка приглушёнными, ошибки отображаются по секциям.

---

# 23. Total active time

Располагается между filters и hero card.

Alignment:

```text
center
```

Структура:

```text
Общее активное время
7 ч. 34 м.
```

Если значение больше 24 часов:

```text
2 д. 14 ч. 38 м.
```

Не использовать отдельную карточку.

Значение получается из системного `ACTIVE`, включая ignored activity и периоды,
когда приложение не удалось определить. Поэтому оно может превышать сумму колонки
«Активно» в таблице. Heatmap использует тот же источник активности.

---

# 24. Hero statistics card

Главный визуальный элемент страницы.

Рекомендуемо:

```text
width: 100%
padding: 24–32 px
border-radius: 28 px
```

Desktop MVP:

```text
10 visible rows
```

До `Показать все`.

---

# 25. Table columns

Визуально:

```text
[rank] [icon] [application] [progress] [Активно] [Запущено]
```

В header показывать только:

```text
Активно
Запущено
```

Не показывать headings:

```text
Приложение
Прогресс
```

---

# 26. Column proportions

Ориентировочно:

```text
rank:          32 px
icon:          36–40 px
application:   190–230 px
progress:      flexible / ~300–380 px
active:        130–150 px
running:       130–150 px
```

На ширине 1280 px строки должны ощущаться просторными.

---

# 27. Application icon

Размер:

```text
24×24 px
```

Не растягивать.

Object fit:

```text
contain
```

Если icon отсутствует:

- pastel circular/rounded-square fallback;
- первая буква display name.

Fallback size:

```text
24×24 px
```

---

# 28. Table row

Высота:

```text
36–42 px
```

Рекомендуемо:

```text
40 px
```

Ряд не должен выглядеть как отдельная карточка.

Разделители:

```text
none
```

Допустим hover background:

```css
rgba(255,255,255,0.30)
```

с очень мягким fade.

---

# 29. Rank

Показывать:

```text
1
2
3
...
10
```

Цвет muted.

Не делать rank визуально доминирующим.

---

# 30. Progress bar

Background:

```text
neutral-200
```

Height:

```text
10–12 px
```

Radius:

```text
999px
```

Fill:

```text
very subtle pink gradient
```

Пример:

```css
background:
linear-gradient(
    90deg,
    #F16D9F 0%,
    #F58AB2 100%
);
```

Градиент должен быть почти незаметным.

---

# 31. Progress normalization

## active_only = ON

```text
bar = active_ms / max(active_ms)
```

## active_only = OFF

```text
bar = running_ms / max(running_ms)
```

Первый элемент:

```text
100%
```

---

# 32. Progress animation

При изменении фильтров / сортировки:

```text
width transition: 250–350 ms
ease-out
```

Не использовать spring.

---

# 33. Time values

Формат:

```text
3 ч. 12 м.
52 м.
2 д. 3 ч. 14 м.
```

Не показывать секунды.

«Запущено» включает время работы приложения в `ACTIVE`, `IDLE`, `LOCKED`.
Время `SLEEP` и промежутки без данных трекера не начисляются.

Если меньше минуты, допустимо:

```text
<1 м.
```

или:

```text
0 м.
```

Рекомендуемо:

```text
<1 м.
```

---

# 34. Row reorder animation

Must-have.

При переключении:

```text
Только активные ON ↔ OFF
```

или при смене date/time filters строки должны плавно менять позиции.

Рекомендуемая длительность:

```text
220–280 ms
```

Easing:

```text
ease-out
```

Stable key:

```text
application_id
```

Нельзя использовать row index как key.

---

# 35. Loading / skeleton

Must-have.

Не показывать skeleton мгновенно на каждый localhost request.

Логика:

```text
request started
↓
150 ms passed?
↓ yes
show skeleton
```

Если response пришёл раньше:

```text
no skeleton flash
```

При обновлении filters желательно:

```text
keep old data
reduce opacity slightly
wait for new result
animate to new state
```

---

# 36. Hero skeleton

Skeleton должен повторять основную структуру card:

```text
10 rows
icon placeholder
name placeholder
progress placeholder
2 time placeholders
```

Использовать soft neutral shimmer или opacity pulse.

Не использовать быстрый сильный shimmer.

---

# 37. Show all

Default:

```text
10 rows
```

Action:

```text
Показать все
```

Расположение:

```text
centered
bottom of hero card
```

Стиль:

```text
subtle pill / text button
```

После раскрытия:

```text
Свернуть
```

Не выполнять новый API request.

---

# 38. Expand animation

Рекомендуемо:

```text
250–300 ms
ease-out
```

Можно использовать:

```text
height transition
+
opacity
```

Не нужно анимировать десятки строк слишком медленно.

---

# 39. Activity section

Располагается ниже hero card.

Heading:

```text
Активность по времени суток
```

Рядом:

```text
info icon
```

Info icon:

```text
16–18 px
muted
```

---

# 40. Activity mode switching

## 1 selected day

Показывать:

```text
single-day timeline
```

## 2–14 selected days

Показывать:

```text
heatmap by exact date × hour
```

## >14 selected days

Показывать:

```text
heatmap by weekday × hour
average activity
```

Переключение происходит автоматически.

---

# 41. Single-day timeline

Главная идея:

```text
one compact horizontal band
```

Не использовать отдельные rows для каждого приложения.

Пример:

```text
08:00      10:00      12:00      14:00

████VSCode██Chrome██░░Idle██Telegram████
```

---

# 42. Timeline dimensions

Высота band:

```text
18–24 px
```

Рекомендуемо:

```text
20 px
```

Radius:

```text
8–12 px
```

Рекомендуемо:

```text
10 px
```

Контейнер:

```text
width: 100%
```

---

# 43. Timeline colors

Application segments:

```text
different muted pastel colors
```

Цель:

```text
визуально различать app switches
```

Не использовать random colors на каждом render.

Цвет должен быть stable в рамках текущего app identity.

---

# 44. Suggested pastel palette

Пример:

```css
--timeline-1: #AFCBFF; /* soft blue */
--timeline-2: #F6A6C1; /* pink */
--timeline-3: #A9DFE8; /* cyan */
--timeline-4: #B9C9F4; /* periwinkle */
--timeline-5: #A8E0C2; /* mint */
--timeline-6: #F6D999; /* pale yellow */
--timeline-7: #B7DCC4; /* soft green */
--timeline-8: #C3B2EE; /* lavender */
--timeline-9: #AAB9CE; /* muted blue-gray */
--timeline-10:#D9C7DD; /* muted lilac */
```

Frontend может вычислять:

```text
palette[hash(application_id) % palette.length]
```

---

# 45. Timeline neutral states

## IDLE

```text
light gray
```

Пример:

```text
#E7E9ED
```

## LOCKED

```text
gray-pink
```

Пример:

```text
#DDD4DA
```

## SLEEP

```text
near-white / very pale gray
```

Пример:

```text
#F0F1F3
```

Можно добавить very subtle hatch только для SLEEP, если без него состояния плохо различаются.

## other_activity

Нейтральный muted color:

```text
#D8DCE3
```

## unknown_activity

Система активна, но foreground-приложение не определено. Нейтральная заливка;
tooltip «Неизвестное приложение». Не приписывать этот интервал соседнему приложению.

## no_data

Прошедший участок без данных трекера — незаполненный участок с тонкой пунктирной
обводкой и tooltip «Нет данных». Визуально отличается от заливки `SLEEP`.
Будущее время остаётся пустым продолжением шкалы и не изображается как сон.

---

# 46. Timeline segment rendering

Сегменты идут вплотную друг к другу.

Это относится к соседним наблюдаемым интервалам. Ширина и положение всех сегментов
определяются timestamps; участки `no_data` сохраняют своё место на шкале.

Не использовать gap между каждой сменой приложения.

Внешний container скрывает overflow:

```css
overflow: hidden;
border-radius: 10px;
```

---

# 47. Timeline time labels

Рекомендуемые labels:

```text
08:00
10:00
12:00
14:00
16:00
18:00
20:00
22:00
```

Если выбран диапазон 00:00–24:00, допустимы:

```text
00:00
04:00
08:00
12:00
16:00
20:00
24:00
```

Frontend может адаптировать density под выбранный interval.

В ночном диапазоне на границе нового локального дня показывать тонкую серую
вертикальную линию и подпись даты, например `09.09 · 00:00`.
Линия накладывается поверх шкалы, не занимает длительность и не создаёт gap.
Tooltip сегмента, переходящего полночь, показывает обе даты вместе со временем.

---

# 48. Timeline tooltip

Must-have.

Application segment:

```text
Visual Studio Code
14:12–15:03 · 51 мин.

database.py — TimeTracker
```

Если title отсутствует:

```text
Visual Studio Code
14:12–15:03 · 51 мин.
```

IDLE:

```text
Нет активности
15:03–15:28 · 25 мин.
```

LOCKED:

```text
Компьютер заблокирован
15:28–16:10 · 42 мин.
```

SLEEP:

```text
Режим сна
16:10–17:20 · 1 ч. 10 мин.
```

Ignored activity:

```text
Другая активность
17:20–17:28 · 8 мин.
```

---

# 49. Tooltip style

```text
dark-ish text
white / near-white background
soft shadow
radius: 10–12 px
padding: 10–12 px
```

Не использовать тёмный tooltip в стиле IDE.

Дизайн должен оставаться в общей soft-light эстетике.

Tooltip delay:

```text
100–150 ms
```

---

# 50. Heatmap 2–14 дней

Rows:

```text
specific dates
```

Columns:

```text
hours
```

Пример:

```text
08.09
09.09
10.09
...
```

Количество hour cells зависит от выбранного time range.

Строка привязана к дате начала выбранного окна. Для строки 08.09 и диапазона
22:00–03:00 колонки идут `22, 23, 00⁺¹, 01⁺¹, 02⁺¹`. `⁺¹` обозначает следующий день.
Tooltip утренней ячейки показывает фактическую дату 09.09; API передаёт `date`
(дату строки), `day_offset`, `local_date`, `hour` и выбранные границы части часа.
Диапазон включает утро после последней выбранной даты, как и backend-фильтр.

---

# 51. Heatmap >14 дней

Rows:

```text
Пн
Вт
Ср
Чт
Пт
Сб
Вс
```

Columns:

```text
hours
```

Значение:

```text
average active time
```

для данного weekday/hour.

Weekday относится к дате начала окна: ночные часы следующего дня остаются в той же
строке с пометкой `⁺¹`. API использует ISO weekday: 1 = Пн, ..., 7 = Вс.
Средняя длительность и интенсивность — разные значения; формулы определены в §53.

Источник активности — system-state `ACTIVE`, тот же, что у общего активного времени.
Ignored activity учитывается; переключатель «Только активные» не меняет heatmap.

---

# 52. Heatmap cell

Форма:

```text
rounded rectangle
```

Radius:

```text
4–6 px
```

Рекомендуемо:

```text
5 px
```

Cell size ориентировочно:

```text
18–26 px
```

Gap:

```text
4–6 px
```

---

# 53. Heatmap intensity

Цвет изменяется непрерывно по:

```text
0.0 → 1.0
```

База:

```text
near-white
```

Максимум:

```text
soft saturated pink
```

Пример interpolation:

```text
#F8F6F7
→
#F16D9F
```

Не использовать 5 резко различающихся discrete colors.

Для конкретной даты: `intensity = active_ms / window_ms`, где window_ms — фактическая
длительность выбранных частей локального часа. Например, 15 минут активности в
выбранных 08:30–09:00 дают 50%, а не 25%.

Повторившийся из-за DST час объединяется в одну ячейку: 90 минут активности из 120
выбранных минут дают 75%. Отсутствующий из-за DST час (`missing_hour`, intensity = null)
имеет нейтральную диагональную штриховку и tooltip «Час отсутствует из-за перевода часов».
Не показывать его как нулевую активность и не сдвигать соседние колонки.

`no_data` обозначается пунктирной обводкой и tooltip «Нет данных трекера»;
`future` — пустой ячейкой с tooltip «Время ещё не наступило».
Известная нулевая активность (например, IDLE или SLEEP) получает обычный нулевой цвет.
При частичном покрытии tooltip показывает tracked_ms и window_ms отдельно.

Для >14 дней: `intensity = total_active_ms / total_window_ms`, а tooltip показывает
`average_active_ms = total_active_ms / sample_days`. API считает эти значения;
frontend не усредняет дневные проценты. Даты без наблюдений входят с нулевой активностью;
полностью отсутствующий DST-час не входит в sample_days. Если знаменатель нулевой,
показывать отсутствие значения, не `0 мин.`. При total_tracked_ms = 0 и существующих
часах обозначать отсутствие данных, а не наблюдаемую нулевую активность.

---

# 54. Heatmap tooltip

Обязательный.

## 2–14 дней

```text
08.09.2026, 14:00–15:00
Активность: 42 мин.
```

## >14 дней

```text
Среда, 14:00–15:00
Средняя активность: 37 мин.
```

---

# 55. Heatmap info tooltip

При hover на `i` рядом с heading:

```text
Для короткого периода показаны конкретные даты.
Для длинного периода — средняя активность по дням недели.
```

Дополнить пояснением: цвет показывает долю активности в выбранной части часа;
пометка `⁺¹` означает следующий день, отсутствующие из-за перевода часов интервалы
не учитываются в среднем.

---

# 56. Activity loading state

Timeline/heatmap могут иметь собственный skeleton.

Рекомендуемо:

```text
single rounded placeholder band
```

для timeline

или:

```text
faint grid placeholders
```

для heatmap.

Не блокировать hero table, если только activity request загружается дольше.

---

# 57. Empty state — no data

Если за выбранный период нет данных:

Hero:

```text
Нет данных за выбранный период
```

Subtitle:

```text
Измените даты или временной диапазон.
```

Activity section:

```text
Нет активности для отображения
```

Не показывать пустую таблицу с десятью blank rows.

Для hero этот вариант определяется `/stats/apps.has_tracking_data = false`,
а не одним только пустым items. Для activity использовать наличие system-state
history: сон/блокировка без ACTIVE остаются данными и отображаются.

---

# 58. Empty state — only active ON

Если `Только активные = ON`, но running data есть, а `active_ms = 0` для всех:

API: `items = []`, `has_running_data = true`. Эти поля приходят вместе с таблицей,
дополнительный запрос без active_only для определения empty state не нужен.

```text
Нет активных приложений за выбранный период
```

Допустима подсказка:

```text
Отключите «Только активные», чтобы увидеть запущенные приложения.
```

Если has_tracking_data = true, но has_running_data = false и items пуст,
показывать «Нет учитываемых приложений за выбранный период» без подсказки отключить
checkbox. Системная активность могла быть с неизвестным/ignored приложением или во сне.

---

# 59. Error state

Если API request завершился ошибкой:

```text
Не удалось загрузить статистику
```

Secondary action:

```text
Повторить
```

Не показывать raw stack trace.

---

# 60. Hover states

Все hover effects должны быть мягкими.

Допустимо:

```text
opacity change
very subtle background
1px translateY
```

Не использовать:

```text
large scale
strong glow
aggressive shadow
```

---

# 61. Motion system

Общее правило:

```text
calm
short
ease-out
```

Recommended durations:

```text
Tab underline:        180–220 ms
Row reorder:          220–280 ms
Progress resize:      250–350 ms
Expand/collapse:      250–300 ms
Tooltip appearance:   100–150 ms
Skeleton fade:        150–200 ms
Hover feedback:       120–180 ms
```

---

# 62. Transition behavior on filter change

При изменении:

```text
date
time
active_only
```

желательно:

1. не очищать UI мгновенно;
2. старые данные немного dim;
3. выполнить request;
4. новые данные вставить;
5. строки reorder animation;
6. progress bars resize animation;
7. activity visualization обновить.

---

# 63. Filter state persistence

Для MVP допустимо:

```text
не сохранять filters между browser sessions
```

Default при reload:

```text
today
00:00–24:00
Только активные = ON
```

В POST-MVP можно добавить persistence.

---

# 64. Application naming

Frontend показывает:

```text
application.name
```

Не использовать:

```text
exe_name
path
```

в основной таблице.

Path может появиться только в future settings/debug view.

---

# 65. Long application names

При длинном имени:

```text
single line
ellipsis
```

Пример:

```css
white-space: nowrap;
overflow: hidden;
text-overflow: ellipsis;
```

Tooltip с полным названием допускается.

---

# 66. Long window titles

В timeline tooltip:

```text
max-width: 320–420 px
```

Window title:

```text
max 2–3 lines
```

Длинный title обрезать с ellipsis.

Не растягивать tooltip на пол-экрана.

---

# 67. Number formatting

Формат durations должен быть единым во всём UI.

Примеры:

```text
12 м.
1 ч. 08 м.
7 ч. 34 м.
2 д. 14 ч. 38 м.
```

Рекомендуется избегать ведущего нуля у часов:

```text
1 ч. 8 м.
```

а не:

```text
01 ч. 08 м.
```

---

# 68. Date formatting

Main date filter:

```text
DD.MM.YY–DD.MM.YY
```

Пример:

```text
08.09.26–14.09.26
```

Heatmap tooltip:

```text
DD.MM.YYYY
```

---

# 69. Time formatting

Всегда:

```text
HH:MM
```

24-hour format.

---

# 70. Z-index layering

Recommended order:

```text
background blobs
content
hero/activity cards
dropdowns
tooltips
date picker
```

Tooltips и popup не должны обрезаться card overflow.

---

# 71. Dashboard page structure

Рекомендуемая component tree:

```text
DashboardPage
├── BackgroundBlobs
├── Header
│   ├── Brand
│   ├── Tabs
│   └── SettingsButton
├── FiltersRow
│   ├── ActiveOnlyCheckbox
│   ├── DateRangePicker
│   ├── TimeRangeControl
│   ├── ResetAction
│   └── RefreshButton
├── TotalActiveTime
├── StatsCard
│   ├── StatsHeader
│   ├── AppRows
│   └── ShowAllAction
└── ActivitySection
    ├── ActivityHeading
    ├── InfoTooltip
    └── ActivityVisualization
        ├── DayTimeline
        └── Heatmap
```

---

# 72. Frontend state model

Минимально:

```text
selectedDateFrom
selectedDateTo
selectedTimeFrom
selectedTimeTo
activeOnly
expanded
activeTab
settingsOpen
```

Async state:

```text
appsLoading
systemLoading
activityLoading
appsError
systemError
activityError
appsGeneration
systemGeneration
activityGeneration
refreshing
```

---

# 73. Main data endpoints

Ожидается использование:

```text
GET /stats/apps
GET /stats/system
GET /stats/timeline
GET /stats/activity
GET /applications/{id}/icon
```

`/stats/apps` возвращает объект `{has_tracking_data, has_running_data, items}`.
Строки, порядок и нормализация progress bars берутся из `items`.
Backend также предоставляет PATCH `/applications/{id}` для ignored/track_titles;
settings view в MVP остаётся заглушкой, дополнительные controls в dashboard не нужны.

---

# 74. API request strategy

При изменении filters:

```text
apps stats
system stats
activity visualization
```

можно загружать параллельно.

Для одного дня:

```text
/stats/timeline
```

Для нескольких:

```text
/stats/activity
```

Не запрашивать оба одновременно без необходимости.

Первый вход, смена date/time/timezone и кнопка `↻` загружают apps, system и текущий
activity endpoint. Смена одного active_only перезапрашивает только apps.
Периодический refresh timer не используется.

Для apps/system/activity вести отдельные generation IDs. Перед новым запросом или
инвалидацией данных увеличить ID соответствующей секции. Применять success/error
только при совпадении ID и актуальных параметров; поздний ответ не возвращает старые
фильтры, ошибку или режим timeline/heatmap. AbortController допустим дополнительно,
но проверки ID нужны и при неудавшейся отмене. Active-only не инвалидирует system/activity.
Refresh повторяет и успешные, и ранее завершившиеся ошибкой запросы.

---

# 75. Debounce

Checkbox:

```text
no debounce
```

Date picker:

```text
request only after complete range selected
```

Time slider:

Во время drag не отправлять request на каждое движение.

Рекомендуемо:

```text
request on pointer release
```

Manual time input:

```text
request after valid value confirmed
```

---

# 76. Time slider interaction

Slider:

```text
15-minute step
```

При dragging показывать current handle time рядом/над handle.

После release обновлять stats.

---

# 77. Date picker behavior

Selection:

```text
first click  = start
second click = end
```

Если:

```text
same date twice
```

выбран один день.

После выбора второго значения popup можно закрывать автоматически.

---

# 78. Settings navigation

Gear открывает settings view.

Допустимые варианты:

```text
route
or
internal view state
```

Рекомендуемо route:

```text
/settings
```

Dashboard:

```text
/
```

Advanced:

```text
/advanced
```

---

# 79. Advanced tab

Пока empty state.

Active tab underline должен корректно переходить на:

```text
Расширенная
```

---

# 80. Scroll behavior

Small page scroll допустим.

Не использовать nested scroll внутри hero card для первых версий.

`Показать все` увеличивает высоту страницы естественным образом.

---

# 81. Desktop target

Основной target:

```text
1920×1080
```

Допускается нормальная работа на desktop widths:

```text
1366–2560 px
```

Но отдельная mobile/tablet adaptation не требуется.

---

# 82. Minimum desktop behavior

Если viewport становится слишком узким:

```text
min-width page
```

и допустим horizontal browser scroll.

Лучше сохранить desktop layout, чем ломать таблицу ради mobile adaptation.

---

# 83. Performance

Frontend должен:

- не rerender-ить все строки без необходимости;
- использовать stable keys;
- кешировать icon requests браузером;
- не отправлять stats request при каждом slider pixel movement;
- не перерисовывать background blobs тяжёлыми canvas-анимациями.

Background blobs должны быть обычным CSS.

---

# 84. Accessibility scope

Специальная accessibility-версия не требуется.

Не нужно отдельно реализовывать:

```text
screen reader optimization
large-text mode
keyboard-only full navigation audit
high-contrast theme
ARIA-heavy custom navigation
```

При этом стандартные HTML controls не следует намеренно ломать.

---

# 85. Do not add in MVP UI

Не добавлять:

- search по приложениям;
- manual sorting dropdown;
- column sorting;
- productivity score;
- charts кроме timeline/heatmap;
- KPI cards grid;
- donut/pie charts;
- mobile navigation;
- onboarding flow;
- dark theme;
- color customization;
- user accounts;
- cloud status;
- export UI;
- advanced settings controls.

---

# 86. MVP acceptance criteria — UI

UI считается готовым, если:

1. Страница визуально соответствует calm semi-premium pink/white стилю.
2. Main container имеет `max-width: 1280px` и desktop width около `66–68vw`.
3. Используется Manrope.
4. Header содержит `TimeTracker`, tabs и settings gear.
5. Active tab имеет animated underline.
6. Filter row не оформлен как отдельная bordered card.
7. `Только активные` по умолчанию включён.
8. Date range отображается единым field.
9. Default time range = `00:00–24:00`.
10. Slider step = 15 минут.
11. Ручной time input поддерживает точность до минуты.
12. `Сбросить` возвращает default filters.
13. Перед hero card отображается `Общее активное время`.
14. Hero card показывает 10 строк по умолчанию.
15. В таблице есть только headers `Активно` и `Запущено`.
16. App icons отображаются в `24×24 px`.
17. Progress bars используют subtle pink gradient.
18. При `active_only=true` bar/sort основаны на active time.
19. При `active_only=false` bar/sort основаны на running time.
20. Row reorder анимируется.
21. Progress width анимируется.
22. Skeleton не мигает на быстрых localhost requests.
23. `Показать все` раскрывает локально уже полученный список.
24. Один день показывает compact single-row timeline.
25. Timeline использует разные pastel colors для приложений.
26. IDLE/LOCKED/SLEEP используют neutral colors.
27. Timeline segment имеет tooltip.
28. 2–14 дней показывают heatmap по конкретным датам.
29. >14 дней показывают weekday/hour average heatmap.
30. Heatmap cell radius = `4–6 px`.
31. Heatmap имеет обязательный tooltip.
32. Heatmap info icon объясняет режимы агрегации.
33. Empty/loading/error states выглядят аккуратно.
34. Небольшой vertical scroll допустим.
35. Mobile layout не требуется.
36. Полный день включает последнюю минуту суток; крайняя правая граница = `24:00`.
37. Сон не добавляет время в колонку «Запущено».
38. Пропуски данных и неопределённый foreground отображаются отдельно от сна.
39. Ночной timeline отмечает полночь серой линией и новой датой без изменения длительностей.
40. `active_only` меняет только таблицу; KPI и heatmap считают системный `ACTIVE`.
41. Ночные heatmap rows привязаны к дате/weekday начала окна, часы следующего дня помечены `⁺¹`.
42. Интенсивность нормализуется по выбранной длительности; отсутствующий/повторяющийся DST-час обработан явно.
43. Heatmap различает известный ноль, no_data, future и отсутствующий DST-час.
44. Кнопка `↻` обновляет статистику без сброса фильтров; периодического auto-refresh нет.
45. Устаревшие responses/errors игнорируются; empty states используют metadata flags API.

---

# 87. Рекомендуемые design tokens

```css
:root {
    --font-main: "Manrope", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;

    --bg-base: #FBFAFB;

    --pink-500: #F16D9F;
    --pink-400: #F58AB2;
    --pink-300: #F8A9C5;
    --pink-200: #FBC8D9;
    --pink-100: #FDE7EF;

    --text-primary: #202330;
    --text-secondary: #6F7480;
    --text-muted: #989DA7;

    --neutral-100: #F4F5F7;
    --neutral-200: #E9EBEF;
    --neutral-300: #D9DDE4;

    --glass-bg: rgba(255,255,255,0.72);

    --radius-card: 28px;
    --radius-control: 14px;
    --radius-cell: 5px;

    --shadow-card: 0 18px 50px rgba(65, 35, 50, 0.07);

    --motion-fast: 150ms;
    --motion-medium: 240ms;
    --motion-slow: 320ms;
}
```

---

# 88. Итоговый UX-принцип

Главная страница должна за несколько секунд отвечать на три вопроса:

```text
1. Сколько времени я реально был активен?
2. В каких приложениях я провёл это время?
3. Когда в течение дня/периода происходила активность?
```

Интерфейс не должен отвлекать от этих трёх задач дополнительной аналитикой.
