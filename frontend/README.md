# Web-интерфейс TimeTracker

React 19 + TypeScript + Vite, по [UI-спецификации](../time_tracker_ui_spec.md).
Manrope и все ресурсы обслуживаются локально. В production нет внешних CDN,
аналитики или демонстрационных данных. Mock-история используется только в тестах.

Из корня проекта (Node.js 22.12+):

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m time_tracker --track
```

Dashboard: http://127.0.0.1:8765/. Для разработки с HMR после запуска Python:

```powershell
npm.cmd --prefix frontend run dev
```

Vite на `127.0.0.1:5173` проксирует `/stats` и `/applications` на локальный API.
В production FastAPI раздаёт `dist`, прокси не используется.

`src/controls.tsx` — календарь и точное время; `Table.tsx` — таблица и FLIP;
`Activity.tsx` — timeline, heatmap, tooltips; `requests.ts` — отдельные поколения
запросов apps/system/activity, отмена и задержка skeleton 150 ms. `styles.css`
содержит desktop-оформление. Данные статистики не пересчитываются на frontend.

Проверки:

```powershell
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend test
```

Playwright по умолчанию использует установленный Microsoft Edge в headless-режиме.
Другой установленный канал задаётся `PLAYWRIGHT_CHANNEL`, например `chrome`.
Проверяются фильтры, раскрытие/refresh, переключение режимов, ошибки, stale responses,
ночная полночь, DST-ячейки и desktop 1920/1366. Скриншоты — `frontend/test-results/`.
`tests/packaged-browser.mjs` вызывается из отдельного Python smoke собранного exe:
он работает с настоящим API и запрещает запросы на внешние адреса.
