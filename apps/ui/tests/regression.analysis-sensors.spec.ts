import { expect, test } from "@playwright/test";

import {
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 15_000 });

test("analysis guidance can reopen and refocus after repeated invalid saves", async ({
  page,
}) => {
  let analysisPutCalls = 0;

  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      if (requestPath(route).startsWith("/api/settings/cars")) {
        await fulfillJson(route, {
          cars: [{ id: "car-1", name: "Selected", type: "sedan", aspects: {} }],
          active_car_id: "car-1",
        });
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
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="analysisTab"]').click();

  const guidanceHelp = page.locator("#analysisGuidanceHelp");
  const bandwidthInput = page.locator("#wheelBandwidthInput");

  await bandwidthInput.fill("120");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPutCalls).toBe(0);
  await expect(guidanceHelp).toHaveAttribute("open", "");
  await expect(bandwidthInput).toHaveAttribute("aria-invalid", "true");
  await expect(bandwidthInput).toBeFocused();

  await guidanceHelp.evaluate((element) => {
    if (!(element instanceof HTMLDetailsElement)) {
      throw new Error("analysisGuidanceHelp must be a details element");
    }
    element.open = false;
  });
  await expect(guidanceHelp).not.toHaveAttribute("open", "");

  await bandwidthInput.fill("130");
  await page.locator("#saveAnalysisBtn").click();

  await expect.poll(() => analysisPutCalls).toBe(0);
  await expect(guidanceHelp).toHaveAttribute("open", "");
  await expect(bandwidthInput).toHaveAttribute("aria-invalid", "true");
  await expect(bandwidthInput).toBeFocused();
});

test("sensor row actions stay wired while live updates keep arriving", async ({
  page,
}) => {
  let identifyCalls = 0;
  let locationUpdateCalls = 0;

  await installCommonRoutes(page, {
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
  });
  await page.route("**/api/clients/**/location", async (route) => {
    locationUpdateCalls += 1;
    await fulfillJson(route, {});
  });
  await page.route("**/api/clients/**/identify", async (route) => {
    identifyCalls += 1;
    await fulfillJson(route, {});
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "sensor-1",
          name: "Chassis Sensor A",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "",
          mac_address: "sensor-1",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
    repeatPayloadCount: 6,
    repeatPayloadIntervalMs: 40,
  });

  await page.goto("/");
  await page.locator("#tab-settings").click();
  await page.locator('[data-settings-tab="sensorsTab"]').click();

  const row = page.locator(
    '#sensorsSettingsBody tr[data-client-id="sensor-1"]',
  );
  const locationSelect = row.locator("select.row-location-select");

  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");
  await locationSelect.selectOption("front_left_wheel");
  await expect.poll(() => locationUpdateCalls).toBe(1);
  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");

  await row.locator(".row-identify").click();
  await expect.poll(() => identifyCalls).toBe(1);
  await expect(row.locator("strong")).toHaveText("Chassis Sensor A");
});
