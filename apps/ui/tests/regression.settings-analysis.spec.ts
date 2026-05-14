import { expect, test } from "@playwright/test";

import {
  bootLiveDashboard,
  cancelPrompt,
  confirmPrompt,
  fulfillJson,
  installCommonRoutes,
  openAnalysisTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

test("analysis tab adds guided helper copy and can reset tuning to defaults", async ({
  page,
}) => {
  let lastAnalysisPayload: Record<string, number> = {
    tire_width_mm: 285,
    tire_aspect_pct: 30,
    rim_in: 21,
    final_drive_ratio: 3.08,
    current_gear_ratio: 0.64,
    wheel_bandwidth_pct: 11,
    driveshaft_bandwidth_pct: 10,
    engine_bandwidth_pct: 9,
    speed_uncertainty_pct: 3,
    tire_diameter_uncertainty_pct: 4,
    final_drive_uncertainty_pct: 1,
    gear_uncertainty_pct: 2,
    min_abs_band_hz: 1.2,
    max_band_half_width_pct: 10,
    tire_deflection_factor: 0.97,
  };
  let analysisPutCalls = 0;
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
    if (route.request().method() === "PUT") {
      analysisPutCalls += 1;
      lastAnalysisPayload = route.request().postDataJSON() as Record<
        string,
        number
      >;
      await fulfillJson(route, {
        ...lastAnalysisPayload,
        tire_width_mm: 285,
        tire_aspect_pct: 30,
        rim_in: 21,
        final_drive_ratio: 3.08,
        current_gear_ratio: 0.64,
        tire_deflection_factor: 0.97,
      });
      return;
    }
    await fulfillJson(route, lastAnalysisPayload);
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);

  const analysisGuidance = page.locator("#analysisGuidanceHelp");
  const analysisGuidanceBody = analysisGuidance.locator(
    ".settings-help-disclosure__body",
  );
  await expect(analysisGuidance).toContainText("Safe starting point");
  await expect(analysisGuidanceBody).not.toBeVisible();
  await analysisGuidance.locator("summary").click();
  await expect(analysisGuidanceBody).toBeVisible();
  await expect(analysisGuidanceBody).toContainText(
    "Values outside the guided range will ask for confirmation",
  );

  const orderBandHelp = page.locator("#analysisOrderBandHelp");
  const orderBandHelpBody = orderBandHelp.locator(
    ".settings-help-disclosure__body",
  );
  await expect(orderBandHelpBody).not.toBeVisible();
  await orderBandHelp.locator("summary").click();
  await expect(orderBandHelpBody).toBeVisible();
  await expect(orderBandHelpBody).toContainText(
    "These values control how far the app searches around each expected order",
  );

  const uncertaintyHelp = page.locator("#analysisUncertaintyHelp");
  const uncertaintyHelpBody = uncertaintyHelp.locator(
    ".settings-help-disclosure__body",
  );
  await expect(uncertaintyHelpBody).not.toBeVisible();
  await uncertaintyHelp.locator("summary").click();
  await expect(uncertaintyHelpBody).toBeVisible();
  await expect(uncertaintyHelpBody).toContainText(
    "Defaults use tire wear from 10/32 in to 2/32 in plus safety margin",
  );
  await expect(uncertaintyHelpBody).toContainText(
    "Use these only when vehicle data is approximate",
  );

  await expect(page.locator("#wheelBandwidthGuidance")).toContainText(
    "Recommended 2% to 12%",
  );
  await expect(page.locator("#wheelBandwidthGuidance")).toContainText(
    "Default 5%",
  );
  await expect(page.locator("#wheelBandwidthGuidance")).not.toContainText(
    "Allowed 0.1% to 100%",
  );

  await page.locator("#resetAnalysisBtn").click();
  await confirmPrompt(page);
  await expect.poll(() => analysisPutCalls).toBe(1);
  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("5");
  await expect(page.locator("#maxBandHalfWidthInput")).toHaveValue("6");
  expect(lastAnalysisPayload.wheel_bandwidth_pct).toBe(5);
  expect(lastAnalysisPayload.max_band_half_width_pct).toBe(6);
});

test("analysis settings ask for confirmation before saving risky values", async ({
  page,
}) => {
  let analysisPutCalls = 0;
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
    if (route.request().method() === "PUT") {
      analysisPutCalls += 1;
      await fulfillJson(route, route.request().postDataJSON());
      return;
    }
    await fulfillJson(route, {});
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#wheelBandwidthInput").fill("40");
  await page.locator("#saveAnalysisBtn").click();
  await cancelPrompt(page);
  await expect.poll(() => analysisPutCalls).toBe(0);

  await page.locator("#saveAnalysisBtn").click();
  await confirmPrompt(page);
  await expect.poll(() => analysisPutCalls).toBe(1);
});

test("analysis settings show a field-specific error when a hard limit is exceeded", async ({
  page,
}) => {
  let analysisPutCalls = 0;
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
    if (route.request().method() === "PUT") {
      analysisPutCalls += 1;
      await fulfillJson(route, route.request().postDataJSON());
      return;
    }
    await fulfillJson(route, {});
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#wheelBandwidthInput").fill("120");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPutCalls).toBe(0);
  await expect(page.locator("#wheelBandwidthGuidance")).toContainText(
    "Wheel Bandwidth (%) must stay between 0.1% and 100%",
  );
  await expect(page.locator("#analysisGuidanceHelp")).toHaveAttribute(
    "open",
    "",
  );
  await expect(page.locator("#wheelBandwidthInput")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
});

test("failed analysis save preserves the draft and explains that saved settings remain active", async ({
  page,
}) => {
  let analysisPutCalls = 0;
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
    if (route.request().method() === "PUT") {
      analysisPutCalls += 1;
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Analysis save failed" }),
      });
      return;
    }
    await fulfillJson(route, {
      tire_width_mm: 285,
      tire_aspect_pct: 30,
      rim_in: 21,
      final_drive_ratio: 3.08,
      current_gear_ratio: 0.64,
      wheel_bandwidth_pct: 5,
      driveshaft_bandwidth_pct: 4,
      engine_bandwidth_pct: 5,
      speed_uncertainty_pct: 1,
      tire_diameter_uncertainty_pct: 2,
      final_drive_uncertainty_pct: 1,
      gear_uncertainty_pct: 1,
      min_abs_band_hz: 0.5,
      max_band_half_width_pct: 6,
      tire_deflection_factor: 0.97,
    });
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#wheelBandwidthInput").fill("7.5");
  await page.locator("#maxBandHalfWidthInput").fill("11");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPutCalls).toBe(1);
  await expect(page.locator("#analysisSaveFeedback")).toBeVisible();
  await expect(page.locator("#analysisSaveFeedback")).toContainText(
    "Analysis save failed",
  );
  await expect(page.locator("#analysisSaveFeedback")).toContainText(
    "previous saved analysis settings remain active",
  );
  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
  await expect(page.locator("#maxBandHalfWidthInput")).toHaveValue("11");
  await expect(page.locator("#analysisGuidanceHelp")).toHaveAttribute(
    "open",
    "",
  );
});
