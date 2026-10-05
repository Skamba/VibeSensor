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

test("journey: Sensors tab assigns a location, identifies, and removes a sensor", async ({
  page,
}) => {
  const locationPosts: Array<{ id: string; body: unknown }> = [];
  const identifyPosts: string[] = [];
  const deletes: string[] = [];

  await installCommonRoutes(page, {
    locations: [
      { code: "front_left_wheel", label: "Front Left Wheel" },
      { code: "rear_right_wheel", label: "Rear Right Wheel" },
    ],
  });
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
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 10,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: CONNECTED_ID,
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

  const rows = page.locator("#sensorsSettingsBody tr[data-client-id]");
  await expect(rows).toHaveCount(2);
  const connectedRow = page.locator(
    `#sensorsSettingsBody tr[data-client-id="${CONNECTED_ID}"]`,
  );
  const offlineRow = page.locator(
    `#sensorsSettingsBody tr[data-client-id="${OFFLINE_ID}"]`,
  );
  await expect(connectedRow).toContainText("Front Left");
  await expect(connectedRow).toContainText("Online");
  await expect(connectedRow).toContainText(CONNECTED_ID);
  await expect(connectedRow.locator("select")).toHaveValue("front_left_wheel");
  // A sensor without a name falls back to its id.
  await expect(offlineRow).toContainText(OFFLINE_ID);
  await expect(offlineRow).toContainText("Offline");
  await expect(offlineRow.locator(".row-identify")).toBeDisabled();

  await connectedRow.locator("select").selectOption("rear_right_wheel");
  await expect
    .poll(() => locationPosts)
    .toEqual([
      { id: CONNECTED_ID, body: { location_code: "rear_right_wheel" } },
    ]);

  await connectedRow.locator(".row-identify").click();
  await expect.poll(() => identifyPosts).toEqual([CONNECTED_ID]);

  // Cancelling the confirmation keeps the sensor.
  await offlineRow.locator(".row-remove").click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText(OFFLINE_ID);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(rows).toHaveCount(2);
  expect(deletes).toEqual([]);

  await offlineRow.locator(".row-remove").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Confirm" })
    .click();
  await expect.poll(() => deletes).toEqual([OFFLINE_ID]);
  await expect(rows).toHaveCount(1);
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
  await expect(page.locator("#sensorsSettingsBody")).toContainText(
    "No sensors detected yet.",
  );
  // The mounting guide is open until all four wheels have a sensor.
  const guide = page.locator("#sensorMountingGuide");
  await expect(guide).toHaveAttribute("open", "");
  await expect(page.locator("#sensorLayoutConsequence")).toHaveText(
    "No connected sensor has a location yet.",
  );
  await expect(guide).toContainText("Never on the wheel or tire");
});

test("journey: Settings fits a phone and the sensor row stays usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installCommonRoutes(page, {
    locations: [{ code: "front_left_wheel", label: "Front Left Wheel" }],
  });
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
  const row = page.locator(
    `#sensorsSettingsBody tr[data-client-id="${CONNECTED_ID}"]`,
  );
  for (const control of [
    row.getByRole("combobox", { name: "Location" }),
    row.locator(".row-identify"),
    row.locator(".row-remove"),
  ]) {
    // Fully inside the phone's width, not in a sideways-scrolled table.
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
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

  await expect(
    page.locator(`tr[data-client-id="${CONNECTED_ID}"] [data-firmware-status]`),
  ).toHaveText(/Firmware esp32-atom-0\.1\s*outdated/);
  await expect(
    page.locator(`tr[data-client-id="${OFFLINE_ID}"] [data-firmware-status]`),
  ).toHaveText(/Firmware fw-20261005\.1200\+0123456789ab\s*up to date/);
  const notice = page.locator("#sensorFirmwareNotice");
  await expect(notice).toContainText(
    "1 sensor runs older firmware than this Pi provides.",
  );
  await expect(notice).toContainText("needs a USB cable");

  await page.locator("#sensorFirmwareUpdateBtn").click();
  await expect(page.locator("#espFlashTab")).toBeVisible();
  await expect(page.locator("#sensorsTab")).toBeHidden();
});
