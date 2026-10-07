import { expect, test } from "@playwright/test";

import {
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  openSensorsTab,
  requestPath,
} from "./smoke.helpers";

test.describe.configure({ timeout: 20_000 });

const CONNECTED_ID = "001122334455";
const OFFLINE_ID = "aabbccddeeff";

test("journey: Sensors tab places sensors on the car, identifies, unplaces and removes one", async ({
  page,
}) => {
  const locationPosts: Array<{ id: string; body: unknown }> = [];
  const identifyPosts: string[] = [];
  const deletes: string[] = [];

  await installCommonRoutes(page);
  await page.route("**/api/clients/**", async (route) => {
    const path = requestPath(route);
    const method = route.request().method();
    const id = decodeURIComponent(path.split("/")[3] ?? "");
    if (path.endsWith("/location") && method === "POST") {
      locationPosts.push({ id, body: route.request().postDataJSON() });
    } else if (path.endsWith("/identify") && method === "POST") {
      identifyPosts.push(id);
    } else if (method === "DELETE") {
      deletes.push(id);
    }
    await fulfillJson(route, {});
  });
  await installFakeWebSocket(page, {
    payload: {
      clients: [
        {
          id: CONNECTED_ID,
          name: "Front Left Wheel",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "00:11:22:33:44:55",
          firmware_version: "fw-1.0.0",
        },
        {
          id: OFFLINE_ID,
          name: "",
          connected: false,
          sample_rate_hz: 1000,
          last_seen_age_ms: 9000,
          dropped_frames: 0,
          frames_total: 5,
          location_code: "",
          mac_address: OFFLINE_ID,
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });
  await page.goto("/");
  await openSensorsTab(page);

  // The unplaced sensor is a chip (named by its id) and is selected to place.
  await expect(page.locator("#sensorsToPlace")).toHaveText("1 sensor to place");
  const chip = page.locator(`.sensor-chip[data-client-id="${OFFLINE_ID}"]`);
  await expect(chip).toHaveText(OFFLINE_ID);
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  const selection = page.locator("#sensorSelection");
  await expect(selection).toContainText("Offline");
  await expect(selection.locator(".sensor-identify")).toBeDisabled();
  // The placed sensor sits on its spot, shown by its short id.
  const frontLeft = page.locator('.car-spot[data-code="front_left_wheel"]');
  await expect(frontLeft).toHaveAttribute("data-client-id", CONNECTED_ID);
  await expect(frontLeft).toContainText("44:55");

  // Tapping a free spot places the selected sensor; nothing is left to place.
  await page
    .getByRole("button", { name: `Place ${OFFLINE_ID} at Trunk` })
    .click();
  await expect
    .poll(() => locationPosts)
    .toEqual([{ id: OFFLINE_ID, body: { location_code: "trunk" } }]);
  await expect(page.locator("#sensorsToPlace")).toHaveText(
    "Every sensor has a place on the car.",
  );
  await expect(selection).toHaveText(
    "Tap a sensor on the car to identify, move or unplace it.",
  );

  // Tapping a placed sensor selects it: Identify blinks it.
  await frontLeft.click();
  await expect(frontLeft).toHaveAttribute("aria-pressed", "true");
  await expect(selection).toContainText("Front Left Wheel · 44:55");
  await expect(selection).toContainText("00:11:22:33:44:55");
  await selection.locator(".sensor-identify").click();
  await expect.poll(() => identifyPosts).toEqual([CONNECTED_ID]);

  // Moving it onto an occupied spot unplaces the sensor that was there first.
  locationPosts.length = 0;
  await page.locator('.car-spot[data-code="trunk"]').click();
  await expect
    .poll(() => locationPosts)
    .toEqual([
      { id: OFFLINE_ID, body: { location_code: "" } },
      { id: CONNECTED_ID, body: { location_code: "trunk" } },
    ]);
  await expect(chip).toBeVisible();

  // Unplace keeps the sensor selected, back among the sensors to place.
  locationPosts.length = 0;
  await page.locator('.car-spot[data-code="trunk"]').click();
  await page.locator("#sensorSelection .sensor-unplace").click();
  await expect
    .poll(() => locationPosts)
    .toEqual([{ id: CONNECTED_ID, body: { location_code: "" } }]);
  await expect(page.locator("#sensorsToPlace")).toHaveText(
    "2 sensors to place",
  );

  // Remove sits behind "More", away from Identify, and still asks first.
  await chip.click();
  await expect(selection.locator(".sensor-remove")).toBeHidden();
  await selection.locator(".sensor-more__summary").click();
  await selection.locator(".sensor-remove").click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText(OFFLINE_ID);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(deletes).toEqual([]);

  await selection.locator(".sensor-remove").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect.poll(() => deletes).toEqual([OFFLINE_ID]);
  await expect(page.locator(".sensor-chip")).toHaveCount(1);
});

test("journey: Sensors tab shows the empty state without live sensors", async ({
  page,
}) => {
  await installCommonRoutes(page);
  await installFakeWebSocket(page, {
    payload: { clients: [], spectra: { clients: {} } },
  });
  await page.goto("/");
  await openSensorsTab(page);
  await expect(page.locator("#sensorsEmpty")).toHaveText(
    "No sensors detected yet.",
  );
  // The car still shows where sensors go; with none to place, spots are inert.
  await expect(page.locator(".car-spot")).toHaveCount(15);
  await expect(page.locator(".car-spot:enabled")).toHaveCount(0);
  // The mounting guide is open until a sensor is placed.
  const guide = page.locator("#sensorMountingGuide");
  await expect(guide).toHaveAttribute("open", "");
  await expect(page.locator("#sensorLayoutConsequence")).toHaveText(
    "No connected sensor has a location yet.",
  );
  await expect(guide).toContainText("Never on the wheel or tire");
});

test("journey: Settings fits a phone and every spot on the car is a full-size tap target", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installCommonRoutes(page);
  await installFakeWebSocket(page, {
    payload: {
      clients: [
        {
          id: CONNECTED_ID,
          name: "Front Left",
          connected: true,
          sample_rate_hz: 800,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "",
          mac_address: CONNECTED_ID,
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
  });
  await page.goto("/");
  await page.locator("#tab-settings").click();

  const pageOverflow = () =>
    page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
  const tabs = page.locator("#settingsView [role='tab']");
  const count = await tabs.count();
  expect(count).toBeGreaterThan(5);
  for (let index = 0; index < count; index += 1) {
    // A plain click: no neighbouring tab may cover the target.
    await tabs.nth(index).click();
    await expect(tabs.nth(index)).toHaveAttribute("aria-selected", "true");
    expect(await pageOverflow()).toBeLessThanOrEqual(0);
  }

  await openSensorsTab(page);
  const controls = page.locator(
    ".car-spot, .sensor-chip, #sensorSelection .btn, .sensor-more__summary",
  );
  await expect(page.locator(".car-spot")).toHaveCount(15);
  for (const control of await controls.all()) {
    // At least 44 px each way, fully inside the phone's width.
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390);
  }
  expect(await pageOverflow()).toBeLessThanOrEqual(0);
});

test("journey: an outdated sensor shows its firmware and the USB update path", async ({
  page,
}) => {
  await installCommonRoutes(page);
  const sensor = {
    connected: true,
    sample_rate_hz: 800,
    last_seen_age_ms: 10,
    dropped_frames: 0,
    frames_total: 100,
    location_code: "",
  };
  await installFakeWebSocket(page, {
    payload: {
      clients: [
        {
          ...sensor,
          id: CONNECTED_ID,
          name: "Front Left",
          mac_address: CONNECTED_ID,
          firmware_version: "esp32-atom-0.1",
          firmware_status: "outdated",
        },
        {
          ...sensor,
          id: OFFLINE_ID,
          name: "Rear Right",
          mac_address: OFFLINE_ID,
          firmware_version: "fw-20261005.1200+0123456789ab",
          firmware_status: "current",
        },
      ],
      spectra: { clients: {} },
    },
  });
  await page.goto("/");
  await openSensorsTab(page);

  // The selected sensor's card shows its firmware.
  const firmware = page.locator("#sensorSelection [data-firmware-status]");
  await expect(firmware).toHaveText(/Firmware esp32-atom-0\.1\s*outdated/);
  await page.locator(`.sensor-chip[data-client-id="${OFFLINE_ID}"]`).click();
  await expect(firmware).toHaveText(
    /Firmware fw-20261005\.1200\+0123456789ab\s*up to date/,
  );
  const notice = page.locator("#sensorFirmwareNotice");
  await expect(notice).toContainText(
    "1 sensor runs older firmware than this Pi provides.",
  );
  await expect(notice).toContainText("needs a USB cable");

  await page.locator("#sensorFirmwareUpdateBtn").click();
  await expect(page.locator("#espFlashTab")).toBeVisible();
  await expect(page.locator("#sensorsTab")).toBeHidden();
});
