import { expect, test, type Route } from "@playwright/test";

import { createHealthyUpdateStatus } from "./maintenance_payload_test_support";
import {
  bootLiveDashboard,
  buildCaptureReadiness,
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  openAnalysisTab,
  openCarsTab,
  openHistoryTab,
  openInternetTab,
  openUpdateTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

const strengthMetrics = {
  vibration_strength_db: 12,
  peak_amp_g: 0.2,
  noise_floor_amp_g: 0.01,
  strength_bucket: null,
  top_peaks: [],
};

function selectedCarPayload() {
  return {
    cars: [
      {
        id: "car-1",
        name: "Test Hatch",
        type: "sedan",
        aspects: {},
      },
    ],
    active_car_id: "car-1",
  };
}

async function activeCarSettingsHandler(route: Route): Promise<void> {
  if (requestPath(route).startsWith("/api/settings/cars")) {
    await fulfillJson(route, selectedCarPayload());
    return;
  }
  await fulfillJson(route, {});
}

test("critical journey: live dashboard records and opens History", async ({
  page,
}) => {
  let startCalls = 0;
  let stopCalls = 0;
  let recordingStatus = {
    enabled: false,
    run_id: null as string | null,
    write_error: null,
    analysis_in_progress: false,
    start_time_utc: null as string | null,
    samples_written: 0,
    samples_dropped: 0,
    last_completed_run_id: null as string | null,
    last_completed_run_error: null,
    capture_readiness: buildCaptureReadiness({
      isReady: true,
      sensors: {
        state: "pass",
        reasonKey: "sensors_ready",
        details: { live_sensor_count: 1 },
      },
      reference: { state: "pass", reasonKey: "reference_ready" },
      speed: {
        state: "pass",
        reasonKey: "speed_stable",
        details: { dwell_elapsed_s: 8 },
      },
    }),
  };

  await installCommonRoutes(page, {
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    runs: [
      {
        run_id: "run-001",
        status: "complete",
        start_time_utc: "2026-01-01T00:00:00Z",
        sample_count: 42,
      },
    ],
    settingsHandler: activeCarSettingsHandler,
  });
  await page.route("**/api/recording/start", async (route) => {
    startCalls += 1;
    recordingStatus = {
      ...recordingStatus,
      enabled: true,
      run_id: "run-001",
      start_time_utc: new Date(Date.now() - 30_000).toISOString(),
      samples_written: 24,
      last_completed_run_id: null,
    };
    await fulfillJson(route, recordingStatus);
  });
  await page.route("**/api/recording/stop", async (route) => {
    stopCalls += 1;
    recordingStatus = {
      ...recordingStatus,
      enabled: false,
      run_id: null,
      analysis_in_progress: true,
      start_time_utc: null,
      last_completed_run_id: "run-001",
    };
    await fulfillJson(route, recordingStatus);
  });
  await page.route("**/api/recording/status", async (route) => {
    await fulfillJson(route, recordingStatus);
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
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {
          "001122334455": {
            freq: [1, 2, 3],
            combined_spectrum_amp_g: [0.1, 0.2, 0.15],
            strength_metrics: strengthMetrics,
          },
        },
      },
    },
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "VibeSensor" })).toBeVisible();
  await expect(page.locator("#liveConnectedSensors [data-value]")).toHaveText(
    "1 / 1",
  );
  await expect(page.locator("#liveActiveCar [data-value]")).toHaveText(
    "Test Hatch",
  );

  await page.locator("#startLoggingBtn").click();
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Recording",
  );
  await page.locator("#stopLoggingBtn").click();
  await expect(page.locator("#liveRecordingState [data-value]")).toHaveText(
    "Processing",
  );
  await page
    .locator("#loggingSummary")
    .getByRole("button", { name: "Open History" })
    .click();
  await expect(page.locator("#historyView")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#historyTableBody")).toContainText("run-001");
  await expect.poll(() => startCalls).toBe(1);
  await expect.poll(() => stopCalls).toBe(1);
});

