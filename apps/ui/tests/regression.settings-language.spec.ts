import { expect, test, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  createSettingsHandlerFromMap,
  installCommonRoutes,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

test("failed language save reverts the selector and shows an error", async ({
  page,
}) => {
  await installCommonRoutes(page, {
    settingsHandler: createSettingsHandlerFromMap({
      "GET /api/settings/language": { language: "en" },
      "PUT /api/settings/language": async (route: Route) => {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Language save failed" }),
        });
      },
      "GET /api/settings/speed-unit": { speed_unit: "kmh" },
    }),
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await page.locator("#languageSelect").selectOption("nl");

  await expect(page.locator("#languageFeedback")).toBeVisible();
  await expect(page.locator("#languageFeedback")).toContainText(
    "Language save failed",
  );
  await expect(page.locator("#languageFeedback")).toContainText(
    "English remains active",
  );
  await expect(page.locator("#languageSelect")).toHaveValue("en");
  await expect(page.locator("#tab-settings")).toContainText("Settings");
});
