import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket, requestPath } from "./smoke.helpers";

test("ui bootstrap smoke: tabs, ws state, recording, history", async ({ page }) => {
  let startCalls = 0;
  let stopCalls = 0;

  await installCommonRoutes(page, {
    runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }],
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
    historyHandler: async (route) => {
      const pathname = requestPath(route);
      if (!pathname.startsWith("/api/history") || pathname.includes("/report.pdf")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, {
        runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }],
      });
    },
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/esp-flash/")) {
        await route.fallback();
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await page.route("**/api/logging/start", async (route) => {
    startCalls += 1;
    await fulfillJson(route, { enabled: true, current_file: "run-001.jsonl" });
  });
  await page.route("**/api/logging/stop", async (route) => {
    stopCalls += 1;
    await fulfillJson(route, { enabled: false, current_file: null });
  });

  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [{ id: "001122334455", name: "Front Left", connected: true, sample_rate_hz: 1000, last_seen_age_ms: 10, dropped_frames: 0, frames_total: 100 }],
      diagnostics: { strength_bands: [{ key: "wheel", label: "Wheel", color: "#2f80ed" }], events: [] },
      spectra: { clients: { "001122334455": { freq: [1, 2, 3], combined_spectrum_amp_g: [0.1, 0.2, 0.15], strength_metrics: { vibration_strength_db: 12 } } } },
    },
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "VibeSensor" })).toBeVisible();
  await expect(page.locator("#linkState")).not.toHaveText(/Connecting/i);
  await page.locator("#tab-dashboard").focus();
  await page.locator("#tab-dashboard").press("ArrowRight");
  await expect(page.locator("#historyView")).toHaveClass(/active/);
  await page.locator("#tab-history").click();
  await expect(page.locator("#historyView")).toHaveClass(/active/);
  await expect(page.locator("#historyTableBody")).toContainText("run-001");
  await page.locator("#tab-dashboard").click();
  await page.locator("#startLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toHaveText("Running");
  await expect.poll(() => startCalls).toBe(1);
  await page.locator("#stopLoggingBtn").click();
  await expect(page.locator("#loggingStatus")).toHaveText("Stopped");
  await expect.poll(() => stopCalls).toBe(1);
});
