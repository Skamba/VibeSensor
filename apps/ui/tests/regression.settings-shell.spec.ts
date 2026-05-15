import { expect, test, type Page } from "@playwright/test";

import { installSettingsRoutes, installFakeWebSocket } from "./smoke.helpers";

test.describe.configure({ timeout: 12_000 });

async function openSettings(page: Page): Promise<void> {
  await installSettingsRoutes(page);
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
}

test("settings shell keeps selected tabs and panels in sync on click", async ({
  page,
}) => {
  await openSettings(page);

  const carTabButton = page.locator('[data-settings-tab="carTab"]');
  const analysisTabButton = page.locator('[data-settings-tab="analysisTab"]');
  const speedSourceTabButton = page.locator(
    '[data-settings-tab="speedSourceTab"]',
  );

  await expect(carTabButton).toHaveAttribute("aria-selected", "true");
  await expect(carTabButton).toHaveAttribute("aria-controls", "carTab");
  await expect(carTabButton).toHaveAttribute("tabindex", "0");
  await expect(page.locator("#carTab")).toHaveJSProperty("hidden", false);

  await analysisTabButton.click();
  await expect(analysisTabButton).toHaveAttribute("aria-selected", "true");
  await expect(analysisTabButton).toHaveAttribute(
    "aria-controls",
    "analysisTab",
  );
  await expect(analysisTabButton).toHaveAttribute("tabindex", "0");
  await expect(carTabButton).toHaveAttribute("aria-selected", "false");
  await expect(carTabButton).toHaveAttribute("tabindex", "-1");
  await expect(page.locator("#analysisTab")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#carTab")).toHaveJSProperty("hidden", true);

  await speedSourceTabButton.click();
  await expect(speedSourceTabButton).toHaveAttribute("aria-selected", "true");
  await expect(speedSourceTabButton).toHaveAttribute("tabindex", "0");
  await expect(analysisTabButton).toHaveAttribute("aria-selected", "false");
  await expect(analysisTabButton).toHaveAttribute("tabindex", "-1");
  await expect(page.locator("#speedSourceTab")).toHaveJSProperty(
    "hidden",
    false,
  );
  await expect(page.locator("#analysisTab")).toHaveJSProperty("hidden", true);
});

test("settings shell supports keyboard tab navigation", async ({ page }) => {
  await openSettings(page);

  const carTabButton = page.locator('[data-settings-tab="carTab"]');
  const analysisTabButton = page.locator('[data-settings-tab="analysisTab"]');
  const espFlashTabButton = page.locator('[data-settings-tab="espFlashTab"]');

  await carTabButton.focus();
  await carTabButton.press("ArrowRight");
  await expect(analysisTabButton).toBeFocused();
  await expect(analysisTabButton).toHaveAttribute("aria-selected", "true");
  await expect(analysisTabButton).toHaveAttribute("tabindex", "0");
  await expect(carTabButton).toHaveAttribute("tabindex", "-1");
  await expect(page.locator("#analysisTab")).toHaveJSProperty("hidden", false);

  await analysisTabButton.press("ArrowLeft");
  await expect(carTabButton).toBeFocused();
  await expect(carTabButton).toHaveAttribute("aria-selected", "true");
  await expect(carTabButton).toHaveAttribute("tabindex", "0");
  await expect(analysisTabButton).toHaveAttribute("tabindex", "-1");
  await expect(page.locator("#carTab")).toHaveJSProperty("hidden", false);

  await carTabButton.press("End");
  await expect(espFlashTabButton).toBeFocused();
  await expect(espFlashTabButton).toHaveAttribute("aria-selected", "true");
  await expect(espFlashTabButton).toHaveAttribute("tabindex", "0");
  await expect(carTabButton).toHaveAttribute("tabindex", "-1");
  await expect(page.locator("#espFlashTab")).toHaveJSProperty("hidden", false);

  await espFlashTabButton.press("Home");
  await expect(carTabButton).toBeFocused();
  await expect(carTabButton).toHaveAttribute("aria-selected", "true");
  await expect(carTabButton).toHaveAttribute("tabindex", "0");
  await expect(espFlashTabButton).toHaveAttribute("tabindex", "-1");
  await expect(page.locator("#carTab")).toHaveJSProperty("hidden", false);
});
