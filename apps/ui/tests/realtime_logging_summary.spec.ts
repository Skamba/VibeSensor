import { expect, test } from "@playwright/test";

import {
  fulfillJson,
  installCommonRoutes,
  installFakeWebSocket,
  requestPath,
  waitForFakeWebSocketSettled,
} from "./smoke.helpers";

test("keeps the no-car Live CTA stable while repeated websocket payloads arrive", async ({ page }) => {
  const trackerKey = "__loggingSummaryRepeatTracker";
  await installCommonRoutes(page, {
    settingsHandler: async (route) => {
      const path = requestPath(route);
      if (path === "/api/settings/cars") {
        await fulfillJson(route, { cars: [], active_car_id: null });
        return;
      }
      await fulfillJson(route, {});
    },
  });
  await installFakeWebSocket(page, {
    payload: {
      server_time: new Date().toISOString(),
      clients: [
        {
          id: "001122334455",
          name: "Front Left",
          connected: true,
          sample_rate_hz: 1000,
          last_seen_age_ms: 12,
          dropped_frames: 0,
          frames_total: 100,
          location_code: "front_left_wheel",
          mac_address: "001122334455",
          firmware_version: "fw-1.0.0",
        },
      ],
      spectra: { clients: {} },
    },
    repeatPayloadCount: 16,
    repeatPayloadIntervalMs: 25,
    trackerKey,
  });

  await page.goto("/");
  const liveSummary = page.locator("#loggingSummary");
  const addCarButton = liveSummary.getByRole("button", { name: "Add a car" });
  await expect(addCarButton).toBeVisible();
  await expect(page.locator("#spectrumPanelRoot")).toBeHidden();
  expect(await page.locator(".dashboard-grid").getAttribute("data-layout")).toBeNull();

  await page.evaluate(() => {
    const summary = document.querySelector<HTMLElement>("#loggingSummary");
    const button = summary?.querySelector<HTMLElement>('[data-inline-state-action="open-add-car"]');
    if (!summary || !button) {
      throw new Error("Live logging summary button was not rendered");
    }
    const tracker = {
      currentButton: button,
      replacements: 0,
    };
    const observer = new MutationObserver(() => {
      const nextButton = summary.querySelector<HTMLElement>('[data-inline-state-action="open-add-car"]');
      if (nextButton && nextButton !== tracker.currentButton) {
        tracker.currentButton = nextButton;
        tracker.replacements += 1;
      }
    });
    observer.observe(summary, { childList: true, subtree: true });
    (
      window as Window & typeof globalThis & {
        __loggingSummaryTracker?: typeof tracker;
        __loggingSummaryObserver?: MutationObserver;
      }
    ).__loggingSummaryTracker = tracker;
    (
      window as Window & typeof globalThis & {
        __loggingSummaryTracker?: typeof tracker;
        __loggingSummaryObserver?: MutationObserver;
      }
    ).__loggingSummaryObserver = observer;
  });

  await waitForFakeWebSocketSettled(page, trackerKey, 17);

  expect(await page.evaluate(() => (
    window as Window & typeof globalThis & {
      __loggingSummaryTracker?: { replacements: number };
    }
  ).__loggingSummaryTracker?.replacements ?? -1)).toBe(0);

  await addCarButton.click();
  await expect(page.locator("#settingsView")).toHaveJSProperty("hidden", false);
  await expect(page.locator("#wizardBackdrop")).toBeVisible();
});
