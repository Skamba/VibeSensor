import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("clears transient car creation feedback after leaving and re-entering the car screen", async ({ page }) => {
  let cars = [] as Array<Record<string, unknown>>;
  let activeCarId: string | null = null;

  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        await fulfillJson(route, { cars, active_car_id: activeCarId });
        return;
      }
      if (path === "/api/settings/cars" && method === "POST") {
        cars = [{
          id: "car-1",
          name: "Track Demo",
          type: "Coupe",
          aspects: {
            tire_width_mm: 225,
            tire_aspect_pct: 45,
            rim_in: 18,
            final_drive_ratio: 3.08,
            current_gear_ratio: 0.64,
          },
        }];
        await fulfillJson(route, { cars, active_car_id: activeCarId });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        activeCarId = "car-1";
        await fulfillJson(route, { cars, active_car_id: activeCarId });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();
  await page.getByRole("button", { name: "+ Add Car" }).click();
  await page.locator("#wizardCustomBrand").fill("Track");
  await page.locator("#wizardCustomBrandBtn").click();
  await page.locator("#wizardCustomType").fill("Coupe");
  await page.locator("#wizardCustomTypeBtn").click();
  await page.locator("#wizardCustomModel").fill("Demo");
  await page.locator("#wizardCustomModelBtn").click();
  await page.locator("#wizTireWidth").fill("225");
  await page.locator("#wizTireAspect").fill("45");
  await page.locator("#wizRim").fill("18");
  await page.locator("#wizFinalDrive").fill("3.08");
  await page.locator("#wizGearRatio").fill("0.64");
  await page.locator("#wizardManualAddBtn").click();

  const guidance = page.locator("#carSelectionGuidance");
  const createdRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(guidance).toContainText("Car added");
  await expect(createdRow).toHaveClass(/car-list-row--highlighted/);
  await expect(createdRow).toContainText("New");

  await page.locator('[data-settings-tab="analysisTab"]').click();
  await page.locator('[data-settings-tab="carTab"]').click();

  await expect(guidance).toBeHidden();
  await expect(createdRow).not.toHaveClass(/car-list-row--highlighted/);
  await expect(createdRow).not.toContainText("New");

  await page.locator("#tab-dashboard").click();
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();

  await expect(guidance).toBeHidden();
  await expect(createdRow).not.toHaveClass(/car-list-row--highlighted/);
  await expect(createdRow).not.toContainText("New");
});