test("critical journey: Settings saves analysis tuning", async ({ page }) => {
  let persistedAnalysisSettings: Record<string, number> = {};
  let analysisPutCalls = 0;

  await installCommonRoutes(page, {
    settingsHandler: activeCarSettingsHandler,
  });
  await page.route("**/api/settings/analysis", async (route) => {
    if (route.request().method() === "PUT") {
      analysisPutCalls += 1;
      persistedAnalysisSettings = route.request().postDataJSON() as Record<
        string,
        number
      >;
      await fulfillJson(route, persistedAnalysisSettings);
      return;
    }
    await fulfillJson(route, persistedAnalysisSettings);
  });

  await bootLiveDashboard(page, { installRoutes: false });
  await openAnalysisTab(page);
  await page.locator("#wheelBandwidthInput").fill("7.5");
  await page.locator("#driveshaftBandwidthInput").fill("8.5");
  await page.locator("#engineBandwidthInput").fill("9.5");
  await page.locator("#speedUncertaintyInput").fill("3");
  await page.locator("#tireDiameterUncertaintyInput").fill("4");
  await page.locator("#finalDriveUncertaintyInput").fill("2");
  await page.locator("#gearUncertaintyInput").fill("4");
  await page.locator("#minAbsBandHzInput").fill("0.7");
  await page.locator("#maxBandHalfWidthInput").fill("12");
  await page.locator("#saveAnalysisBtn").click();
  await expect.poll(() => analysisPutCalls).toBe(1);
  await page.reload();
  await openAnalysisTab(page);
  await expect(page.locator("#wheelBandwidthInput")).toHaveValue("7.5");
});

test("critical journey: car wizard creates and activates a manual car", async ({
  page,
}) => {
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
        cars = [
          {
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
          },
        ];
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

  await bootLiveDashboard(page, { installRoutes: false });
  await openCarsTab(page);
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
  const createdRow = page.locator('#carListBody tr[data-car-id="car-1"]');
  await expect(createdRow).toContainText("Active");
  await expect(createdRow).toContainText("Ready");
});

test("critical journey: History empty state returns users to Live", async ({
  page,
}) => {
  await bootLiveDashboard(page, {
    settingsHandler: activeCarSettingsHandler,
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, { runs: [] });
    },
  });

  await openHistoryTab(page);
  const emptyState = page.locator("#historyTableBody .empty-state");
  await expect(emptyState).toContainText("Capture the first run from Live.");
  await emptyState.getByRole("button", { name: "Go to Live" }).click();
  await expect(page.locator("#dashboardView")).toHaveJSProperty(
    "hidden",
    false,
  );
});

test("critical journey: updater becomes startable after Wi-Fi setup", async ({
  page,
}) => {
  await installCommonRoutes(page);
  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, {
      state: "idle",
      phase: "idle",
      transport: "wifi",
      ssid: null,
      uplink_interface: null,
      started_at: null,
      phase_started_at: null,
      phase_elapsed_s: null,
      finished_at: null,
      last_success_at: null,
      updated_at: null,
      issues: [],
      log_tail: [],
      exit_code: null,
      runtime: {
        version: "1.2.3",
        commit: "abcdef1234567890",
        ui_source_hash: "ui-hash",
        static_assets_hash: "feedfacecafebeef",
        static_build_source_hash: "build-hash",
        static_build_commit: "build-commit",
        assets_verified: true,
        has_packaged_static: true,
      },
    });
  });
  await page.route("**/api/health", async (route) => {
    await fulfillJson(route, createHealthyUpdateStatus());
  });

  await bootLiveDashboard(page, { installRoutes: false });
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeDisabled();
  await openInternetTab(page);
  await page.locator("#updateSsidInput").fill("Workshop Wi-Fi");
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "All visible prerequisites are ready to start the update.",
  );
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
});
