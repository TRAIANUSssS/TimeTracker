import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

type Outcome = "success" | "failure";

async function setup(page: Page, outcome: Outcome = "success") {
  const preferences = {
    display: {
      time_units: { days: true, hours: true, minutes: true },
      personal_day_start: "00:00",
      timezone: "Europe/Moscow",
    },
    recording: { tracking_paused: false, autostart: false },
    onboarding_completed: false,
  };
  const displayChanges: unknown[] = [];
  const actions: string[] = [];
  let installing = false;
  let installChecks = 0;
  const status = () => ({
    mode:
      installing && outcome === "success" && installChecks > 1
        ? "etw"
        : "polling",
    active_mode: "polling",
    effective_mode: "polling",
    installed: installing && outcome === "success" && installChecks > 1,
    can_install: true,
    busy: installing && installChecks <= 1,
    error:
      installing && outcome === "failure" && installChecks > 0
        ? "Пользователь отменил запрос Windows"
        : null,
    restart_required: false,
    external: false,
    token: "onboarding-token",
  });

  await page.route("**/stats/**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.route("**/settings/preferences", (route) =>
    route.fulfill({ json: preferences }),
  );
  await page.route("**/settings/display", async (route) => {
    const changes = route.request().postDataJSON();
    displayChanges.push(changes);
    Object.assign(preferences.display, changes);
    await route.fulfill({ json: preferences.display });
  });
  await page.route("**/settings/onboarding", async (route) => {
    preferences.onboarding_completed = true;
    await route.fulfill({ json: { completed: true } });
  });
  await page.route("**/settings/collection", async (route) => {
    if (route.request().method() === "GET") {
      if (installing) installChecks += 1;
      return route.fulfill({ json: status() });
    }
    const { action } = route.request().postDataJSON();
    actions.push(action);
    if (action === "install") installing = true;
    return route.fulfill({ status: 202, json: status() });
  });
  return { preferences, displayChanges, actions };
}

test("first launch saves the personal day and can choose ordinary collection", async ({
  page,
}) => {
  const state = await setup(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(
    page.getByRole("heading", { name: "Похоже, вы здесь впервые" }),
  ).toBeVisible();
  await page.getByLabel("Начало нового дня").fill("02:00");
  await page.getByRole("button", { name: "Далее" }).click();
  await expect(page.getByLabel("Оптимизированный Рекомендуется")).toBeChecked();
  await page.getByRole("button", { name: "Пропустить" }).click();

  await expect(page).toHaveURL(/\/$/);
  expect(state.displayChanges).toEqual([{ personal_day_start: "02:00" }]);
  expect(state.actions).toEqual(["polling"]);
  expect(state.preferences.onboarding_completed).toBe(true);
});

test("optimized collection waits for installation before completing", async ({
  page,
}) => {
  const state = await setup(page, "success");
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Пропустить" }).click();
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(
    page.getByText("Устанавливаем оптимизированный режим…"),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/$/, { timeout: 5000 });
  expect(state.actions).toEqual(["install"]);
  expect(state.preferences.onboarding_completed).toBe(true);
});

test("cancelled UAC offers a safe polling fallback", async ({ page }) => {
  const state = await setup(page, "failure");
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Пропустить" }).click();
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Не удалось установить оптимизированный режим.",
    }),
  ).toBeVisible();
  expect(state.preferences.onboarding_completed).toBe(false);
  await page.getByRole("button", { name: "Продолжить" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(state.actions).toEqual(["install", "polling"]);
  expect(state.preferences.onboarding_completed).toBe(true);
});
