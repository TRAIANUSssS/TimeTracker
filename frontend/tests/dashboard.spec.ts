import { expect, test } from "@playwright/test";

const base = Date.parse("2026-09-08T00:00:00+03:00");
const appNames = [
  "Visual Studio Code",
  "Google Chrome",
  "Telegram",
  "Cities: Skylines II",
  "PyCharm",
  "Проводник",
  "Spotify",
  "Discord",
  "Steam",
  "Notion",
  "Windows Terminal",
  "Obsidian",
];
const rows = appNames.map((name, i) => ({
  application_id: i + 1,
  name,
  active_ms: Math.max(60000, 11520000 / (i + 1) ** 1.65),
  running_ms: 12480000 + i * 480000,
  icon_url: `/applications/${i + 1}/icon`,
}));
const segments = [
  { type: "no_data", started_at: base, ended_at: base + 8 * 3600000 },
  ...Array.from({ length: 48 }, (_, i) => ({
    type: i % 7 === 0 ? "idle" : i % 13 === 0 ? "sleep" : "application",
    application_id: i % 7 === 0 || i % 13 === 0 ? undefined : (i % 10) + 1,
    name: i % 7 === 0 || i % 13 === 0 ? undefined : appNames[i % 10],
    title: i % 7 === 0 ? undefined : "database.py — TimeTracker",
    started_at: base + (8 + i / 4) * 3600000,
    ended_at: base + (8 + (i + 1) / 4) * 3600000,
  })),
];

