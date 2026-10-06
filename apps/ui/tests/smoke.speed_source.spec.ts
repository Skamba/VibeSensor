import { expect, test, type Page } from "@playwright/test";

import type {
  CarsPayload,
  ObdPairPayload,
  ObdScanPayload,
  ObdStatusPayload,
  SpeedSourcePayload,
  SpeedSourceRequest,
  SpeedSourceStatusPayload,
  SpeedUnitPayload,
} from "../src/api/types";
import {
  bootLiveDashboard,
  fulfillJson,
  openSpeedSourceTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

type SpeedSourceServer = {
  saved: SpeedSourcePayload;
  puts: SpeedSourceRequest[];
  scans: number;
  pairs: string[];
  failNextPut: boolean;
  putDelayMs?: number;
  /** gpsd runs but has never seen a receiver. */
  noGpsReceiver?: boolean;
};

function statusPayload(server: SpeedSourceServer): SpeedSourceStatusPayload {
  const source = server.saved.speed_source;
  if (server.noGpsReceiver) {
    return {
      ...statusPayload({ ...server, noGpsReceiver: false }),
      device: null,
      fix_wait_s: null,
      effective_speed_kmh: null,
      fix_dimension: "none",
      fix_mode: null,
      last_update_age_s: null,
      raw_speed_kmh: null,
      speed_confidence: "low",
      speed_source: "none",
    };
  }
  return {
    connection_state: "connected",
    device: "/dev/ttyACM0",
    fix_wait_s: null,
    effective_speed_kmh:
      source === "manual" ? server.saved.manual_speed_kph : 52.3,
    epv_m: null,
    epx_m: null,
    epy_m: null,
    fallback_active: false,
    fix_dimension: "3d",
    fix_mode: 3,
    gps_enabled: source === "gps",
    last_error: null,
    last_update_age_s: 0.4,
    raw_speed_kmh: 52.3,
    reconnect_delay_s: null,
    speed_confidence: "high",
    speed_source: source,
    stale_timeout_s: server.saved.stale_timeout_s,
  };
}

function obdStatusPayload(server: SpeedSourceServer): ObdStatusPayload {
  return {
    backoff_active: false,
    configured_device_mac: server.saved.obd_device_mac ?? null,
    configured_device_name: server.saved.obd_device_name ?? null,
    connected: Boolean(server.saved.obd_device_mac),
    connection_state: "connected",
    debug_hint: null,
    device_mac: server.saved.obd_device_mac ?? null,
    device_name: server.saved.obd_device_name ?? null,
    error_count: 0,
    last_error: null,
    last_raw_response: null,
    last_rpm: 850,
    last_sample_age_s: 0.2,
    last_speed_kmh: 0,
    paired: true,
    poll_mode: "rpm_priority",
    reconnect_delay_s: null,
    request_rtt_ms: 40,
    rfcomm_channel: 1,
    rpm_effective_hz: 4,
    rpm_sample_age_s: 0.2,
    rpm_target_interval_ms: 250,
    timeout_count: 0,
    trusted: true,
  };
}

async function installSpeedSourceRoutes(
  page: Page,
  server: SpeedSourceServer,
): Promise<void> {
  await bootLiveDashboard(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      const method = route.request().method();
      if (path === "/api/settings/speed-source" && method === "PUT") {
        const body = route.request().postDataJSON() as SpeedSourceRequest;
        server.puts.push(body);
        await new Promise((resolve) =>
          setTimeout(resolve, server.putDelayMs ?? 0),
        );
        if (server.failNextPut) {
          server.failNextPut = false;
          await route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Settings store unavailable" }),
          });
          return;
        }
        server.saved = {
          ...server.saved,
          manual_speed_kph: body.manual_speed_kph ?? null,
          speed_source: body.speed_source ?? server.saved.speed_source,
          stale_timeout_s: body.stale_timeout_s ?? server.saved.stale_timeout_s,
        };
        await fulfillJson<SpeedSourcePayload>(route, server.saved);
        return;
      }
      if (path === "/api/settings/speed-source") {
        await fulfillJson(route, server.saved);
        return;
      }
      if (path === "/api/settings/speed-source/status") {
        await fulfillJson(route, statusPayload(server));
        return;
      }
      if (path === "/api/settings/obd/status") {
        await fulfillJson(route, obdStatusPayload(server));
        return;
      }
      if (path === "/api/settings/obd/scan") {
        server.scans += 1;
        await fulfillJson<ObdScanPayload>(route, {
          devices: [
            {
              connected: false,
              mac_address: "00:1D:A5:00:00:02",
              name: null,
              paired: false,
              rfcomm_channel: null,
              trusted: false,
            },
            {
              connected: false,
              mac_address: "00:1D:A5:00:00:01",
              name: "OBDII Link",
              paired: false,
              rfcomm_channel: null,
              trusted: false,
            },
          ],
        });
        return;
      }
      if (path === "/api/settings/obd/pair") {
        const body = route.request().postDataJSON() as { mac_address: string };
        server.pairs.push(body.mac_address);
        server.saved = {
          ...server.saved,
          obd_device_mac: body.mac_address,
          obd_device_name: "OBDII Link",
        };
        await fulfillJson<ObdPairPayload>(route, {
          configured_device_mac: body.mac_address,
          configured_device_name: "OBDII Link",
          connected: true,
          paired: true,
          rfcomm_channel: 1,
          trusted: true,
        });
        return;
      }
      if (path.startsWith("/api/settings/cars")) {
        await fulfillJson<CarsPayload>(route, {
          cars: [],
          active_car_id: null,
        });
        return;
      }
      await fulfillJson(route, {});
    },
  });
}

