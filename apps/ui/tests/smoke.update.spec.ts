import { expect, test } from "@playwright/test";

import { fulfillJson, installCommonRoutes, installFakeWebSocket } from "./smoke.helpers";

test("settings update tab renders readiness guidance when idle", async ({ page }) => {
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
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "Ready to start once the Pi has either temporary Wi-Fi credentials or a usable USB internet uplink.",
  );
  await expect(page.locator("#updateStatusPanel")).not.toContainText("Update journey");
  await expect(page.locator("#updateStatusPanel")).not.toContainText("No blockers recorded");
  await expect(page.locator("#updateStatusPanel")).toContainText("No updater log yet");
  await expect(page.locator("#updateStatusPanel")).toContainText("1.2.3");
  await expect(page.locator("#updateStatusPanel")).toContainText("Background service health");
  await expect(page.locator("#updateTransportOptions")).toHaveJSProperty("hidden", true);
  await expect(page.locator("#updateUsbTransportOption")).toHaveJSProperty("hidden", true);
  await expect(page.locator("#updateTab")).not.toContainText("Review before you start");
  await expect(page.locator("#updateTab")).not.toContainText("What happens next");
  await expect(page.locator("#updateTab")).not.toContainText("If something goes wrong");
  await expect(page.locator("#updateTab")).toContainText(
    "Starting a Wi-Fi update temporarily pauses hotspot access",
  );
  await expect(page.locator("#updateTab")).not.toContainText("The hotspot pauses while the Pi joins the Wi-Fi network you provide.");
});

test("settings internet tab and updater show USB internet when usable", async ({ page }) => {
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
  await page.route("**/api/update/internet-status", async (route) => {
    await fulfillJson(route, {
      detected: true,
      usable: true,
      interface_name: "usb0",
      connection_name: "iPhone USB",
      driver: "ipheth",
      ipv4_addresses: ["172.20.10.2/28"],
      gateway: "172.20.10.1",
      has_default_route: true,
      diagnostic: "USB internet is ready on 'usb0'.",
    });
  });
  await installFakeWebSocket(page);
  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="internetTab"]').click();
  await expect(page.locator("#internetStatusPanel")).toContainText("USB internet status");
  await expect(page.locator("#internetStatusPanel")).toContainText("usb0");
  await expect(page.locator("#internetStatusPanel")).toContainText("Usable");
  await page.locator('[data-settings-tab="updateTab"]').click();
  await expect(page.locator("#updateTransportOptions")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#updateUsbTransportOption")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#updateUsbTransportOption")).toContainText("Existing USB internet");
});
