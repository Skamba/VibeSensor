import { expect, test, type Route } from "@playwright/test";

import {
  bootLiveDashboard,
  cancelPrompt,
  confirmPrompt,
  installSettingsRoutes,
  openAnalysisTab,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

const activeCarSettings = {
  cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }],
  active_car_id: "car-1",
};

test("analysis tab adds guided helper copy and can reset tuning to defaults", async ({
  page,
}) => {
  let lastAnalysisPayload: Record<string, number> = {
    tire_width_mm: 285,
    tire_aspect_pct: 30,
    rim_in: 21,
    final_drive_ratio: 3.08,
    current_gear_ratio: 0.64,
    speed_uncertainty_pct: 3,
    tire_diameter_uncertainty_pct: 4,
    final_drive_uncertainty_pct: 1,
    gear_uncertainty_pct: 2,
    tire_deflection_factor: 0.97,
  };
  let analysisPutCalls = 0;
  await installSettingsRoutes(page, {
    "/api/settings/cars": activeCarSettings,
    "GET /api/settings/analysis": () => lastAnalysisPayload,
    "PUT /api/settings/analysis": async (route: Route) => {
      analysisPutCalls += 1;
      lastAnalysisPayload = route.request().postDataJSON() as Record<
        string,
        number
      >;
      return {
        ...lastAnalysisPayload,
        tire_width_mm: 285,
        tire_aspect_pct: 30,
        rim_in: 21,
        final_drive_ratio: 3.08,
        current_gear_ratio: 0.64,
        tire_deflection_factor: 0.97,
      };
    },
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

  await expect(page.locator("#speedUncertaintyGuidance")).toContainText(
    "Recommended 0% to 5%",
  );
  await expect(page.locator("#speedUncertaintyGuidance")).toContainText(
    "Default 1%",
  );
  await expect(page.locator("#speedUncertaintyGuidance")).not.toContainText(
    "Allowed 0% to 100%",
  );

  await page.locator("#resetAnalysisBtn").click();
  await confirmPrompt(page);
  await expect.poll(() => analysisPutCalls).toBe(1);
  await expect(page.locator("#speedUncertaintyInput")).toHaveValue("1");
  await expect(page.locator("#gearUncertaintyInput")).toHaveValue("0.2");
  expect(lastAnalysisPayload).toMatchObject({
    final_drive_uncertainty_pct: 0.1,
    gear_uncertainty_pct: 0.2,
    speed_uncertainty_pct: 1,
    tire_diameter_uncertainty_pct: 1,
  });
});

test("analysis settings ask for confirmation before saving risky values", async ({
  page,
}) => {
  let analysisPutCalls = 0;
  let lastSavedPayload: Record<string, number> | null = null;
  await installSettingsRoutes(page, {
    "/api/settings/cars": activeCarSettings,
    "PUT /api/settings/analysis": async (route: Route) => {
      analysisPutCalls += 1;
      lastSavedPayload = route.request().postDataJSON() as Record<
        string,
        number
      >;
      return lastSavedPayload;
    },
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#speedUncertaintyInput").fill("40");
  await page.locator("#saveAnalysisBtn").click();
  await expect(page.locator(".confirmation-dialog")).toContainText(
    "Speed Uncertainty (%)",
  );
  await expect(page.locator(".confirmation-dialog")).toContainText(
    "guided 0% to 5%",
  );
  await cancelPrompt(page);
  await expect.poll(() => analysisPutCalls).toBe(0);
  expect(lastSavedPayload).toBeNull();
  await expect(page.locator("#speedUncertaintyInput")).toHaveValue("40");

  await page.locator("#saveAnalysisBtn").click();
  await confirmPrompt(page);
  await expect.poll(() => analysisPutCalls).toBe(1);
  expect(lastSavedPayload).toMatchObject({
    speed_uncertainty_pct: 40,
  });
});

test("analysis settings show a field-specific error when a hard limit is exceeded", async ({
  page,
}) => {
  let analysisPutCalls = 0;
  await installSettingsRoutes(page, {
    "/api/settings/cars": activeCarSettings,
    "PUT /api/settings/analysis": async (route: Route) => {
      analysisPutCalls += 1;
      return route.request().postDataJSON();
    },
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#speedUncertaintyInput").fill("120");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPutCalls).toBe(0);
  await expect(page.locator("#speedUncertaintyGuidance")).toContainText(
    "Speed Uncertainty (%) must stay between 0% and 100%",
  );
  await expect(page.locator("#analysisGuidanceHelp")).toHaveAttribute(
    "open",
    "",
  );
  await expect(page.locator("#speedUncertaintyInput")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.locator("#speedUncertaintyInput")).toBeFocused();
  await expect(page.locator("#analysisSaveFeedback")).toBeHidden();
});

test("failed analysis save preserves the draft and explains that saved settings remain active", async ({
  page,
}) => {
  let analysisPutCalls = 0;
  await installSettingsRoutes(page, {
    "/api/settings/cars": activeCarSettings,
    "PUT /api/settings/analysis": async (route: Route) => {
      analysisPutCalls += 1;
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Analysis save failed" }),
      });
    },
    "GET /api/settings/analysis": {
      tire_width_mm: 285,
      tire_aspect_pct: 30,
      rim_in: 21,
      final_drive_ratio: 3.08,
      current_gear_ratio: 0.64,
      speed_uncertainty_pct: 1,
      tire_diameter_uncertainty_pct: 2,
      final_drive_uncertainty_pct: 1,
      gear_uncertainty_pct: 1,
      tire_deflection_factor: 0.97,
    },
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#speedUncertaintyInput").fill("2.5");
  await page.locator("#gearUncertaintyInput").fill("3");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPutCalls).toBe(1);
  await expect(page.locator("#analysisSaveFeedback")).toBeVisible();
  await expect(page.locator("#analysisSaveFeedback")).toContainText(
    "Analysis save failed",
  );
  await expect(page.locator("#analysisSaveFeedback")).toContainText(
    "previous saved analysis settings remain active",
  );
  await expect(page.locator("#speedUncertaintyInput")).toHaveValue("2.5");
  await expect(page.locator("#gearUncertaintyInput")).toHaveValue("3");
  await expect(page.locator("#analysisGuidanceHelp")).toHaveAttribute(
    "open",
    "",
  );
  await expect(
    page.locator("#analysisSaveFeedback .settings-feedback"),
  ).toHaveAttribute("data-tone", "error");
});
