import { expect, test } from "@playwright/test";

import {
  installFakeWebSocket,
  openHistoryTab,
  openSettingsTab,
} from "./smoke.helpers";

test("browser MSW mock mode boots history and settings without a backend", async ({
  page,
}) => {
  await installFakeWebSocket(page);
  await page.goto("/");

  await openHistoryTab(page);
  await expect(
    page.locator('[data-run-toggle="details"][data-run="run-001"]'),
  ).toBeVisible();

  await openSettingsTab(page, "carTab");
  await expect(page.locator('[data-settings-tab="carTab"]')).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.locator("#carTab")).toHaveJSProperty("hidden", false);
});
