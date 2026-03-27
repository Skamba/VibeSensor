import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("shows header warning and blocks car-dependent analysis save when no car is selected", async ({ page }) => {
  let analysisPutCalls = 0;
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/cars") {
        await fulfillJson(route, { cars: [], active_car_id: null });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/settings/analysis", async (route) => {
    if (route.request().method() === "PUT") {
      analysisPutCalls += 1;
    }
    await fulfillJson(route, {});
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await expect(page.locator("#carSelectionBanner")).toBeVisible();
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(page.locator("#analysisNoCarMessage")).toBeVisible();
  await expect(page.locator("#saveAnalysisBtn")).toBeDisabled();
  await page.waitForTimeout(150);
  await expect.poll(() => analysisPutCalls).toBe(0);
});

test("hides header warning when a valid selected car exists", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], active_car_id: "car-1" });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await expect(page.locator("#carSelectionBanner")).toBeHidden();
});

test("keeps warning UI hidden until active car bootstrap resolves and then marks the car active", async ({ page }) => {
  let releaseCars: (() => void) | null = null;
  const waitForCars = new Promise<void>((resolve) => {
    releaseCars = resolve;
  });
  const analysisPayload = {
    tire_width_mm: 285,
    tire_aspect_pct: 30,
    rim_in: 21,
    final_drive_ratio: 3.08,
    current_gear_ratio: 0.64,
    wheel_bandwidth_pct: 7.5,
    driveshaft_bandwidth_pct: 8.5,
    engine_bandwidth_pct: 9.5,
    speed_uncertainty_pct: 3,
    tire_diameter_uncertainty_pct: 4,
    final_drive_uncertainty_pct: 2,
    gear_uncertainty_pct: 5,
    min_abs_band_hz: 0.7,
    max_band_half_width_pct: 12,
    tire_deflection_factor: 0.97,
  };

  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/cars") {
        await waitForCars;
        await fulfillJson(route, {
          cars: [{
            id: "car-1",
            name: "Audit Demo Car",
            type: "sedan",
            aspects: {
              tire_width_mm: 285,
              tire_aspect_pct: 30,
              rim_in: 21,
              final_drive_ratio: 3.08,
              current_gear_ratio: 0.64,
            },
          }],
          active_car_id: "car-1",
        });
        return;
      }
      if (path === "/api/settings/analysis") {
        await fulfillJson(route, analysisPayload);
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await expect(page.locator("#carSelectionBanner")).toBeHidden();

  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();

  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
  await expect(page.locator("#saveAnalysisBtn")).toBeDisabled();
  await expect(page.locator("#analysisNoCarMessage")).toBeHidden();
  await expect(page.locator("#carSelectionBanner")).toBeHidden();

  if (!releaseCars) {
    throw new Error("cars bootstrap gate was not initialized");
  }
  releaseCars();

  await expect(page.locator("#saveAnalysisBtn")).toBeEnabled();
  await expect(page.locator("#carSelectionBanner")).toBeHidden();
  await expect(page.locator("#analysisNoCarMessage")).toBeHidden();

  await page.locator('[data-settings-tab="carTab"]').click();
  const activeRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(activeRow).toContainText("Audit Demo Car");
  await expect(activeRow.locator(".car-active-pill")).toHaveClass(/active/);
});

test("shows warning for invalid persisted selection and after deleting selected car", async ({ page }) => {
  let firstCarsGet = true;
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        if (firstCarsGet) {
          firstCarsGet = false;
          await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }, { id: "car-2", name: "Two", type: "suv", aspects: {} }], active_car_id: "missing-car" });
          return;
        }
        await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }, { id: "car-2", name: "Two", type: "suv", aspects: {} }], active_car_id: "car-2" });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }, { id: "car-2", name: "Two", type: "suv", aspects: {} }], active_car_id: "car-2" });
        return;
      }
      if (path === "/api/settings/cars/car-2" && method === "DELETE") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }], active_car_id: null });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page, { confirmResult: true });
  await page.goto("/");
  await expect(page.locator("#carSelectionBanner")).toBeVisible();
  await page.locator("#tab-settings").click();
  await page.locator("#carListBody .car-activate-btn").last().click();
  await expect(page.locator("#carSelectionBanner")).toBeHidden();
  await page.locator('#carListBody tr[data-car-id="car-2"] .car-delete-btn').click();
  await expect(page.locator("#carSelectionBanner")).toBeVisible();
});
