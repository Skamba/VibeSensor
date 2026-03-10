import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("shows header warning and blocks car-dependent analysis save when no car is selected", async ({ page }) => {
  let analysisPostCalls = 0;
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/cars") {
        await fulfillJson(route, { cars: [], activeCarId: null });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/settings/analysis", async (route) => {
    if (route.request().method() === "POST") {
      analysisPostCalls += 1;
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
  await expect.poll(() => analysisPostCalls).toBe(0);
});

test("hides header warning when a valid selected car exists", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }], activeCarId: "car-1" });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await expect(page.locator("#carSelectionBanner")).toBeHidden();
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
          await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }, { id: "car-2", name: "Two", type: "suv", aspects: {} }], activeCarId: "missing-car" });
          return;
        }
        await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }, { id: "car-2", name: "Two", type: "suv", aspects: {} }], activeCarId: "car-2" });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "POST") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }, { id: "car-2", name: "Two", type: "suv", aspects: {} }], activeCarId: "car-2" });
        return;
      }
      if (path === "/api/settings/cars/car-2" && method === "DELETE") {
        await fulfillJson(route, { cars: [{ id: "car-1", name: "One", type: "sedan", aspects: {} }], activeCarId: null });
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