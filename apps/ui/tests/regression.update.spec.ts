import { expect, test } from "@playwright/test";

import { createHealthyUpdateStatus } from "./maintenance_payload_test_support";
import {
  bootLiveDashboard,
  fulfillJson,
  installCommonRoutes,
  openInternetTab,
  openUpdateTab,
} from "./smoke.helpers";

test.describe.configure({ timeout: 15_000 });

test("settings update tab renders readiness guidance when idle", async ({
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
  await expect(page.locator("#updateOverviewPanel")).toContainText(
    "Ready to start once the Pi has either temporary Wi-Fi credentials or a usable USB internet uplink.",
  );
  await expect(page.locator("#updateOverviewPanel")).toContainText(
    "Background service health",
  );
  await expect(page.locator("#updateOverviewPanel")).toContainText("1.2.3");
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "Update journey",
  );
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "Validating...",
  );
  await expect(page.locator("#updateStatusPanel")).not.toContainText(
    "No blockers recorded",
  );
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "No updater log yet",
  );
  await expect(page.locator("#updateStatusPanel")).not.toContainText(
    "Background service health",
  );
  await expect(page.locator("#updateStartBtn")).toBeDisabled();
  await openInternetTab(page);
  await expect(page.locator("#updateTransportOptions")).toHaveJSProperty(
    "hidden",
    false,
  );
  await expect(page.locator("#updateTransportChoiceWifi")).toHaveAttribute(
    "data-selected",
    "true",
  );
  await expect(page.locator("#updateTransportChoiceWifi")).toHaveAttribute(
    "data-choice-state",
    "active",
  );
  await expect(page.locator("#updateTransportChoiceWifi")).toHaveAttribute(
    "data-choice-badge",
    "Selected",
  );
  await expect(page.locator("#updateTransportChoiceUsb")).toHaveAttribute(
    "data-disabled",
    "true",
  );
  await expect(page.locator("#updateTransportChoiceUsb")).toContainText(
    "USB internet is not ready yet.",
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Complete the blocked item before starting the update.",
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Enter a Wi-Fi SSID to enable Start Update.",
  );
  await expect(page.locator("#internetTab")).toContainText("What happens next");
  await expect(page.locator("#updateDetailsCaption")).toContainText(
    "Hotspot access pauses while the Pi joins Wi-Fi.",
  );
  await expect(page.locator("#internetTab")).toContainText(
    "Starting a Wi-Fi update temporarily pauses hotspot access",
  );
  await page.locator("#updateSsidInput").fill("Workshop Wi-Fi");
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "All visible prerequisites are ready to start the update.",
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "A Wi-Fi network name is entered and ready to use.",
  );
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
});

