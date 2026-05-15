import { expect, test } from "@playwright/test";

import { createDeferred } from "./deferred_test_helpers";
import {
  gpsStatus,
  installSettingsRoutes,
  installFakeWebSocket,
  obdStatus,
  speedSourceSettings,
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
  let scanCalls = 0;
  await installSettingsRoutes(page, {
    "GET /api/settings/speed-source": speedSourceSettings({
      speed_source: "obd2",
      obd_device_mac: null,
      obd_device_name: null,
    }),
    "GET /api/settings/speed-source/status": gpsStatus({
      speed_source: "obd2",
      connection_state: "disconnected",
    }),
    "GET /api/settings/obd/status": obdStatus(),
    "POST /api/settings/obd/scan": async () => {
      scanCalls += 1;
      return await scanResponse.promise;
    },
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
  await expect.poll(() => scanCalls).toBe(1);
  await expect(scanStatus).toContainText("1 adapter(s) found.");
  const deviceRow = page.locator(".speed-source-device").first();
  await expect(deviceRow.locator(".speed-source-device__name")).toHaveText(
    "OBDLink CX",
  );
  await expect(deviceRow.locator(".speed-source-device__mac")).toHaveText(
    "0022d9001bb1",
  );
  await expect(
    deviceRow.locator(".speed-source-device__actions .btn"),
  ).toHaveText("Pair and use");
  await expect(page.locator("#appErrorBanner")).toBeHidden();
  await expect(scanStatus).not.toContainText("aborted");
});
