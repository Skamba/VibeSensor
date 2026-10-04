import { expect, test } from "@playwright/test";

import type { CarsPayload, SpeedSourcePayload } from "../src/api/types";
import { bootLiveDashboard, fulfillJson, requestPath } from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

test("journey: tabs follow the keyboard and the status pills leave the dashboard", async ({
  page,
}) => {
  await bootLiveDashboard(page, {
    fakeWebSocket: { payload: { clients: [], spectra: { clients: {} } } },
  });
  const liveTab = page.locator("#tab-dashboard");
  await expect(liveTab).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".site-header__status")).toBeHidden();

  await liveTab.focus();
  await page.keyboard.press("ArrowRight");
  const historyTab = page.locator("#tab-history");
  await expect(historyTab).toBeFocused();
  await expect(historyTab).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#historyView")).toBeVisible();
  await expect(page.locator("#linkState")).toHaveText("Connected");

  await page.keyboard.press("End");
  await expect(page.locator("#tab-settings")).toBeFocused();
  await expect(page.locator("#settingsView")).toBeVisible();
  await page.keyboard.press("Home");
  await expect(liveTab).toBeFocused();
  await expect(page.locator("#dashboardView")).toBeVisible();

  await page.locator("#tab-settings").click();
  const carTab = page.locator('[data-settings-tab="carTab"]');
  await carTab.focus();
  await page.keyboard.press("ArrowLeft");
  const espTab = page.locator('[data-settings-tab="espFlashTab"]');
  await expect(espTab).toBeFocused();
  await expect(page.locator("#espFlashTab")).toBeVisible();
  await expect(page.locator("#carTab")).toBeHidden();
});

test("journey: a view that fails to load keeps the current view and shows the error", async ({
  page,
}) => {
  let speedSourceFailures = 0;
  const startupLoad = page.waitForResponse((response) =>
    response.url().endsWith("/api/settings/speed-source"),
  );
  await bootLiveDashboard(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/speed-source" && speedSourceFailures > 0) {
        speedSourceFailures -= 1;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "settings store locked" }),
        });
        return;
      }
      if (path.startsWith("/api/settings/cars")) {
        await fulfillJson<CarsPayload>(route, {
          cars: [],
          active_car_id: null,
        });
        return;
      }
      if (path === "/api/settings/speed-source") {
        await fulfillJson<SpeedSourcePayload>(route, {
          speed_source: "gps",
          manual_speed_kph: null,
          stale_timeout_s: 10,
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  // Let the dashboard's startup load succeed, then fail the Settings load.
  await startupLoad;
  speedSourceFailures = 1;
  await page.locator("#tab-settings").click();
  await expect(page.locator("#appErrorBanner")).toContainText(
    "settings store locked",
  );
  await expect(page.locator("#dashboardView")).toBeVisible();
  await expect(page.locator("#tab-dashboard")).toHaveAttribute(
    "aria-selected",
    "true",
  );

  // Retrying loads the view.
  await page.locator("#tab-settings").click();
  await expect(page.locator("#settingsView")).toBeVisible();
});

test("journey: the first-load hotspot hint stays dismissed after a reload", async ({
  page,
}) => {
  await bootLiveDashboard(page, {
    fakeWebSocket: { payload: { clients: [], spectra: { clients: {} } } },
  });
  const hint = page.locator("#hotspotHint");
  await expect(hint).toContainText("no internet");
  await hint.getByRole("button", { name: "Got it" }).click();
  await expect(hint).toHaveCount(0);

  await page.reload();
  await expect(page.locator("#tab-dashboard")).toBeVisible();
  await expect(hint).toHaveCount(0);
});
