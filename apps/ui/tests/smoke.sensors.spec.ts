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
});