test("settings internet tab and updater show USB internet when usable", async ({
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
  await bootLiveDashboard(page, { installRoutes: false });
  await openInternetTab(page);
  await expect(page.locator("#internetStatusPanel")).toContainText(
    "USB internet status",
  );
  await expect(page.locator("#internetStatusPanel")).toContainText("usb0");
  await expect(page.locator("#internetStatusPanel")).toContainText("Usable");
  await expect(page.locator("#updateTransportOptions")).toHaveJSProperty(
    "hidden",
    false,
  );
  await expect(page.locator("#updateTransportChoiceUsb")).toContainText(
    "Existing USB internet",
  );
  await page.locator("#updateTransportChoiceUsb").click();
  await expect(page.locator("#updateTransportChoiceUsb")).toHaveAttribute(
    "data-selected",
    "true",
  );
  await expect(page.locator("#updateTransportChoiceUsb")).toHaveAttribute(
    "data-choice-state",
    "active",
  );
  await expect(page.locator("#updateTransportChoiceUsb")).toHaveAttribute(
    "data-choice-badge",
    "Selected",
  );
  await expect(page.locator("#updateWifiFields")).toHaveJSProperty(
    "hidden",
    true,
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "USB internet is ready on usb0.",
  );
  await expect(page.locator("#updateDetailsCaption")).toContainText(
    "The hotspot stays up while the USB uplink is reused.",
  );
  await expect(page.locator("#updateTransportNote")).toContainText(
    "Starting a USB-internet update keeps the hotspot up",
  );
  await page.locator("#updateTransportWifiRadio").focus();
  await expect(page.locator("#updateTransportWifiRadio")).toBeFocused();
  await expect(page.locator("#updateTransportChoiceUsb")).toHaveAttribute(
    "data-choice-state",
    "active",
  );
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
});

test("settings internet tab restores persisted Wi-Fi SSID after reboot", async ({
  page,
}) => {
  await installCommonRoutes(page);
  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, {
      state: "idle",
      phase: "idle",
      transport: "wifi",
      ssid: "Workshop Wi-Fi",
      uplink_interface: null,
      started_at: null,
      phase_started_at: null,
      phase_elapsed_s: null,
      finished_at: null,
      last_success_at: 123,
      updated_at: 123,
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
  await openInternetTab(page);
  await expect(page.locator("#updateSsidInput")).toHaveValue("Workshop Wi-Fi");
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "All visible prerequisites are ready to start the update.",
  );
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
});

test("settings internet tab toggles the Wi-Fi password field without losing the draft", async ({
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
  await openInternetTab(page);
  await page.locator("#updatePasswordInput").fill("secret");
  await expect(page.locator("#updatePasswordInput")).toHaveAttribute(
    "type",
    "password",
  );
  await expect(page.locator("#updateTogglePasswordBtn")).toContainText("Show");
  await page.locator("#updateTogglePasswordBtn").click();
  await expect(page.locator("#updatePasswordInput")).toHaveAttribute(
    "type",
    "text",
  );
  await expect(page.locator("#updateTogglePasswordBtn")).toContainText("Hide");
  await expect(page.locator("#updatePasswordInput")).toHaveValue("secret");
  await page.locator("#updateTogglePasswordBtn").click();
  await expect(page.locator("#updatePasswordInput")).toHaveAttribute(
    "type",
    "password",
  );
  await expect(page.locator("#updatePasswordInput")).toHaveValue("secret");
});

test("settings update failure shows retry guidance, failed-stage retention, and latest attempt context", async ({
  page,
}) => {
  await installCommonRoutes(page);
  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, {
      state: "failed",
      phase: "downloading",
      transport: "usb_internet",
      ssid: null,
      uplink_interface: "usb0",
      started_at: 1,
      phase_started_at: 1,
      phase_elapsed_s: 42,
      finished_at: 2,
      last_success_at: null,
      updated_at: 2,
      issues: [
        {
          phase: "downloading",
          message: "GitHub release download timed out",
          detail:
            "The upstream connection dropped while fetching the release package.",
        },
      ],
      log_tail: [],
      exit_code: 28,
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
  await bootLiveDashboard(page, { installRoutes: false });
  await openInternetTab(page);
  await page.locator("#updateTransportChoiceUsb").click();
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Recovery guidance",
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Failed step",
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Downloading update",
  );
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Check upstream connectivity",
  );
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toHaveText("Retry Update");
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "GitHub release download timed out",
  );
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "Latest attempt",
  );
  await expect(page.locator("#updateStatusPanel")).toContainText("Exit code");
  await expect(page.locator("#updateStatusPanel")).toContainText(
    "No failure log was captured",
  );
  await expect(
    page.locator(
      '#updateStatusPanel .maintenance-stage[data-stage-phase="downloading"]',
    ),
  ).toHaveAttribute("data-stage-state", "attention");
});

test("settings update recovery keeps Retry Update enabled even when readiness stays blocked", async ({
  page,
}) => {
  await installCommonRoutes(page);
  await page.route("**/api/update/status", async (route) => {
    await fulfillJson(route, {
      state: "failed",
      phase: "downloading",
      transport: "usb_internet",
      ssid: null,
      uplink_interface: null,
      started_at: 1,
      phase_started_at: 1,
      phase_elapsed_s: 42,
      finished_at: 2,
      last_success_at: null,
      updated_at: 2,
      issues: [
        {
          phase: "downloading",
          message: "GitHub release download timed out",
          detail:
            "The upstream connection dropped while fetching the release package.",
        },
      ],
      log_tail: [],
      exit_code: 28,
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
    await fulfillJson(
      route,
      createHealthyUpdateStatus({
        status: "degraded",
        degradation_reasons: ["disk"],
        persistence: {
          ...createHealthyUpdateStatus().persistence,
          write_error: "disk full",
        },
      }),
    );
  });
  await page.route("**/api/update/internet-status", async (route) => {
    await fulfillJson(route, {
      detected: false,
      usable: false,
      interface_name: null,
      connection_name: null,
      driver: null,
      ipv4_addresses: [],
      gateway: null,
      has_default_route: false,
      diagnostic: "USB internet is not available.",
    });
  });
  await bootLiveDashboard(page, { installRoutes: false });
  await openInternetTab(page);
  await expect(page.locator("#updateReadinessSummary")).toContainText(
    "Clear the blocked item before retrying.",
  );
  await openUpdateTab(page);
  await expect(page.locator("#updateStartBtn")).toHaveText("Retry Update");
  await expect(page.locator("#updateStartBtn")).toBeEnabled();
});
