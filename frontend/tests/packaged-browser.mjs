// Invoked by the opt-in packaged smoke against the actual frozen server, without API mocks.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
const url = process.argv[2];
const browser = await chromium.launch({
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
    headless: true,
});
await mkdir("test-results", { recursive: true });
try {
    const page = await browser.newPage({
        viewport: { width: 1920, height: 1080 },
        timezoneId: "Europe/Moscow",
    });
    const failures = [],
        external = [];
    page.on("pageerror", (error) => failures.push(error.message));
    await page.route("**/*", (route) => {
        if (!route.request().url().startsWith(url)) {
            external.push(route.request().url());
            return route.abort();
        }
        return route.continue();
    });
    await page.goto(url);
    await page.waitForFunction(
        () =>
            document
                .querySelector("h1")
                ?.textContent?.includes("TimeTracker") ||
            document
                .querySelector("h1")
                ?.textContent?.includes("Похоже, вы здесь впервые"),
    );
    if (
        await page
            .getByRole("heading", { name: "Похоже, вы здесь впервые" })
            .count()
    ) {
        await page.getByRole("button", { name: "Пропустить" }).click();
        await page
            .getByRole("heading", { name: "Выберите режим сбора активности" })
            .waitFor();
        await page.getByRole("radio", { name: /^Обычный/ }).check();
        await page.getByRole("button", { name: "Готово" }).click();
    }
    await page
        .getByRole("heading", { name: "TimeTracker", exact: true })
        .waitFor();
    await page.waitForFunction(
        () =>
            document.querySelector(".refresh")?.getAttribute("disabled") ===
            null,
    );
    if (await page.getByRole("alert").count())
        throw new Error("Dashboard request failed");
    await page.getByRole("button", { name: "Выбрать диапазон дат" }).click();
    await page.getByRole("button", { name: "Последние 7 дней" }).click();
    await page.getByTestId("heatmap").waitFor();
    await page.getByRole("button", { name: "Сбросить", exact: true }).click();
    await page.getByTestId("timeline").waitFor();
    await page.getByRole("button", { name: "Обновить статистику" }).click();
    await page.waitForFunction(
        () =>
            document.querySelector(".refresh")?.getAttribute("disabled") ===
            null,
    );
    await page.getByRole("button", { name: "Настройки", exact: true }).click();
    await page.reload();
    await page
        .getByRole("heading", { name: "Приложения и приватность", exact: true })
        .waitFor();
    await page
        .getByRole("link", { name: "Сбор активности", exact: true })
        .click();
    await page.getByRole("radio", { name: /^Обычный/ }).waitFor();
    if (await page.getByRole("alert").count())
        throw new Error("Collection settings request failed");
    await page.screenshot({
        path: "test-results/packaged-settings.png",
        fullPage: true,
    });
    await page.getByRole("link", { name: "Данные", exact: true }).click();
    await page.getByRole("heading", { name: "Данные", exact: true }).waitFor();
    const download = await Promise.all([
        page.waitForEvent("download"),
        page.getByRole("button", { name: "Экспорт JSON", exact: true }).click(),
    ]).then(([item]) => item);
    if (!download.suggestedFilename().endsWith(".json"))
        throw new Error("Export download filename is invalid");
    await page.getByRole("link", { name: "Основная", exact: true }).click();
    await page.getByTestId("timeline").waitFor();
    await page.waitForTimeout(350);
    await mkdir("test-results", { recursive: true });
    await page.screenshot({
        path: "test-results/packaged-dashboard.png",
        fullPage: true,
    });
    if (failures.length || external.length)
        throw new Error(JSON.stringify({ failures, external }));
    console.log(
        "Packaged dashboard rendered; real filters/API, local fonts, no external requests.",
    );
} finally {
    await browser.close();
}
