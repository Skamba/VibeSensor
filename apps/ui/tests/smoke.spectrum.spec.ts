import { expect, test } from "@playwright/test";

import { installCommonRoutes, installFakeWebSocket } from "./smoke.helpers";

test("spectrum controls simplify the chart and update the inspector", async ({ page }) => {
  await page.goto("/?demo=1");

  const inspector = page.locator("#spectrumInspector");
  const bandToggle = page.locator("#spectrumBandToggle");
  const bandLegend = page.locator("#bandLegend");
  const allTracesChip = page.getByRole("button", { name: /All sensor traces/i });
  const sensorChip = page.getByRole("button", { name: /Front Right Wheel/i });

  await expect(bandToggle).toBeVisible();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "false");
  await expect(bandLegend).toBeHidden();
  await expect(inspector).toContainText("Strongest trace:");
  await sensorChip.click();
  await expect(sensorChip).toHaveAttribute("aria-pressed", "true");
  await expect(inspector).toContainText("Focused trace:");
  await expect(inspector).toContainText("Front Right Wheel");

  await bandToggle.click();
  await expect(bandToggle).toHaveAttribute("aria-pressed", "true");
  await expect(bandToggle).toHaveText("Hide reference bands");
  await expect(bandLegend).toBeVisible();
  await expect(bandLegend).toContainText("Wheel 1x");

  await allTracesChip.click();
  await expect(allTracesChip).toHaveAttribute("aria-pressed", "true");
  await expect(sensorChip).toHaveAttribute("aria-pressed", "false");
  await expect(inspector).toContainText("Strongest trace:");
});

test("spectrum band toggle stays hidden when no spectrum data is available", async ({ page }) => {
  await installCommonRoutes(page);
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 50,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: {
        clients: {},
      },
    },
  });

  await page.goto("/");

  await expect(page.locator("#spectrumOverlay")).toBeVisible();
  await expect(page.locator("#spectrumBandToggle")).toBeHidden();
  await expect(page.locator("#bandLegend")).toBeHidden();
});