test("journey: Speed source validates, saves a manual override, and recovers from a failed save", async ({
  page,
}) => {
  const server: SpeedSourceServer = {
    saved: { speed_source: "gps", manual_speed_kph: null, stale_timeout_s: 10 },
    puts: [],
    scans: 0,
    pairs: [],
    failNextPut: false,
  };
  await installSpeedSourceRoutes(page, server);
  await openSpeedSourceTab(page);

  await expect(page.locator("#speedSourceCurrentSource")).toHaveText("GPS");
  await expect(page.locator("#speedSourceEffectiveSpeed")).toContainText(
    "52.3",
  );
  await expect(page.locator("#gpsFallbackPanel")).toBeVisible();
  await expect(page.locator("#gpsReceiverMissing")).toHaveCount(0);
  const consequences = page.locator("#speedSourceConsequences");
  await expect(consequences.locator(".speed-source-consequence")).toHaveCount(
    3,
  );
  await expect(consequences).toContainText("assuming top gear (or D)");
  await expect(page.locator("#staleTimeoutInput")).toHaveValue("10");
  await expect(page.locator("#manualSpeedConfig")).toBeHidden();

  // An out-of-range stale timeout is rejected before anything is sent.
  await page.locator("#staleTimeoutInput").fill("500");
  await page.locator("#saveSpeedSourceBtn").click();
  await expect(page.locator("#staleTimeoutFeedback")).toContainText(
    "Enter a stale timeout between 3s and 120s.",
  );
  await expect(page.locator("#staleTimeoutInput")).toBeFocused();
  await page.locator("#staleTimeoutInput").fill("15");

  await page.locator("#speedSourceChoiceManual").click();
  await expect(page.locator("#manualSpeedConfig")).toBeVisible();
  await page.locator("#manualSpeedInput").fill("0");
  await page.locator("#saveSpeedSourceBtn").click();
  await expect(page.locator("#manualSpeedFeedback")).toContainText(
    "Enter a manual speed above 0 and up to 500 km/h.",
  );
  await expect(page.locator("#speedSourceSaveFeedback")).toContainText(
    "GPS remains active right now. No changes were saved.",
  );
  expect(server.puts).toEqual([]);

  await page.locator("#manualSpeedInput").fill("80");
  server.failNextPut = true;
  await page.locator("#saveSpeedSourceBtn").click();
  await expect(page.locator("#speedSourceSaveFeedback")).toContainText(
    "Speed source was not saved.",
  );
  await expect(page.locator("#speedSourceSaveFeedback")).toContainText(
    "Settings store unavailable",
  );
  // The draft survives the failed save.
  await expect(page.locator("#manualSpeedInput")).toHaveValue("80");

  await page.locator("#saveSpeedSourceBtn").click();
  await expect.poll(() => server.puts.length).toBe(2);
  expect(server.puts[1]).toEqual({
    manual_speed_kph: 80,
    speed_source: "manual",
    stale_timeout_s: 15,
  });
  await expect(page.locator("#speedSourceSaveFeedback")).toBeHidden();
  await expect(page.locator("#speedSourceCurrentSource")).toHaveText(
    "Manual override",
  );

  // In m/s the field shows and takes the speed in m/s; it is saved in km/h.
  await page.route("**/api/settings/speed-unit", async (route) => {
    await fulfillJson<SpeedUnitPayload>(route, { speed_unit: "mps" });
  });
  await page.locator("#speedUnitSelect").selectOption("mps");
  await expect(page.locator('label[for="manualSpeedInput"]')).toHaveText(
    "Manual Speed (m/s)",
  );
  await expect(page.locator("#manualSpeedInput")).toHaveValue("22.22");
  await page.locator("#manualSpeedInput").fill("140");
  await page.locator("#saveSpeedSourceBtn").click();
  await expect(page.locator("#manualSpeedFeedback")).toContainText(
    "Enter a manual speed above 0 and up to 138.8 m/s.",
  );
  await page.locator("#manualSpeedInput").fill("25");
  await page.locator("#saveSpeedSourceBtn").click();
  await expect.poll(() => server.puts.length).toBe(3);
  expect(server.puts[2]).toMatchObject({ manual_speed_kph: 90 });
});

