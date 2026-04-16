import { expect, test } from "@playwright/test";

import {
  activateWizardCloseButton,
  buildCaptureReadiness,
  confirmPrompt,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  readSemanticToneStyles,
  requestPath,
} from "./smoke.helpers";

test("dark mode warning pills use semantic theme tokens in Live and Cars", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Needs Work",
              type: "coupe",
              aspects: {
                tire_width_mm: 245,
              },
            },
          ],
          active_car_id: null,
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: buildCaptureReadiness({
        isReady: false,
        sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
        reference: { state: "fail", reasonKey: "active_car_missing" },
        speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
        overall: {
          state: "fail",
          reasonKey: "capture_blocked",
          details: { blocking_check: "reference_ready" },
        },
      }),
    });
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 12,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });

  await page.goto("/");
  const liveHealth = page.locator("#liveRunHealth");
  await expect(liveHealth).toHaveText("Needs attention");
  const liveHealthStyles = await readSemanticToneStyles(liveHealth, {
    surfaceVar: "--pill-warn-bg",
    textVar: "--pill-warn-text",
  });
  expect(liveHealthStyles.backgroundColor).toBe(liveHealthStyles.expectedBackgroundColor);
  expect(liveHealthStyles.color).toBe(liveHealthStyles.expectedColor);

  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();
  const readinessPill = page.locator(
    '#carListBody tr[data-car-id="car-1"] .car-readiness-pill[data-state="incomplete"]',
  );
  await expect(readinessPill).toHaveText("Needs specs");
  const readinessStyles = await readSemanticToneStyles(readinessPill, {
    surfaceVar: "--pill-warn-bg",
    textVar: "--pill-warn-text",
  });
  expect(readinessStyles.backgroundColor).toBe(readinessStyles.expectedBackgroundColor);
  expect(readinessStyles.color).toBe(readinessStyles.expectedColor);
});

test("dark mode quiet danger buttons use semantic danger tokens in Cars", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Active Car",
              type: "sedan",
              aspects: {
                tire_width_mm: 245,
                tire_aspect_pct: 40,
                rim_in: 18,
                final_drive_ratio: 3.91,
                current_gear_ratio: 0.82,
              },
            },
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
  const deleteButton = page.locator('#carListBody tr[data-car-id="car-1"] .car-delete-btn');
  await expect(deleteButton).toBeVisible();

  const idleStyles = await readSemanticToneStyles(deleteButton, {
    surfaceVar: "--button-danger-quiet-surface",
    borderVar: "--button-danger-quiet-border",
    textVar: "--button-danger-quiet-text",
  });
  await expect(deleteButton).toHaveCSS("background-color", idleStyles.expectedBackgroundColor);
  await expect(deleteButton).toHaveCSS("border-top-color", idleStyles.expectedBorderColor);
  await expect(deleteButton).toHaveCSS("color", idleStyles.expectedColor);

  const deleteButtonBox = await deleteButton.boundingBox();
  if (!deleteButtonBox) {
    throw new Error("expected car delete button to have a layout box");
  }
  await page.mouse.move(
    deleteButtonBox.x + (deleteButtonBox.width / 2),
    deleteButtonBox.y + (deleteButtonBox.height / 2),
  );
  await expect.poll(() => deleteButton.evaluate((element) => element.matches(":hover"))).toBe(true);
  await page.waitForTimeout(150);
  const hoverStyles = await readSemanticToneStyles(deleteButton, {
    surfaceVar: "--button-danger-quiet-hover-surface",
    borderVar: "--button-danger-quiet-hover-border",
    textVar: "--button-danger-quiet-text",
  });
  await expect(deleteButton).toHaveCSS("background-color", hoverStyles.expectedBackgroundColor);
  await expect(deleteButton).toHaveCSS("border-top-color", hoverStyles.expectedBorderColor);
  await expect(deleteButton).toHaveCSS("color", hoverStyles.expectedColor);
});

