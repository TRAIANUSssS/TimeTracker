import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test("application load error retries to an empty catalogue", async ({
  page,
}) => {
  await setup(page);
  let fail = true;
  await page.route(/\/applications$/, (route) =>
    fail
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({ json: [] }),
  );
  await page.goto("/settings");
  await expect(page.getByRole("alert")).toContainText(
    "Не удалось загрузить настройки",
  );
  fail = false;
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(
    page.getByText("Приложения пока не обнаружены", { exact: true }),
  ).toBeVisible();
});

async function setup(page: Page) {
  const preferences = {
    display: {
      time_units: { days: true, hours: true, minutes: true },
      personal_day_start: "00:00",
      timezone: "Europe/Moscow",
    },
    recording: { tracking_paused: false, autostart: false },
  };
  const apps = [
    "Google Chrome",
    "Firefox",
    "Visual Studio Code",
    "Telegram Desktop",
    "PyCharm",
    "Проводник",
    "notepad",
    "LockApp.exe",
    "openvpn-gui",
    "timetracker",
  ].map((name, i) => ({
    id: i + 1,
    name,
    icon_url: `/applications/${i + 1}/icon`,
    color: null as string | null,
    track_titles: i % 3 !== 0,
    ignored: i === 6,
    active_ms: (10 - i) * 60_000,
  }));
  let fail = false;
  await page.route("**/stats/**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.route("**/settings/preferences", (route) =>
    route.fulfill({ json: preferences }),
  );
  await page.route(/\/settings\/(display|recording)$/, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    const section = route.request().url().endsWith("display")
      ? "display"
      : "recording";
    if (fail) return route.fulfill({ status: 503, json: {} });
    Object.assign(preferences[section], route.request().postDataJSON());
    await route.fulfill({ json: preferences[section] });
  });
  await page.route(/\/applications(?:\/\d+)?$/, async (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: apps });
    if (fail) return route.fulfill({ status: 503, json: {} });
    const app = apps.find((app) =>
      route.request().url().endsWith(`/${app.id}`),
    )!;
    Object.assign(app, route.request().postDataJSON());
    return route.fulfill({ json: app });
  });
  await page.route("**/applications/*/icon", (route) =>
    route.fulfill({ status: 404 }),
  );
  return {
    preferences,
    apps,
    fail: (value: boolean) => {
      fail = value;
    },
  };
}

test("applications search, persistence, color palette and failed save", async ({
  page,
}) => {
  const state = await setup(page);
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Приложения и приватность" }),
  ).toBeVisible();
  await expect(page.getByText("Обнаружено приложений: 10")).toBeVisible();
  await page.screenshot({
    path: "test-results/settings-desktop.png",
    fullPage: true,
  });
  await page.getByRole("textbox", { name: "Поиск приложений" }).fill("chrome");
  await expect(page.getByText("Показано: 1 из 10")).toBeVisible();
  const toggle = page.getByRole("switch", {
    name: "Заголовки: Google Chrome",
    exact: true,
  });
  await toggle.click();
  await expect(toggle).toBeChecked();
  state.fail(true);
  await toggle.click();
  await expect(page.getByRole("alert")).toContainText(
    "Не удалось сохранить настройку",
  );
  await expect(toggle).toBeChecked();
  state.fail(false);
  await page
    .getByRole("button", { name: "Цвет: Google Chrome", exact: true })
    .click();
  await page.getByRole("button", { name: "#8CB6EF", exact: true }).click();
  await expect.poll(() => state.apps[0].color).toBe("#8CB6EF");
  await page
    .getByRole("button", { name: "Цвет: Google Chrome", exact: true })
    .click();
  await page.getByRole("button", { name: "Авто", exact: true }).click();
  await expect.poll(() => state.apps[0].color).toBeNull();
  await page.reload();
  await expect(toggle).toBeChecked();
  await page.getByRole("textbox", { name: "Поиск приложений" }).fill("missing");
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
});

test("applications activity sorting, enabled filter, row cues and lock fallback", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/settings");

  const rows = page.locator(".settings-table tbody tr");
  await expect(rows.first()).toContainText("Google Chrome");
  await expect(rows.last()).toContainText("timetracker");
  await expect(page.getByText("10 м.", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "По названию", exact: true }).click();
  await expect(rows.first()).toContainText("Проводник");

  await page.getByRole("checkbox", { name: "Только включённые" }).check();
  await expect(page.getByText("Показано: 9 из 10")).toBeVisible();
  await expect(page.getByText("notepad", { exact: true })).toHaveCount(0);

  const lockRow = rows.filter({ hasText: "Блокировка" });
  await expect(lockRow.locator(".settings-app-icon svg")).toBeVisible();
  await expect(page.getByText("LockApp.exe", { exact: true })).toHaveCount(0);

  const firstBackground = await rows
    .first()
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  const secondBackground = await rows
    .nth(1)
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  expect(firstBackground).not.toBe(secondBackground);
  await rows.first().hover();
  await expect
    .poll(() =>
      rows
        .first()
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .not.toBe(firstBackground);
});

