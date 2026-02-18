import { test, expect } from "@playwright/test";

test.describe("Live view", () => {
  test("renders spectrum and car map", async ({ page }) => {
    await page.goto("/?demo=1");
    // Wait for demo data to render (spectrum + car map dots)
    await page.waitForSelector(".car-map-dot--visible", { timeout: 5_000 });
    // Wait for the event pulse animation to fire and the pulse class to be removed
    await page.waitForFunction(
      () => document.querySelector(".log-row .log-time") !== null,
      { timeout: 5_000 },
    );
    await expect(page).toHaveScreenshot("live-view.png", { fullPage: true });
  });
});

test.describe("Settings view", () => {
  test("renders analysis tab", async ({ page }) => {
    await page.goto("/?demo=1");
    // Navigate to Settings
    await page.click('[data-view="settingsView"]');
    // Click the Analysis tab
    await page.click('[data-settings-tab="analysisTab"]');
    // Wait for the analysis panel to be visible
    await page.waitForSelector("#analysisTab.active", { timeout: 3_000 });
    await expect(page).toHaveScreenshot("settings-analysis.png", { fullPage: true });
  });
});
