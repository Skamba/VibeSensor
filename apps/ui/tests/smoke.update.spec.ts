import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket } from "./smoke.helpers";

test("settings update tab renders readiness guidance when idle", async ({ page }) => {
  await installCommonRoutes(page);
  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, {
      state: "idle",
      phase: "idle",
      ssid: null,
      started_at: null,
      phase_started_at: null,
      phase_elapsed_s: null,
      finished_at: null,
      last_success_at: null,
      issues: [],
      log_tail: [],
      runtime: {
        version: "1.2.3",
        commit: "abcdef1234567890",
        static_assets_hash: "feedfacecafebeef",
        assets_verified: true,
      },
    });
  });
  await page.route("**/api/health", async (route) => {
    await fulfillJson(route, {
      status: "ok",
      processing_state: "idle",
      processing_failures: 0,
      degradation_reasons: [],
      data_loss: {
        affected_clients: 0,
        tracked_clients: 0,
        frames_dropped: 0,
        queue_overflow_drops: 0,
        server_queue_drops: 0,
        parse_errors: 0,
      },
      persistence: {
        analysis_in_progress: false,
        analysis_queue_depth: 0,
        write_error: null,
        analysis_active_run_id: null,
        analysis_started_at: null,
        analysis_elapsed_s: null,
      },
    });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="updateTab"]').click();
  await expect(page.locator("#updateStatusPanel")).toContainText("Ready to start once the Pi has temporary Wi-Fi credentials");
  await expect(page.locator("#updateStatusPanel")).toContainText("Update journey");
  await expect(page.locator("#updateStatusPanel")).toContainText("No blockers recorded");
  await expect(page.locator("#updateStatusPanel")).toContainText("No updater log yet");
  await expect(page.locator("#updateStatusPanel")).toContainText("1.2.3");
  await expect(page.locator("#updateTab")).toContainText("Review before you start");
  await expect(page.locator("#updateTab")).toContainText("Starting an update temporarily pauses hotspot access");
  await expect(page.locator("#updateTab")).toContainText("The hotspot pauses while the Pi joins the Wi-Fi network you provide.");
});
