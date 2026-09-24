import { expect, test } from "@playwright/test";

test("missing application diagnostic traces a process into saved foreground history", async ({
  page,
}) => {
  const candidate = {
    pid: 4242,
    process_started_at: Date.now() - 60_000,
    process_name: "discord.exe",
    executable_path: "c:\\apps\\discord.exe",
    display_name: "Discord",
    tracker_known: true,
    session_saved: true,
    application_id: 7,
    application_name: "Discord",
    ignored: false,
    is_foreground: true,
    foreground_saved_since_start: true,
  };
  await page.route("**/stats/**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
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
  await page.route("**/diagnostics/process", async (route) => {
    const request = route.request().postDataJSON();
    await route.fulfill({
      json: {
        observed_at: Date.now(),
        tracking_paused: false,
        system_state: "ACTIVE",
        collection: { source: "polling", healthy: true },
        foreground_pid: 4242,
        matches: [
          request.query
            ? { ...candidate, foreground_saved_since_start: false }
            : candidate,
        ],
      },
    });
  });

  await page.goto("/settings/activity");
  await page.getByRole("button", { name: "Проверить приложение" }).click();
  await page
    .getByPlaceholder("Например, Discord или discord.exe")
    .fill("discord");
  await page.getByRole("button", { name: "Найти" }).click();
  await expect(page.getByText("discord.exe · PID 4242")).toBeVisible();
  await page.getByRole("button", { name: "Начать проверку" }).click();
  await expect(
    page.getByText("Переключитесь в нужное приложение"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Активность записывается правильно" }),
  ).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Открыть приложения" }).click();
  await expect(page).toHaveURL(/\/settings\/apps$/);
});