async function fixture(page) {
  await page.route("**/settings/preferences", (route) =>
    route.fulfill({
      json: {
        display: {
          time_units: { days: true, hours: true, minutes: true },
          personal_day_start: "00:00",
          timezone: "Europe/Moscow",
        },
        recording: { tracking_paused: false, autostart: false },
        onboarding_completed: true,
      },
    }),
  );
  await page.route("**/settings/collection", (route) =>
    route.fulfill({
      json: {
        mode: "polling",
        active_mode: "polling",
        effective_mode: "polling",
        installed: false,
        can_install: true,
        busy: false,
        error: null,
        restart_required: false,
        external: false,
        token: "test-token",
      },
    }),
  );
  await page.clock.setFixedTime(new Date("2026-09-08T22:00:00+03:00"));
  const counts: Record<string, number> = {
    apps: 0,
    system: 0,
    timeline: 0,
    activity: 0,
    kpi: 0,
    weekly: 0,
    dynamics: 0,
    transitions: 0,
  };
  await page.route("**/applications/*/icon", (route) =>
    route.fulfill({ status: 404, body: "" }),
  );
  await page.route("**/stats/**", async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname.split("/").pop()!;
    counts[path]++;
    if (url.pathname.includes("/stats/advanced/")) {
      if (path === "kpi")
        return route.fulfill({
          json: {
            has_tracking_data: true,
            context_switches: 184,
            context_switches_per_active_hour: 24.3,
            longest_focus: {
              duration_ms: 6420000,
              started_at: base,
              ended_at: base + 6420000,
              application: {
                id: 1,
                name: appNames[0],
                icon_url: "/applications/1/icon",
              },
            },
            average_active_per_day_ms: 19080000,
            comparison: {
              has_tracking_data: true,
              previous_context_switches: 209,
              context_switches_change_percent: -12,
              previous_switches_per_active_hour: 26.1,
              previous_average_active_per_day_ms: 17460000,
            },
          },
        });
      if (path === "weekly") {
        const start = Date.parse(
            `${url.searchParams.get("date_from")}T00:00:00Z`,
          ),
          end = Date.parse(`${url.searchParams.get("date_to")}T00:00:00Z`),
          selectedDays = Math.round((end - start) / 86400000) + 1,
          chartStart = selectedDays === 1 ? start - 6 * 86400000 : start,
          chartDays = selectedDays === 1 ? 7 : selectedDays;
        return route.fulfill({
          json: {
            mode: selectedDays <= 7 ? "week" : "weekday_average",
            days:
              selectedDays <= 7
                ? Array.from({ length: chartDays }, (_, index) => {
                    const date = new Date(chartStart + index * 86400000),
                      active = (4 + ((index * 7) % 4)) * 3600000;
                    return {
                      weekday: ((date.getUTCDay() + 6) % 7) + 1,
                      date: date.toISOString().slice(0, 10),
                      active_ms: active,
                      tracked_ms: 8 * 3600000,
                      status: "data",
                    };
                  })
                : Array.from({ length: 7 }, (_, index) => ({
                    weekday: index + 1,
                    average_active_ms: (4 + ((index * 7) % 4)) * 3600000,
                    sample_days: 4,
                  })),
            previous_period_average_ms: 16680000,
          },
        });
      }
      if (path === "dynamics") {
        const start = Date.parse(
            `${url.searchParams.get("date_from")}T00:00:00Z`,
          ),
          end = Date.parse(`${url.searchParams.get("date_to")}T00:00:00Z`),
          selectedDays = Math.round((end - start) / 86400000) + 1;
        if (selectedDays === 1)
          return route.fulfill({
            json: {
              granularity: "hour",
              points: Array.from({ length: 24 }, (_, hour) => ({
                start: `${url.searchParams.get("date_from")}T${String(hour).padStart(2, "0")}:00`,
                end: `${url.searchParams.get("date_from")}T${String(hour + 1).padStart(2, "0")}:00`,
                label: `${String(hour).padStart(2, "0")}:00`,
                end_label: `${String((hour + 1) % 24).padStart(2, "0")}:00`,
                active_ms: (20 + ((hour * 7) % 38)) * 60000,
                total_active_ms: (20 + ((hour * 7) % 38)) * 60000,
                average_per_day_ms: null,
                sample_days: 1,
                status: "data",
              })),
            },
          });
        return route.fulfill({
          json: {
            granularity: "day",
            points: Array.from({ length: selectedDays }, (_, index) => {
              const pointStart = new Date(start + index * 86400000),
                pointEnd = new Date(start + (index + 1) * 86400000),
                active = (4 + ((index * 5) % 4)) * 3600000;
              return {
                start: pointStart.toISOString().slice(0, 10),
                end: pointEnd.toISOString().slice(0, 10),
                active_ms: active,
                total_active_ms: active,
                average_per_day_ms: active,
                sample_days: 1,
                status: "data",
              };
            }),
          },
        });
      }
      if (path === "apps")
        return route.fulfill({
          json: {
            has_tracking_data: true,
            items: rows.map((row, index) => ({
              ...row,
              color: null,
              usage_ratio: row.active_ms / row.running_ms,
              launch_count: 18 + index,
              average_session_ms: 640000 - index * 12000,
              max_session_ms: 6420000 - index * 120000,
            })),
          },
        });
      const allApplications = appNames.map((name, index) => ({
          id: index + 1,
          name,
          icon_url: `/applications/${index + 1}/icon`,
          color: null,
          participation: 100 - index,
        })),
        requested = url.searchParams.getAll("application_ids").map(Number),
        selected = requested.length
          ? requested.map((id) => allApplications[id - 1])
          : allApplications.slice(0, 10),
        pairs = selected.slice(0, -1).map((app, index) => ({
          from_application_id: app.id,
          to_application_id: selected[index + 1].id,
          count: 47 - index * 3,
        }));
      return route.fulfill({
        json: {
          has_tracking_data: true,
          top_transitions: [
            { from_application_id: 1, to_application_id: 2, count: 47 },
            { from_application_id: 2, to_application_id: 1, count: 39 },
            { from_application_id: 1, to_application_id: 5, count: 31 },
          ],
          default_applications: allApplications.slice(0, 10),
          selected_applications: selected,
          applications: allApplications,
          matrix: pairs,
        },
      });
    }
    if (path === "apps")
      return route.fulfill({
        json: {
          has_tracking_data: true,
          has_running_data: true,
          items:
            url.searchParams.get("active_only") === "false"
              ? [...rows].reverse()
              : rows,
        },
      });
    if (path === "system")
      return route.fulfill({
        json: {
          active_ms: 27240000,
          idle_ms: 600000,
          locked_ms: 1200000,
          sleep_ms: 3600000,
        },
      });
    if (path === "timeline")
      return route.fulfill({
        json: segments,
        headers: {
          "X-TimeTracker-Windows": JSON.stringify([[base, base + 86400000]]),
        },
      });
    const start = Date.parse(url.searchParams.get("date_from")!),
      end = Date.parse(url.searchParams.get("date_to")!),
      days = (end - start) / 86400000 + 1;
    return route.fulfill({
      json: Array.from({ length: days > 14 ? 7 : days }, (_, d) =>
        Array.from({ length: 24 }, (_, hour) =>
          days > 14
            ? {
                weekday: d + 1,
                day_offset: 0,
                hour,
                local_time_from: `${String(hour).padStart(2, "0")}:00`,
                local_time_to: `${String(hour + 1).padStart(2, "0")}:00`,
                sample_days: 3,
                total_active_ms: 1800000,
                total_window_ms: 10800000,
                total_tracked_ms: 10800000,
                average_active_ms: 600000,
                intensity: ((hour + d) % 9) / 9,
              }
            : {
                date: new Date(start + d * 86400000).toISOString().slice(0, 10),
                local_date: new Date(start + d * 86400000)
                  .toISOString()
                  .slice(0, 10),
                day_offset: 0,
                hour,
                local_time_from: `${String(hour).padStart(2, "0")}:00`,
                local_time_to: `${String(hour + 1).padStart(2, "0")}:00`,
                hour_occurrences: 1,
                active_ms: 1800000,
                window_ms: 3600000,
                tracked_ms: 3600000,
                status: "data",
                intensity: ((hour + d) % 9) / 9,
              },
        ).flat(),
      ).flat(),
    });
  });
  return counts;
}
test("reference layout, expand, independent checkbox and preserved refresh", async ({
  page,
}) => {
  const counts = await fixture(page);
  await page.goto("/");
  await expect(page.getByText("7 ч. 34 м.", { exact: true })).toBeVisible();
  await expect(page.getByTestId("app-row")).toHaveCount(10);
  const before = { ...counts };
  await page.getByRole("button", { name: "Показать все" }).click();
  await expect(page.getByTestId("app-row")).toHaveCount(12);
  expect(counts).toEqual(before);
  await page.getByLabel("Только активные", { exact: true }).uncheck();
  await expect(page.getByTestId("app-row").first()).toContainText("Obsidian");
  expect(counts.system).toBe(before.system);
  expect(counts.timeline).toBe(before.timeline);
  await page.getByRole("button", { name: "Обновить статистику" }).click();
  await expect(
    page.getByRole("button", { name: "Обновить статистику" }),
  ).toBeEnabled();
  await expect(page.getByTestId("app-row")).toHaveCount(12);
  expect(counts.system).toBe(before.system + 1);
  await page.getByLabel("Только активные", { exact: true }).check();
  await expect(page.getByTestId("app-row").first()).toContainText(
    "Visual Studio Code",
  );
  await page.getByRole("button", { name: "Свернуть", exact: true }).click();
  await page.waitForTimeout(350); // Capture the settled collapse/reorder animation.
  await page.screenshot({
    path: "test-results/dashboard-1920.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1366, height: 900 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("date range completes on second click, switches heatmap modes, exact minute and reset", async ({
  page,
}) => {
  const counts = await fixture(page);
  await page.goto("/");
  await expect(page.getByTestId("timeline")).toBeVisible();
  await page.getByRole("button", { name: "Выбрать диапазон дат" }).click();
  const before = counts.activity;
  await page.getByRole("button", { name: "2026-09-01", exact: true }).click();
  expect(counts.activity).toBe(before);
  await page.getByRole("button", { name: "2026-09-08", exact: true }).click();
  await expect(page.getByTestId("heatmap")).toHaveAttribute(
    "data-mode",
    "dates",
  );
  await page.getByRole("button", { name: "Выбрать диапазон дат" }).click();
  await page.getByRole("button", { name: "Последние 30 дней" }).click();
  await expect(page.getByTestId("heatmap")).toHaveAttribute(
    "data-mode",
    "weekdays",
  );
  await page.screenshot({
    path: "test-results/heatmap-1920.png",
    fullPage: true,
  });
  const request = page.waitForRequest(
    (r) => r.url().includes("/stats/apps?") && r.url().includes("08%3A07"),
  );
  await page.getByLabel("Начало времени", { exact: true }).fill("08:07");
  await page.getByLabel("Начало времени", { exact: true }).press("Enter");
  await request;
  await expect(page.getByLabel("Начало времени", { exact: true })).toHaveValue(
    "08:07",
  );
  await page.getByRole("button", { name: "Сбросить", exact: true }).click();
  await expect(page.getByLabel("Конец времени", { exact: true })).toHaveValue(
    "24:00",
  );
  await expect(page.getByTestId("timeline")).toBeVisible();
});
test("time slider commits on release, supports night range, rejects invalid text", async ({
  page,
}) => {
  const counts = await fixture(page);
  await page.goto("/");
  await expect(page.getByTestId("timeline")).toBeVisible();
  const thumb = page.getByLabel("Начало диапазона", { exact: true }),
    box = await thumb.boundingBox();
  const before = counts.apps;
  await page.mouse.move(box!.x + 8, box!.y + 15);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.4, box!.y + 15);
  expect(counts.apps).toBe(before);
  await page.mouse.up();
  await expect.poll(() => counts.apps).toBe(before + 1);
  await page.getByLabel("Начало времени", { exact: true }).fill("22:00");
  await page.getByLabel("Начало времени", { exact: true }).press("Enter");
  await page.getByLabel("Конец времени", { exact: true }).fill("03:00");
  await page.getByLabel("Конец времени", { exact: true }).press("Enter");
  await expect(
    page.getByText("Конец — на следующий день", { exact: true }),
  ).toBeVisible();
  const n = counts.apps;
  await page.getByLabel("Конец времени", { exact: true }).fill("25:00");
  await page.getByLabel("Конец времени", { exact: true }).press("Enter");
  await expect(page.getByRole("alert")).toContainText("Введите время");
  expect(counts.apps).toBe(n);
});
test("delayed skeleton, section failure retry, empty metadata and advanced navigation", async ({
  page,
}) => {
  await fixture(page);
  let release: () => void = () => {};
  const pending = new Promise<void>((r) => (release = r));
  await page.route("**/stats/apps?**", async (route) => {
    await pending;
    await route.fulfill({ status: 503, body: "unavailable" });
  });
  await page.goto("/");
  await expect(page.getByLabel("Загрузка приложений")).toBeVisible();
  release();
  await expect(page.getByRole("alert")).toContainText("Не удалось загрузить");
  await page.unroute("**/stats/apps?**");
  await page.route("**/stats/apps?**", (route) =>
    route.fulfill({
      json: { has_tracking_data: true, has_running_data: true, items: [] },
    }),
  );
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(
    page.getByText("Нет активных приложений за выбранный период", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Расширенная", exact: true }).click();
  await expect(page.getByText("Переключения", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Приложения и приватность",
      exact: true,
    }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", {
      name: "Приложения и приватность",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Основная", exact: true }).click();
  await expect(page.getByLabel("Начало времени", { exact: true })).toHaveValue(
    "00:00",
  );
});

test("advanced analytics layout, details, matrix picker and shared filters", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/advanced");
  await expect(page.getByText("184", { exact: true })).toBeVisible();
  await expect(page.getByTestId("advanced-weekly-chart")).toBeVisible();
  await expect(page.getByTestId("advanced-dynamics-chart")).toBeVisible();
  await expect(page.locator(".weekly-slot.data")).toHaveCount(7);
  await expect(page.locator(".weekly-slot.selected")).toHaveCount(1);
  await expect(page.locator(".dynamics-labels > span")).toHaveCount(24);
  await page.screenshot({
    path: "test-results/advanced-one-day-1920.png",
    fullPage: true,
  });
  await expect(page.getByTestId("advanced-app-row")).toHaveCount(10);
  await expect(
    page.getByLabel("Только активные", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page
      .locator(".advanced-filters")
      .getByLabel("Конец времени", { exact: true }),
  ).toHaveValue("24:00");
  await page.getByRole("button", { name: "Выбрать диапазон дат" }).click();
  await page.getByRole("button", { name: "Последние 7 дней" }).click();
  await expect(page.locator(".weekly-slot.data")).toHaveCount(7);
  await page.screenshot({
    path: "test-results/advanced-applications-1920.png",
    fullPage: true,
  });

  await page.getByRole("tab", { name: "Переходы" }).click();
  await expect(page.getByText("Самые частые переходы")).toBeVisible();
  await expect(page.locator(".matrix-cell")).toHaveCount(100);
  await page
    .getByRole("button", { name: "Заменить Visual Studio Code" })
    .first()
    .click();
  await page.getByPlaceholder("Поиск приложения...").fill("Windows Terminal");
  await page
    .getByRole("dialog", { name: "Выбор приложения" })
    .getByRole("button")
    .filter({ hasText: "Windows Terminal" })
    .click();
  await expect(
    page.getByRole("button", { name: "Сбросить к топ-10" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Сбросить к топ-10" }).click();
  await expect(
    page.getByRole("button", { name: "Сбросить к топ-10" }),
  ).toHaveCount(0);

  await page.screenshot({
    path: "test-results/advanced-1920.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1366, height: 900 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("generation rejects old success and error even when cancellation is ignored", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  const committed = await page.evaluate(async () => {
    const { LatestRequest } = await import("/src/requests.ts");
    const gate = new LatestRequest(),
      values: string[] = [];
    let oldResolve: (v: string) => void = () => {},
      oldReject: (e: Error) => void = () => {};
    const first = gate.run(
      () => new Promise<string>((r) => (oldResolve = r)),
      (v) => values.push(v),
      () => values.push("old error"),
    );
    await gate.run(
      async () => "new",
      (v) => values.push(v),
      () => values.push("error"),
    );
    oldResolve("old");
    await first;
    const second = gate.run(
      () => new Promise<string>((_, r) => (oldReject = r)),
      (v) => values.push(v),
      () => values.push("old error"),
    );
    await gate.run(
      async () => "newest",
      (v) => values.push(v),
      () => values.push("error"),
    );
    oldReject(new Error("stale"));
    await second;
    return values;
  });
  expect(committed).toEqual(["new", "newest"]);
});

test("night marker preserves real duration and tooltip includes both dates", async ({
  page,
}) => {
  await fixture(page);
  const start = base + 22 * 3600000,
    end = base + 27 * 3600000;
  await page.route("**/stats/timeline?**", (route) =>
    route.fulfill({
      json: [
        {
          type: "application",
          application_id: 1,
          name: "Visual Studio Code",
          title: "Across midnight",
          started_at: start,
          ended_at: end,
        },
      ],
      headers: { "X-TimeTracker-Windows": JSON.stringify([[start, end]]) },
    }),
  );
  await page.goto("/");
  await expect(page.getByTestId("midnight-marker")).toBeVisible();
  await expect(page.getByTestId("midnight-marker")).toContainText(
    "09.09 · 00:00",
  );
  const width = await page
    .locator(".timeline-segment.application")
    .evaluate((e) => (e as HTMLElement).style.width);
  expect(width).toBe("100%");
  await page.locator(".timeline-segment.application").hover();
  await expect(page.getByRole("tooltip")).toContainText("08.09");
  await expect(page.getByRole("tooltip")).toContainText("09.09");
  await expect(page.getByRole("tooltip")).toContainText("5 ч.");
});

test("heatmap differentiates missing, future, no data, partial and repeated hours", async ({
  page,
}) => {
  await fixture(page);
  const cells = ["missing_hour", "future", "no_data", "data", "data"].map(
    (status, hour) => ({
      date: "2026-09-08",
      local_date: "2026-09-08",
      hour,
      day_offset: 0,
      local_time_from: `0${hour}:00`,
      local_time_to: `0${hour + 1}:00`,
      hour_occurrences: hour === 0 ? 0 : hour === 4 ? 2 : 1,
      active_ms: hour === 4 ? 5400000 : hour === 3 ? 900000 : 0,
      window_ms: hour === 0 ? 0 : hour === 4 ? 7200000 : 1800000,
      tracked_ms: hour < 3 ? 0 : hour === 3 ? 900000 : 7200000,
      intensity: hour === 0 ? null : hour === 3 ? 0.5 : hour === 4 ? 0.75 : 0,
      status,
    }),
  );
  await page.route("**/stats/activity?**", (route) =>
    route.fulfill({ json: cells }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Выбрать диапазон дат" }).click();
  await page.getByRole("button", { name: "Последние 7 дней" }).click();
  await expect(page.locator(".heat-cell")).toHaveCount(5);
  for (const [status, text] of [
    ["missing_hour", "Час отсутствует"],
    ["future", "Время ещё не наступило"],
    ["no_data", "Нет данных трекера"],
  ]) {
    await page.locator(`.heat-cell.${status}`).hover();
    await expect(page.getByRole("tooltip")).toContainText(text);
  }
  await page.locator(".heat-cell.data").first().hover();
  await expect(page.getByRole("tooltip")).toContainText(
    "Известно: 15 м. из 30 м.",
  );
  await page.locator(".heat-cell.data").last().hover();
  await expect(page.getByRole("tooltip")).toContainText("Час повторился");
  await expect(page.getByRole("tooltip")).toContainText("1 ч. 30 м.");
});
