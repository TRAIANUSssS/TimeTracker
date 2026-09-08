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
  await page.clock.setFixedTime(new Date("2026-09-08T22:00:00+03:00"));
  const counts = { apps: 0, system: 0, timeline: 0, activity: 0 };
  await page.route("**/applications/*/icon", (route) =>
    route.fulfill({ status: 404, body: "" }),
  );
  await page.route("**/stats/**", async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname.split("/").pop()!;
    counts[path]++;
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
    page.getByText("До следующего дня", { exact: true }),
  ).toBeVisible();
  const n = counts.apps;
  await page.getByLabel("Конец времени", { exact: true }).fill("25:00");
  await page.getByLabel("Конец времени", { exact: true }).press("Enter");
  await expect(page.getByRole("alert")).toContainText("Введите время");
  expect(counts.apps).toBe(n);
});
test("delayed skeleton, section failure retry, empty metadata and placeholder navigation", async ({
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
  await expect(
    page.getByText("Расширенная статистика появится позже"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await expect(page.getByText("Настройки появятся позже")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Настройки появятся позже")).toBeVisible();
  await page.getByRole("button", { name: "Вернуться на основную" }).click();
  await expect(page.getByLabel("Начало времени", { exact: true })).toHaveValue(
    "00:00",
  );
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