test("journey: GPS without a receiver says to plug one in or switch to OBD-II", async ({
  page,
}) => {
  await installSpeedSourceRoutes(page, {
    saved: { speed_source: "gps", manual_speed_kph: null, stale_timeout_s: 10 },
    puts: [],
    scans: 0,
    pairs: [],
    failNextPut: false,
    noGpsReceiver: true,
  });
  await openSpeedSourceTab(page);
  await expect(page.locator("#gpsReceiverMissing")).toContainText(
    "No GPS receiver found",
  );
});

test("journey: Speed source scans, pairs, and saves an OBD-II adapter", async ({
  page,
}) => {
  const server: SpeedSourceServer = {
    saved: { speed_source: "gps", manual_speed_kph: null, stale_timeout_s: 10 },
    puts: [],
    scans: 0,
    pairs: [],
    failNextPut: false,
  };
  await installSpeedSourceRoutes(page, server);
  await openSpeedSourceTab(page);

  await page.locator("#speedSourceChoiceObd").click();
  await expect(page.locator("#obdSpeedConfig")).toBeVisible();
  await expect(page.locator("#obdConfiguredDevice")).toHaveText(
    "No adapter configured",
  );

  // OBD-II cannot be saved without a paired adapter.
  await page.locator("#saveSpeedSourceBtn").click();
  await expect(page.locator("#speedSourceSaveFeedback")).toContainText(
    "Pair a Bluetooth OBD adapter before saving OBD-II as the speed source.",
  );
  await expect(page.locator("#scanObdDevicesBtn")).toBeFocused();
  expect(server.puts).toEqual([]);
  await expect(page.locator("#obdScanInterruptNote")).toContainText(
    "briefly interrupts sensor data",
  );

  await page.locator("#scanObdDevicesBtn").click();
  await expect(page.locator("#obdDeviceScanStatus")).toHaveText(
    "2 adapters found.",
  );
  const devices = page.locator("#obdDeviceList .speed-source-device");
  await expect(devices).toHaveCount(2);
  // Named adapters sort ahead of unnamed ones.
  await expect(devices.first()).toContainText("OBDII Link");
  await expect(devices.nth(1)).toContainText("00:1D:A5:00:00:02");
  await expect(devices.first()).toContainText("Pair and use");

  await page.locator('[data-obd-pair-mac="00:1D:A5:00:00:01"]').click();
  await expect(page.locator("#obdDeviceScanStatus")).toHaveText(
    "Adapter paired and saved.",
  );
  await expect(page.locator("#obdConfiguredDevice")).toContainText(
    "OBDII Link",
  );
  expect(server.pairs).toEqual(["00:1D:A5:00:00:01"]);

  await page.locator("#saveSpeedSourceBtn").click();
  await expect.poll(() => server.puts.length).toBe(1);
  expect(server.puts[0]).toMatchObject({ speed_source: "obd2" });
  await expect(page.locator("#speedSourceCurrentSource")).toHaveText(/OBD/);
  // Each scan interrupts sensor data, so the page never rescans on its own.
  expect(server.scans).toBe(1);
});

test("journey: a double-clicked save sends one speed source update", async ({
  page,
}) => {
  const server: SpeedSourceServer = {
    saved: { speed_source: "gps", manual_speed_kph: null, stale_timeout_s: 10 },
    puts: [],
    scans: 0,
    pairs: [],
    failNextPut: false,
    putDelayMs: 400,
  };
  await installSpeedSourceRoutes(page, server);
  await openSpeedSourceTab(page);
  await page.locator("#speedSourceChoiceManual").click();
  await page.locator("#manualSpeedInput").fill("65");
  await page.locator("#saveSpeedSourceBtn").dblclick();
  await expect(page.locator("#speedSourceCurrentSource")).toHaveText(
    "Manual override",
  );
  expect(server.puts).toHaveLength(1);
});