test("routes no-car blockers to the add-car flow from Live and Cars", async ({ page }) => {
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
  await expect(page.locator("#liveActiveCar")).not.toHaveAttribute("data-variant", "warn");
  await expect(page.locator("#liveActiveCar .stat__value-icon")).toHaveCount(0);
  await expect(page.locator("#liveActiveCar [data-value]")).toContainText("No cars added yet");
  await expect(page.locator("#loggingChecklist")).toBeHidden();
  const liveSummary = page.locator("#loggingSummary");
  await expect(liveSummary).toContainText("Add a car before recording.");
  await expect(liveSummary).toContainText("Runs need an active car");
  await liveSummary.getByRole("button", { name: "Add a car" }).click();
  await expect(page.locator("#settingsView")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#wizardBackdrop")).toBeVisible();
  await activateWizardCloseButton(page);
  await expect(page.locator("#carSelectionBanner")).toHaveCount(0);
  await page.locator("#tab-history").click();
  await expect(page.locator("#carSelectionBanner")).toHaveCount(0);
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();
  await expect(page.locator("#carSelectionGuidance")).toBeHidden();
  await expect(page.locator("#carListBody .settings-table-empty-state")).toBeVisible();
  const carEmptyState = page.locator("#carListBody .empty-state");
  await expect(carEmptyState).toContainText("Add the first car profile.");
  await expect(carEmptyState).toContainText("Cars define the setup used for recording");
  await carEmptyState.getByRole("button", { name: "Add a car" }).click();
  await expect(page.locator("#wizardBackdrop")).toBeVisible();
  await activateWizardCloseButton(page);
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(page.locator("#analysisNoCarMessage")).toBeVisible();
  await expect(page.locator("#saveAnalysisBtn")).toBeDisabled();
  await expect(page.locator("#resetAnalysisBtn")).toBeDisabled();
  await page.waitForTimeout(150);
  await expect.poll(() => analysisPutCalls).toBe(0);
});

test("hides contextual car guidance when a valid selected car exists", async ({ page }) => {
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
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="carTab"]').click();
  await expect(page.locator("#carSelectionGuidance")).toBeHidden();
  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(page.locator("#analysisNoCarMessage")).toBeHidden();
  await expect(page.locator("#resetAnalysisBtn")).toBeEnabled();
});

test("keeps contextual no-car guidance hidden until active car bootstrap resolves and then marks the car active", async ({ page }) => {
  let releaseCars: (() => void) | null = null;
  let captureReady = false;
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
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 12,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: captureReady
        ? buildCaptureReadiness({
          isReady: true,
          sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
          reference: { state: "pass", reasonKey: "reference_ready" },
          speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
        })
        : buildCaptureReadiness({
          isReady: false,
          sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
          reference: { state: "fail", reasonKey: "active_car_missing" },
          speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
          overall: {
            state: "fail",
            reasonKey: "capture_blocked",
            details: { blocking_check: "reference_ready" },
          },
        }),
    });
  });
  await page.goto("/");
  await expect(page.locator("#carSelectionBanner")).toHaveCount(0);
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText("Loading active car...");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Blocked");
  await expect(page.locator("#liveRunHealth")).toHaveText("Needs attention");
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#startLoggingBtn")).toBeDisabled();

  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();

  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
  await expect(page.locator("#saveAnalysisBtn")).toBeDisabled();
  await expect(page.locator("#resetAnalysisBtn")).toBeDisabled();
  await expect(page.locator("#analysisNoCarMessage")).toBeHidden();
  await page.locator('[data-settings-tab="carTab"]').click();
  await expect(page.locator("#carSelectionGuidance")).toBeHidden();

  if (!releaseCars) {
    throw new Error("cars bootstrap gate was not initialized");
  }
  captureReady = true;
  releaseCars();

  await page.locator('[data-settings-tab="analysisTab"]').click();
  await expect(page.locator("#saveAnalysisBtn")).toBeEnabled();
  await expect(page.locator("#resetAnalysisBtn")).toBeEnabled();
  await expect(page.locator("#analysisNoCarMessage")).toBeHidden();

  await page.locator('[data-settings-tab="carTab"]').click();
  await expect(page.locator("#carSelectionGuidance")).toBeHidden();
  const activeRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(activeRow).toContainText("Audit Demo Car");
  await expect(activeRow.locator(".car-active-pill")).toHaveAttribute("data-state", "active");

  await page.locator("#tab-dashboard").click();
  await expect(page.locator("#liveActiveCar")).not.toHaveAttribute("data-variant", "warn");
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText("Audit Demo Car");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Ready");
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#startLoggingBtn")).toBeEnabled();
});

