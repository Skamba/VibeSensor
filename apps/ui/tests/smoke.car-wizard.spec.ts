import { expect, test } from "@playwright/test";

import {
  createSettingsHandlerFromMap,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
} from "./smoke.helpers";

test("opens the add car wizard in a focused task container and restores focus when canceled", async ({ page }) => {
  await installCommonRoutes(page, {
    settingsHandler: createSettingsHandlerFromMap({
      "/api/settings/cars": {
        cars: [{ id: "car-1", name: "Audit Demo Car", type: "sedan", aspects: {} }],
        active_car_id: "car-1",
      },
    }),
  });
  await page.route("**/api/car-library/**", async (route) => {
    const path = requestPath(route);
    if (path === "/api/car-library/brands") {
      await fulfillJson(route, { brands: ["BMW", "Volvo"] });
      return;
    }
    await fulfillJson(route, { brands: [], types: [], models: [] });
  });
  await installFakeWebSocket(page);

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();
  await page.locator("#addCarBtn").click();

  await expect(page.locator("#wizardBackdrop")).toBeVisible();
  await expect(page.locator("#addCarWizard")).toBeVisible();
  await expect(page.locator("#wizardProgressText")).toContainText("Step 1 of 5");
  await expect(page.locator(".wizard-step-dot[aria-current='step']")).toContainText("Brand");
  await expect(page.locator(".wizard-summary-card")).toContainText("Guided setup");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("Not selected yet");

  await page.locator("#wizardCloseBtn").click();

  await expect(page.locator("#addCarWizard")).toBeHidden();
  await expect(page.locator("#wizardBackdrop")).toBeHidden();
  await expect(page.locator("#addCarBtn")).toBeFocused();
});

test("keeps the manual branch deliberate while summarizing selections and activating the new car", async ({ page }) => {
  const cars = [{ id: "car-1", name: "Audit Demo Car", type: "sedan", aspects: {} }];
  let activeCarId = "car-1";
  let createdCarName = "";

  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        await fulfillJson(route, { cars, active_car_id: activeCarId });
        return;
      }
      if (path === "/api/settings/cars" && method === "POST") {
        const body = route.request().postDataJSON() as {
          name: string;
          type: string;
          aspects: Record<string, number>;
        };
        createdCarName = body.name;
        cars.push({
          id: "car-2",
          name: body.name,
          type: body.type,
          aspects: body.aspects,
        });
        await fulfillJson(route, { cars, active_car_id: activeCarId });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        const body = route.request().postDataJSON() as { car_id: string };
        activeCarId = body.car_id;
        await fulfillJson(route, { cars, active_car_id: activeCarId });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/car-library/**", async (route) => {
    const path = requestPath(route);
    if (path === "/api/car-library/brands") {
      await fulfillJson(route, { brands: ["BMW"] });
      return;
    }
    if (path === "/api/car-library/types") {
      await fulfillJson(route, { types: ["SUV"] });
      return;
    }
    if (path === "/api/car-library/models") {
      await fulfillJson(route, {
        models: [{
          model: "X5",
          tire_width_mm: 275,
          tire_aspect_pct: 40,
          rim_in: 21,
          variants: [],
          gearboxes: [],
          tire_options: [],
        }],
      });
      return;
    }
    await fulfillJson(route, { brands: [], types: [], models: [] });
  });
  await installFakeWebSocket(page);

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();
  await page.locator("#addCarBtn").click();

  await page.locator("#wizardBrandList .wiz-opt").click();
  await expect(page.locator("#wizardProgressText")).toContainText("Step 2 of 5");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("BMW");

  await page.locator("#wizardTypeList .wiz-opt").click();
  await expect(page.locator("#wizardProgressText")).toContainText("Step 3 of 5");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("SUV");

  await page.locator("#wizardCustomModel").fill("X5 M60i");
  await page.locator("#wizardCustomModelBtn").click();

  await expect(page.locator("#wizardProgressText")).toContainText("Step 5 of 5");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("BMW X5 M60i");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("225/45R18");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("Final drive 3.08");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("Top gear 0.64");
  await expect(page.locator(".wizard-custom-specs__note")).toBeVisible();
  await expect(page.locator("#wizardGearboxList")).toContainText("Enter specs manually below.");
  await page.locator("#wizTireWidth").fill("245");
  await page.locator("#wizGearRatio").fill("0.68");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("245/45R18");
  await expect(page.locator("#wizardSummaryPanel")).toContainText("Top gear 0.68");

  await page.locator("#wizardManualAddBtn").click();

  await expect.poll(() => createdCarName).toBe("BMW X5 M60i");
  await expect(page.locator("#addCarWizard")).toBeHidden();
  await expect(page.locator("#wizardBackdrop")).toBeHidden();
  const newRow = page.locator('#carListBody tr[data-car-id="car-2"]');
  await expect(newRow).toContainText("BMW X5 M60i");
  await expect(newRow).toContainText("245/45R18");
  await expect(newRow).toContainText("3.08");
  await expect(newRow).toContainText("0.68");
  await expect(newRow.locator(".car-active-pill")).toHaveClass(/active/);
});
