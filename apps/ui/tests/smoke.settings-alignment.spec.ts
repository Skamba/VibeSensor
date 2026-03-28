import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

const analysisSettingsPayload = {
  wheel_bandwidth_pct: 5,
  driveshaft_bandwidth_pct: 5,
  engine_bandwidth_pct: 5,
  min_abs_band_hz: 0.5,
  max_band_half_width_pct: 6,
  speed_uncertainty_pct: 3,
  tire_diameter_uncertainty_pct: 4,
  final_drive_uncertainty_pct: 1,
  gear_uncertainty_pct: 2,
};

test("analysis uncertainty inputs stay aligned when the middle label wraps", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }],
          active_car_id: "car-1",
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/settings/analysis", async (route) => {
    await fulfillJson(route, analysisSettingsPayload);
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();

  const speedLabel = page.locator('label[for="speedUncertaintyInput"]');
  const tireLabel = page.locator('label[for="tireDiameterUncertaintyInput"]');
  const finalDriveLabel = page.locator('label[for="finalDriveUncertaintyInput"]');
  await expect(speedLabel).toBeVisible();
  await expect(tireLabel).toBeVisible();
  await expect(finalDriveLabel).toBeVisible();

  const [speedLabelBox, tireLabelBox, speedTop, tireTop, finalDriveTop] = await Promise.all([
    speedLabel.boundingBox(),
    tireLabel.boundingBox(),
    page.locator("#speedUncertaintyInput").evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    page.locator("#tireDiameterUncertaintyInput").evaluate((el) =>
      Math.round(el.getBoundingClientRect().top),
    ),
    page.locator("#finalDriveUncertaintyInput").evaluate((el) =>
      Math.round(el.getBoundingClientRect().top),
    ),
  ]);

  if (!speedLabelBox || !tireLabelBox) {
    throw new Error("Expected uncertainty labels to have layout boxes");
  }

  expect(tireLabelBox.height).toBeGreaterThan(speedLabelBox.height);
  expect(Math.abs(speedTop - tireTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(finalDriveTop - tireTop)).toBeLessThanOrEqual(1);
});

test("manage cars delete button stays in the same visible column across rows", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson(route, {
          cars: [
            { id: "car-1", name: "Active Car", type: "sedan", aspects: {} },
            { id: "car-2", name: "Inactive Car", type: "suv", aspects: {} },
          ],
          active_car_id: "car-1",
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();

  const activeRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  const inactiveRow = page.locator('#carListBody tr[data-car-id="car-2"]');
  const activeDeleteButton = activeRow.locator(".car-delete-btn");
  const inactiveDeleteButton = inactiveRow.locator(".car-delete-btn");

  await expect(activeDeleteButton).toBeVisible();
  await expect(inactiveDeleteButton).toBeVisible();
  await expect(activeRow.locator(".car-activate-btn")).toHaveCount(0);
  await expect(inactiveRow.locator(".car-activate-btn")).toHaveCount(1);

  const [activeDeleteRight, inactiveDeleteRight] = await Promise.all([
    activeDeleteButton.evaluate((el) => {
      const { right } = el.getBoundingClientRect();
      return Math.round(right);
    }),
    inactiveDeleteButton.evaluate((el) => {
      const { right } = el.getBoundingClientRect();
      return Math.round(right);
    }),
  ]);

  expect(Math.abs(activeDeleteRight - inactiveDeleteRight)).toBeLessThanOrEqual(1);
});

test("live strongest signal stat stays aligned with peer summary metrics", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1280 });
  await page.goto("/?demo=1");

  const dataFreshnessStat = page.locator("#liveDataFreshness");
  const strongestSignalStat = page.locator("#liveStrongestSignal");
  const dataFreshnessLabel = dataFreshnessStat.locator(".stat__label");
  const strongestSignalLabel = strongestSignalStat.locator(".stat__label");
  const dataFreshnessValue = dataFreshnessStat.locator("[data-value]");
  const strongestSignalValue = strongestSignalStat.locator("[data-value]");
  const speedValue = page.locator("#speed");

  await expect(strongestSignalStat).toHaveClass(/stat--spotlight/);
  await expect(dataFreshnessValue).toBeVisible();
  await expect(strongestSignalValue).toBeVisible();
  await expect(speedValue).toBeVisible();

  const [
    dataFreshnessLabelTop,
    strongestSignalLabelTop,
    speedLabelTop,
    dataFreshnessValueTop,
    strongestSignalValueTop,
    speedValueTop,
  ] = await Promise.all([
    dataFreshnessLabel.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    strongestSignalLabel.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    speedValue.evaluate((el) =>
      Math.round((el.previousElementSibling as HTMLElement).getBoundingClientRect().top),
    ),
    dataFreshnessValue.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    strongestSignalValue.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
    speedValue.evaluate((el) => Math.round(el.getBoundingClientRect().top)),
  ]);

  expect(Math.abs(dataFreshnessLabelTop - strongestSignalLabelTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(speedLabelTop - strongestSignalLabelTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(dataFreshnessValueTop - strongestSignalValueTop)).toBeLessThanOrEqual(1);
  expect(Math.abs(speedValueTop - strongestSignalValueTop)).toBeLessThanOrEqual(1);
});