test("shows a live warning state until an active car is selected, then clears it automatically", async ({ page }) => {
  let activeCarId: string | null = null;
  let startCalls = 0;
  const completeAspects = {
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 18,
    final_drive_ratio: 3.91,
    current_gear_ratio: 0.82,
  };

  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        await fulfillJson(route, {
          cars: [
            { id: "car-1", name: "Touring", type: "wagon", aspects: completeAspects },
            { id: "car-2", name: "Coupe", type: "coupe", aspects: completeAspects },
          ],
          active_car_id: activeCarId,
        });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        activeCarId = "car-2";
        await fulfillJson(route, {
          cars: [
            { id: "car-1", name: "Touring", type: "wagon", aspects: completeAspects },
            { id: "car-2", name: "Coupe", type: "coupe", aspects: completeAspects },
          ],
          active_car_id: activeCarId,
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: activeCarId
        ? buildCaptureReadiness({
          isReady: true,
          sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
          reference: { state: "pass", reasonKey: "reference_ready" },
          speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
        })
        : buildCaptureReadiness({
          isReady: false,
          sensors: { state: "pass", reasonKey: "sensors_ready", details: { live_sensor_count: 1 } },
          reference: { state: "fail", reasonKey: "active_car_missing" },
          speed: { state: "pass", reasonKey: "speed_stable", details: { dwell_elapsed_s: 8 } },
          overall: {
            state: "fail",
            reasonKey: "capture_blocked",
            details: { blocking_check: "reference_ready" },
          },
        }),
    });
  });
  await page.route("**/api/recording/start", async (route) => {
    startCalls += 1;
    await fulfillJson(route, {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
    });
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 12,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });

  await page.goto("/");
  await expect(page.locator("#liveActiveCar")).not.toHaveAttribute("data-variant", "warn");
  await expect(page.locator("#liveActiveCar .stat__value-icon")).toHaveCount(0);
  await expect(page.locator("#liveActiveCar [data-value]")).toContainText("No active car selected");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Blocked");
  await expect(page.locator("#liveRunHealth")).toHaveText("Needs attention");
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#loggingChecklist")).toBeHidden();
  const liveSummary = page.locator("#loggingSummary");
  await expect(liveSummary).toContainText("Choose the active car before recording.");
  await expect(liveSummary).toContainText("none is active for the next run");
  await expect(page.locator("#loggingSummary")).toHaveCSS("text-align", "left");
  await expect(page.locator("#startLoggingBtn")).toBeHidden();
  await expect(page.locator("#startLoggingBtn")).toBeDisabled();
  await expect.poll(() => startCalls).toBe(0);

  await liveSummary.getByRole("button", { name: "Choose active car" }).click();
  await expect(page.locator("#settingsView")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#carTab")).toHaveJSProperty("hidden", false);
  await page.locator('#carListBody tr[data-car-id="car-2"] .car-activate-btn').click();

  await page.locator("#tab-dashboard").click();
  await expect(page.locator("#liveActiveCar")).not.toHaveAttribute("data-variant", "warn");
  await expect(page.locator("#liveActiveCar .stat__value-icon")).toHaveCount(0);
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText("Coupe");
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText("Ready");
  await expect(page.locator("#loggingStatus")).toBeHidden();
  await expect(page.locator("#startLoggingBtn")).toBeVisible();
  await expect(page.locator("#startLoggingBtn")).toBeEnabled();
});