test("data export downloads CSV, opts into titles and reports failures", async ({
  page,
}) => {
  await setup(page);
  let exportUrl = "";
  let fail = false;
  await page.route(/\/export\/(csv|json)\?/, (route) => {
    exportUrl = route.request().url();
    if (fail) return route.fulfill({ status: 503, json: {} });
    const format = exportUrl.includes("/csv?") ? "csv" : "json";
    return route.fulfill({
      body: format === "csv" ? "started_at;ended_at\r\n" : '{"records":[]}',
      contentType: format === "csv" ? "text/csv" : "application/json",
      headers: {
        "Content-Disposition": `attachment; filename="timetracker-test.${format}"`,
      },
    });
  });
  await page.goto("/settings/data");
  await expect(page.getByRole("heading", { name: "Данные" })).toBeVisible();
  await page.screenshot({
    path: "test-results/settings-data.png",
    fullPage: true,
  });
  await page.getByRole("checkbox", { name: "Включить заголовки окон" }).check();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт CSV" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("timetracker-test.csv");
  const params = new URL(exportUrl).searchParams;
  expect(params.get("include_titles")).toBe("true");
  expect(params.get("timezone")).toBe("Europe/Moscow");
  expect(params.get("personal_day_start")).toBe("00:00");

  fail = true;
  await page.getByRole("button", { name: "Экспорт JSON" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Не удалось подготовить экспорт",
  );
});

test("display units, last selected unit, personal day and global pause", async ({
  page,
}) => {
  const state = await setup(page);
  await page.goto("/settings/display");
  await page.getByRole("checkbox", { name: "Часы", exact: true }).uncheck();
  await expect(page.getByText("3 д. 605 м.", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "Дни", exact: true }).uncheck();
  await expect(
    page.getByRole("checkbox", { name: "Минуты", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Начало суток", { exact: true }).fill("02:00");
  await page.getByLabel("Начало суток", { exact: true }).press("Enter");
  await expect
    .poll(() => state.preferences.display.personal_day_start)
    .toBe("02:00");
  await page.getByRole("link", { name: "Основная", exact: true }).click();
  await expect(page.getByLabel("Начало времени", { exact: true })).toHaveValue(
    "02:00",
  );
  await expect(page.getByLabel("Конец времени", { exact: true })).toHaveValue(
    "02:00",
  );
  await expect(page.getByText("02:00⁺¹", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  await page
    .getByRole("link", { name: "Запись и запуск", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Приостановить", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Пауза", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Возобновить", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("switch", { name: "Запускать вместе с Windows" })
    .click();
  await expect.poll(() => state.preferences.recording.autostart).toBe(true);
  await page.getByRole("button", { name: "Возобновить", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Пауза", exact: true }),
  ).toHaveCount(0);
});

test("duration rounding and Today before the personal day boundary", async ({
  page,
}) => {
  await setup(page);
  await page.goto("/settings");
  const result = await page.evaluate(async () => {
    // Import the same formatter used by all dashboard components through Vite.
    const format = await import(/* @vite-ignore */ "/src/format.ts");
    return [
      format.duration(12.5 * 3600000, {
        days: false,
        hours: true,
        minutes: false,
      }),
      format.duration(9.44 * 3600000, {
        days: false,
        hours: true,
        minutes: false,
      }),
      format.duration(1, { days: true, hours: false, minutes: false }),
      format.duration(62.4 * 60000, {
        days: false,
        hours: true,
        minutes: true,
      }),
      format.duration(60.5 * 60000, {
        days: false,
        hours: true,
        minutes: true,
      }),
      format.duration((23 * 60 + 59.9999) * 60000, {
        days: true,
        hours: true,
        minutes: true,
      }),
      format.personalToday(
        new Date("2026-09-22T01:00:00+03:00"),
        "02:00",
        "Europe/Moscow",
      ),
    ];
  });
  expect(result).toEqual([
    "13 ч.",
    "9,4 ч.",
    "<0,1 д.",
    "1 ч. 2 м.",
    "1 ч. 0,5 м.",
    "1 д.",
    "2026-09-21",
  ]);
});

test("settings navigation works at smaller widths", async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/settings");
  await expect(page.getByRole("table")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 700, height: 800 });
  await expect(
    page.getByRole("link", { name: "Отображение", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
