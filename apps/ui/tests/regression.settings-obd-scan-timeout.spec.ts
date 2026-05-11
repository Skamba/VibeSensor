import { expect, test } from "@playwright/test";

import { createDeferred } from "./async_test_helpers";
import {
  createSettingsHandlerFromMap,
  gpsStatus,
  installCommonRoutes,
  installFakeWebSocket,
} from "./smoke.helpers";

test("manual OBD scan renders a successful response without surfacing an abort banner", async ({
  page,
}) => {
  const scanPayload = {
    devices: [
      {
        mac_address: "0022d9001bb1",
        name: "OBDLink CX",
        paired: false,
        trusted: false,
        connected: false,
        rfcomm_channel: null,
      },
    ],
  };
  const scanResponse = createDeferred<typeof scanPayload>();
  await installCommonRoutes(page, {
    settingsHandler: createSettingsHandlerFromMap({
      "GET /api/settings/language": { language: "en" },
      "GET /api/settings/speed-unit": { speed_unit: "kmh" },
      "GET /api/settings/speed-source": {
        speed_source: "obd2",
        manual_speed_kph: null,
        stale_timeout_s: 5,
        obd_device_mac: null,
        obd_device_name: null,
      },
      "GET /api/settings/speed-source/status": gpsStatus({
        speed_source: "obd2",
        connection_state: "disconnected",
      }),
      "GET /api/settings/obd/status": {
        configured_device_mac: null,
        configured_device_name: null,
        paired: false,
        trusted: false,
        connected: false,
        rfcomm_channel: null,
        last_rpm: null,
        rpm_sample_age_s: null,
        rpm_target_interval_ms: 50,
        rpm_effective_hz: null,
        request_rtt_ms: null,
        timeout_count: 0,
        error_count: 0,
        poll_mode: null,
        backoff_active: false,
        last_raw_response: null,
        debug_hint: null,
      },
      "POST /api/settings/obd/scan": async () => await scanResponse.promise,
    }),
  });
  await installFakeWebSocket(page);

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="speedSourceTab"]').click();
  await page.locator("#scanObdDevicesBtn").click();

  const scanStatus = page.locator("#obdDeviceScanStatus");
  await expect(scanStatus).toContainText(
    "Scanning for Bluetooth OBD adapters...",
  );
  scanResponse.resolve(scanPayload);
  await expect(scanStatus).toContainText("1 adapter(s) found.");
  await expect(page.locator(".speed-source-device__name").first()).toHaveText(
    "OBDLink CX",
  );
  await expect(page.locator("#appErrorBanner")).toBeHidden();
});