test("shows car-tab guidance for invalid persisted selection and after deleting the selected car", async ({ page }) => {
  let firstCarsGet = true;
  const completeAspects = {
    tire_width_mm: 245,
    tire_aspect_pct: 40,
    rim_in: 18,
    final_drive_ratio: 3.91,
    current_gear_ratio: 0.82,
  };
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        if (firstCarsGet) {
          firstCarsGet = false;
          await fulfillJson(route, {
            cars: [
              { id: "car-1", name: "One", type: "sedan", aspects: completeAspects },
              { id: "car-2", name: "Two", type: "suv", aspects: completeAspects },
            ],
            active_car_id: "missing-car",
          });
          return;
        }
        await fulfillJson(route, {
          cars: [
            { id: "car-1", name: "One", type: "sedan", aspects: completeAspects },
            { id: "car-2", name: "Two", type: "suv", aspects: completeAspects },
          ],
          active_car_id: "car-2",
        });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        await fulfillJson(route, {
          cars: [
            { id: "car-1", name: "One", type: "sedan", aspects: completeAspects },
            { id: "car-2", name: "Two", type: "suv", aspects: completeAspects },
          ],
          active_car_id: "car-2",
        });
        return;
      }
      if (path === "/api/settings/cars/car-2" && method === "DELETE") {
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "One", type: "sedan", aspects: completeAspects }],
          active_car_id: null,
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await expect(page.locator("#carSelectionGuidance")).toBeVisible();
  await page.locator("#carListBody .car-activate-btn").last().click();
  await expect(page.locator("#carSelectionGuidance")).toBeHidden();
  await page.locator('#carListBody tr[data-car-id="car-2"] .car-delete-btn').click();
  await confirmPrompt(page);
  await expect(page.locator("#carSelectionGuidance")).toBeVisible();
});

test("routes incomplete cars through Finish setup instead of generic activation", async ({ page }) => {
  let activateCalls = 0;
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/cars" && method === "GET") {
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Ready Car",
              type: "sedan",
              aspects: {
                tire_width_mm: 245,
                tire_aspect_pct: 40,
                rim_in: 18,
                final_drive_ratio: 3.91,
                current_gear_ratio: 0.82,
              },
            },
            {
              id: "car-2",
              name: "Needs Work",
              type: "coupe",
              aspects: {
                tire_width_mm: 245,
              },
            },
          ],
          active_car_id: "car-1",
        });
        return;
      }
      if (path === "/api/settings/cars/active" && method === "PUT") {
        activateCalls += 1;
        await fulfillJson(route, {
          cars: [
            {
              id: "car-1",
              name: "Ready Car",
              type: "sedan",
              aspects: {
                tire_width_mm: 245,
                tire_aspect_pct: 40,
                rim_in: 18,
                final_drive_ratio: 3.91,
                current_gear_ratio: 0.82,
              },
            },
            {
              id: "car-2",
              name: "Needs Work",
              type: "coupe",
              aspects: {
                tire_width_mm: 245,
              },
            },
          ],
          active_car_id: "car-2",
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

  const incompleteRow = page.locator('#carListBody tr[data-car-id="car-2"]');
  await expect(incompleteRow).toContainText("Inactive");
  await expect(incompleteRow).toContainText("Needs specs");
  await expect(incompleteRow).toContainText("Tire size not set");
  await expect(incompleteRow).toContainText("Not set");
  await expect(incompleteRow.locator(".car-activate-btn")).toHaveCount(0);
  await expect(incompleteRow.getByRole("button", { name: "Finish setup" })).toBeVisible();
  await incompleteRow.getByRole("button", { name: "Finish setup" }).click();

  await expect.poll(() => activateCalls).toBe(1);
  await expect(page.locator("#analysisTab")).toHaveJSProperty("hidden", false);
});

test("returns from the add-car flow with visible success feedback and row highlighting", async ({ page }) => {
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

  await expect(page.locator("#wizardBackdrop")).toBeHidden();
  await expect(page.locator("#carSelectionGuidance")).toContainText("Car added");
  await expect(page.locator("#carSelectionGuidance")).toContainText("Track Demo was added and selected for this setup.");
  const createdRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(createdRow).toHaveAttribute("data-highlighted", "true");
  await expect(createdRow).toContainText("Active");
  await expect(createdRow).toContainText("Ready");
  await expect(createdRow).toContainText("New");
});
