import { expect, test } from "@playwright/test";

test("collection setup, pending restart, fallback and removal guard", async ({
  page,
}) => {
  const state = {
    mode: "polling",
    active_mode: "polling",
    effective_mode: "polling",
    installed: false,
    can_install: true,
    busy: false,
    error: null,
    restart_required: false,
    external: false,
    token: "settings-test-token",
  };
  const actions: string[] = [];
  await page.route("**/stats/**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.route("**/settings/collection", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().headers()["x-timetracker-token"]).toBe(
        state.token,
      );
      const action = route.request().postDataJSON().action;
      actions.push(action);
      if (action === "install") {
        state.installed = true;
        state.mode = "etw";
        state.restart_required = true;
      } else {
        state.mode = action;
        state.restart_required = state.active_mode !== action;
      }
    }
    await route.fulfill({ json: state });
  });
  await page.goto("/settings");
  await expect(
    page.getByRole("radio", { name: /^Экономичный/ }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Установить и выбрать экономичный режим" })
    .click();
  await expect(page.getByText(/Настройка сохранена/)).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Экономичный/ })).toBeChecked();
  expect(actions).toEqual(["install"]);
  state.active_mode = "etw";
  state.restart_required = false;
  await page.reload();
  await expect(
    page.getByText(/экономичный источник пока недоступен/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Удалить компонент" }),
  ).toBeDisabled();
  await page.getByRole("radio", { name: /^Обычный/ }).check();
  await expect(page.getByText(/Настройка сохранена/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Удалить компонент" }),
  ).toBeDisabled();
});

test("cancelled Windows confirmation is visible without selecting ETW", async ({
  page,
}) => {
  const state = {
    mode: "polling",
    active_mode: "polling",
    effective_mode: "polling",
    installed: false,
    can_install: true,
    busy: false,
    error: null as string | null,
    restart_required: false,
    external: false,
    token: "settings-test-token",
  };
  await page.route("**/stats/**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.route("**/settings/collection", async (route) => {
    if (route.request().method() === "POST")
      state.error = "Подтверждение Windows отменено. Режим не изменён.";
    await route.fulfill({ json: state });
  });
  await page.goto("/settings");
  await page
    .getByRole("button", { name: "Установить и выбрать экономичный режим" })
    .click();
  await expect(
    page.getByText("Подтверждение Windows отменено. Режим не изменён."),
  ).toBeVisible();
  await expect(page.getByRole("radio", { name: /^Обычный/ })).toBeChecked();
});
